"""Calibrate and evaluate RAG abstention against the labelled evaluation sets.

    python -m smartdesk.rag.calibrate [--split dev|heldout|all]

Two splits are kept apart:

- dev (data/eval/eval_set.jsonl): used for calibration. The threshold sweep
  and recommendation come only from this split, and prompts may be refined
  against it.
- held-out (data/eval/heldout/eval_set.jsonl): never used for tuning. It is
  scored once, at the configured threshold, to estimate how the agent does
  on unseen questions.

For every question this runs the real router (intent, domain), domain-aware
and unfiltered retrieval, and the grounded-answer step. It then reports:

- end-to-end outcome per category (answer / escalate / decline / greet),
  combining routing with the RAG decision,
- routing accuracy per category,
- retrieval quality with and without the domain filter,
- RAG escalation precision/recall (gap questions should escalate,
  answerable questions should be answered) and, on dev, a threshold sweep,
- citation accuracy of the answers that were given.

Similarities are ranking scores, not probabilities: the threshold is only a
cheap pre-filter, chosen with a safety margin below the lowest answerable
score, and the LLM sufficiency check makes the final call. Per-question detail
is written to data/eval/calibration_report.json for manual review.
"""

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from smartdesk.config import get_settings
from smartdesk.graph import prompts
from smartdesk.graph.state import Intent, IntentClassification
from smartdesk.kb.evaluate import EVAL_PATH, HELDOUT_PATH, EvalCategory, EvalItem, load_eval_set
from smartdesk.llm import get_chat_model
from smartdesk.rag.answer import generate_answer
from smartdesk.rag.retriever import Retriever, build_retriever

REPORT_PATH = Path("data/eval/calibration_report.json")
SPLITS = {"dev": EVAL_PATH, "heldout": HELDOUT_PATH}
SAFETY_MARGIN = 0.05
EXPECTED_INTENT = {
    EvalCategory.ANSWERABLE: {Intent.KNOWLEDGE_QUESTION},
    # A gap question is either asked as a question or reported as a problem
    # with a request for help; both lead to escalation and a ticket offer.
    EvalCategory.GAP: {Intent.KNOWLEDGE_QUESTION, Intent.CREATE_TICKET},
    EvalCategory.OUT_OF_SCOPE: {Intent.OUT_OF_SCOPE},
    EvalCategory.GREETING: {Intent.GREETING},
}
EXPECTED_OUTCOME = {
    EvalCategory.ANSWERABLE: "answer",
    EvalCategory.GAP: "escalate",
    EvalCategory.OUT_OF_SCOPE: "decline",
    EvalCategory.GREETING: "greet",
}


@dataclass
class ItemResult:
    id: str
    category: str
    question: str
    expected_doc_ids: list[str]
    intent: str
    domain: str
    search_query: str
    top_similarity: float  # domain-aware retrieval, as used by the agent
    ranked_doc_ids: list[str]
    ranked_doc_ids_unfiltered: list[str]
    sufficient: bool = False  # LLM sufficiency check passed with valid citations
    rejection_reason: str | None = None
    cited_doc_ids: list[str] = field(default_factory=list)
    answer: str = ""

    def escalates(self, threshold: float) -> bool:
        """The RAG decision alone, as if the question had been routed to the KB."""
        return self.top_similarity < threshold or not self.sufficient

    def outcome(self, threshold: float) -> str:
        """What the employee actually gets: routing first, then the RAG decision."""
        if self.intent == Intent.KNOWLEDGE_QUESTION:
            return "escalate" if self.escalates(threshold) else "answer"
        return {
            Intent.CREATE_TICKET: "escalate",  # goes straight to the ticket flow
            Intent.OUT_OF_SCOPE: "decline",
            Intent.GREETING: "greet",
        }.get(Intent(self.intent), self.intent)


def _unique_docs(chunks) -> list[str]:
    return list(dict.fromkeys(c.doc_id for c in chunks))


