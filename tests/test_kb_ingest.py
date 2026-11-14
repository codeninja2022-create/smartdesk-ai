import uuid

import chromadb
import pytest

from smartdesk.kb.documents import render
from smartdesk.kb.ingest import IngestReport, ingest, load_documents
from smartdesk.kb.vectorstore import get_collection, search
from tests.kb_helpers import fake_embed, make_doc

pytestmark = pytest.mark.rubric("A2")


class CountingEmbed:
    def __init__(self):
        self.calls = 0
        self.texts = 0

    def __call__(self, texts):
        self.calls += 1
        self.texts += len(texts)
        return fake_embed(texts)


@pytest.fixture
def collection():
    return get_collection(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex[:8]}")


def test_first_ingest_embeds_every_chunk(collection):
    embed, report = CountingEmbed(), IngestReport()
    ingest([make_doc("it-a"), make_doc("hr-b")], collection, embed, report)

    assert (report.documents, report.chunks, report.embedded, report.unchanged) == (2, 8, 8, 0)
    assert collection.count() == 8


def test_reingest_is_idempotent_and_skips_unchanged_chunks(collection):
    docs = [make_doc("it-a"), make_doc("hr-b")]
    ingest(docs, collection, CountingEmbed(), IngestReport())

    embed, report = CountingEmbed(), IngestReport()
    ingest(docs, collection, embed, report)

    assert embed.texts == 0
    assert (report.embedded, report.unchanged, report.deleted) == (0, 8, 0)
    assert collection.count() == 8


def test_changed_chunks_are_re_embedded_and_removed_ones_deleted(collection):
    ingest([make_doc("it-a"), make_doc("hr-b")], collection, CountingEmbed(), IngestReport())
    edited = make_doc("it-a", body="# Sample Article\n\nNew overview.\n\n## Steps\n\n1. Do this.\n2. Then that.")

    embed, report = CountingEmbed(), IngestReport()
    ingest([edited], collection, embed, report)

    assert embed.texts == 1  # only the edited overview
    assert report.deleted == 6  # it-a's two FAQs + all four hr-b chunks
    assert {m["doc_id"] for m in collection.get()["metadatas"]} == {"it-a"}


def test_embedding_failures_are_reported_not_raised(collection):
    def broken(texts):
        raise TimeoutError("embedding API timed out")

    report = IngestReport()
    ingest([make_doc("it-a")], collection, broken, report)

    assert report.embedded == 0
    assert "timed out" in report.failures[0]


def test_load_documents_collects_invalid_files(tmp_path):
    (tmp_path / "it-a.md").write_text(render(make_doc("it-a")), encoding="utf-8")
    (tmp_path / "it-broken.md").write_text("no front matter", encoding="utf-8")

    report = IngestReport()
    docs = load_documents(tmp_path, report)

    assert [d.doc_id for d in docs] == ["it-a"]
    assert report.failures and report.failures[0].startswith("it-broken.md")


def test_search_returns_similarity_scores(collection):
    ingest([make_doc("it-a")], collection, fake_embed, IngestReport())
    query = fake_embed(["Sample Article > Steps\n\n1. Do this.\n2. Then that."])[0]

    hits = search(collection, query, k=2)

    assert hits[0].chunk_id == "it-a#section-steps"
    assert hits[0].similarity == pytest.approx(1.0, abs=1e-3)
    assert search(get_collection(chromadb.EphemeralClient(), "empty-coll"), query) == []
