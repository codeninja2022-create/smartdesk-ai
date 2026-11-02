"""SQLite store: employee-to-ticket mappings and idempotent creation operations.

`ticket_ops` records every creation attempt under its stable op_id:

- `pending`: a caller owns the op: a POST or reconcile is about to run or in flight
- `unknown`: the outcome was ambiguous (timeout, 5xx), no issue was found, and the
  caller gave up; the next call takes it over and reconciles first
- `created`: the issue exists; `ticket_key` is set
- `failed`: Jira definitely did not create anything, so a retry is safe

Every write bumps `version`. Ownership changes and the owner's own writes are
compare-and-set on it (`take_over`, `heartbeat`), so at most one caller can
work on an op: a caller whose version is stale has lost it and must not POST.

`employee_tickets` is the local email -> ticket mapping. Jira stays the source
of truth for status and comments.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

OpStatus = Literal["pending", "unknown", "created", "failed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_ops (
  op_id       TEXT PRIMARY KEY,
  email       TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('pending', 'unknown', 'created', 'failed')),
  ticket_key  TEXT,
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_error  TEXT,
  version     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_tickets (
  email       TEXT NOT NULL,
  ticket_key  TEXT NOT NULL,
  category    TEXT NOT NULL CHECK (category IN ('IT', 'HR')),
  op_id       TEXT REFERENCES ticket_ops(op_id),
  created_at  TEXT NOT NULL,
  PRIMARY KEY (email, ticket_key)
);

CREATE INDEX IF NOT EXISTS ix_employee_tickets_email ON employee_tickets(email);
"""


@dataclass(frozen=True)
class TicketOp:
    op_id: str
    email: str
    status: OpStatus
    ticket_key: str | None
    attempts: int
    last_error: str | None
    updated_at: str
    version: int = 1


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class TicketStore:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: explicit BEGIN IMMEDIATE where atomicity matters.
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(ticket_ops)")}
        if "version" not in columns:  # databases created before M6
            self._conn.execute("ALTER TABLE ticket_ops ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

    def close(self) -> None:
        self._conn.close()

    # --- creation operations ---

    def get_op(self, op_id: str) -> TicketOp | None:
        row = self._conn.execute("SELECT * FROM ticket_ops WHERE op_id = ?", (op_id,)).fetchone()
        if row is None:
            return None
        return TicketOp(
            op_id=row["op_id"],
            email=row["email"],
            status=row["status"],
            ticket_key=row["ticket_key"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            updated_at=row["updated_at"],
            version=row["version"],
        )

    def claim_op(self, op_id: str, email: str) -> bool:
        """Atomically move an op to `pending` if it is new or `failed`.

        Returns False when the op already exists in any other state, i.e. another
        submission owns it (pending/unknown) or it already succeeded (created).
        """
        now = _now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute("SELECT status FROM ticket_ops WHERE op_id = ?", (op_id,)).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO ticket_ops (op_id, email, status, attempts, created_at, updated_at) "
                    "VALUES (?, ?, 'pending', 0, ?, ?)",
                    (op_id, email, now, now),
                )
                claimed = True
            elif row["status"] == "failed":
                self._conn.execute(
                    "UPDATE ticket_ops SET status = 'pending', attempts = 0, last_error = NULL, updated_at = ?, "
                    "version = version + 1 WHERE op_id = ?",
                    (now, op_id),
                )
                claimed = True
            else:
                claimed = False
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return claimed

    def record_attempt(self, op_id: str) -> int:
        """Count a POST before it is sent, so a crash mid-request still leaves a trace."""
        self._conn.execute(
            "UPDATE ticket_ops SET attempts = attempts + 1, status = 'pending', updated_at = ?, version = version + 1 "
            "WHERE op_id = ?",
            (_now(), op_id),
        )
        op = self.get_op(op_id)
        assert op is not None
        return op.attempts

    def take_over(self, observed: TicketOp) -> int | None:
        """Become the owner of an `unknown` or stale `pending` op, if it is unchanged since `observed`.

        Returns the new version, or None when another caller changed the op first.
        """
        cursor = self._conn.execute(
            "UPDATE ticket_ops SET status = 'pending', updated_at = ?, version = version + 1 "
            "WHERE op_id = ? AND status = ? AND version = ?",
            (_now(), observed.op_id, observed.status, observed.version),
        )
        return observed.version + 1 if cursor.rowcount == 1 else None

    def heartbeat(self, op_id: str, version: int, *, attempt: bool = False, error: str | None = None) -> int | None:
        """The owner's write: stay `pending`, refresh `updated_at`, optionally count a POST or note an error.

        Returns the new version, or None when `version` is stale (ownership was lost).
        """
        cursor = self._conn.execute(
            "UPDATE ticket_ops SET status = 'pending', updated_at = ?, attempts = attempts + ?, "
            "last_error = COALESCE(?, last_error), version = version + 1 WHERE op_id = ? AND version = ?",
            (_now(), 1 if attempt else 0, error, op_id, version),
        )
        return version + 1 if cursor.rowcount == 1 else None

    def mark_unknown(self, op_id: str, error: str, *, version: int | None = None) -> None:
        """Give up on an ambiguous op. With `version`, only if the caller still owns it."""
        if version is None:
            self._set_status(op_id, "unknown", error=error)
            return
        self._conn.execute(
            "UPDATE ticket_ops SET status = 'unknown', last_error = ?, updated_at = ?, version = version + 1 "
            "WHERE op_id = ? AND version = ?",
            (error, _now(), op_id, version),
        )

    def mark_failed(self, op_id: str, error: str) -> None:
        self._set_status(op_id, "failed", error=error)

    def mark_created(self, op_id: str, ticket_key: str, category: str) -> None:
        """Record success and the email mapping in one transaction."""
        now = _now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "UPDATE ticket_ops SET status = 'created', ticket_key = ?, last_error = NULL, updated_at = ?, "
                "version = version + 1 WHERE op_id = ?",
                (ticket_key, now, op_id),
            )
            email = self._conn.execute("SELECT email FROM ticket_ops WHERE op_id = ?", (op_id,)).fetchone()["email"]
            self._conn.execute(
                "INSERT INTO employee_tickets (email, ticket_key, category, op_id, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (email, ticket_key) DO UPDATE SET op_id = excluded.op_id",
                (email, ticket_key, category, op_id, now),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def _set_status(self, op_id: str, status: OpStatus, error: str | None) -> None:
        self._conn.execute(
            "UPDATE ticket_ops SET status = ?, last_error = ?, updated_at = ?, version = version + 1 WHERE op_id = ?",
            (status, error, _now(), op_id),
        )

    # --- email -> ticket mapping ---

    def add_mapping(self, email: str, ticket_key: str, category: str) -> None:
        """Record a ticket discovered in Jira; keeps any existing op link."""
        self._conn.execute(
            "INSERT INTO employee_tickets (email, ticket_key, category, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (email, ticket_key) DO NOTHING",
            (email, ticket_key, category, _now()),
        )

    def ticket_keys(self, email: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT ticket_key FROM employee_tickets WHERE email = ? ORDER BY created_at DESC", (email,)
        ).fetchall()
        return [row["ticket_key"] for row in rows]

    def is_mapped(self, email: str, ticket_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM employee_tickets WHERE email = ? AND ticket_key = ?", (email, ticket_key)
        ).fetchone()
        return row is not None
