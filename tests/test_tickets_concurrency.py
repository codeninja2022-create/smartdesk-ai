"""M6-1: at most one caller works on a creation op, even across processes.

Each service has its own TicketStore connection to the same SQLite file, as two
SmartDesk processes would. `FakeJira.on_search` runs caller B in the middle of
caller A's reconcile, so the interleaving is deterministic.
"""

import sqlite3

import pytest

from smartdesk.tickets.models import TicketCreationUncertain, TicketDraft, op_label
from smartdesk.tickets.service import JiraTicketService
from smartdesk.tickets.store import TicketStore
from tests.jira_fake import FakeJira

EMAIL = "jane.doe@novatech.example"
OP = "a" * 64
DRAFT = TicketDraft(email=EMAIL, summary="Monitor flickers", description="Flickers when docked.", category="IT")


@pytest.fixture
def jira() -> FakeJira:
    return FakeJira()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "smartdesk.db"


def service(jira: FakeJira, db, **options) -> JiraTicketService:
    options.setdefault("reconcile_delay_seconds", 0)
    return JiraTicketService(jira.client(), TicketStore(db), project_key="KAN", sleep=lambda s: None, **options)


def unknown_op(db) -> None:
    """An op left `unknown` by an earlier call that gave up (its POST outcome was never confirmed)."""
    store = TicketStore(db)
    store.claim_op(OP, EMAIL)
    store.record_attempt(OP)
    store.mark_unknown(OP, "ReadTimeout")
    store.close()


def test_second_caller_during_takeover_is_in_flight_and_only_one_post_is_sent(jira, db):
    unknown_op(db)
    a = service(jira, db, reconcile_polls=1, in_flight_seconds=60)
    b = service(jira, db, reconcile_polls=1, in_flight_seconds=60)
    outcome = {}

    def b_tries_now():
        try:
            b.create_ticket(DRAFT, OP)
        except TicketCreationUncertain as exc:
            outcome["b"] = exc

    jira.on_search = b_tries_now  # fires during A's reconcile search
    ticket = a.create_ticket(DRAFT, OP)

    assert "already being created" in str(outcome["b"])
    assert jira.posts_to_create() == 1
    assert ticket.key == "KAN-1"
    assert TicketStore(db).get_op(OP).status == "created"


def test_stale_pending_op_is_taken_over_and_the_old_owner_stops_before_posting(jira, db):
    # Every op is "stale" for in_flight_seconds=0, so B may take over while A is reconciling.
    store = TicketStore(db)
    store.claim_op(OP, EMAIL)
    store.record_attempt(OP)  # a POST was counted, then the process died: `pending`, never confirmed
    a = service(jira, db, reconcile_polls=1, in_flight_seconds=0)
    b = service(jira, db, reconcile_polls=3, in_flight_seconds=0)
    results = {}
    jira.on_search = lambda: results.setdefault("b", b.create_ticket(DRAFT, OP))
    # B's 3 polls and then A's single poll all see an empty index, so neither finds B's issue by search.
    jira.search_lag = 4

    with pytest.raises(TicketCreationUncertain, match="already being created"):
        a.create_ticket(DRAFT, OP)  # its lease was taken over by B: no POST

    assert results["b"].key == "KAN-1"
    assert jira.posts_to_create() == 1
    op = store.get_op(OP)
    assert (op.status, op.ticket_key) == ("created", "KAN-1")  # A's give-up did not overwrite B's result


def test_take_over_from_an_outdated_read_is_refused(db):
    unknown_op(db)
    first, second = TicketStore(db), TicketStore(db)
    observed = second.get_op(OP)

    assert first.take_over(first.get_op(OP)) is not None
    assert second.take_over(observed) is None  # the op changed after `second` read it


def test_owner_writes_fail_once_the_lease_is_lost(db):
    unknown_op(db)
    store = TicketStore(db)
    mine = store.take_over(store.get_op(OP))
    theirs = TicketStore(db).take_over(TicketStore(db).get_op(OP))  # e.g. after my lease went stale

    assert theirs is not None
    assert store.heartbeat(OP, mine, attempt=True) is None
    store.mark_unknown(OP, "gave up", version=mine)  # no-op: not the owner any more
    assert store.get_op(OP).status == "pending"


def test_existing_database_gets_the_version_column(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE ticket_ops (op_id TEXT PRIMARY KEY, email TEXT NOT NULL, status TEXT NOT NULL, "
        "ticket_key TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ticket_ops VALUES (?, ?, 'unknown', NULL, 1, NULL, '2026-10-01T00:00:00+00:00', "
        "'2026-10-01T00:00:00+00:00')",
        (OP, EMAIL),
    )
    conn.commit()
    conn.close()

    store = TicketStore(db)
    assert store.get_op(OP).version == 1
    assert store.take_over(store.get_op(OP)) == 2


def test_label_still_carries_the_op(jira, db):
    service(jira, db).create_ticket(DRAFT, OP)
    assert op_label(OP) in next(iter(jira.issues.values()))["fields"]["labels"]
