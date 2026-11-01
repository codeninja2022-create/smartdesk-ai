"""Integrity checks on the committed knowledge base and evaluation set."""

from pathlib import Path

import pytest

from smartdesk.kb.catalog import GAPS, TOPICS, find_gap_mentions
from smartdesk.kb.documents import Domain, load_dir
from smartdesk.kb.evaluate import EVAL_PATH, EvalCategory, RetrievalResult, compute_metrics, load_eval_set
from smartdesk.kb.generate import validate_body

KB_DIR = Path("data/kb")


@pytest.fixture(scope="module")
def docs():
    return load_dir(KB_DIR)


@pytest.fixture(scope="module")
def eval_set():
    return load_eval_set()


def test_kb_has_30_to_50_documents_covering_every_topic(docs):
    assert 30 <= len(docs) <= 50
    assert {d.doc_id for d in docs} == {t.doc_id for t in TOPICS}
    assert {d.domain for d in docs} == {Domain.IT, Domain.HR}


def test_kb_documents_pass_generation_validation(docs):
    failures = {d.doc_id: reason for d in docs if (reason := validate_body(d.body))}
    assert failures == {}


def test_kb_documents_never_mention_gap_topics(docs):
    assert {d.doc_id: find_gap_mentions(d.body) for d in docs if find_gap_mentions(d.body)} == {}


def test_kb_documents_carry_provenance(docs):
    for doc in docs:
        assert doc.provenance.generator_model and doc.provenance.generated_at
        if doc.provenance.source_record_ids:
            assert doc.provenance.datasets


def test_eval_set_is_separate_from_kb():
    assert KB_DIR.resolve() not in EVAL_PATH.resolve().parents
    assert not list(KB_DIR.glob("*.jsonl"))


def test_eval_set_covers_all_categories_and_gaps(eval_set):
    categories = {item.category for item in eval_set}
    assert categories == set(EvalCategory)
    assert {item.gap_id for item in eval_set if item.gap_id} == {g.gap_id for g in GAPS}
    assert len({item.id for item in eval_set}) == len(eval_set)


def test_eval_expected_doc_ids_exist(eval_set, docs):
    known = {d.doc_id for d in docs}
    assert {doc_id for item in eval_set for doc_id in item.expected_doc_ids} <= known


def test_compute_metrics(eval_set):
    answerable = [i for i in eval_set if i.category == EvalCategory.ANSWERABLE][:2]
    gap = next(i for i in eval_set if i.category == EvalCategory.GAP)
    results = [
        RetrievalResult(answerable[0], [answerable[0].expected_doc_ids[0], "x"], 0.6),
        RetrievalResult(answerable[1], ["x", "y"], 0.5),
        RetrievalResult(gap, ["x"], 0.3),
    ]
    m = compute_metrics(results, k=5)
    assert (m.answerable, m.hit_at_1, m.recall_at_k, m.mrr) == (2, 0.5, 0.5, 0.5)
    assert m.misses == [answerable[1].id]
    assert m.top_similarity["gap"] == {"min": 0.3, "median": 0.3, "max": 0.3}
