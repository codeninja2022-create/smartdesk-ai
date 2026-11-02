"""Chainlit UI: `chainlit run src/smartdesk/ui/app.py` (from the repository root).

Thin handlers over `AsyncChatSession` (D5.9, D8.1). One Chainlit chat is one
session with a new thread_id; New Chat starts another, which is how a
different email is used (D5.6). The graph and its services are built once per
process and shared. What a turn looks like is decided in `ui.render`.
"""

import asyncio
import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import chainlit as cl
from langgraph.graph.state import CompiledStateGraph

from smartdesk import observability
from smartdesk.config import Settings, get_settings
from smartdesk.graph import AsyncChatSession, ChatSession, TurnResult, build_graph, open_checkpointer, prompts
from smartdesk.llm import get_resilient_chat_model
from smartdesk.rag.retriever import build_retriever
from smartdesk.redaction import install_log_redaction
from smartdesk.tickets import build_ticket_service
from smartdesk.ui import render

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
install_log_redaction()  # emails, keys and tokens never reach the log output (K6)

NOT_AVAILABLE = "SmartDesk isn't available right now. Please check the server log and start a new chat."
KB_EMPTY = "The knowledge base index is empty; run `python -m smartdesk.kb.ingest` and restart SmartDesk."
EDIT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class _App:
    settings: Settings
    graph: CompiledStateGraph | None  # None when the knowledge base index is empty
    jira_on: bool


_app: _App | None = None
_app_lock = asyncio.Lock()


def _build() -> _App:
    settings = get_settings()
    retriever = build_retriever(settings)
    if retriever.collection.count() == 0:
        return _App(settings, None, False)
    ticket_service = build_ticket_service(settings) if settings.jira_configured else None
    graph = build_graph(
        get_resilient_chat_model(settings),
        retriever,
        min_similarity=settings.rag_min_similarity,
        ticket_service=ticket_service,
        checkpointer=open_checkpointer(settings.db_path),
        router_history_turns=settings.router_history_turns,
    )
    return _App(settings, graph, ticket_service is not None)


async def _get_app() -> _App:
    global _app
    async with _app_lock:
        if _app is None:
            _app = await asyncio.to_thread(_build)
    return _app


