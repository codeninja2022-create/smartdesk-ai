from enum import StrEnum
from typing import Literal

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class Intent(StrEnum):
    GREETING = "greeting"
    KNOWLEDGE_QUESTION = "knowledge_question"
    CREATE_TICKET = "create_ticket"
    TICKET_STATUS = "ticket_status"
    OUT_OF_SCOPE = "out_of_scope"


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
    # stored as plain strings and dicts. All per-turn fields are reset by the
    # router at the start of every turn.
    intent: str | None
    domain: str | None
    search_query: str | None
    retrieved: list[dict]  # RetrievedChunk.to_dict() for the current question
    citations: list[dict]  # Citation.to_dict() for the last grounded answer
    escalation_reason: str | None  # set when the KB cannot answer; offers a ticket
