"""Session (conversation checkpoint) maintenance: `python -m smartdesk.sessions`.

    list                          sessions, newest first: id, last activity, checkpoints, size, pending approval
    delete --session ID           delete one session
    delete --older-than 30d|12h   delete sessions with no activity for that long
    compact                       keep only each session's newest checkpoint, then shrink the file

Only conversation checkpoints are touched. Ticket mappings, ticket creation
operations and Jira tickets are never deleted, so status lookups keep working.
`delete` and `compact` ask for confirmation unless `--yes` is given. Stop
SmartDesk first; a deleted session cannot be resumed.
"""

import argparse
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smartdesk.graph.checkpoint import SessionInfo, compact, delete_sessions, list_sessions, open_checkpointer

_AGE = re.compile(r"^(\d+)([dh])$")


def parse_age(text: str) -> timedelta:
    match = _AGE.fullmatch(text.strip().lower())
    if not match or int(match.group(1)) == 0:
        raise argparse.ArgumentTypeError("use a positive number of days or hours, e.g. 30d or 12h")
    amount = int(match.group(1))
    return timedelta(days=amount) if match.group(2) == "d" else timedelta(hours=amount)


def _row(session: SessionInfo) -> str:
    when = session.last_activity.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    pending = "yes" if session.pending_approval else ""
    return f"{session.thread_id:<38} {when:<17} {session.checkpoints:>6} {session.size_bytes / 1024:>9.1f}  {pending}"


def _default_db() -> Path:
    if path := os.getenv("SMARTDESK_DB_PATH"):
        return Path(path)
    try:
        from smartdesk.config import get_settings

        return get_settings().db_path
    except ValueError:  # settings need OPENAI_API_KEY; this command does not
        return Path("data/smartdesk.db")


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    confirm: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m smartdesk.sessions", description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, help="SQLite file (default: SMARTDESK_DB_PATH or data/smartdesk.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list sessions")
    delete = commands.add_parser("delete", help="delete sessions")
    which = delete.add_mutually_exclusive_group(required=True)
    which.add_argument("--session", help="the session id to delete")
    which.add_argument("--older-than", type=parse_age, help="delete sessions inactive for this long, e.g. 30d or 12h")
    delete.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    compact_cmd = commands.add_parser("compact", help="keep only the newest checkpoint per session and shrink the file")
    compact_cmd.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)

    db = args.db or _default_db()
    if not db.exists():
        print(f"No session database at {db}.")
        return 0
    saver = open_checkpointer(db)
    try:
        sessions = list_sessions(saver)
        if args.command == "list":
            if not sessions:
                print("No sessions.")
                return 0
            print(f"{'session':<38} {'last activity UTC':<17} {'ckpts':>6} {'size KB':>9}  approval pending")
            for session in sessions:
                print(_row(session))
            return 0

        if args.command == "compact":
            count = sum(s.checkpoints for s in sessions) - len(sessions)
            prompt = f"Remove {count} older checkpoints from {len(sessions)} sessions (conversations stay resumable)?"
            if not args.yes and confirm(f"{prompt} [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing changed.")
                return 1
            before = db.stat().st_size
            removed = compact(saver)
            print(f"Removed {removed} checkpoints; {db.name}: {before / 1024:.0f} KB -> {db.stat().st_size / 1024:.0f} KB.")
            return 0

        if args.session:
            targets = [s for s in sessions if s.thread_id == args.session]
            if not targets:
                print(f"No session {args.session}.")
                return 1
        else:
            cutoff = (now or datetime.now(UTC)) - args.older_than
            targets = [s for s in sessions if s.last_activity < cutoff]
            if not targets:
                print("No sessions are that old.")
                return 0
        for session in targets:
            print(_row(session))
        prompt = f"Delete these {len(targets)} sessions? Tickets and ticket lookups are not affected."
        if not args.yes and confirm(f"{prompt} [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing deleted.")
            return 1
        delete_sessions(saver, [s.thread_id for s in targets])
        print(f"Deleted {len(targets)} sessions.")
        return 0
    finally:
        saver.conn.close()


if __name__ == "__main__":
    sys.exit(main())
