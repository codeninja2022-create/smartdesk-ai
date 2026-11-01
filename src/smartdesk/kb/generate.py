"""Step A: one-time KB generation.

    python -m smartdesk.kb.generate --confirm [--only DOC_ID ...]

Downloads the pinned datasets, cleans and deduplicates them, assigns records
to catalogue topics by embedding similarity, and has the LLM write one
document per topic against the company fact sheet. Output goes to `data/kb/`
and is committed. LLM output is non-deterministic, so this command never runs
as part of ingestion and refuses to start without `--confirm`.
"""

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from smartdesk.config import Settings, get_settings
from smartdesk.kb import sources
from smartdesk.kb.catalog import GAPS, TOPICS, Topic, find_gap_mentions
from smartdesk.kb.company import COMPANY_NAME, COMPANY_PROFILE
from smartdesk.kb.documents import KBDocument, Provenance, SourceType, render
from smartdesk.llm import get_chat_model, get_embeddings

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
REPORT_PATH = Path("data/kb_generation_report.json")
MAX_ATTEMPTS = 3
MIN_WORDS = 250
GENERATION_TEMPERATURE = 0.3  # some variety in phrasing; facts are pinned by the fact sheet


class Section(BaseModel):
    heading: str
    body: str = Field(description="Markdown. Use numbered lists for procedures.")


class FAQ(BaseModel):
    question: str
    answer: str


class GeneratedDoc(BaseModel):
    summary: str = Field(description="2-3 sentence overview of the document.")
    sections: list[Section] = Field(min_length=3, max_length=7)
    faqs: list[FAQ] = Field(min_length=4, max_length=7)


SYSTEM_PROMPT = f"""\
You write internal knowledge-base articles for {COMPANY_NAME}'s employee help desk.

Company fact sheet (authoritative):
{COMPANY_PROFILE}

Rules:
1. Every fact you state must agree with the fact sheet. If a source record \
conflicts with the fact sheet, the fact sheet wins.
2. You may add realistic, topic-specific detail the fact sheet does not \
cover (menu paths, troubleshooting steps, examples, limits specific to this \
topic), but never contradict the fact sheet and never invent new contact \
channels, systems or URLs. Never link to external websites: employees \
install software only from Software Center (Windows) or Self Service (macOS).
3. Source records come from public datasets about other companies. Use them \
only to learn which questions and problems employees really have; never copy \
their company names, ticket numbers, names or email addresses.
4. Write for employees: clear, specific, professional and friendly. Prefer \
numbered steps for procedures. End with a section on who to contact if the \
article does not solve the problem.
5. The FAQs must mix simple factual questions, procedural how-to questions \
and policy-interpretation questions (edge cases, "what if" scenarios).
6. These topics are deliberately out of scope for the knowledge base. Do not \
mention them at all, not even in passing:
{chr(10).join(f"   - {gap.description}" for gap in GAPS)}"""


@dataclass
class TopicSources:
    topic: Topic
    records: list[sources.SourceRecord] = field(default_factory=list)
    similarities: list[float] = field(default_factory=list)


# --- Source assignment ------------------------------------------------------


