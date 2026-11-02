"""SmartDesk LangGraph workflow: a single agent with deterministic routing.

    START -> classify_intent -> email_locked                        (a different email in a locked session)
                             -> greeting | out_of_scope | clarify | cancel_flow
                             -> retrieve -> generate_answer | escalate          (knowledge questions, M3)
                             -> collect_ticket -> present_ticket -> review_ticket -> submit_ticket
                             -> check_status
    every branch ends the turn (END) or pauses in review_ticket's interrupt()

`classify_intent` is flow-aware: when SmartDesk is waiting for an answer
(email, issue details, which ticket) it tells the classifier, so a reply can
be told apart from a new request. A new request mid-flow is handled normally
and an open ticket draft is kept on hold.

The ticket nodes live in `graph/tickets.py` and the status node in
`graph/status.py`. Application code drives the graph only through
`graph.session.ChatSession`.
"""

from collections.abc import Callable
from typing import Any, Protocol

from smartdesk.llm import StructuredLLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smartdesk.graph import prompts, tickets
from smartdesk.graph.identity import find_email_claim, mask_email
from smartdesk.graph.state import Intent, IntentClassification, SmartDeskState
from smartdesk.graph.status import CHECK_STATUS, choice_number, make_status_node
from smartdesk.rag import answer as rag_answer
from smartdesk.rag.retriever import RetrievedChunk
from smartdesk.tickets.service import TicketService

CLASSIFY = "classify_intent"
RETRIEVE, GENERATE_ANSWER, ESCALATE = "retrieve", "generate_answer", "escalate"
CLARIFY, CANCEL_FLOW, EMAIL_LOCKED = "clarify", "cancel_flow", "email_locked"
TICKET_AWAITING = ("ticket_details", "ticket_category", "held_draft")


class SupportsRetrieve(Protocol):
    def retrieve(self, query: str, domain: str | None = None) -> list[RetrievedChunk]: ...


def _latest_question(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _latest_question_index(messages: list[BaseMessage]) -> int | None:
    return next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)


def _on_hold(node: Callable[[SmartDeskState], dict]) -> Callable[[SmartDeskState], dict]:
    """Remind the employee of a ticket draft left open while they asked something else."""

    def wrapped(state: SmartDeskState) -> dict:
        result = node(state)
        if state.get("ticket_draft") and result.get("messages") and not result.get("awaiting"):
            *rest, last = result["messages"]
            result["messages"] = [*rest, AIMessage(content=f"{last.content}\n\n{prompts.ON_HOLD_NOTE}")]
        return result

    wrapped.__name__ = getattr(node, "__name__", "node")
    return wrapped


def _reply(text: str) -> Callable[[SmartDeskState], dict]:
    def node(state: SmartDeskState) -> dict:
        return {"messages": [AIMessage(content=text)]}

    return node


# --- routing ---


def _flow_context(state: SmartDeskState) -> str | None:
    lines = []
    if awaiting := state.get("awaiting"):
        lines.append(prompts.FLOW_CONTEXT_AWAITING.format(label=prompts.AWAITING_LABELS[awaiting]))
    if state.get("ticket_draft") or state.get("ticket_flow_start") is not None:  # started, even if still empty
        lines.append(prompts.FLOW_CONTEXT_DRAFT)
    if state.get("ticket_offered"):
        lines.append(prompts.FLOW_CONTEXT_OFFER)
    return "\n".join([prompts.FLOW_CONTEXT_HEADER, *lines]) if lines else None


def _email_update(state: SmartDeskState, text: str) -> dict[str, Any]:
    """Apply the session email lock to the latest message."""
    awaiting_email = state.get("awaiting") == "email"
    claim = find_email_claim(text, awaiting_email=awaiting_email)
    locked = state.get("session_email")
    if claim is None:
        return {"email_event": None}
    if claim.email is None:
        return {"email_event": "invalid" if awaiting_email else None}
    if locked is None:
        return {"email_event": "captured", "session_email": claim.email}
    if claim.email != locked:
        return {"email_event": "conflict"}
    return {"email_event": "captured" if awaiting_email else None}


def recent_turns(messages: list[BaseMessage], turns: int) -> list[BaseMessage]:
    """The messages from the `turns`-th last employee message on. Stored history is never trimmed."""
    human = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
    return messages[human[-turns]:] if len(human) > turns else list(messages)


