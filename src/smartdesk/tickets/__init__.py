"""Jira ticket integration: idempotent creation, employee lookup, status and comments."""

from smartdesk.tickets.models import (
    CreatedTicket,
    JiraAuthError,
    JiraError,
    JiraRequestRejected,
    JiraUnavailable,
    TicketComment,
    TicketCreationUncertain,
    TicketDetails,
    TicketDraft,
    TicketSummary,
    derive_op_id,
    normalize_email,
)
from smartdesk.tickets.service import JiraTicketService, TicketService, build_ticket_service

__all__ = [
    "CreatedTicket",
    "JiraAuthError",
    "JiraError",
    "JiraRequestRejected",
    "JiraTicketService",
    "JiraUnavailable",
    "TicketComment",
    "TicketCreationUncertain",
    "TicketDetails",
    "TicketDraft",
    "TicketService",
    "TicketSummary",
    "build_ticket_service",
    "derive_op_id",
    "normalize_email",
]
