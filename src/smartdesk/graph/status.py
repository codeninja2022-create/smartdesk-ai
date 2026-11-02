"""Ticket status: look up the session employee's tickets and present one.

    no session email          -> ask for it
    ticket key in the message -> details (ownership is enforced by the service)
    choosing from a list      -> number / key, else the LLM picks from the list, else ask again
    otherwise list tickets:  0 -> say so and offer a ticket
                             1 -> details
                             n -> the LLM picks if the message singles one out, else list and ask

Lookups always use the locked session email. Support comments are shown to
the employee as-is and never sent to the LLM.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from smartdesk.graph import prompts
from smartdesk.graph.state import SmartDeskState
from smartdesk.llm import StructuredLLM
from smartdesk.tickets.models import (
    JiraAuthError,
    JiraError,
    JiraRequestRejected,
    TicketDetails,
    TicketSummary,
)
from smartdesk.tickets.service import TicketService

log = logging.getLogger(__name__)

CHECK_STATUS = "check_status"
MAX_LISTED = 10
_KEY = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*)\b")
_NUMBER = re.compile(r"^\W*(?:#|no\.?|number|ticket)?\s*(\d{1,2})\W*$", re.I)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1}
_ORDINAL = re.compile(r"^\W*(?:the\s+)?(first|second|third|fourth|fifth|last)(?:\s+one)?\W*$", re.I)


class TicketChoice(BaseModel):
    number: int = Field(
        default=0, description="The number of the ticket the message refers to, or 0 if it does not single one out."
    )


def find_ticket_key(text: str) -> str | None:
    match = _KEY.search(text)
    return match.group(1).upper() if match else None


def choice_number(text: str, count: int) -> int | None:
    """A 1-based list position from "2", "#2" or "the second one"; None if the text is not one."""
    if match := _NUMBER.match(text):
        number = int(match.group(1))
    elif match := _ORDINAL.match(text):
        number = _ORDINALS[match.group(1).lower()]
        number = count if number == -1 else number
    else:
        return None
    return number if 1 <= number <= count else None


def order_for_listing(tickets: list[TicketSummary]) -> list[TicketSummary]:
    """Open tickets first, each group most recently updated first (the service's order)."""
    return [t for t in tickets if t.status_category != "Done"] + [t for t in tickets if t.status_category == "Done"]


def _when(timestamp: str) -> str:
    return timestamp[:16].replace("T", " ") if timestamp else "unknown"


def render_listing(tickets: list[dict]) -> str:
    return "\n".join(
        f"{n}. {t['key']}: {t['summary']} ({t['status']}, updated {_when(t['updated'])})"
        for n, t in enumerate(tickets, start=1)
    )


def render_details(ticket: TicketDetails) -> str:
    lines = [
        f"{ticket.key}: {ticket.summary}",
        f"Status: {ticket.status}",
        f"Last updated: {_when(ticket.updated)}",
        f"Link: {ticket.url}",
        "",
    ]
    if ticket.comments:
        lines.append("Updates from the support team:")
        lines += [f"- {c.author} ({_when(c.created)}): {c.body}" for c in ticket.comments]
    else:
        lines.append(prompts.NO_COMMENTS)
    return "\n".join(lines)


def make_status_node(
    llm: StructuredLLM, service: TicketService | None
) -> Callable[[SmartDeskState], dict]:
    chooser = llm.with_structured_output(TicketChoice)

    def llm_choice(text: str, candidates: list[dict]) -> dict | None:
        result = chooser.invoke([
            SystemMessage(content=prompts.TICKET_CHOICE_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Tickets:\n{render_listing(candidates)}\n\nEmployee message:\n<message>\n{text}\n</message>"
            ),
        ])
        assert isinstance(result, TicketChoice)
        return candidates[result.number - 1] if 1 <= result.number <= len(candidates) else None

    def details(email: str, key: str) -> dict:
        assert service is not None
        ticket = service.get_ticket(email, key)
        text = render_details(ticket) if ticket else prompts.TICKET_NOT_FOUND.format(key=key, email=email)
        return _done(text)

    def check_status(state: SmartDeskState) -> dict:
        if service is None:
            return _error("not_configured")
        email = state.get("session_email")
        if not email:
            prefix = prompts.INVALID_EMAIL if state.get("email_event") == "invalid" else ""
            ask = prompts.ASK_EMAIL.format(purpose=prompts.EMAIL_PURPOSE["status"])
            return {"active_flow": "status", "awaiting": "email", "messages": [AIMessage(content=prefix + ask)]}

        text = str(state["messages"][-1].content)
        if state.get("awaiting") == "email":  # the message was the email, not a ticket reference
            text = ""
        candidates = state.get("status_candidates") or []
        try:
            if key := find_ticket_key(text):
                return details(email, key)
            if state.get("awaiting") == "ticket_choice" and candidates:
                number = choice_number(text, len(candidates))
                chosen = candidates[number - 1] if number else llm_choice(text, candidates)
                if chosen:
                    return details(email, chosen["key"])
                return _choose(candidates, len(candidates), prefix=prompts.CHOICE_NOT_UNDERSTOOD)

            tickets = order_for_listing(service.list_tickets(email))
            if not tickets:
                return {**_done(prompts.NO_TICKETS.format(email=email)), "ticket_offered": True}
            if len(tickets) == 1:
                return details(email, tickets[0].key)
            listed = [t.to_dict() for t in tickets[:MAX_LISTED]]
            if text and (chosen := llm_choice(text, listed)):
                return details(email, chosen["key"])
            return _choose(listed, len(tickets))
        except JiraAuthError:
            log.error("Jira refused SmartDesk's credentials during a status lookup")
            return _error("jira_auth")
        except JiraRequestRejected as exc:
            log.warning("Jira rejected a status lookup: %s", exc)
            return _error("jira_rejected")
        except JiraError:
            return _error("jira_unavailable")

    return check_status


def _done(text: str) -> dict[str, Any]:
    return {"active_flow": None, "awaiting": None, "status_candidates": [], "messages": [AIMessage(content=text)]}


def _choose(candidates: list[dict], total: int, prefix: str = "") -> dict[str, Any]:
    text = prefix + prompts.CHOOSE_TICKET.format(count=total, listing=render_listing(candidates))
    if total > len(candidates):
        text += "\n" + prompts.MORE_TICKETS.format(shown=len(candidates), count=total)
    return {
        "active_flow": "status",
        "awaiting": "ticket_choice",
        "status_candidates": candidates,
        "messages": [AIMessage(content=text)],
    }


def _error(code: str) -> dict[str, Any]:
    return {**_done(prompts.STATUS_ERROR[code]), "last_error": code}