def _make_classify_node(llm: StructuredLLM, router_history_turns: int) -> Callable[[SmartDeskState], dict]:
    classifier = llm.with_structured_output(IntentClassification)

    def classify_intent(state: SmartDeskState) -> dict:
        question = _latest_question(state["messages"])
        email = _email_update(state, question)
        awaiting = state.get("awaiting")

        # Plain answers to SmartDesk's own question need no LLM call.
        answered = (
            (awaiting == "email" and email["email_event"] in ("captured", "invalid"))
            or (awaiting == "ticket_choice" and choice_number(question, len(state.get("status_candidates") or [])) is not None)
            or (awaiting == "held_draft" and tickets.held_draft_decision(question) is not None)
        )
        if answered:
            result = IntentClassification(intent=Intent.PROVIDE_INFO)
        else:
            context = _flow_context(state)
            extra = [SystemMessage(content=context)] if context else []
            # Only the recent turns: the flow-state line carries what routing needs from older ones.
            recent = recent_turns(state["messages"], router_history_turns)
            result = classifier.invoke([SystemMessage(content=prompts.INTENT_SYSTEM_PROMPT), *extra, *recent])
            assert isinstance(result, IntentClassification)

        # A rewrite only helps follow-ups; on the first question it can only drift.
        is_follow_up = sum(isinstance(m, HumanMessage) for m in state["messages"]) > 1
        query = (result.search_query.strip() if is_follow_up else "") or question
        update: dict[str, Any] = {
            "intent": result.intent.value,
            "domain": None if result.domain == "unknown" else result.domain,
            "search_query": query if result.intent == Intent.KNOWLEDGE_QUESTION else None,
            "retrieved": [],
            "citations": [],
            "escalation_reason": None,
            "last_error": None,
            "ticket_offered": False,
            # The question just handled seeds a ticket only when the very next turn asks for one.
            "seed_start": state.get("seed_start") if result.intent == Intent.CREATE_TICKET else None,
            # Kept only while "continue or new?" is the open question (asked in the last turn).
            "pending_request_index": state.get("pending_request_index") if awaiting == "held_draft" else None,
            **email,
        }
        # A new request ends any pending question; the flow nodes ask again if needed.
        if result.intent != Intent.PROVIDE_INFO:
            update["awaiting"] = None
            update["active_flow"] = None
            if result.intent != Intent.TICKET_STATUS:
                update["status_candidates"] = []
        return update

    return classify_intent


def _route_by_intent(state: SmartDeskState) -> str:
    if state.get("email_event") == "conflict":
        return EMAIL_LOCKED
    intent = state.get("intent") or Intent.OUT_OF_SCOPE.value
    if intent == Intent.KNOWLEDGE_QUESTION.value:
        return RETRIEVE
    if intent == Intent.CREATE_TICKET.value:
        return tickets.COLLECT_TICKET
    if intent == Intent.TICKET_STATUS.value:
        return CHECK_STATUS
    if intent == Intent.CANCEL.value:
        return CANCEL_FLOW
    if intent == Intent.PROVIDE_INFO.value:
        awaiting, flow = state.get("awaiting"), state.get("active_flow")
        if awaiting in TICKET_AWAITING or (awaiting == "email" and flow == "ticket"):
            return tickets.COLLECT_TICKET
        if awaiting == "ticket_choice" or (awaiting == "email" and flow == "status"):
            return CHECK_STATUS
        if state.get("ticket_draft"):  # a correction to the draft on hold
            return tickets.COLLECT_TICKET
        return CLARIFY
    if intent == Intent.UNCLEAR.value:
        return CLARIFY
    return intent  # greeting, out_of_scope


# --- small nodes ---


def _clarify(state: SmartDeskState) -> dict:
    if state.get("email_event") == "captured":
        return {"messages": [AIMessage(content=prompts.EMAIL_NOTED_REPLY.format(email=state["session_email"]))]}
    return {"messages": [AIMessage(content=prompts.CLARIFY_REPLY)]}


def _email_locked(state: SmartDeskState) -> dict:
    text = prompts.EMAIL_LOCKED_REPLY.format(email=mask_email(state["session_email"] or ""))
    return {"messages": [AIMessage(content=text)]}


def _cancel_flow(state: SmartDeskState) -> dict:
    if state.get("ticket_draft"):
        text = prompts.TICKET_CANCELLED
    elif state.get("status_candidates"):
        text = prompts.STATUS_CANCELLED
    else:
        text = prompts.NOTHING_TO_CANCEL
    return {
        "ticket_draft": {},
        "ticket_flow_start": None,
        "pending_flow_start": None,
        "pending_request_index": None,
        "status_candidates": [],
        "active_flow": None,
        "awaiting": None,
        "approved_op_id": None,
        "messages": [AIMessage(content=text)],
    }


# --- knowledge questions (M3) ---


def _make_retrieve_node(retriever: SupportsRetrieve, min_similarity: float) -> Callable[[SmartDeskState], dict]:
    def retrieve(state: SmartDeskState) -> dict:
        chunks = retriever.retrieve(state.get("search_query") or "", state.get("domain"))
        if not chunks:
            return {"retrieved": [], "escalation_reason": "no_results"}
        if chunks[0].similarity < min_similarity:
            return {"retrieved": [c.to_dict() for c in chunks], "escalation_reason": "low_similarity"}
        return {"retrieved": [c.to_dict() for c in chunks]}

    return retrieve


