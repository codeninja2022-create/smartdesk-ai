import pytest

from smartdesk.rag.calibrate import ItemResult, escalation_metrics, outcome_metrics, recommend_threshold

pytestmark = pytest.mark.rubric("A5", "M7-ESC")


def item(category, top, sufficient, id_="x", intent="knowledge_question"):
    return ItemResult(
        id=id_, category=category, question="q", expected_doc_ids=[], intent=intent,
        domain="IT", search_query="q", top_similarity=top, ranked_doc_ids=[], ranked_doc_ids_unfiltered=[],
        sufficient=sufficient,
    )


RESULTS = [
    item("answerable", 0.60, True),
    item("answerable", 0.41, True),
    item("answerable", 0.70, False),  # LLM wrongly abstains
    item("gap", 0.30, False),
    item("gap", 0.45, True),  # LLM wrongly answers; only a high threshold catches it
]


def test_escalation_combines_threshold_and_llm_verdict():
    assert item("gap", 0.30, True).escalates(0.35)
    assert item("gap", 0.50, False).escalates(0.35)
    assert not item("answerable", 0.50, True).escalates(0.35)


def test_escalation_metrics_treat_gap_as_positive():
    m = escalation_metrics(RESULTS, 0.35)
    assert (m["gap_escalated"], m["answerable_escalated"]) == ("1/2", "1/3")
    assert (m["precision"], m["recall"]) == (0.5, 0.5)
    assert (m["gap_escalated_by_threshold"], m["answerable_escalated_by_threshold"]) == (1, 0)


def test_higher_threshold_trades_answerable_recall_for_gap_recall():
    m = escalation_metrics(RESULTS, 0.50)
    assert (m["gap_escalated"], m["answerable_escalated"]) == ("2/2", "2/3")
    assert m["recall"] == 1.0 and m["precision"] == pytest.approx(0.5)


def test_end_to_end_outcome_applies_routing_before_the_rag_decision():
    results = [
        item("gap", 0.60, True, "g1", intent="out_of_scope"),  # misrouted: declined, not escalated
        item("gap", 0.60, True, "g2", intent="create_ticket"),  # straight to the ticket flow
        item("gap", 0.30, False, "g3"),
        item("answerable", 0.60, True, "a1"),
        item("out_of_scope", 0.10, False, "o1", intent="out_of_scope"),
        item("greeting", 0.0, False, "h1", intent="greeting"),
    ]
    m = outcome_metrics(results, 0.35)
    assert m["gap"] == {"expected": "escalate", "correct": "2/3", "wrong": {"g1": "decline"}}
    assert m["answerable"]["correct"] == "1/1"
    assert m["out_of_scope"]["correct"] == m["greeting"]["correct"] == "1/1"


def test_recommended_threshold_keeps_a_margin_below_the_lowest_answerable_score():
    assert recommend_threshold(RESULTS) == 0.36  # 0.41 - 0.05
