"""Retrieval check against the labelled evaluation set.

    python -m smartdesk.kb.evaluate [--k 5]

Reports document-level Hit@1, Recall@k and MRR for answerable questions, and
the distribution of top-1 similarity per category. The similarity figures are
raw ranking scores used as calibration input for abstention (Milestone 3);
they are not probabilities.
"""

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, model_validator

from smartdesk.config import get_settings
from smartdesk.kb.vectorstore import get_client, get_collection, search
from smartdesk.llm import get_embeddings

EVAL_PATH = Path("data/eval/eval_set.jsonl")  # dev split: calibration and tuning
HELDOUT_PATH = Path("data/eval/heldout/eval_set.jsonl")  # never used for tuning


class EvalCategory(StrEnum):
    ANSWERABLE = "answerable"
    GAP = "gap"
    OUT_OF_SCOPE = "out_of_scope"
    GREETING = "greeting"


class EvalItem(BaseModel):
    id: str
    category: EvalCategory
    question: str
    expected_doc_ids: list[str]
    expected_behavior: str
    gap_id: str | None = None

    @model_validator(mode="after")
    def _check_labels(self) -> "EvalItem":
        if (self.category == EvalCategory.ANSWERABLE) != bool(self.expected_doc_ids):
            raise ValueError(f"{self.id}: only answerable items have expected_doc_ids")
        if (self.category == EvalCategory.GAP) != bool(self.gap_id):
            raise ValueError(f"{self.id}: gap items (and only gap items) need a gap_id")
        return self


def load_eval_set(path: Path = EVAL_PATH) -> list[EvalItem]:
    return [EvalItem(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class RetrievalResult:
    item: EvalItem
    ranked_doc_ids: list[str]  # unique doc ids in rank order
    top_similarity: float

    def rank_of_expected(self) -> int | None:
        for rank, doc_id in enumerate(self.ranked_doc_ids, start=1):
            if doc_id in self.item.expected_doc_ids:
                return rank
        return None


@dataclass
class Metrics:
    k: int
    answerable: int = 0
    hit_at_1: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    misses: list[str] = field(default_factory=list)
    top_similarity: dict[str, dict[str, float]] = field(default_factory=dict)


def compute_metrics(results: list[RetrievalResult], k: int) -> Metrics:
    metrics = Metrics(k=k)
    answerable = [r for r in results if r.item.category == EvalCategory.ANSWERABLE]
    ranks = [r.rank_of_expected() for r in answerable]
    if answerable:
        metrics.answerable = len(answerable)
        metrics.hit_at_1 = sum(rank == 1 for rank in ranks) / len(answerable)
        metrics.recall_at_k = sum(rank is not None and rank <= k for rank in ranks) / len(answerable)
        metrics.mrr = sum(1 / rank for rank in ranks if rank) / len(answerable)
        metrics.misses = [r.item.id for r, rank in zip(answerable, ranks) if rank is None or rank > k]
    for category in EvalCategory:
        scores = [r.top_similarity for r in results if r.item.category == category]
        if scores:
            metrics.top_similarity[category.value] = {
                "min": min(scores), "median": statistics.median(scores), "max": max(scores),
            }
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)

    settings = get_settings()
    collection = get_collection(get_client(settings), settings.chroma_collection)
    if collection.count() == 0:
        print("The index is empty; run `python -m smartdesk.kb.ingest` first.", file=sys.stderr)
        return 1
    embeddings = get_embeddings(settings)
    items = load_eval_set()
    query_vectors = embeddings.embed_documents([item.question for item in items])

    results = []
    for item, vector in zip(items, query_vectors):
        hits = search(collection, vector, k=args.k * 4)  # several chunks can share a document
        ranked = list(dict.fromkeys(hit.metadata["doc_id"] for hit in hits))[: args.k]
        results.append(RetrievalResult(item, ranked, hits[0].similarity if hits else 0.0))

    m = compute_metrics(results, args.k)
    print(f"Answerable questions: {m.answerable}")
    print(f"  Hit@1: {m.hit_at_1:.3f}   Recall@{m.k}: {m.recall_at_k:.3f}   MRR: {m.mrr:.3f}")
    print(f"  Misses (expected doc not in top {m.k}): {m.misses or 'none'}")
    print("Top-1 similarity by category (raw scores, not probabilities):")
    for category, stats in m.top_similarity.items():
        print(f"  {category:13s} min {stats['min']:.3f}  median {stats['median']:.3f}  max {stats['max']:.3f}")
    print("\nPer-question detail:")
    for r in results:
        rank = r.rank_of_expected()
        mark = "" if r.item.category != EvalCategory.ANSWERABLE else (f"rank {rank}" if rank else "MISS")
        print(f"  {r.item.id:9s} {r.top_similarity:.3f}  {', '.join(r.ranked_doc_ids[:3]):60s} {mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
