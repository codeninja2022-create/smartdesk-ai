import pytest
from langchain_core.runnables import RunnableLambda

from smartdesk.kb import generate
from smartdesk.kb.catalog import GAPS, TOPICS
from smartdesk.kb.documents import SourceType
from smartdesk.kb.sources import SourceRecord

TOPIC_A, TOPIC_B = TOPICS[0], TOPICS[1]


def _vector_embed(mapping: dict[str, list[float]]):
    """Embed by prefix lookup so tests control similarities exactly."""
    def embed(texts):
        return [next(v for prefix, v in mapping.items() if text.startswith(prefix)) for text in texts]
    return embed


def test_assign_sources_routes_records_to_best_topic_and_drops_gap_matches():
    embed = _vector_embed({
        TOPIC_A.title: [1, 0, 0], TOPIC_B.title: [0, 1, 0],
        **{g.description: [0, 0, 1] for g in GAPS},
        "rec-a": [0.9, 0.1, 0], "rec-b": [0.1, 0.9, 0], "rec-gap": [0, 0.1, 0.9], "rec-weak": [0.3, 0.3, 0.9],
    })
    records = [SourceRecord(rid, "it_tickets", rid) for rid in ("rec-a", "rec-b", "rec-gap", "rec-weak")]

    assigned, stats = generate.assign_sources([TOPIC_A, TOPIC_B], records, embed, min_similarity=0.5, max_per_topic=5)

    assert [r.record_id for r in assigned[TOPIC_A.doc_id].records] == ["rec-a"]
    assert [r.record_id for r in assigned[TOPIC_B.doc_id].records] == ["rec-b"]
    assert stats["dropped_gap_semantic"] == 2 and stats["assigned"] == 2


def test_assign_sources_applies_threshold_and_per_topic_limit():
    embed = _vector_embed({
        TOPIC_A.title: [1, 0], **{g.description: [0, 1] for g in GAPS},
        "r1": [1, 0.05], "r2": [1, 0.1], "r3": [1, 0.2], "low": [0.6, 0.5],
    })
    records = [SourceRecord(rid, "it_tickets", rid) for rid in ("r1", "r2", "r3", "low")]

    assigned, stats = generate.assign_sources([TOPIC_A], records, embed, min_similarity=0.8, max_per_topic=2)

    assert [r.record_id for r in assigned[TOPIC_A.doc_id].records] == ["r1", "r2"]
    assert stats == {"assigned": 2, "dropped_gap_semantic": 0, "below_threshold": 1, "over_topic_limit": 1}


def _long_body(extra: str = "") -> str:
    return "# T\n\n" + "word " * 300 + extra


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (_long_body("Check the printer."), "out-of-scope"),
        (_long_body("See https://www.cisco.com/download"), "not in the fact sheet"),
        ("# T\n\ntoo short", "too short"),
    ],
)
def test_validate_body_rejections(body, reason):
    assert reason in generate.validate_body(body)


def test_validate_body_accepts_fact_sheet_urls():
    assert generate.validate_body(_long_body("Visit https://passwords.novatech.example.")) is None


class _ScriptedWriter:
    def __init__(self, drafts):
        self.drafts = list(drafts)
        self.prompts = []

    def with_structured_output(self, schema):
        def invoke(messages):
            self.prompts.append(messages[-1].content)
            return self.drafts.pop(0)
        return RunnableLambda(invoke)


def _draft(text: str) -> generate.GeneratedDoc:
    return generate.GeneratedDoc(
        summary=text,
        sections=[generate.Section(heading=f"S{i}", body="word " * 100) for i in range(3)],
        faqs=[generate.FAQ(question=f"Q{i}?", answer="A.") for i in range(4)],
    )


def test_generate_document_retries_with_feedback_after_rejection():
    llm = _ScriptedWriter([_draft("Ask about parking."), _draft("A clean summary.")])
    doc = generate.generate_document(llm, generate.TopicSources(TOPIC_A), "gpt-test", "2026-10-31")

    assert "parking" not in doc.body
    assert "previous draft was rejected" in llm.prompts[1]
    assert doc.provenance.source_type is SourceType.SYNTHETIC
    assert doc.body.startswith(f"# {TOPIC_A.title}")


def test_generate_document_records_provenance_of_source_records():
    records = [SourceRecord("it_tickets:abc", "it_tickets", "VPN down")]
    llm = _ScriptedWriter([_draft("Fine.")])
    doc = generate.generate_document(llm, generate.TopicSources(TOPIC_A, records), "gpt-test", "2026-10-31")

    assert doc.provenance.source_type is SourceType.DATASET_DERIVED
    assert doc.provenance.source_record_ids == ["it_tickets:abc"]
    assert doc.provenance.datasets == ["Console-AI/IT-helpdesk-synthetic-tickets@165693849d95"]


def test_generate_document_gives_up_after_max_attempts():
    llm = _ScriptedWriter([_draft("parking")] * generate.MAX_ATTEMPTS)
    with pytest.raises(RuntimeError, match="rejected after"):
        generate.generate_document(llm, generate.TopicSources(TOPIC_A), "gpt-test", "2026-10-31")


def test_cli_refuses_to_run_without_confirm(capsys):
    with pytest.raises(SystemExit) as exc:
        generate.main([])
    assert exc.value.code == 2
    assert "--confirm" in capsys.readouterr().err