def _guarded(handler: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Any failure outside ChatSession (which handles its own) becomes a safe reply.

    Chainlit passes arguments by the handler's parameter names (`action=...`), so both kinds are forwarded.
    """

    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            await handler(*args, **kwargs)
        except Exception as exc:
            log.error("UI handler %s failed: %s", handler.__name__, type(exc).__name__)  # only the type
            await cl.ErrorMessage(content=prompts.INTERNAL_ERROR).send()

    return wrapper


def _session() -> AsyncChatSession | None:
    return cl.user_session.get("session")


async def _clear_buttons() -> None:
    """Remove the buttons of the last message that had any: only the newest message offers actions."""
    message = cl.user_session.get("buttons_message")
    if message is not None:
        cl.user_session.set("buttons_message", None)
        await message.remove_actions()


def _actions(buttons: list[render.Button]) -> list[cl.Action]:
    return [cl.Action(name=b.name, label=b.label, payload=b.payload) for b in buttons]


def _citation_elements(result: TurnResult, settings: Settings) -> list[cl.Text]:
    elements = []
    for citation in render.cited_in_text(result):
        if (panel := render.citation_panel(citation, settings.kb_dir)) is not None:
            elements.append(cl.Text(name=citation["doc_id"], content=panel, display="side"))
    return elements


async def _show(result: TurnResult) -> None:
    app = await _get_app()
    kind = render.message_kind(result)
    replies = result.replies or [prompts.INTERNAL_ERROR]
    for index, reply in enumerate(replies):
        text = render.to_markdown(reply)
        if kind == "error":
            await cl.ErrorMessage(content=text).send()
            continue
        if index < len(replies) - 1:
            await cl.Message(content=text).send()
            continue
        if kind == "warning":
            text = f"⚠️ {text}"
        if result.created_ticket:
            text = f"{render.created_banner(result.created_ticket)}\n\n{text}"
        buttons = render.approval_buttons(result.approval) if result.approval else []
        if not buttons and result.error is None:
            buttons = render.candidate_buttons(result.state)
        message = cl.Message(content=text, elements=_citation_elements(result, app.settings), actions=_actions(buttons))
        await message.send()
        if buttons:
            cl.user_session.set("buttons_message", message)


async def _show_pending(session: AsyncChatSession, note: str) -> None:
    """After a dialog changed nothing: say so and offer the review buttons again."""
    approval = await session.pending_approval()
    buttons = render.approval_buttons(approval) if approval else []
    message = cl.Message(content=note, actions=_actions(buttons))
    await message.send()
    if buttons:
        cl.user_session.set("buttons_message", message)


@cl.on_chat_start
@_guarded
async def on_chat_start() -> None:
    try:
        app = await _get_app()
    except Exception as exc:
        log.error("SmartDesk failed to start: %s", type(exc).__name__)
        await cl.ErrorMessage(content=NOT_AVAILABLE).send()
        return
    if app.graph is None:
        await cl.ErrorMessage(content=KB_EMPTY).send()
        return
    settings = app.settings
    thread_id = str(uuid.uuid4())
    session = ChatSession(
        app.graph, thread_id, observability.get_callbacks(settings), max_input_chars=settings.max_input_chars
    )
    cl.user_session.set("session", AsyncChatSession(session))
    await cl.Message(content=render.welcome_text(thread_id, app.jira_on)).send()


@cl.on_message
@_guarded
async def on_message(message: cl.Message) -> None:
    session = _session()
    if session is None:
        await cl.ErrorMessage(content=NOT_AVAILABLE).send()
        return
    await _clear_buttons()
    await _show(await session.send(message.content))


@cl.action_callback(render.APPROVE)
@_guarded
async def on_approve(action: cl.Action) -> None:
    if session := _session():
        await _clear_buttons()
        await _show(await session.approve(action.payload["op_id"]))


@cl.action_callback(render.CANCEL)
@_guarded
async def on_cancel(action: cl.Action) -> None:
    if session := _session():
        await _clear_buttons()
        await _show(await session.cancel())


@cl.action_callback(render.CHOOSE)
@_guarded
async def on_choose(action: cl.Action) -> None:
    if session := _session():
        await _clear_buttons()
        await _show(await session.send(action.payload["key"]))


@cl.action_callback(render.EDIT)
@_guarded
async def on_edit(action: cl.Action) -> None:
    # An Ask* message ends with task_start() ("busy"), and Chainlit sends no task_end() after an
    # action callback (only after on_message), so every button would stay disabled without this.
    try:
        await _edit_dialog(action)
    finally:
        await cl.context.emitter.task_end()


async def _edit_dialog(action: cl.Action) -> None:
    session = _session()
    if session is None:
        return
    await _clear_buttons()
    if ((await session.pending_approval()) or {}).get("op_id") != action.payload["op_id"]:
        await cl.Message(content=prompts.NO_PENDING_APPROVAL).send()
        return
    field = await cl.AskActionMessage(
        content="Which field would you like to change?",
        actions=[cl.Action(name="field", label=label, payload={"field": name})
                 for name, label in render.FIELD_LABELS.items()],
        timeout=EDIT_TIMEOUT_SECONDS,
    ).send()
    if not field:
        await _show_pending(session, "Nothing was changed. The ticket is still waiting for your approval.")
        return
    name = field["payload"]["field"]
    label = render.FIELD_LABELS[name].lower()
    if name in render.FIELD_CHOICES:
        choice = await cl.AskActionMessage(
            content=f"Choose the new {label}:",
            actions=[cl.Action(name="value", label=v, payload={"value": v}) for v in render.FIELD_CHOICES[name]],
            timeout=EDIT_TIMEOUT_SECONDS,
        ).send()
        value = choice["payload"]["value"] if choice else None
    else:
        answer = await cl.AskUserMessage(content=f"Type the new {label}:", timeout=EDIT_TIMEOUT_SECONDS).send()
        value = answer["output"] if answer else None
    if value is None:
        await _show_pending(session, "Nothing was changed. The ticket is still waiting for your approval.")
        return
    await _show(await session.edit({name: value}))


@cl.on_chat_end
async def on_chat_end() -> None:
    await asyncio.to_thread(observability.flush)
