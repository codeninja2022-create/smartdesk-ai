"""In-memory ticket service for evaluation runs: Jira is never called (docs/specs/m7-plan.md §3)."""

from dataclasses import dataclass, field

from smartdesk.tickets.models import CreatedTicket, TicketDetails, TicketDraft, TicketSummary

BROWSE = "https://eval.invalid/browse"


@dataclass
class MockTicketService:
    create_calls: list[tuple[TicketDraft, str]] = field(default_factory=list)
    _by_op: dict[str, str] = field(default_factory=dict)

    def create_ticket(self, draft: TicketDraft, op_id: str) -> CreatedTicket:
        self.create_calls.append((draft, op_id))
        if op_id in self._by_op:
            key = self._by_op[op_id]
            return CreatedTicket(key, f"{BROWSE}/{key}", already_existed=True)
        key = f"EVAL-{len(self._by_op) + 1}"
        self._by_op[op_id] = key
        return CreatedTicket(key, f"{BROWSE}/{key}", already_existed=False)

    @property
    def created_count(self) -> int:
        """Distinct tickets created; a repeated op_id is a suppressed duplicate, not a new ticket."""
        return len(self._by_op)

    def list_tickets(self, email: str) -> list[TicketSummary]:
        return []

    def get_ticket(self, email: str, key: str) -> TicketDetails | None:
        return None
