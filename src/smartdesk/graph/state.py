from enum import StrEnum

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


class SmartDeskState(MessagesState):
    # Stored as the plain string value: checkpoints only round-trip built-in types.
    intent: str | None
