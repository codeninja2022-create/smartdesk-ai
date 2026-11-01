"""Ticket data models, errors and the stable identifiers used on Jira issues.

Two identifiers end up as Jira labels:

- `employee_label(email)`: `sd-emp-<sha256(email)[:16]>`, used to look up an
  employee's tickets. It is a pseudonym, not anonymisation: an unsalted hash of
  an email address can be reversed by hashing candidate addresses.
- `op_label(op_id)`: `sd-op-<op_id[:32]>`, which marks the creation operation
  so an ambiguous timeout can be reconciled before any retry.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["IT", "HR"]
Priority = Literal["Low", "Medium", "High", "Critical"]

APP_LABEL = "smartdesk"
_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_OP_VERSION = "smartdesk-op-v1"


def normalize_email(email: str) -> str:
    """Trim and lower-case an email address; raise ValueError if it is not valid."""
    normalized = email.strip().lower()
    if len(normalized) > 254 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("not a valid email address")
    return normalized


def employee_label(email: str) -> str:
    digest = hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()
    return f"sd-emp-{digest[:16]}"


def category_label(category: Category) -> str:
    return f"sd-cat-{category.lower()}"


def op_label(op_id: str) -> str:
    return f"sd-op-{op_id[:32]}"


class TicketDraft(BaseModel):
    """The fields collected from the employee before a ticket is created."""

    model_config = ConfigDict(frozen=True)

    email: str
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=20_000)
    category: Category
    priority: Priority | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("summary")
    @classmethod
    def _one_line_summary(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("summary must be a single non-empty line")
        return value

    @field_validator("description")
    @classmethod
    def _non_empty_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be empty")
        return value


def derive_op_id(session_id: str, draft: TicketDraft) -> str:
    """Stable id for "create this exact ticket in this session".

    Re-submitting the same approved draft in the same session yields the same id
    (so only one ticket is created); an edited draft or a new session yields a new one.
    """
    if not session_id.strip():
        raise ValueError("session_id must not be empty")
    canonical = json.dumps(draft.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{_OP_VERSION}\n{session_id}\n{canonical}".encode("utf-8")).hexdigest()


# Results are plain dataclasses of built-in types so they can live in checkpointed state.


@dataclass(frozen=True)
class CreatedTicket:
    key: str
    url: str
    already_existed: bool  # True when a duplicate submission was suppressed

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TicketComment:
    author: str
    created: str
    body: str


@dataclass(frozen=True)
class TicketSummary:
    key: str
    url: str
    summary: str
    status: str  # Jira status name, e.g. "In Progress"
    status_category: str  # Jira status category: "To Do", "In Progress" or "Done"
    category: str  # "IT", "HR" or "unknown"
    updated: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TicketDetails(TicketSummary):
    priority: str | None = None
    created: str = ""
    description: str = ""
    comments: list[TicketComment] = field(default_factory=list)


class JiraError(Exception):
    """Base class for Jira failures. Messages never include credentials."""


class JiraAuthError(JiraError):
    """401/403: the credentials are wrong or lack permission."""


class JiraUnavailable(JiraError):
    """Jira could not be reached or kept failing after bounded retries."""


class JiraRequestRejected(JiraError):
    """Jira rejected the request (4xx other than auth); nothing was created."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Jira rejected the request ({status_code}): {message}")
        self.status_code = status_code


class TicketCreationUncertain(JiraError):
    """Creation timed out and reconciliation found no issue yet.

    The operation stays `unknown`; calling `create_ticket` again with the same
    op_id reconciles before it posts again.
    """