def _route_after_retrieve(state: SmartDeskState) -> str:
    return ESCALATE if state.get("escalation_reason") else GENERATE_ANSWER


def _make_answer_node(llm: StructuredLLM) -> Callable[[SmartDeskState], dict]:
    def generate_answer(state: SmartDeskState) -> dict:
        question = state.get("search_query") or _latest_question(state["messages"])
        result = rag_answer.generate_answer(llm, question, state["retrieved"])
        if not result.grounded:
            return {"escalation_reason": result.reason, "retrieved": _without_text(state["retrieved"])}
        return {
            "messages": [AIMessage(content=rag_answer.render(result))],
            "citations": [c.to_dict() for c in result.citations],
            "retrieved": _without_text(state["retrieved"]),
            "seed_start": _latest_question_index(state["messages"]),  # "raise a ticket for it"
        }

    return generate_answer


def _without_text(retrieved: list[dict]) -> list[dict]:
    """Keep only what identifies each chunk; its text is not needed once the answer step has run."""
    return [{k: chunk[k] for k in ("chunk_id", "doc_id", "similarity")} for chunk in retrieved]


def _route_after_answer(state: SmartDeskState) -> str:
    return ESCALATE if state.get("escalation_reason") else END


def _escalate(state: SmartDeskState) -> dict:
    team = prompts.ESCALATION_TEAM.get(state.get("domain") or "", prompts.ESCALATION_DEFAULT_TEAM)
    return {
        "messages": [AIMessage(content=prompts.ESCALATION_REPLY.format(team=team))],
        "retrieved": _without_text(state.get("retrieved") or []),
        "ticket_offered": True,
        "seed_start": _latest_question_index(state["messages"]),  # a ticket accepting the offer starts here
    }


def build_graph(
    llm: StructuredLLM,
    retriever: SupportsRetrieve,
    *,
    min_similarity: float,
    ticket_service: TicketService | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    router_history_turns: int = 4,
) -> CompiledStateGraph:
    """`ticket_service=None` means Jira is not configured: ticket requests get an explanation."""
    builder = StateGraph(SmartDeskState)

    builder.add_node(CLASSIFY, _make_classify_node(llm, router_history_turns))
    builder.add_node(Intent.GREETING.value, _on_hold(_reply(prompts.GREETING_REPLY)))
    builder.add_node(Intent.OUT_OF_SCOPE.value, _on_hold(_reply(prompts.OUT_OF_SCOPE_REPLY)))
    builder.add_node(CLARIFY, _on_hold(_clarify))
    builder.add_node(EMAIL_LOCKED, _on_hold(_email_locked))
    builder.add_node(CANCEL_FLOW, _cancel_flow)
    builder.add_node(RETRIEVE, _make_retrieve_node(retriever, min_similarity))
    builder.add_node(GENERATE_ANSWER, _on_hold(_make_answer_node(llm)))
    builder.add_node(ESCALATE, _on_hold(_escalate))
    builder.add_node(tickets.COLLECT_TICKET, tickets.make_collect_node(llm))
    builder.add_node(tickets.PRESENT_TICKET, tickets.present_ticket)
    builder.add_node(
        tickets.REVIEW_TICKET,
        tickets.review_ticket,
        destinations=(tickets.SUBMIT_TICKET, tickets.PRESENT_TICKET, CLASSIFY, END),
    )
    builder.add_node(tickets.SUBMIT_TICKET, tickets.make_submit_node(ticket_service))
    builder.add_node(CHECK_STATUS, _on_hold(make_status_node(llm, ticket_service)))

    replies = [Intent.GREETING.value, Intent.OUT_OF_SCOPE.value, CLARIFY, EMAIL_LOCKED, CANCEL_FLOW, CHECK_STATUS]
    builder.add_edge(START, CLASSIFY)
    builder.add_conditional_edges(
        CLASSIFY,
        _route_by_intent,
        {RETRIEVE: RETRIEVE, tickets.COLLECT_TICKET: tickets.COLLECT_TICKET, **{n: n for n in replies}},
    )
    builder.add_conditional_edges(RETRIEVE, _route_after_retrieve, {ESCALATE: ESCALATE, GENERATE_ANSWER: GENERATE_ANSWER})
    builder.add_conditional_edges(GENERATE_ANSWER, _route_after_answer, {ESCALATE: ESCALATE, END: END})
    builder.add_conditional_edges(
        tickets.COLLECT_TICKET, tickets.route_after_collect, {END: END, tickets.PRESENT_TICKET: tickets.PRESENT_TICKET}
    )
    builder.add_edge(tickets.PRESENT_TICKET, tickets.REVIEW_TICKET)
    for node in [*replies, ESCALATE, tickets.SUBMIT_TICKET]:
        builder.add_edge(node, END)

    return builder.compile(checkpointer=checkpointer)
