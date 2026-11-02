"""ChatSession: the only way application code (CLI, and Chainlit in M8) drives the graph.

It hides LangGraph's interrupt/resume mechanics. When a ticket is waiting for
approval, the next input resumes that interrupt instead of starting a new turn:

    approve(op_id=None)  -> {"action": "approve", "op_id": <the given op_id, else the pending one>}
    edit(fields)         -> {"action": "edit", "fields": {...}}
    cancel()             -> {"action": "cancel"}
    send(text)           -> approve / cancel for an exact approval or cancel word, else
                            {"action": "message", "text": text}

Keeping this the single entry point means the checkpointer or execution model
can change without touching the nodes. `AsyncChatSession` is that change for
Chainlit: the same calls, run on one process-wide worker thread (D8.1).

It is also where the input guardrails run (`smartdesk.guardrails`): a rejected
message gets a reply and never reaches the graph. Any failure inside a turn
becomes a safe reply; only the exception type is logged, never its message.
"""

import asyncio
import functools
import logging
import re
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from smartdesk.graph import prompts
from smartdesk.guardrails import check_input
from smartdesk.llm import FALLBACK_ERRORS

log = logging.getLogger(__name__)

APPROVE_WORDS = {"approve", "approved", "yes", "y", "confirm", "submit", "create it", "yes create it", "yes please"}
CANCEL_WORDS = {"cancel", "no", "n", "abort", "cancel it", "don't create it"}


def normalize_reply(text: str) -> str:
    return re.sub(r"[^a-z' ]", "", " ".join(text.lower().replace("’", "'").split())).strip()


def resume_for_text(text: str, op_id: str) -> dict[str, Any]:
    """Map typed text at the approval step to a resume value. Only exact words approve."""
    normalized = normalize_reply(text)
    if normalized in APPROVE_WORDS:
        return {"action": "approve", "op_id": op_id}
    if normalized in CANCEL_WORDS:
        return {"action": "cancel"}
    return {"action": "message", "text": text}


@dataclass(frozen=True)
class TurnResult:
    replies: list[str]  # SmartDesk messages produced by this turn, in order
    approval: dict | None  # the pending ticket approval (op_id, draft, text), if the graph is paused
    state: dict
    # empty | too_long (input rejected) | llm_unavailable | internal_error | no_pending_approval
    error: str | None = None
    created_ticket: dict | None = None  # CreatedTicket.to_dict(), only on the turn that created (or found) it

    @property
    def text(self) -> str:
        return "\n\n".join(self.replies)


class ChatSession:
    def __init__(
        self, graph: CompiledStateGraph, thread_id: str, callbacks: list | None = None, *, max_input_chars: int = 2000
    ) -> None:
        self.graph = graph
        self.thread_id = thread_id
        self.max_input_chars = max_input_chars
        self.config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        if callbacks:
            self.config["callbacks"] = callbacks

    def pending_approval(self) -> dict | None:
        for pending in self.graph.get_state(self.config).interrupts:
            if isinstance(pending.value, dict) and pending.value.get("type") == "ticket_approval":
                return pending.value
        return None

    def state(self) -> dict:
        return dict(self.graph.get_state(self.config).values)

    def send(self, text: str) -> TurnResult:
        text, problem = check_input(text, self.max_input_chars)
        if problem:  # never reaches the graph, the LLM or the stored history
            reply = prompts.INPUT_REJECTED[problem].format(limit=self.max_input_chars)
            return TurnResult([reply], self.pending_approval(), self.state(), error=problem)
        if approval := self.pending_approval():
            return self._run(Command(resume=resume_for_text(text, approval["op_id"])))
        return self._run({"messages": [HumanMessage(content=text)]})

    def approve(self, op_id: str | None = None) -> TurnResult:
        """Approve the pending ticket. A UI passes the op_id it displayed: a stale one is rejected (D5.3)."""
        approval = self._require_approval()
        return self._run(Command(resume={"action": "approve", "op_id": op_id or approval["op_id"]}))

    def edit(self, fields: dict[str, Any]) -> TurnResult:
        approval = self._require_approval()
        cleaned = dict(fields)
        for name, value in fields.items():  # typed values get the same input guardrails as messages
            if isinstance(value, str):
                cleaned[name], problem = check_input(value, self.max_input_chars)
                if problem:
                    reply = prompts.INPUT_REJECTED[problem].format(limit=self.max_input_chars)
                    return TurnResult([reply], approval, self.state(), error=problem)
        return self._run(Command(resume={"action": "edit", "fields": cleaned}))

    def cancel(self) -> TurnResult:
        self._require_approval()
        return self._run(Command(resume={"action": "cancel"}))

    def _require_approval(self) -> dict:
        approval = self.pending_approval()
        if approval is None:
            raise RuntimeError("no ticket is waiting for approval")
        return approval

    def _run(self, graph_input: Any) -> TurnResult:
        previous = self.state()
        before = len(previous.get("messages", []))
        try:
            self.graph.invoke(graph_input, self.config)
        except Exception as exc:  # the conversation must survive any failure inside a turn
            # Only the type: messages can carry user text, emails or secrets.
            log.error("Turn failed in session %s: %s", self.thread_id[:8], type(exc).__name__)
            state = self.state()
            llm_down = isinstance(exc, FALLBACK_ERRORS)
            reply = prompts.LLM_UNAVAILABLE if llm_down else prompts.INTERNAL_ERROR
            if state.get("ticket_draft"):
                reply = f"{reply} {prompts.DRAFT_SAVED}"
            return TurnResult(
                [reply], self.pending_approval(), state, error="llm_unavailable" if llm_down else "internal_error"
            )
        state = self.state()
        replies = [str(m.content) for m in state.get("messages", [])[before:] if isinstance(m, AIMessage)]
        ticket = state.get("last_ticket")
        created = ticket if ticket and ticket != previous.get("last_ticket") else None
        return TurnResult(replies, self.pending_approval(), state, created_ticket=created)


# One worker for every session: TicketStore and SqliteSaver each share a single
# SQLite connection across threads, so turns run one at a time (D8.1).
_TURN_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smartdesk-turn")


class AsyncChatSession:
    """ChatSession for async UIs (Chainlit): every call runs on the shared worker thread.

    approve / edit / cancel check for a pending approval inside the same worker task,
    so a double click or a stale button gets a reply instead of an exception.
    """

    def __init__(self, session: ChatSession, executor: Executor = _TURN_WORKER) -> None:
        self.session = session
        self._executor = executor

    @property
    def thread_id(self) -> str:
        return self.session.thread_id

    async def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._executor, functools.partial(fn, *args))

    async def send(self, text: str) -> TurnResult:
        return await self._call(self.session.send, text)

    async def pending_approval(self) -> dict | None:
        return await self._call(self.session.pending_approval)

    async def state(self) -> dict:
        return await self._call(self.session.state)

    async def approve(self, op_id: str | None = None) -> TurnResult:
        return await self._call(self._if_pending, self.session.approve, op_id)

    async def edit(self, fields: dict[str, Any]) -> TurnResult:
        return await self._call(self._if_pending, self.session.edit, fields)

    async def cancel(self) -> TurnResult:
        return await self._call(self._if_pending, self.session.cancel)

    def _if_pending(self, action: Callable[..., TurnResult], *args: Any) -> TurnResult:
        if self.session.pending_approval() is None:
            return TurnResult([prompts.NO_PENDING_APPROVAL], None, self.session.state(), error="no_pending_approval")
        return action(*args)
