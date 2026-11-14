import uuid

import chromadb
import pytest

from smartdesk.kb.vectorstore import get_collection
from smartdesk.rag.retriever import Retriever

pytestmark = pytest.mark.rubric("A3", "M7-RET")


def unit(*xs):
    return [float(x) for x in xs]


@pytest.fixture
def collection():
    """Three chunks in 2-D: IT at 0°, HR at ~10° and ~90° from the IT axis."""
    collection = get_collection(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex[:8]}")
    rows = [
        ("it-vpn-setup#section-a", unit(1, 0), "IT", "VPN Setup"),
        ("hr-leave-policy#section-a", unit(1, 0.18), "HR", "Leave Policy"),
        ("hr-hybrid-work#section-a", unit(0, 1), "HR", "Hybrid Work"),
    ]
    collection.add(
        ids=[r[0] for r in rows],
        embeddings=[r[1] for r in rows],
        documents=[f"{r[3]} > A\n\ntext" for r in rows],
        metadatas=[
            {"doc_id": r[0].split("#")[0], "title": r[3], "section": "A", "domain": r[2]} for r in rows
        ],
    )
    return collection


def retriever(collection, vector, fallback=0.35, k=5):
    return Retriever(collection, lambda query: vector, top_k=k, domain_fallback_similarity=fallback)


def test_unfiltered_search_ranks_by_similarity(collection):
    hits = retriever(collection, unit(1, 0)).retrieve("q")
    assert [h.doc_id for h in hits] == ["it-vpn-setup", "hr-leave-policy", "hr-hybrid-work"]
    assert hits[0].similarity == pytest.approx(1.0)
    assert (hits[0].title, hits[0].section, hits[0].domain) == ("VPN Setup", "A", "IT")


def test_domain_hint_restricts_the_search(collection):
    hits = retriever(collection, unit(1, 0)).retrieve("q", domain="HR")
    assert [h.doc_id for h in hits] == ["hr-leave-policy", "hr-hybrid-work"]


def test_weak_domain_results_fall_back_to_the_whole_kb(collection):
    # Pointing straight at the IT chunk, but hinted as HR with a fallback bar above
    # the best HR score (cos ~10° = 0.98): the hint is ignored.
    hits = retriever(collection, unit(1, 0), fallback=0.99).retrieve("q", domain="HR")
    assert hits[0].doc_id == "it-vpn-setup"


def test_unknown_domain_hint_is_ignored(collection):
    hits = retriever(collection, unit(1, 0)).retrieve("q", domain="Finance")
    assert hits[0].doc_id == "it-vpn-setup"


def test_top_k_limits_results(collection):
    assert len(retriever(collection, unit(1, 0), k=2).retrieve("q")) == 2


def test_empty_collection_returns_nothing():
    empty = get_collection(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex[:8]}")
    assert retriever(empty, unit(1, 0)).retrieve("q", domain="IT") == []


def test_chunks_serialise_to_builtin_types(collection):
    chunk = retriever(collection, unit(1, 0)).retrieve("q")[0].to_dict()
    assert set(chunk) == {"chunk_id", "doc_id", "title", "section", "domain", "text", "similarity"}
    assert all(type(v) in (str, float) for v in chunk.values())
