from enum import StrEnum
from typing import Literal

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class Intent(StrEnum):
    GREETING = "greeting"
    KNOWLEDGE_QUESTION = "knowledge_question"
    CREATE_TICKET = "create_ticket"
    TICKET_STATUS = "ticket_status"
    PROVIDE_INFO = "provide_info"  # an answer to SmartDesk's last question
    CANCEL = "cancel"
    UNCLEAR = "unclear"
    OUT_OF_SCOPE = "out_of_scope"


Flow = Literal["ticket", "status"]
# What SmartDesk's last question asked for.
Awaiting = Literal["email", "ticket_details", "ticket_category", "ticket_choice", "held_draft"]
# Outcome of looking for the session email in the latest message.
EmailEvent = Literal["captured", "invalid", "conflict"]


class IntentClassification(BaseModel):
    """Structured output returned by the intent classifier."""

    intent: Intent = Field(description="The single best intent for the employee's latest message.")
    domain: Literal["IT", "HR", "unknown"] = Field(
        default="unknown",
        description="IT for technology support; HR for people policies, onboarding, benefits and payroll; "
        "unknown if unclear or not applicable.",
    )
    search_query: str = Field(
        default="",
        description="For knowledge_question only: the employee's question rewritten as a standalone search "
        "query, resolving references to earlier turns. Empty otherwise.",
    )


class SmartDeskState(MessagesState):
    # Checkpoints only round-trip built-in types, so enums and dataclasses are
    # stored as plain strings and dicts.

    # Per turn: reset by classify_intent at the start of every turn.
    intent: str | None
    domain: str | None
    search_query: str | None
    retrieved: list[dict]  # RetrievedChunk.to_dict() for the current question
    citations: list[dict]  # Citation.to_dict() for the last grounded answer
    escalation_reason: str | None  # set when the KB cannot answer; offers a ticket
    email_event: EmailEvent | None
    last_error: str | None  # jira_unavailable | jira_auth | jira_rejected | ticket_uncertain | not_configured
    ticket_offered: bool  # SmartDesk's reply offered a ticket; read by the next turn's classifier
    # Message index of the knowledge question just handled (answered or escalated), so a
    # ticket requested in the very next turn ("raise a ticket for it") can start from it.
    # Set by generate_answer / escalate; kept by classify_intent only when the next turn is
    # create_ticket. Living one turn, it can never reach past a created or cancelled ticket.
    seed_start: int | None

    # Session: written by classify_intent only, and only while unset (the email lock).
    session_email: str | None

    # Flow: kept across turns until the flow finishes or is cancelled.
    active_flow: Flow | None
    awaiting: Awaiting | None
    ticket_draft: dict  # summary, description, category, priority; the email comes from session_email
    # Message index where the current ticket flow began; the extractor only sees messages
    # from here on. None = no ticket flow, so the next ticket request starts a fresh draft.
    # Kept while a draft is on hold or after a Jira error; cleared on creation or cancel.
    ticket_flow_start: int | None
    # Start index for a new ticket requested while a draft was on hold; used only while
    # awaiting == "held_draft" (the employee is choosing "continue" or "new").
    pending_flow_start: int | None
    # Index of the request that first triggered the "continue or new?" question; "new"
    # extracts the fresh draft up to it. A re-asked question keeps it (K18).
    pending_request_index: int | None
    status_candidates: list[dict]  # TicketSummary.to_dict() offered for selection
    approved_op_id: str | None  # set only by review_ticket on an explicit approval of that exact draft
    last_ticket: dict | None  # CreatedTicket.to_dict() of the last ticket created in this session
