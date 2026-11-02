"""Minimal CLI for the workflow: `python -m smartdesk [--session ID]`.

Each run starts a new session (a new thread_id) unless `--session` resumes an
earlier one from the SQLite checkpoints, including a ticket awaiting approval.
"""

import argparse
import logging
import sys
import uuid

from smartdesk import observability
from smartdesk.config import get_settings
from smartdesk.graph import ChatSession, TurnResult, build_graph, open_checkpointer
from smartdesk.llm import get_resilient_chat_model
from smartdesk.rag.retriever import build_retriever
from smartdesk.redaction import install_log_redaction
from smartdesk.tickets import build_ticket_service

APPROVAL_HINT = "[ticket awaiting approval: type 'approve', 'cancel', or describe a change]"


def _print(result: TurnResult) -> None:
    state = result.state
    debug = f"intent: {state.get('intent')}, domain: {state.get('domain') or '-'}"
    if state.get("retrieved"):
        debug += f", top similarity: {state['retrieved'][0]['similarity']:.3f}"
    if state.get("escalation_reason"):
        debug += f", escalated: {state['escalation_reason']}"
    if state.get("last_error"):
        debug += f", error: {state['last_error']}"
    if result.error:
        debug += f", turn error: {result.error}"
    print(f"[{debug}]")
    print(f"SmartDesk: {result.text}")
    if result.approval:
        print(APPROVAL_HINT)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m smartdesk")
    parser.add_argument("--session", help="resume an earlier session by its id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    install_log_redaction()  # emails, keys and tokens never reach the log output

    settings = get_settings()
    retriever = build_retriever(settings)
    if retriever.collection.count() == 0:
        print("The knowledge base index is empty; run `python -m smartdesk.kb.ingest` first.", file=sys.stderr)
        sys.exit(1)
    ticket_service = build_ticket_service(settings) if settings.jira_configured else None
    checkpointer = open_checkpointer(settings.db_path)
    graph = build_graph(
        get_resilient_chat_model(settings),
        retriever,
        min_similarity=settings.rag_min_similarity,
        ticket_service=ticket_service,
        checkpointer=checkpointer,
        router_history_turns=settings.router_history_turns,
    )
    session = ChatSession(
        graph,
        args.session or str(uuid.uuid4()),
        observability.get_callbacks(settings),
        max_input_chars=settings.max_input_chars,
    )

    tracing = "on" if settings.langfuse_enabled else "off"
    jira = "on" if ticket_service else "off (ticket features disabled)"
    fallback = settings.llm_fallback_model or "canned reply"
    print(f"SmartDesk AI (model={settings.llm_model}, fallback={fallback}, tracing={tracing}, jira={jira}).")
    print(f"Session: {session.thread_id}  (resume with --session {session.thread_id}). Type 'exit' to quit.")
    if approval := session.pending_approval():
        print(f"\nSmartDesk: {approval['text']}\n{APPROVAL_HINT}")
    try:
        while True:
            text = input("\nYou: ")
            if text.strip().lower() in {"exit", "quit"}:
                break
            if text.strip():
                _print(session.send(text))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        observability.flush()
        checkpointer.conn.close()


if __name__ == "__main__":
    main()
