"""`python -m smartdesk.sessions`: checkpoint maintenance that never touches tickets.

Everything shares one SQLite file, as in production: LangGraph checkpoints, the
ticket store, and the ticket service (over the in-memory fake Jira).
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from smartdesk import sessions
from smartdesk.graph import ChatSession, build_graph, open_checkpointer
from smartdesk.graph.checkpoint import list_sessions
from smartdesk.graph.state import Intent as I
from smartdesk.tickets.service import JiraTicketService
from smartdesk.tickets.store import TicketStore
from tests.conftest import FakeLLM, FakeRetriever
from tests.graph_helpers import EMAIL, MONITOR, MONITOR_TEXT
from tests.jira_fake import FakeJira

pytestmark = pytest.mark.rubric("D2", "M7-MULTI")

RAISE = "I want to raise a ticket"


@pytest.fixture
def db(tmp_path):
    return tmp_path / "smartdesk.db"


@pytest.fixture
def jira():
    return FakeJira()


def start(db, jira, thread_id: str) -> tuple[ChatSession, JiraTicketService]:
    service = JiraTicketService(jira.client(), TicketStore(db), project_key="KAN", reconcile_delay_seconds=0)
    llm = FakeLLM({RAISE: I.CREATE_TICKET, MONITOR_TEXT: I.PROVIDE_INFO}, tickets_by_text={MONITOR_TEXT: MONITOR})
    graph = build_graph(
        llm, FakeRetriever(), min_similarity=0.35, ticket_service=service, checkpointer=open_checkpointer(db)
    )
    return ChatSession(graph, thread_id), service


def to_review(session: ChatSession) -> None:
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    assert session.send(EMAIL).approval is not None


def ticket_counts(db) -> tuple[int, int]:
    conn = sqlite3.connect(db)
    try:
        return (
            conn.execute("SELECT COUNT(*) FROM ticket_ops").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM employee_tickets").fetchone()[0],
        )
    finally:
        conn.close()


def checkpoint_threads(db) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
    finally:
        conn.close()


def run(db, *args, now=None, answer="y"):
    return sessions.main(["--db", str(db), *args], now=now, confirm=lambda prompt: answer)


def later(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def test_tickets_remain_listable_after_delete_older_than(db, jira):
    session, service = start(db, jira, "old-session")
    to_review(session)
    created = session.send("approve")
    assert created.text.startswith("Your ticket has been created: KAN-1")
    counts_before, requests_before = ticket_counts(db), len(jira.requests)

    assert run(db, "delete", "--older-than", "30d", "--yes", now=later(40)) == 0

    assert checkpoint_threads(db) == set()  # the conversation is gone
    assert ticket_counts(db) == counts_before == (1, 1)  # ticket ops and mappings are untouched
    assert len(jira.requests) == requests_before  # and Jira was never called
    assert [t.key for t in service.list_tickets(EMAIL)] == ["KAN-1"]  # status lookups still work


def test_older_than_keeps_recent_sessions(db, jira):
    session, _ = start(db, jira, "recent")
    session.send(RAISE)

    assert run(db, "delete", "--older-than", "30d", "--yes", now=later(10)) == 0
    assert checkpoint_threads(db) == {"recent"}


def test_delete_one_session_only(db, jira):
    first, _ = start(db, jira, "first")
    second, _ = start(db, jira, "second")
    first.send(RAISE)
    second.send(RAISE)

    assert run(db, "delete", "--session", "first", "--yes") == 0
    assert checkpoint_threads(db) == {"second"}
    assert run(db, "delete", "--session", "nope", "--yes") == 1


def test_declined_confirmation_changes_nothing(db, jira):
    session, _ = start(db, jira, "keep")
    session.send(RAISE)

    assert run(db, "delete", "--session", "keep", answer="n") == 1
    assert run(db, "compact", answer="") == 1
    assert checkpoint_threads(db) == {"keep"}


def test_list_shows_sessions_and_pending_approvals(db, jira, capsys):
    paused, _ = start(db, jira, "paused")
    to_review(paused)
    done, _ = start(db, jira, "done")
    done.send(RAISE)

    saver = open_checkpointer(db)
    info = {s.thread_id: s for s in list_sessions(saver)}
    saver.conn.close()
    assert info["paused"].pending_approval is True  # also checks LangGraph's interrupt channel name
    assert info["done"].pending_approval is False
    assert info["paused"].checkpoints > 1 and info["paused"].size_bytes > 0

    assert run(db, "list") == 0
    out = capsys.readouterr().out
    assert "paused" in out and "done" in out and "yes" in out


def test_compact_keeps_one_checkpoint_per_session_and_a_paused_approval_still_resumes(db, jira):
    paused, _ = start(db, jira, "paused")
    to_review(paused)
    op_id = paused.pending_approval()["op_id"]
    paused.graph.checkpointer.conn.close()
    size_before = db.stat().st_size

    assert run(db, "compact", "--yes") == 0

    saver = open_checkpointer(db)
    assert [s.checkpoints for s in list_sessions(saver)] == [1]
    saver.conn.close()
    assert db.stat().st_size < size_before

    resumed, service = start(db, jira, "paused")
    assert resumed.pending_approval()["op_id"] == op_id
    assert resumed.state()["session_email"] == EMAIL
    assert resumed.send("approve").text.startswith("Your ticket has been created: KAN-1")
    assert [t.key for t in service.list_tickets(EMAIL)] == ["KAN-1"]


@pytest.mark.parametrize("value", ["30", "0d", "2w", "-1d"])
def test_invalid_age_is_rejected(db, jira, value):
    session, _ = start(db, jira, "s")
    session.send(RAISE)
    with pytest.raises(SystemExit):
        run(db, "delete", "--older-than", value, "--yes")


def test_missing_database_is_reported(tmp_path, capsys):
    assert run(tmp_path / "none.db", "list") == 0
    assert "No session database" in capsys.readouterr().out
