"""Ticket creation: slot-filling, human approval via interrupt(), and submission.

    collect_ticket -> (a field is missing: ask for it) -> END
                   -> present_ticket -> review_ticket --interrupt()--> approve -> submit_ticket -> END
                                             ^                      -> edit    -> present_ticket
                                             |                      -> cancel  -> END
                                             |                      -> message -> classify_intent

Approval is bound to an op_id, which hashes the session and the exact draft
(`derive_op_id`). Any edit changes the op_id, so an earlier approval can never
create an edited ticket. `submit_ticket` checks the binding again before it
calls Jira, and it is the only node that creates tickets.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, ValidationError

from smartdesk.graph import prompts
from smartdesk.graph.session import normalize_reply
from smartdesk.graph.state import Intent, SmartDeskState
from smartdesk.llm import StructuredLLM
from smartdesk.tickets.models import (
    JiraAuthError,
    JiraError,
    JiraRequestRejected,
    JiraUnavailable,
    TicketCreationUncertain,
    TicketDraft,
    derive_op_id,
)
from smartdesk.tickets.service import TicketService

log = logging.getLogger(__name__)

COLLECT_TICKET, PRESENT_TICKET, REVIEW_TICKET, SUBMIT_TICKET = (
    "collect_ticket", "present_ticket", "review_ticket", "submit_ticket"
)
EDITABLE_FIELDS = ("summary", "description", "category", "priority")
_HISTORY_MESSAGES = 20
_SUMMARY_FALLBACK_CHARS = 80
_PLACEHOLDER = dict(email="placeholder@example.com", summary="x", description="x", category="IT")
_DATA_TAGS = re.compile(r"</?\s*(?:conversation|message)[^>]*>", re.I)
# Exact answers to the held-draft question, matched like approve/cancel (graph/session.py).
# A request that is itself a continue phrase ("try again") resumes without asking.
CONTINUE_WORDS = {
    "continue", "continue it", "continue that one", "continue that", "continue my ticket", "continue the ticket",
    "continue that ticket", "continue the old one", "continue the draft", "resume", "resume my ticket",
    "the old one", "old one", "that one", "keep it", "try again", "retry",
}
NEW_WORDS = {
    "new", "new one", "a new one", "new ticket", "a new ticket", "start new", "start a new one",
    "start a new ticket", "start fresh", "fresh", "start over",
}
_CATEGORY_REPLY = re.compile(r"^\W*(?:it'?s\s+)?(?:an?\s+)?(it|hr)(?:\s+(?:issue|problem|one|ticket))?\W*$", re.I)


class TicketFieldsUpdate(BaseModel):
    """Structured output of the ticket extractor: the complete updated draft."""

    description: str = Field(
        default="", description="The issue, summarised from what the employee said. Empty if not described yet."
    )
    summary: str = Field(default="", description="One-line title, at most 80 characters.")
    category: Literal["IT", "HR", "unknown"] = Field(default="unknown")
    priority: Literal["Low", "Medium", "High", "Critical", "none"] = Field(default="none")


# --- draft helpers ---


def validate_field(name: str, value: Any) -> Any:
    """Validate one draft field with TicketDraft's own rules; raise ValueError if invalid."""
    if name == "priority" and value in (None, "", "none"):
        return None
    if name == "summary" and isinstance(value, str):
        value = " ".join(value.split())
    try:
        return getattr(TicketDraft(**{**_PLACEHOLDER, name: value}), name)
    except ValidationError as exc:
        raise ValueError(f"invalid {name}") from exc


def apply_fields(draft: dict, fields: dict[str, Any]) -> tuple[dict, list[str]]:
    """Merge validated fields into a copy of `draft`; return it with a list of problems."""
    updated, problems = dict(draft), []
    for name, value in fields.items():
        if name not in EDITABLE_FIELDS:
            problems.append(f"{name} can't be edited")
            continue
        try:
            updated[name] = validate_field(name, value)
        except ValueError:
            problems.append(f"the {name} wasn't valid")
    return updated, problems