def _normalise(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def assign_sources(
    topics: list[Topic],
    records: list[sources.SourceRecord],
    embed: Callable[[list[str]], list[list[float]]],
    *,
    min_similarity: float,
    max_per_topic: int,
) -> tuple[dict[str, TopicSources], dict[str, int]]:
    """Give each record to its most similar topic (same source dataset).

    Gap descriptions compete as pseudo-topics: a record closest to a gap is
    dropped, so gap content cannot leak into the KB through source material.
    """
    assigned = {topic.doc_id: TopicSources(topic) for topic in topics}
    stats = {"assigned": 0, "dropped_gap_semantic": 0, "below_threshold": 0, "over_topic_limit": 0}
    if not records:
        return assigned, stats

    targets = [f"{t.title}. {t.brief}" for t in topics] + [g.description for g in GAPS]
    target_vecs = _normalise(np.array(embed(targets)))
    record_vecs = _normalise(np.array(embed([r.text for r in records])))
    sims = record_vecs @ target_vecs.T

    best = np.argmax(sims, axis=1)
    scored: dict[str, list[tuple[float, sources.SourceRecord]]] = {t.doc_id: [] for t in topics}
    for i, record in enumerate(records):
        j, score = int(best[i]), float(sims[i, best[i]])
        if j >= len(topics):
            stats["dropped_gap_semantic"] += 1
        elif score < min_similarity:
            stats["below_threshold"] += 1
        else:
            scored[topics[j].doc_id].append((score, record))

    for doc_id, items in scored.items():
        items.sort(key=lambda item: item[0], reverse=True)
        stats["over_topic_limit"] += max(0, len(items) - max_per_topic)
        for score, record in items[:max_per_topic]:
            assigned[doc_id].records.append(record)
            assigned[doc_id].similarities.append(round(score, 3))
            stats["assigned"] += 1
    return assigned, stats


# --- Generation -------------------------------------------------------------


def _user_prompt(topic_sources: TopicSources, feedback: str | None) -> str:
    topic = topic_sources.topic
    parts = [
        f"Write the knowledge-base article titled \"{topic.title}\".",
        f"Domain: {topic.domain.value}. Category: {topic.category} / {topic.subcategory}.",
        f"It must cover: {topic.brief}",
    ]
    if topic_sources.records:
        listing = "\n".join(f"- {r.text[:600]}" for r in topic_sources.records)
        parts.append(f"Real employee questions/tickets on this topic from public datasets:\n{listing}")
    if feedback:
        parts.append(f"Your previous draft was rejected: {feedback} Rewrite it to fix this.")
    return "\n\n".join(parts)


def to_markdown(topic: Topic, generated: GeneratedDoc) -> str:
    lines = [f"# {topic.title}", "", generated.summary.strip(), ""]
    for section in generated.sections:
        lines += [f"## {section.heading.strip()}", "", section.body.strip(), ""]
    lines += ["## Frequently asked questions", ""]
    for faq in generated.faqs:
        lines += [f"### {faq.question.strip()}", "", faq.answer.strip(), ""]
    return "\n".join(lines).strip()


_URL = re.compile(r"https?://[^\s)\]>\"']+")
_KNOWN_URLS = {url.rstrip(".,") for url in _URL.findall(COMPANY_PROFILE)}


def validate_body(body: str) -> str | None:
    """Return a rejection reason, or None if the body is acceptable."""
    gaps = find_gap_mentions(body)
    if gaps:
        return f"it mentions out-of-scope topics ({', '.join(gaps)})."
    unknown_urls = sorted({url.rstrip(".,") for url in _URL.findall(body)} - _KNOWN_URLS)
    if unknown_urls:
        return (f"it links to URLs that are not in the fact sheet ({', '.join(unknown_urls)}). "
                "Only use the internal URLs from the fact sheet; software comes from Software Center/Self Service.")
    words = len(body.split())
    if words < MIN_WORDS:
        return f"it is too short ({words} words; at least {MIN_WORDS} needed)."
    return None


def generate_document(
    llm: BaseChatModel, topic_sources: TopicSources, model_name: str, today: str
) -> KBDocument:
    writer = llm.with_structured_output(GeneratedDoc)
    feedback = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        generated = writer.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=_user_prompt(topic_sources, feedback))]
        )
        assert isinstance(generated, GeneratedDoc)
        body = to_markdown(topic_sources.topic, generated)
        feedback = validate_body(body)
        if feedback is None:
            break
        logger.warning("%s attempt %d rejected: %s", topic_sources.topic.doc_id, attempt, feedback)
    else:
        raise RuntimeError(f"{topic_sources.topic.doc_id}: rejected after {MAX_ATTEMPTS} attempts: {feedback}")

    topic = topic_sources.topic
    used = [sources.DATASETS[r.dataset].pinned_id for r in topic_sources.records]
    return KBDocument(
        doc_id=topic.doc_id,
        title=topic.title,
        domain=topic.domain,
        category=topic.category,
        subcategory=topic.subcategory,
        provenance=Provenance(
            source_type=SourceType.DATASET_DERIVED if topic_sources.records else SourceType.SYNTHETIC,
            datasets=sorted(set(used)),
            source_record_ids=[r.record_id for r in topic_sources.records],
            generator_model=model_name,
            generated_at=today,
        ),
        body=body,
    )


