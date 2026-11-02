"""SQLite-backed LangGraph checkpoints, and maintenance of them.

Checkpoints share `SMARTDESK_DB_PATH` (default `data/smartdesk.db`) with the
ticket tables. They hold each session's full conversation, the session email
and any ticket draft awaiting approval, so a session survives a restart when
it is resumed with the same thread_id.

The maintenance helpers (`list_sessions`, `delete_sessions`, `compact`) read and
delete only LangGraph's `checkpoints` and `writes` tables. Ticket mappings and
creation operations (`employee_tickets`, `ticket_ops`) and Jira are never touched.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

# LangGraph's channel for interrupt() writes. It is private in LangGraph, so a test
# checks it against a real paused session.
INTERRUPT_CHANNEL = "__interrupt__"


@dataclass(frozen=True)
class SessionInfo:
    thread_id: str
    last_activity: datetime  # timestamp of the newest checkpoint (UTC)
    checkpoints: int
    size_bytes: int  # checkpoint and pending-write payloads
    pending_approval: bool


def open_checkpointer(db_path: Path | str) -> SqliteSaver:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")  # the ticket store writes to the same file
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _latest_checkpoint_ids(conn: sqlite3.Connection) -> dict[str, str]:
    # Checkpoint ids are time-ordered (uuid6), as SqliteSaver itself relies on.
    rows = conn.execute(
        "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints WHERE checkpoint_ns = '' GROUP BY thread_id"
    )
    return dict(rows.fetchall())


def list_sessions(saver: SqliteSaver) -> list[SessionInfo]:
    """All sessions, most recently active first."""
    conn = saver.conn
    counts = dict(
        (thread, (count, size))
        for thread, count, size in conn.execute(
            "SELECT thread_id, COUNT(*), SUM(LENGTH(checkpoint) + COALESCE(LENGTH(metadata), 0)) "
            "FROM checkpoints GROUP BY thread_id"
        )
    )
    write_sizes = dict(conn.execute("SELECT thread_id, SUM(COALESCE(LENGTH(value), 0)) FROM writes GROUP BY thread_id"))
    sessions = []
    for thread_id, latest in _latest_checkpoint_ids(conn).items():
        latest_tuple = saver.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        assert latest_tuple is not None
        pending = conn.execute(
            "SELECT 1 FROM writes WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id = ? AND channel = ?",
            (thread_id, latest, INTERRUPT_CHANNEL),
        ).fetchone()
        count, size = counts[thread_id]
        sessions.append(
            SessionInfo(
                thread_id=thread_id,
                last_activity=datetime.fromisoformat(latest_tuple.checkpoint["ts"]),
                checkpoints=count,
                size_bytes=(size or 0) + (write_sizes.get(thread_id) or 0),
                pending_approval=pending is not None,
            )
        )
    return sorted(sessions, key=lambda s: s.last_activity, reverse=True)


def delete_sessions(saver: SqliteSaver, thread_ids: list[str]) -> int:
    """Delete these sessions' checkpoints and pending writes; return how many were deleted."""
    for thread_id in thread_ids:
        saver.delete_thread(thread_id)
    return len(thread_ids)


def compact(saver: SqliteSaver) -> int:
    """Keep only the newest checkpoint (and its pending writes) of every session.

    That is all a session needs to continue, including a ticket awaiting approval.
    Returns the number of checkpoints removed; then reclaims the space on disk.
    """
    conn = saver.conn
    removed = 0
    with saver.lock:
        for thread_id, latest in _latest_checkpoint_ids(conn).items():
            removed += conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id != ?", (thread_id, latest)
            ).rowcount
            conn.execute("DELETE FROM writes WHERE thread_id = ? AND checkpoint_id != ?", (thread_id, latest))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    return removed