def held_draft_decision(text: str) -> Literal["continue", "new"] | None:
    """Exact-phrase answer to "continue that one, or start a new ticket?"; None if unclear."""
    normalized = normalize_reply(text)
    if normalized in CONTINUE_WORDS:
        return "continue"
    if normalized in NEW_WORDS:
        return "new"
    return None


def summary_from(description: str) -> str:
    line = " ".join(description.split())
    if len(line) <= _SUMMARY_FALLBACK_CHARS:
        return line
    return line[: _SUMMARY_FALLBACK_CHARS - 1].rsplit(" ", 1)[0] + "…"


def missing_field(draft: dict, email: str | None) -> str | None:
    """The next thing to ask for, in order: issue details, email, category."""
    if not draft.get("description"):
        return "ticket_details"
    if not email:
        return "email"
    if draft.get("category") not in ("IT", "HR"):
        return "ticket_category"
    return None


def build_draft(state: SmartDeskState) -> TicketDraft:
    draft = state.get("ticket_draft") or {}
    return TicketDraft(email=state["session_email"], **{k: draft.get(k) for k in EDITABLE_FIELDS})


def thread_id(config: RunnableConfig) -> str:
    return str(config["configurable"]["thread_id"])


def render_review(draft: TicketDraft) -> str:
    return prompts.TICKET_REVIEW.format(
        email=draft.email,
        category=draft.category,
        priority=draft.priority or prompts.PRIORITY_NOT_SET,
        summary=draft.summary,
        description=draft.description,
    )


def _transcript(messages: list[BaseMessage]) -> str:
    lines = []
    for message in messages[-_HISTORY_MESSAGES:]:
        speaker = "Employee" if isinstance(message, HumanMessage) else "SmartDesk"
        lines.append(f"{speaker}: {_DATA_TAGS.sub('', str(message.content))}")
    return "\n".join(lines)


def build_extraction_messages(draft: dict, messages: list[BaseMessage], flow_start: int) -> list[BaseMessage]:
    """Extractor input: only this ticket's part of the conversation, from `flow_start` on."""
    latest = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    current = {name: draft.get(name) for name in EDITABLE_FIELDS}
    return [
        SystemMessage(content=prompts.TICKET_FIELDS_SYSTEM_PROMPT),
        HumanMessage(
            content=prompts.TICKET_FIELDS_INPUT.format(
                draft=json.dumps(current, ensure_ascii=False),
                conversation=_transcript(messages[flow_start:-1]),
                message=_DATA_TAGS.sub("", latest),
            )
        ),
    ]


def _merge_extraction(draft: dict, update: TicketFieldsUpdate) -> dict:
    """Apply the extractor's non-empty values; invalid ones are dropped (and asked for again)."""
    fields: dict[str, Any] = {}
    if update.description.strip():
        fields["description"] = update.description
    if update.summary.strip():
        fields["summary"] = update.summary
    if update.category != "unknown":
        fields["category"] = update.category
    if update.priority != "none":
        fields["priority"] = update.priority
    merged, problems = apply_fields(draft, fields)
    if problems:
        log.info("Ticket extractor returned invalid fields: %s", problems)
    if not merged.get("description"):  # no issue yet, so no title ("Support ticket request", K2)
        merged.pop("summary", None)
    return merged


# --- nodes ---


