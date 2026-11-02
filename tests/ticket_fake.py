"""An in-memory TicketService for graph tests.

- Creation is idempotent per op_id, like JiraTicketService: the same op_id
  returns the same ticket with `already_existed=True`.
- `create_errors` / `read_errors`: exceptions raised by successive calls
  (None means "succeed"); consumed one per call.
- `get_ticket` only returns tickets owned by the given email.
"""

from dataclasses import dataclass, field

from smartdesk.tickets.models import CreatedTicket, TicketComment, TicketDetails, TicketDraft, TicketSummary

BROWSE = "https://novatech-test.atlassian.net/browse"


@dataclass
class FakeTicketService:
    create_errors: list[Exception | None] = field(default_factory=list)
    read_errors: list[Exception | None] = field(default_factory=list)
    tickets: dict[str, tuple[str, TicketDetails]] = field(default_factory=dict)  # key -> (owner email, details)
    created: list[tuple[TicketDraft, str]] = field(default_factory=list)  # successful creations
    create_calls: list[tuple[TicketDraft, str]] = field(default_factory=list)
    list_calls: list[str] = field(default_factory=list)
    get_calls: list[tuple[str, str]] = field(default_factory=list)
    _by_op: dict[str, str] = field(default_factory=dict)
    _counter: int = 0

    def add_ticket(
        self, email: str, summary: str, status: str = "To Do", status_category: str = "To Do",
        comments: list[TicketComment] | None = None, updated: str | None = None,
    ) -> str:
        self._counter += 1
        key = f"KAN-{self._counter}"
        stamp = updated or f"2026-11-01T10:{self._counter:02d}:00.000+0000"
        self.tickets[key] = (email, TicketDetails(
            key=key, url=f"{BROWSE}/{key}", summary=summary, status=status, status_category=status_category,
            category="IT", updated=stamp, priority="Medium", created=stamp, description="", comments=comments or [],
        ))
        return key

    def create_ticket(self, draft: TicketDraft, op_id: str) -> CreatedTicket:
        self.create_calls.append((draft, op_id))
        if self.create_errors and (error := self.create_errors.pop(0)) is not None:
            raise error
        if op_id in self._by_op:
            key = self._by_op[op_id]
            return CreatedTicket(key, f"{BROWSE}/{key}", already_existed=True)
        key = self.add_ticket(draft.email, draft.summary)
        self._by_op[op_id] = key
        self.created.append((draft, op_id))
        return CreatedTicket(key, f"{BROWSE}/{key}", already_existed=False)

    def list_tickets(self, email: str) -> list[TicketSummary]:
        self.list_calls.append(email)
        self._maybe_fail()
        owned = [d for owner, d in self.tickets.values() if owner == email]
        summaries = [TicketSummary(**{k: getattr(d, k) for k in TicketSummary.__dataclass_fields__}) for d in owned]
        return sorted(summaries, key=lambda s: s.updated, reverse=True)

    def get_ticket(self, email: str, key: str) -> TicketDetails | None:
        self.get_calls.append((email, key))
        self._maybe_fail()
        owner, details = self.tickets.get(key, (None, None))
        return details if owner == email else None

    def _maybe_fail(self) -> None:
        if self.read_errors and (error := self.read_errors.pop(0)) is not None:
            raise error
