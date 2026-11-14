"""Scripted conversations with deterministic state checks (docs/specs/m7-plan.md §3–§5).

A case file is JSONL; each case is a fresh session:

    {"id": "A1", "type": "unrelated_then_ticket",
     "turns": [{"say": "...", "expect": {...}}, ...]}

`expect` is checked against the ChatSession state after that turn. Every check
is exact or keyword containment on fields; no LLM judges anything:

    intent          str or list of allowed intents
    awaiting        str or null
    escalated       true/false (escalation_reason set or not)
    query_has       keywords that must appear in search_query
    cites           doc_ids, at least one of which must be cited
    draft_has       keywords that must appear in the draft (summary + description)
    draft_lacks     keywords that must not appear in the draft
    draft_empty     true: no draft fields at all
    asks_clarification  true: no retrieval/answer, and either the clarify reply or
                    a ticket start that asks for details with an empty draft
    no_tickets      true: the mock ticket service received no create call
    tickets_created exact number of distinct tickets created so far in the case
    approval_pending  true/false: a ticket summary is waiting for approval (interrupt)
    any_of         list of expect objects; at least one must pass

A keyword "a|b" matches if either alternative appears (case-insensitive).
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from smartdesk.graph import prompts
from smartdesk.graph.session import ChatSession

CHECKS = {"intent", "awaiting", "escalated", "query_has", "cites", "draft_has", "draft_lacks", "draft_empty",
          "asks_clarification", "no_tickets", "tickets_created", "approval_pending", "any_of"}


class Turn(BaseModel):
    say: str
    expect: dict[str, Any] = Field(default_factory=dict)


class Case(BaseModel):
    id: str
    type: str
    turns: list[Turn]
    note: str = ""


def load_cases(path: Path) -> list[Case]:
    cases = [Case(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for case in cases:
        for turn in case.turns:
            _validate_expect(turn.expect, case.id)
    return cases


def _validate_expect(expect: dict, case_id: str) -> None:
    unknown = set(expect) - CHECKS
    if unknown:
        raise ValueError(f"{case_id}: unknown checks {sorted(unknown)}")
    for option in expect.get("any_of", []):
        _validate_expect(option, case_id)


def _matches(keyword: str, text: str) -> bool:
    return any(alternative.lower() in text for alternative in keyword.split("|"))


def draft_text(state: dict) -> str:
    draft = state.get("ticket_draft") or {}
    return f"{draft.get('summary', '')} {draft.get('description', '')}".lower()


def clarification_route(state: dict, reply: str) -> str | None:
    """How SmartDesk asked for clarification, or None if it did not (plan §5)."""
    if state.get("retrieved") or state.get("citations"):
        return None
    if state.get("intent") == "unclear" and prompts.CLARIFY_REPLY in reply:
        return "clarify_reply"
    if (
        state.get("intent") == "create_ticket"
        and state.get("awaiting") == "ticket_details"
        and not state.get("ticket_draft")
        and prompts.ASK_TICKET_DETAILS in reply
    ):
        return "ticket_asks_details"
    return None


def check_turn(expect: dict, state: dict, reply: str, tickets_created: int, approval: bool = False) -> list[str]:
    """Failures for one turn; an empty list means every check passed."""
    failures: list[str] = []
    if "approval_pending" in expect and approval != expect["approval_pending"]:
        failures.append(f"approval pending is {approval}, expected {expect['approval_pending']}")
    if "tickets_created" in expect and tickets_created != expect["tickets_created"]:
        failures.append(f"{tickets_created} ticket(s) created, expected {expect['tickets_created']}")
    if "intent" in expect:
        allowed = expect["intent"] if isinstance(expect["intent"], list) else [expect["intent"]]
        if state.get("intent") not in allowed:
            failures.append(f"intent {state.get('intent')!r} not in {allowed}")
    if "awaiting" in expect and state.get("awaiting") != expect["awaiting"]:
        failures.append(f"awaiting {state.get('awaiting')!r} != {expect['awaiting']!r}")
    if "escalated" in expect and bool(state.get("escalation_reason")) != expect["escalated"]:
        reason = state.get("escalation_reason")
        failures.append(f"escalation_reason {reason!r}, expected escalated={expect['escalated']}")
    query = (state.get("search_query") or "").lower()
    for keyword in expect.get("query_has", []):
        if not _matches(keyword, query):
            failures.append(f"search_query {query!r} lacks {keyword!r}")
    if "cites" in expect:
        cited = {c["doc_id"] for c in state.get("citations") or []}
        if not cited & set(expect["cites"]):
            failures.append(f"cited {sorted(cited)}, expected one of {expect['cites']}")
    text = draft_text(state)
    for keyword in expect.get("draft_has", []):
        if not _matches(keyword, text):
            failures.append(f"draft lacks {keyword!r}: {text!r}")
    for keyword in expect.get("draft_lacks", []):
        if _matches(keyword, text):
            failures.append(f"draft contains {keyword!r}: {text!r}")
    if expect.get("draft_empty") and state.get("ticket_draft"):
        failures.append(f"draft not empty: {state.get('ticket_draft')}")
    if expect.get("asks_clarification") and clarification_route(state, reply) is None:
        failures.append(f"did not ask for clarification (intent {state.get('intent')!r}, reply {reply[:80]!r})")
    if expect.get("no_tickets") and tickets_created:
        failures.append(f"{tickets_created} ticket(s) created")
    if "any_of" in expect:
        options = [check_turn(option, state, reply, tickets_created, approval) for option in expect["any_of"]]
        if all(options):
            failures.append("no any_of option passed: " + " / ".join("; ".join(o) for o in options))
    return failures


@dataclass
class TurnRecord:
    say: str
    reply: str
    intent: str | None
    failures: list[str]
    clarification_route: str | None = None


@dataclass
class CaseResult:
    id: str
    type: str
    passed: bool
    turns: list[TurnRecord] = field(default_factory=list)
    error: str | None = None


# (thread_id) -> (session, number of tickets created so far)
SessionFactory = Callable[[str], tuple[ChatSession, Callable[[], int]]]


def run_case(case: Case, make_session: SessionFactory, timed: Callable | None = None) -> CaseResult:
    session, tickets_created = make_session(f"eval-{case.id}")
    result = CaseResult(case.id, case.type, passed=True)
    for turn in case.turns:
        if timed:
            with timed():
                turn_result = session.send(turn.say)
        else:
            turn_result = session.send(turn.say)
        state, reply = turn_result.state, turn_result.text
        failures = check_turn(turn.expect, state, reply, tickets_created(), turn_result.approval is not None)
        if turn_result.error and turn.expect:
            failures.append(f"turn error: {turn_result.error}")
        route = clarification_route(state, reply)
        result.turns.append(TurnRecord(turn.say, reply, state.get("intent"), failures, route))
        if failures:
            result.passed = False
    return result


def summarize(results: list[CaseResult]) -> dict:
    by_type: dict[str, dict] = {}
    for kind in dict.fromkeys(r.type for r in results):
        group = [r for r in results if r.type == kind]
        by_type[kind] = {
            "passed": sum(r.passed for r in group),
            "total": len(group),
            "rate": round(sum(r.passed for r in group) / len(group), 3),
            "failed_ids": [r.id for r in group if not r.passed],
        }
    routes = Counter(t.clarification_route for r in results for t in r.turns if t.clarification_route)
    return {"by_type": by_type, "clarification_routes": dict(routes)}


def run_cases(cases: list[Case], make_session: SessionFactory, *, timed: Callable | None = None,
              stop: Callable[[], bool] = lambda: False) -> tuple[list[CaseResult], bool]:
    """Run cases in order; returns (results, complete).

    `stop()` (the budget flag) is checked after each case: a case it interrupted
    is dropped rather than scored, because its failure says nothing about the agent.
    """
    results = []
    for case in cases:
        result = run_case(case, make_session, timed)
        if stop():
            return results, False
        results.append(result)
    return results, True


def results_payload(results: list[CaseResult], complete: bool, extra: dict) -> dict:
    return {**extra, "complete": complete, "summary": summarize(results), "cases": [asdict(r) for r in results]}