def make_collect_node(llm: StructuredLLM) -> Callable[[SmartDeskState], dict]:
    extractor = llm.with_structured_output(TicketFieldsUpdate)

    def collect_ticket(state: SmartDeskState) -> dict:
        messages = state["messages"]
        awaiting = state.get("awaiting")
        latest = str(messages[-1].content)
        start = state.get("ticket_flow_start")
        held = start is not None and bool(state.get("ticket_draft"))
        extract_from = messages  # the last human message here is the one the extractor reads
        # Replies that carry no ticket details: an email when asked, or "continue".
        skip_extraction = awaiting == "email" and state.get("email_event") == "captured"

        if awaiting == "held_draft":
            decision = held_draft_decision(latest)
            if decision is None:
                return _ask_about_held_draft(state, state.get("pending_flow_start"), prompts.HELD_DRAFT_REASK)
            if decision == "new":
                # Start over from the request that triggered the question. The question may have
                # been asked again since, so the request is found by its recorded index.
                pending = state.get("pending_flow_start")
                request = state.get("pending_request_index")
                request = request if request is not None else len(messages) - 3
                draft, start = {}, pending if pending is not None else request
                extract_from = messages[: request + 1]
            else:
                draft = dict(state.get("ticket_draft") or {})
                skip_extraction = True
        elif state.get("intent") == Intent.CREATE_TICKET.value and held and held_draft_decision(latest) != "continue":
            if state.get("pending_request_index") is not None:  # the question is still open: not an answer
                return _ask_about_held_draft(state, state.get("pending_flow_start"), prompts.HELD_DRAFT_REASK)
            seed = state.get("seed_start")
            request = len(messages) - 1
            return _ask_about_held_draft(state, seed if seed is not None else request, request_index=request)
        elif start is None:
            # A new ticket: nothing carries over from earlier tickets or turns, except the
            # knowledge question handled in the turn just before ("raise a ticket for it").
            draft = {}
            seed = state.get("seed_start")
            start = seed if seed is not None else len(messages) - 1
        else:  # continuing a draft (on hold, after a Jira error, or mid-collection)
            draft = dict(state.get("ticket_draft") or {})

        if not skip_extraction:
            update = extractor.invoke(build_extraction_messages(draft, extract_from, start))
            assert isinstance(update, TicketFieldsUpdate)
            draft = _merge_extraction(draft, update)
        if awaiting == "ticket_category" and (match := _CATEGORY_REPLY.match(latest)):
            draft["category"] = match.group(1).upper()
        if draft.get("category") not in ("IT", "HR") and state.get("domain") in ("IT", "HR"):
            draft["category"] = state["domain"]
        if draft.get("description") and not draft.get("summary"):
            draft["summary"] = summary_from(draft["description"])

        missing = missing_field(draft, state.get("session_email"))
        update_state: dict[str, Any] = {
            "ticket_draft": draft,
            "ticket_flow_start": start,
            "pending_flow_start": None,
            "pending_request_index": None,
            "seed_start": None,
            "active_flow": "ticket",
            "awaiting": missing,
            "status_candidates": [],
        }
        if missing == "ticket_details":
            update_state["messages"] = [AIMessage(content=prompts.ASK_TICKET_DETAILS)]
        elif missing == "email":
            prefix = prompts.INVALID_EMAIL if state.get("email_event") == "invalid" else ""
            so_far = prompts.TICKET_SO_FAR.format(summary=draft["summary"])
            ask = prompts.ASK_EMAIL.format(purpose=prompts.EMAIL_PURPOSE["ticket"])
            update_state["messages"] = [AIMessage(content=prefix + so_far + ask)]
        elif missing == "ticket_category":
            so_far = prompts.TICKET_SO_FAR.format(summary=draft["summary"])
            update_state["messages"] = [AIMessage(content=so_far + prompts.ASK_TICKET_CATEGORY)]
        return update_state

    return collect_ticket


def _ask_about_held_draft(
    state: SmartDeskState, pending_start: int | None, prefix: str = "", *, request_index: int | None = None
) -> dict:
    draft = state.get("ticket_draft") or {}
    summary = draft.get("summary") or summary_from(draft.get("description", ""))
    update = {
        "active_flow": "ticket",
        "awaiting": "held_draft",
        "pending_flow_start": pending_start,
        "seed_start": None,
        "messages": [AIMessage(content=prefix + prompts.HELD_DRAFT_QUESTION.format(summary=summary))],
    }
    if request_index is not None:  # first time asked; a re-ask keeps the original request
        update["pending_request_index"] = request_index
    return update


def route_after_collect(state: SmartDeskState) -> str:
    return END if state.get("awaiting") else PRESENT_TICKET