# --- CLI --------------------------------------------------------------------


def run(settings: Settings, only: set[str] | None, min_similarity: float, max_per_topic: int) -> int:
    topics = [t for t in TOPICS if not only or t.doc_id in only]
    unknown = (only or set()) - {t.doc_id for t in TOPICS}
    if unknown:
        print(f"Unknown doc ids: {sorted(unknown)}", file=sys.stderr)
        return 2

    embeddings = get_embeddings(settings)
    report: dict = {"generated_at": date.today().isoformat(), "model": settings.llm_model, "datasets": {}}

    assignments: dict[str, TopicSources] = {}
    for spec, loader in ((sources.HR_QA, sources.load_hr_qa), (sources.IT_TICKETS, sources.load_it_tickets)):
        path = sources.download(spec, RAW_DIR)
        records, cleaning = loader(path)
        dataset_topics = [t for t in TOPICS if t.source == spec.key]
        assigned, stats = assign_sources(
            dataset_topics, records, embeddings.embed_documents,
            min_similarity=min_similarity, max_per_topic=max_per_topic,
        )
        assignments.update(assigned)
        report["datasets"][spec.key] = {
            "repo_id": spec.repo_id, "revision": spec.revision, "licence": spec.licence,
            "cleaning": {**asdict(cleaning), "kept": cleaning.kept}, "assignment": stats,
        }
        print(f"{spec.repo_id}: loaded {cleaning.loaded}, kept {cleaning.kept} "
              f"(dupes {cleaning.duplicates}, gap keywords {cleaning.gap_topic}, empty {cleaning.empty}); "
              f"assigned {stats['assigned']}, gap-similar {stats['dropped_gap_semantic']}")

    settings.kb_dir.mkdir(parents=True, exist_ok=True)
    llm = get_chat_model(settings).model_copy(update={"temperature": GENERATION_TEMPERATURE})
    failures, written = [], []
    for topic in topics:
        try:
            doc = generate_document(llm, assignments.get(topic.doc_id, TopicSources(topic)),
                                    settings.llm_model, report["generated_at"])
        except Exception as exc:  # report and continue with the remaining topics
            failures.append({"doc_id": topic.doc_id, "error": str(exc)})
            print(f"  FAILED {topic.doc_id}: {exc}", file=sys.stderr)
            continue
        (settings.kb_dir / f"{doc.doc_id}.md").write_text(render(doc), encoding="utf-8")
        written.append(doc.doc_id)
        print(f"  wrote {doc.doc_id} ({doc.provenance.source_type.value}, "
              f"{len(doc.provenance.source_record_ids)} source records, {len(doc.body.split())} words)")

    topic_entries = {
        doc_id: {"source_records": [r.record_id for r in a.records], "similarities": a.similarities}
        for doc_id, a in assignments.items() if doc_id in written
    }
    if only and REPORT_PATH.exists():  # partial re-run: update the existing report in place
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        topic_entries = {**previous.get("topics", {}), **topic_entries}
    report["topics"] = dict(sorted(topic_entries.items()))
    report["written"], report["failures"] = written, failures
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {len(written)}/{len(topics)} documents to {settings.kb_dir}; report: {REPORT_PATH}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true",
                        help="required: acknowledges that this regenerates (overwrites) KB documents")
    parser.add_argument("--only", nargs="+", metavar="DOC_ID", help="regenerate only these documents")
    parser.add_argument("--min-similarity", type=float, default=0.40)
    parser.add_argument("--max-sources", type=int, default=8)
    args = parser.parse_args(argv)
    if not args.confirm:
        parser.error("refusing to run without --confirm: this overwrites committed KB documents "
                     "with new, non-deterministic LLM output")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return run(get_settings(), set(args.only) if args.only else None, args.min_similarity, args.max_sources)


if __name__ == "__main__":
    sys.exit(main())
