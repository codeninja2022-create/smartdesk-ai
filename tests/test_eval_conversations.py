"""Offline tests for the M7 conversation runner, case files and held-out run rules."""

import json
from pathlib import Path

import pytest

from smartdesk.eval.conversations import (
    Case,
    check_turn,
    clarification_route,
    load_cases,
    run_cases,
    summarize,
)
from smartdesk.eval.harness import BudgetExceeded
from smartdesk.eval.mock_tickets import MockTicketService
from smartdesk.graph import prompts
from smartdesk.graph.state import Intent
from smartdesk.graph.tickets import TicketFieldsUpdate
from smartdesk.kb.evaluate import HELDOUT_PATH, EvalCategory, EvalItem, load_eval_set
from smartdesk.rag import calibrate
from smartdesk.tickets.models import TicketDraft
from tests.conftest import FakeLLM
from tests.graph_helpers import make_session

MULTITURN = Path("data/eval/multiturn.jsonl")
UNCLEAR = Path("data/eval/unclear.jsonl")


# --- case files ---


@pytest.mark.rubric("D2", "M7-MULTI")
def test_multiturn_file_has_six_cases_of_each_type():
    cases = load_cases(MULTITURN)
    counts = {kind: sum(c.type == kind for c in cases) for kind in {c.type for c in cases}}
    assert sorted(counts) == ["A_unrelated_then_ticket", "B_ticket_for_it", "C_held_draft_new_request",
                              "D_earlier_turn_follow_up"]
    assert set(counts.values()) == {6}
    assert len({c.id for c in cases}) == len(cases)


@pytest.mark.rubric("D2", "M7-MULTI")
def test_multiturn_c_cases_include_the_k18_reask_and_never_create_the_held_draft_before_new():
    cases = {c.id: c for c in load_cases(MULTITURN) if c.type.startswith("C_")}
    reask = cases["C2"].turns
    assert [t.expect.get("awaiting") for t in reask[2:4]] == ["held_draft", "held_draft"]
    assert reask[-1].say == "new" and reask[-1].expect["no_tickets"]


@pytest.mark.rubric("D3", "M7-INTENT")
def test_unclear_file_has_the_nine_written_cases():
    cases = load_cases(UNCLEAR)
    assert [c.id for c in cases] == [f"U{n}" for n in range(1, 10)]
    for case in cases[:8]:
        assert len(case.turns) == 1 and case.turns[0].expect == {"asks_clarification": True, "no_tickets": True}
    assert [t.say for t in cases[8].turns][1] == "same issue as before"
    assert cases[7].turns[0].say == "same issue as before"


def test_unknown_check_names_are_rejected(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "X", "type": "t", "turns": [{"say": "hi", "expect": {"intnet": "x"}}]}))
    with pytest.raises(ValueError, match="intnet"):
        load_cases(path)


# --- checks ---

DRAFT_STATE = {
    "intent": "create_ticket",
    "ticket_draft": {"summary": "Laptop request", "description": "Needs a new laptop"},
}


@pytest.mark.parametrize(("expect", "passes"), [
    ({"intent": "create_ticket"}, True),
    ({"intent": ["knowledge_question", "create_ticket"]}, True),
    ({"intent": "knowledge_question"}, False),
    ({"draft_has": ["laptop"]}, True),
    ({"draft_has": ["monitor|laptop"]}, True),
    ({"draft_has": ["monitor"]}, False),
    ({"draft_lacks": ["monitor", "sick"]}, True),
    ({"draft_lacks": ["LAPTOP"]}, False),
    ({"draft_empty": True}, False),
    ({"awaiting": None}, True),
    ({"awaiting": "held_draft"}, False),
    ({"escalated": False}, True),
    ({"escalated": True}, False),
    ({"any_of": [{"intent": "greeting"}, {"draft_has": ["laptop"]}]}, True),
    ({"any_of": [{"intent": "greeting"}, {"draft_has": ["monitor"]}]}, False),
])
def test_draft_and_intent_checks(expect: dict, passes: bool):
    assert (check_turn(expect, DRAFT_STATE, "", 0) == []) is passes


def test_query_and_citation_checks():
    state = {"search_query": "VPN setup on macOS", "citations": [{"doc_id": "it-vpn-setup"}]}
    assert check_turn({"query_has": ["vpn"], "cites": ["it-vpn-setup", "x"]}, state, "", 0) == []
    assert check_turn({"query_has": ["wifi"]}, state, "", 0)
    assert check_turn({"cites": ["it-mfa-setup"]}, state, "", 0)
    assert check_turn({"query_has": ["vpn"]}, {"search_query": None}, "", 0)