def present_ticket(state: SmartDeskState) -> dict:
    """Show the complete draft. A separate node so the summary is in the history before the interrupt."""
    return {"messages": [AIMessage(content=render_review(build_draft(state)))], "approved_op_id": None}


def review_ticket(state: SmartDeskState, config: RunnableConfig) -> Command:
    # Re-runs from the top on resume, so nothing before interrupt() may have side effects.
    draft = build_draft(state)
    op_id = derive_op_id(thread_id(config), draft)
    decision = interrupt(
        {"type": "ticket_approval", "op_id": op_id, "draft": draft.model_dump(), "text": render_review(draft)}
    )
    action = decision.get("action") if isinstance(decision, dict) else None

    if action == "approve":
        if decision.get("op_id") == op_id:
            return Command(goto=SUBMIT_TICKET, update={"approved_op_id": op_id, "awaiting": None})
        return Command(goto=PRESENT_TICKET, update={"messages": [AIMessage(content=prompts.REVIEW_STALE)]})

    if action == "edit":
        fields = dict(decision.get("fields") or {})
        problems = []
        email = fields.pop("email", None)
        if email is not None and str(email).strip().lower() != draft.email:
            problems.append(prompts.EMAIL_NOT_EDITABLE)
        updated, field_problems = apply_fields(state.get("ticket_draft") or {}, fields)
        problems += field_problems
        update: dict[str, Any] = {"ticket_draft": updated}
        if problems:
            update["messages"] = [AIMessage(content=prompts.EDIT_REJECTED.format(problems="; ".join(problems)))]
        return Command(goto=PRESENT_TICKET, update=update)

    if action == "cancel":
        cancelled = AIMessage(content=prompts.TICKET_CANCELLED)
        return Command(goto=END, update={**_cleared_ticket(), "messages": [cancelled]})

    # Free text (a correction, a question, anything else): route it like a new turn.
    text = str(decision.get("text", "")) if isinstance(decision, dict) else str(decision)
    return Command(goto="classify_intent", update={"messages": [HumanMessage(content=text)]})


def _cleared_ticket() -> dict:
    return {
        "ticket_draft": {},
        "ticket_flow_start": None,
        "pending_flow_start": None,
        "pending_request_index": None,
        "active_flow": None,
        "awaiting": None,
        "approved_op_id": None,
    }


def make_submit_node(service: TicketService | None) -> Callable[[SmartDeskState, RunnableConfig], dict]:
    def submit_ticket(state: SmartDeskState, config: RunnableConfig) -> dict:
        draft = build_draft(state)
        op_id = derive_op_id(thread_id(config), draft)
        if state.get("approved_op_id") != op_id:  # defence in depth: only an approval of this exact draft
            return {"approved_op_id": None, "messages": [AIMessage(content=prompts.TICKET_NOT_APPROVED)]}
        if service is None:
            return _ticket_error("not_configured")

        try:
            created = service.create_ticket(draft, op_id)
        except TicketCreationUncertain:
            return _ticket_error("ticket_uncertain")
        except JiraAuthError:
            log.error("Jira refused SmartDesk's credentials while creating a ticket")
            return _ticket_error("jira_auth")
        except JiraRequestRejected as exc:
            log.warning("Jira rejected a ticket: %s", exc)
            return _ticket_error("jira_rejected")
        except JiraUnavailable:
            return _ticket_error("jira_unavailable")
        except JiraError as exc:  # e.g. not configured; raised before anything is sent
            log.error("Ticket creation failed: %s", exc)
            return _ticket_error("jira_unavailable")

        template = prompts.TICKET_ALREADY_CREATED if created.already_existed else prompts.TICKET_CREATED
        return {
            **_cleared_ticket(),
            "last_ticket": created.to_dict(),
            "messages": [AIMessage(content=template.format(key=created.key, url=created.url))],
        }

    return submit_ticket


def _ticket_error(code: str) -> dict:
    # The draft is kept so "try again" can go back through review (same draft, same op_id).
    return {
        "approved_op_id": None,
        "awaiting": None,
        "last_error": code,
        "messages": [AIMessage(content=prompts.TICKET_ERROR[code])],
    }
