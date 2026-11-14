import pytest

from smartdesk.kb.chunking import MAX_TOKENS, chunk_document, count_tokens
from tests.kb_helpers import make_doc

pytestmark = pytest.mark.rubric("A2")


def test_splits_into_overview_sections_and_individual_faqs():
    chunks = chunk_document(make_doc())

    assert [c.metadata["chunk_type"] for c in chunks] == ["overview", "section", "faq", "faq"]
    assert [c.chunk_id for c in chunks] == [
        "it-sample#overview-overview",
        "it-sample#section-steps",
        "it-sample#faq-how-long-does-it-take",
        "it-sample#faq-who-do-i-contact",
    ]


def test_chunks_carry_context_header_and_metadata():
    faq = chunk_document(make_doc())[2]

    assert faq.text == "Sample Article > FAQ\n\nQ: How long does it take?\nA: Five minutes."
    assert faq.metadata["doc_id"] == "it-sample"
    assert faq.metadata["domain"] == "IT"
    assert faq.metadata["section"] == "How long does it take?"
    assert len(faq.metadata["content_hash"]) == 16


def test_chunk_ids_are_stable_across_runs():
    assert [c.chunk_id for c in chunk_document(make_doc())] == [c.chunk_id for c in chunk_document(make_doc())]


def test_long_sections_are_split_with_overlap_and_stay_under_limit():
    paragraphs = [f"Paragraph {i}. " + "detail " * 60 for i in range(8)]
    body = "# Sample Article\n\nIntro.\n\n## Long\n\n" + "\n\n".join(paragraphs)

    parts = [c for c in chunk_document(make_doc(body=body)) if c.metadata["section"] == "Long"]

    assert len(parts) > 1
    assert all(c.chunk_id.startswith("it-sample#section-long-p") for c in parts)
    assert all(count_tokens(c.text) <= MAX_TOKENS for c in parts)
    first_tail = parts[0].text.split("\n\n")[-1]
    assert parts[1].text.split("\n\n")[1] == first_tail  # previous paragraph carried over


def test_repeated_headings_get_unique_ids():
    body = "# Sample Article\n\nIntro.\n\n## Notes\n\nOne.\n\n## Notes\n\nTwo."
    ids = [c.chunk_id for c in chunk_document(make_doc(body=body))]
    assert "it-sample#section-notes" in ids and "it-sample#section-notes-2" in ids