def test_ticket_count_and_approval_checks():
    assert check_turn({"no_tickets": True, "tickets_created": 0}, {}, "", 0) == []
    assert check_turn({"no_tickets": True}, {}, "", 1)
    assert check_turn({"tickets_created": 1}, {}, "", 2)
    assert check_turn({"approval_pending": True}, {}, "", 0, approval=True) == []
    assert check_turn({"approval_pending": True}, {}, "", 0, approval=False)


@pytest.mark.rubric("D3", "M7-INTENT")
def test_clarification_passes_via_the_clarify_reply():
    state = {"intent": "unclear", "retrieved": [], "citations": [], "ticket_draft": {}}
    assert clarification_route(state, prompts.CLARIFY_REPLY) == "clarify_reply"
    assert check_turn({"asks_clarification": True}, state, prompts.CLARIFY_REPLY, 0) == []


@pytest.mark.rubric("D3", "M7-INTENT")
def test_clarification_passes_via_a_ticket_start_that_asks_for_details_with_an_empty_draft():
    state = {"intent": "create_ticket", "awaiting": "ticket_details", "ticket_draft": {}, "retrieved": []}
    assert clarification_route(state, prompts.ASK_TICKET_DETAILS) == "ticket_asks_details"


@pytest.mark.rubric("D3", "M7-INTENT")
@pytest.mark.parametrize("state", [
    # a ticket start that already drafted a field (plan §5: fails)
    {"intent": "create_ticket", "awaiting": "ticket_details", "ticket_draft": {"category": "IT"}, "retrieved": []},
    # retrieved something
    {"intent": "unclear", "retrieved": [{"doc_id": "it-vpn-setup"}]},
    # answered with citations
    {"intent": "knowledge_question", "retrieved": [], "citations": [{"doc_id": "x"}]},
    # escalated knowledge question with no retrieval is still not a clarification
    {"intent": "knowledge_question", "retrieved": []},
])
def test_clarification_fails_when_anything_was_retrieved_answered_or_drafted(state: dict):
    reply = prompts.ASK_TICKET_DETAILS if state["intent"] == "create_ticket" else prompts.CLARIFY_REPLY
    assert clarification_route(state, reply) is None
    assert check_turn({"asks_clarification": True}, state, reply, 0)


@pytest.mark.rubric("D3", "M7-INTENT")
def test_clarification_fails_with_a_different_reply():
    state = {"intent": "unclear", "retrieved": []}
    assert check_turn({"asks_clarification": True}, state, "Here is how to reset it.", 0)


# --- runner, through the real graph with fakes ---

EMAIL = "alex.kim@acme-demo.com"
TICKET_TEXT = f"Please raise a ticket: my laptop won't charge. My email is {EMAIL}"


def _factory(llm: FakeLLM, services: list):
    def make(thread_id: str):
        service = MockTicketService()
        services.append(service)
        return make_session(llm, service, thread_id=thread_id), lambda: service.created_count

    return make


@pytest.mark.rubric("D2", "D3", "M7-MULTI")
def test_runner_passes_a_clarify_case_and_a_ticket_case_end_to_end():
    llm = FakeLLM(
        {"it's broken": Intent.UNCLEAR, TICKET_TEXT: Intent.CREATE_TICKET},
        tickets_by_text={TICKET_TEXT: TicketFieldsUpdate(description="Laptop won't charge", category="IT")},
    )
    cases = [
        Case(id="U", type="unclear", turns=[{"say": "it's broken", "expect": {"asks_clarification": True}}]),
        Case(id="T", type="ticket", turns=[
            {"say": TICKET_TEXT, "expect": {"approval_pending": True, "draft_has": ["charge"], "no_tickets": True}},
            {"say": "approve", "expect": {"tickets_created": 1, "approval_pending": False}},
        ]),
    ]
    services: list[MockTicketService] = []
    results, complete = run_cases(cases, _factory(llm, services))
    assert complete
    assert [r.passed for r in results] == [True, True], [t.failures for r in results for t in r.turns]
    assert results[0].turns[0].clarification_route == "clarify_reply"
    assert len(services[1].create_calls) == 1 and isinstance(services[1].create_calls[0][0], TicketDraft)
    summary = summarize(results)
    assert summary["by_type"]["ticket"] == {"passed": 1, "total": 1, "rate": 1.0, "failed_ids": []}
    assert summary["clarification_routes"] == {"clarify_reply": 1}