def run_item(item: EvalItem, classifier, llm, retriever: Retriever, unfiltered: Retriever) -> ItemResult:
    route = classifier.invoke([SystemMessage(content=prompts.INTENT_SYSTEM_PROMPT), HumanMessage(content=item.question)])
    assert isinstance(route, IntentClassification)
    query = item.question  # single-turn, so the agent uses the question verbatim (see workflow)
    domain = None if route.domain == "unknown" else route.domain
    chunks = retriever.retrieve(query, domain)
    result = ItemResult(
        id=item.id,
        category=item.category.value,
        question=item.question,
        expected_doc_ids=item.expected_doc_ids,
        intent=route.intent.value,
        domain=route.domain,
        search_query=query,
        top_similarity=chunks[0].similarity if chunks else 0.0,
        ranked_doc_ids=_unique_docs(chunks),
        ranked_doc_ids_unfiltered=_unique_docs(unfiltered.retrieve(query)),
    )
    # Run the answer step for every KB-style item regardless of the threshold,
    # so the sweep below can combine any threshold with the LLM's verdict.
    if chunks and item.category != EvalCategory.GREETING:
        answer = generate_answer(llm, query, [c.to_dict() for c in chunks])
        result.sufficient = answer.grounded
        result.rejection_reason = answer.reason
        result.cited_doc_ids = [c.doc_id for c in answer.citations]
        result.answer = answer.text
    return result


def _retrieval_metrics(results: list[ItemResult], attr: str) -> dict:
    answerable = [r for r in results if r.category == EvalCategory.ANSWERABLE]
    ranks = []
    for r in answerable:
        ranked = getattr(r, attr)
        ranks.append(next((i for i, d in enumerate(ranked, 1) if d in r.expected_doc_ids), None))
    n = len(answerable) or 1
    return {
        "hit_at_1": round(sum(rank == 1 for rank in ranks) / n, 3),
        "recall_at_k": round(sum(rank is not None for rank in ranks) / n, 3),
        "mrr": round(sum(1 / rank for rank in ranks if rank) / n, 3),
    }


def escalation_metrics(results: list[ItemResult], threshold: float) -> dict:
    """Positive class = gap (should escalate); answerable items should be answered."""
    gap = [r for r in results if r.category == EvalCategory.GAP]
    answerable = [r for r in results if r.category == EvalCategory.ANSWERABLE]
    tp = sum(r.escalates(threshold) for r in gap)
    fp = sum(r.escalates(threshold) for r in answerable)
    fn = len(gap) - tp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "threshold": round(threshold, 2),
        "gap_escalated": f"{tp}/{len(gap)}",
        "answerable_escalated": f"{fp}/{len(answerable)}",
        "gap_escalated_by_threshold": sum(r.top_similarity < threshold for r in gap),
        "answerable_escalated_by_threshold": sum(r.top_similarity < threshold for r in answerable),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
    }


def recommend_threshold(results: list[ItemResult]) -> float:
    answerable = [r.top_similarity for r in results if r.category == EvalCategory.ANSWERABLE]
    # Round before flooring so float error (0.41 - 0.05 = 0.35999...) does not drop a step.
    return max(0.0, math.floor(round((min(answerable) - SAFETY_MARGIN) * 100, 6)) / 100)


def outcome_metrics(results: list[ItemResult], threshold: float) -> dict:
    by_category = {}
    for category in EvalCategory:
        group = [r for r in results if r.category == category]
        if not group:
            continue
        wrong = {r.id: r.outcome(threshold) for r in group if r.outcome(threshold) != EXPECTED_OUTCOME[category]}
        by_category[category.value] = {
            "expected": EXPECTED_OUTCOME[category],
            "correct": f"{len(group) - len(wrong)}/{len(group)}",
            "wrong": wrong,
        }
    return by_category


