"""Ticket service: idempotent creation, employee lookup and status details.

Creation (`create_ticket`) is keyed by a stable op_id (`derive_op_id`):

    op created          -> return the existing ticket; no Jira call
    op pending (recent) -> another submission is in flight; raise TicketCreationUncertain
    op pending (stale) / unknown -> take it over (compare-and-set; the loser raises
                                    TicketCreationUncertain), then reconcile before anything else
    op new / failed     -> claim it, then POST

    each POST (at most JIRA_MAX_CREATE_ATTEMPTS per call):
      201                         -> created
      definite failure (4xx, connect error) -> failed, re-raise (a later call may retry)
      ambiguous (timeout, 5xx)    -> still ours (pending), reconcile, then POST again only if nothing is found
    gave up without a ticket      -> unknown, raise TicketCreationUncertain

The caller that claims or takes over an op holds a lease (`_OpLease`): before
each POST and each reconcile poll it renews it with a compare-and-set
heartbeat. That keeps the op `pending` and fresh, so other callers see it as in
flight, and a caller whose lease was taken over stops before posting.

So a JiraError other than TicketCreationUncertain from `create_ticket` means
no ticket was created. A failed reconcile search raises TicketCreationUncertain.

Reconciling searches Jira for the op's `sd-op-` label, polling a few times
because Jira search is eventually consistent. If several issues carry the
label, the oldest wins.

Lookups union the local SQLite mapping with a Jira search on the employee's
`sd-emp-` label. Jira is the source of truth for status and comments.
"""

import logging
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from smartdesk.config import Settings
from smartdesk.tickets.adf import adf_to_text, text_to_adf
from smartdesk.tickets.jira import AmbiguousCreateError, JiraClient, build_jira_client
from smartdesk.tickets.models import (
    APP_LABEL,
    CreatedTicket,
    JiraError,
    TicketComment,
    TicketCreationUncertain,
    TicketDetails,
    TicketDraft,
    TicketSummary,
    category_label,
    employee_label,
    normalize_email,
    op_label,
)
from smartdesk.tickets.store import TicketStore

log = logging.getLogger(__name__)

# SmartDesk priorities -> Jira's default priority scheme
_PRIORITY_TO_JIRA = {"Low": "Low", "Medium": "Medium", "High": "High", "Critical": "Highest"}
_ISSUE_FIELDS = ["summary", "status", "priority", "labels", "created", "updated", "description"]
_SUMMARY_FIELDS = ["summary", "status", "labels", "updated"]
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
_MAX_KEY_LEN = 32
_MAX_LISTED = 50


_OP_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_IN_FLIGHT = "this ticket is already being created; check its status shortly"


class _OpLease:
    """A caller's ownership of an op. Each renewal is a compare-and-set on the version it last wrote."""

    def __init__(self, store: TicketStore, op_id: str, version: int) -> None:
        self.store, self.op_id, self.version = store, op_id, version

    def renew(self, *, attempt: bool = False, error: str | None = None) -> None:
        version = self.store.heartbeat(self.op_id, self.version, attempt=attempt, error=error)
        if version is None:
            log.warning("Lost ownership of op %s to another caller; not posting", self.op_id[:12])
            raise TicketCreationUncertain(_IN_FLIGHT)
        self.version = version


class TicketService(Protocol):
    def create_ticket(self, draft: TicketDraft, op_id: str) -> CreatedTicket: ...

    def list_tickets(self, email: str) -> list[TicketSummary]: ...

    def get_ticket(self, email: str, key: str) -> TicketDetails | None: ...


def _category_from_labels(labels: Sequence[str]) -> str:
    for category in ("IT", "HR"):
        if category_label(category) in labels:
            return category
    return "unknown"