def test_runner_reports_a_failing_case_with_its_reason():
    llm = FakeLLM({"it's broken": Intent.KNOWLEDGE_QUESTION})
    case = Case(id="U", type="unclear", turns=[{"say": "it's broken", "expect": {"asks_clarification": True}}])
    results, _ = run_cases([case], _factory(llm, []))
    assert not results[0].passed
    assert "did not ask for clarification" in results[0].turns[0].failures[0]


def test_a_case_interrupted_by_the_budget_is_dropped_and_the_run_marked_incomplete():
    llm = FakeLLM({"hi": Intent.GREETING})
    cases = [Case(id=f"G{n}", type="g", turns=[{"say": "hi", "expect": {"intent": "greeting"}}]) for n in range(3)]
    stopped = iter([False, True])  # the budget trips during the second case
    results, complete = run_cases(cases, _factory(llm, []), stop=lambda: next(stopped, True))
    assert not complete and [r.id for r in results] == ["G0"]


def test_mock_ticket_service_counts_a_repeated_op_id_once():
    service = MockTicketService()
    draft = TicketDraft(email=EMAIL, summary="s", description="d", category="IT")
    first, again = service.create_ticket(draft, "op-1"), service.create_ticket(draft, "op-1")
    assert first.key == again.key and again.already_existed and service.created_count == 1


# --- held-out run rules (calibrate) ---


def _item(n: int) -> EvalItem:
    return EvalItem(id=f"ho-{n:02d}", category=EvalCategory.GREETING, question="hi", expected_doc_ids=[],
                    expected_behavior="greet")


def _result(item: EvalItem) -> calibrate.ItemResult:
    return calibrate.ItemResult(id=item.id, category=item.category.value, question=item.question,
                                expected_doc_ids=[], intent="greeting", domain="unknown", search_query="",
                                top_similarity=0.0, ranked_doc_ids=[], ranked_doc_ids_unfiltered=[])


@pytest.mark.rubric("A3", "A5")
def test_heldout_is_refused_once_marked_or_from_uncommitted_code(tmp_path: Path):
    marker = tmp_path / "RUN.json"
    assert calibrate.heldout_refusal(marker, dirty=False) is None
    assert "uncommitted" in calibrate.heldout_refusal(marker, dirty=True)
    marker.write_text("{}")
    assert "already been scored" in calibrate.heldout_refusal(marker, dirty=False)


@pytest.mark.rubric("A3", "A5")
def test_a_crashed_heldout_run_leaves_no_marker_so_a_rerun_is_allowed(tmp_path: Path):
    marker = tmp_path / "RUN.json"

    def crash_on_second(item: EvalItem):
        if item.id == "ho-02":
            raise RuntimeError("network down")
        return _result(item)

    with pytest.raises(RuntimeError):
        calibrate.score_items([_item(1), _item(2), _item(3)], crash_on_second)
    assert not marker.exists() and calibrate.heldout_refusal(marker) is None


@pytest.mark.rubric("A3", "A5")
def test_a_budget_stopped_heldout_run_is_incomplete_and_writes_no_marker(tmp_path: Path):
    marker = tmp_path / "RUN.json"

    def over_budget_on_second(item: EvalItem):
        if item.id == "ho-02":
            raise BudgetExceeded("spent")
        return _result(item)

    results, complete = calibrate.score_items([_item(1), _item(2), _item(3)], over_budget_on_second)
    assert [r.id for r in results] == ["ho-01"] and not complete
    assert calibrate.finish_heldout(marker, complete, {"x": 1}) is False
    assert not marker.exists() and calibrate.heldout_refusal(marker) is None


@pytest.mark.rubric("A3", "A5")
def test_a_complete_heldout_run_writes_the_marker_and_blocks_a_rerun(tmp_path: Path):
    marker = tmp_path / "RUN.json"
    results, complete = calibrate.score_items([_item(1), _item(2)], _result)
    assert complete and len(results) == 2
    assert calibrate.finish_heldout(marker, complete, {"items": [r.id for r in results]})
    assert json.loads(marker.read_text()) == {"items": ["ho-01", "ho-02"]}
    assert calibrate.heldout_refusal(marker) is not None


@pytest.mark.rubric("A3", "A5")
def test_heldout_fresh_and_seen_subsets_match_the_documented_history():
    ids = [item.id for item in load_eval_set(HELDOUT_PATH)]
    fresh = [i for i in ids if calibrate.is_fresh_heldout(i)]
    assert len(ids) == 32 and len(fresh) == 11
    assert fresh == [f"ho-{n}" for n in range(22, 33)]
    subsets = calibrate.heldout_subsets([_result(_item(n)) for n in (1, 21, 22, 32)], threshold=0.35)
    assert [s["items_evaluated"] for s in subsets.values()] == [2, 2]