def evaluate_split(results: list[ItemResult], threshold: float, calibrate: bool) -> dict:
    routing = {}
    for category in EvalCategory:
        group = [r for r in results if r.category == category]
        if group:
            correct = [r for r in group if Intent(r.intent) in EXPECTED_INTENT[category]]
            routing[category.value] = {
                "correct": f"{len(correct)}/{len(group)}",
                "misrouted": {r.id: r.intent for r in group if r not in correct},
            }
    answered = [r for r in results if r.category == EvalCategory.ANSWERABLE and r.outcome(threshold) == "answer"]
    cited_correctly = [r for r in answered if set(r.cited_doc_ids) & set(r.expected_doc_ids)]
    report = {
        "items_evaluated": len(results),
        "end_to_end": outcome_metrics(results, threshold),
        "routing": routing,
        "retrieval": {
            "domain_aware": _retrieval_metrics(results, "ranked_doc_ids"),
            "unfiltered": _retrieval_metrics(results, "ranked_doc_ids_unfiltered"),
        },
        "escalation": escalation_metrics(results, threshold),
        "answers": {
            "answerable_answered": f"{len(answered)}/{sum(r.category == EvalCategory.ANSWERABLE for r in results)}",
            "cites_expected_doc": f"{len(cited_correctly)}/{len(answered)}",
            "wrong_citation_ids": [r.id for r in answered if r not in cited_correctly],
        },
    }
    if calibrate:
        report["recommended_min_similarity"] = recommend_threshold(results)
        report["threshold_sweep"] = [escalation_metrics(results, t / 100) for t in range(20, 51, 2)]
    report["items"] = [asdict(r) for r in results]
    return report


def _print_split(name: str, report: dict, threshold: float) -> None:
    print(f"\n=== {name} ({report['items_evaluated']} questions, min_similarity {threshold:.2f}) ===")
    print("End-to-end outcome:")
    for category, stats in report["end_to_end"].items():
        print(f"  {category:13s} {stats['expected']:9s} {stats['correct']:7s} wrong: {stats['wrong'] or 'none'}")
    print("Routing:")
    for category, stats in report["routing"].items():
        print(f"  {category:13s} {stats['correct']:7s} misrouted: {stats['misrouted'] or 'none'}")
    print("Retrieval on answerable:")
    for mode, m in report["retrieval"].items():
        print(f"  {mode:13s} Hit@1 {m['hit_at_1']:.3f}  Recall@k {m['recall_at_k']:.3f}  MRR {m['mrr']:.3f}")
    e = report["escalation"]
    print(
        f"RAG escalation (positive = gap): gap {e['gap_escalated']}, answerable {e['answerable_escalated']}, "
        f"precision {e['precision']:.3f}, recall {e['recall']:.3f}, f1 {e['f1']:.3f}"
    )
    print(f"Answers: {report['answers']}")
    if "threshold_sweep" in report:
        print("Threshold sweep (threshold pre-filter + LLM sufficiency check):")
        print("  thresh  gap esc  ans esc  by-thresh gap/ans  precision  recall  f1")
        for row in report["threshold_sweep"]:
            print(
                f"  {row['threshold']:.2f}    {row['gap_escalated']:7s}  {row['answerable_escalated']:7s}  "
                f"{row['gap_escalated_by_threshold']:>5}/{row['answerable_escalated_by_threshold']:<11}"
                f"{row['precision']:.3f}      {row['recall']:.3f}   {row['f1']:.3f}"
            )
        print(
            f"Recommended min_similarity (lowest answerable score - {SAFETY_MARGIN} margin): "
            f"{report['recommended_min_similarity']:.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    args = parser.parse_args(argv)

    settings = get_settings()
    retriever = build_retriever(settings)
    if retriever.collection.count() == 0:
        print("The index is empty; run `python -m smartdesk.kb.ingest` first.", file=sys.stderr)
        return 1
    unfiltered = Retriever(retriever.collection, retriever.embed_query, top_k=retriever.top_k)
    llm = get_chat_model(settings)
    classifier = llm.with_structured_output(IntentClassification)
    threshold = settings.rag_min_similarity

    report: dict = {
        "settings": {
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "top_k": settings.rag_top_k,
            "min_similarity": threshold,
        },
    }
    for name in ["dev", "heldout"] if args.split == "all" else [args.split]:
        items = load_eval_set(SPLITS[name])
        results = []
        for n, item in enumerate(items, 1):
            print(f"\r  {name}: evaluating {n}/{len(items)}", end="", file=sys.stderr, flush=True)
            results.append(run_item(item, classifier, llm, retriever, unfiltered))
        print(file=sys.stderr)
        report[name] = evaluate_split(results, threshold, calibrate=name == "dev")
        _print_split(name, report[name], threshold)

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nPer-question detail: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