class JiraTicketService:
    def __init__(
        self,
        client: JiraClient,
        store: TicketStore,
        *,
        project_key: str,
        issue_type: str = "Task",
        max_create_attempts: int = 2,
        reconcile_polls: int = 3,
        reconcile_delay_seconds: float = 2.0,
        in_flight_seconds: float = 20.0,
        extra_labels: Sequence[str] = (),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.store = store
        self.project_key = project_key
        self.issue_type = issue_type
        self.max_create_attempts = max_create_attempts
        self.reconcile_polls = reconcile_polls
        self.reconcile_delay_seconds = reconcile_delay_seconds
        self.in_flight_seconds = in_flight_seconds
        self.extra_labels = tuple(extra_labels)
        self._sleep = sleep

    # --- creation ---

    def create_ticket(self, draft: TicketDraft, op_id: str) -> CreatedTicket:
        if not _OP_ID_RE.fullmatch(op_id):
            raise ValueError("op_id must be 64 lowercase hex characters (derive_op_id)")
        op = self.store.get_op(op_id)
        if (op is None or op.status == "failed") and self.store.claim_op(op_id, draft.email):
            resumed = False
        else:
            op = self.store.get_op(op_id)  # existing op, or another submission won the claim
            assert op is not None
            if op.email != draft.email:
                raise ValueError("op_id belongs to a different employee")
            if op.status == "created":
                assert op.ticket_key
                return CreatedTicket(op.ticket_key, self.client.browse_url(op.ticket_key), already_existed=True)
            if op.status == "pending" and self._age_seconds(op.updated_at) < self.in_flight_seconds:
                raise TicketCreationUncertain(_IN_FLIGHT)
            # `unknown`, or `pending` gone stale: exactly one caller may take it over.
            if self.store.take_over(op) is None:
                raise TicketCreationUncertain(_IN_FLIGHT)
            resumed = True

        current = self.store.get_op(op_id)
        assert current is not None
        lease = _OpLease(self.store, op_id, current.version)
        try:
            return self._create_as_owner(draft, op_id, lease, resumed)
        except TicketCreationUncertain:
            self.store.mark_unknown(op_id, "not confirmed", version=lease.version)  # no-op if the lease was lost
            raise

    def _create_as_owner(self, draft: TicketDraft, op_id: str, lease: "_OpLease", resumed: bool) -> CreatedTicket:
        needs_reconcile = resumed
        for _ in range(self.max_create_attempts):
            if needs_reconcile and (key := self._reconcile(op_id, draft.category, lease)):
                return CreatedTicket(key, self.client.browse_url(key), already_existed=resumed)
            lease.renew(attempt=True)  # counted before sending, so a crash mid-request leaves a trace
            try:
                key = self.client.create_issue(self._issue_fields(draft, op_id))
            except AmbiguousCreateError as exc:
                log.warning("Ambiguous result creating ticket for op %s: %s", op_id[:12], exc)
                lease.renew(error=str(exc))
                needs_reconcile = True
                continue
            except JiraError as exc:
                self.store.mark_failed(op_id, f"{type(exc).__name__}: {exc}")
                raise
            self.store.mark_created(op_id, key, draft.category)
            return CreatedTicket(key, self.client.browse_url(key), already_existed=False)

        if key := self._reconcile(op_id, draft.category, lease):
            return CreatedTicket(key, self.client.browse_url(key), already_existed=resumed)
        raise TicketCreationUncertain(
            "Jira did not confirm the ticket; it may still appear. Retrying will check before creating another."
        )

    def _reconcile(self, op_id: str, category: str, lease: "_OpLease") -> str | None:
        """Find the op's issue, if Jira created one.

        Runs only when an earlier POST may have succeeded, so a failed search
        means "outcome unknown", never "nothing was created".
        """
        jql = f'project = "{self.project_key}" AND labels = "{op_label(op_id)}" ORDER BY created ASC'
        for poll in range(self.reconcile_polls):
            if poll:
                self._sleep(self.reconcile_delay_seconds)
            lease.renew()
            try:
                issues = self.client.search_issues(jql, ["created"], max_results=10)
            except JiraError as exc:
                raise TicketCreationUncertain(
                    "Jira could not be checked for an earlier attempt; the ticket may already exist."
                ) from exc
            if issues:
                if len(issues) > 1:
                    log.warning("Op %s matches %d issues; keeping the oldest", op_id[:12], len(issues))
                key = str(issues[0]["key"])
                self.store.mark_created(op_id, key, category)
                return key
        return None

    def _issue_fields(self, draft: TicketDraft, op_id: str) -> dict[str, Any]:
        header = f"Employee email: {draft.email}\nCategory: {draft.category}\nRaised via SmartDesk AI"
        fields: dict[str, Any] = {
            "project": {"key": self.project_key},
            "issuetype": {"name": self.issue_type},
            "summary": draft.summary,
            "description": text_to_adf(f"{header}\n\n{draft.description}"),
            "labels": [
                APP_LABEL,
                category_label(draft.category),
                employee_label(draft.email),
                op_label(op_id),
                *self.extra_labels,
            ],
        }
        if draft.priority:
            fields["priority"] = {"name": _PRIORITY_TO_JIRA[draft.priority]}
        return fields

    @staticmethod
    def _age_seconds(timestamp: str) -> float:
        return (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds()

    # --- lookup ---

    def list_tickets(self, email: str) -> list[TicketSummary]:
        """All of the employee's tickets, most recently updated first; [] when there are none."""
        email = normalize_email(email)
        jql = f'project = "{self.project_key}" AND labels = "{employee_label(email)}" ORDER BY updated DESC'
        issues = {issue["key"]: issue for issue in self.client.search_issues(jql, _SUMMARY_FIELDS, _MAX_LISTED)}

        for key, issue in issues.items():  # write back tickets the local mapping did not know
            category = _category_from_labels(issue["fields"].get("labels", []))
            if category != "unknown":
                self.store.add_mapping(email, key, category)

        for key in self.store.ticket_keys(email):  # mapped locally but not (yet) in search results
            if key not in issues:
                issue = self.client.get_issue(key, _SUMMARY_FIELDS)
                if issue is None:
                    log.info("Mapped ticket %s no longer exists in Jira; skipping", key)
                    continue
                issues[key] = issue

        summaries = [self._summary(issue) for issue in issues.values()]
        return sorted(summaries, key=lambda s: s.updated, reverse=True)

    def get_ticket(self, email: str, key: str) -> TicketDetails | None:
        """Status, details and comments, or None if the ticket does not exist or is not this employee's."""
        email = normalize_email(email)
        key = key.strip().upper()
        if len(key) > _MAX_KEY_LEN or not _KEY_RE.fullmatch(key) or not key.startswith(f"{self.project_key}-"):
            return None
        issue = self.client.get_issue(key, _ISSUE_FIELDS)
        if issue is None:
            return None
        fields = issue["fields"]
        owned = employee_label(email) in fields.get("labels", []) or self.store.is_mapped(email, key)
        if not owned:
            return None

        comments = [
            TicketComment(
                author=(c.get("author") or {}).get("displayName", "Unknown"),
                created=c.get("created", ""),
                body=adf_to_text(c.get("body")),
            )
            for c in self.client.get_comments(key)
        ]
        summary = self._summary(issue)
        return TicketDetails(
            **summary.to_dict(),
            priority=(fields.get("priority") or {}).get("name"),
            created=fields.get("created", ""),
            description=adf_to_text(fields.get("description")),
            comments=comments,
        )

    def _summary(self, issue: dict[str, Any]) -> TicketSummary:
        fields = issue["fields"]
        status = fields.get("status") or {}
        return TicketSummary(
            key=issue["key"],
            url=self.client.browse_url(issue["key"]),
            summary=fields.get("summary", ""),
            status=status.get("name", "Unknown"),
            status_category=(status.get("statusCategory") or {}).get("name", "Unknown"),
            category=_category_from_labels(fields.get("labels", [])),
            updated=fields.get("updated", ""),
        )


def build_ticket_service(settings: Settings, **overrides: Any) -> JiraTicketService:
    client = build_jira_client(settings)  # raises JiraError unless all JIRA_* values are set
    options: dict[str, Any] = dict(
        project_key=settings.jira_project_key,
        issue_type=settings.jira_issue_type,
        max_create_attempts=settings.jira_max_create_attempts,
        reconcile_polls=settings.jira_reconcile_polls,
        reconcile_delay_seconds=settings.jira_reconcile_delay_seconds,
        in_flight_seconds=2 * settings.jira_timeout_seconds,
    )
    options.update(overrides)
    return JiraTicketService(client, TicketStore(settings.db_path), **options)
