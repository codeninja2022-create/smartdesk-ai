"""SmartDesk LangGraph workflow.

    START -> classify_intent -> greeting | out_of_scope | create_ticket | ticket_status -> END
                             -> retrieve -> (no hits / top similarity < min_similarity) -> escalate -> END
                                         -> generate_answer -> (grounded) -> END
                                                            -> (insufficient / ungrounded) -> escalate -> END

The ticket and status nodes return placeholder replies until Milestones 4-5.
`escalate` offers a ticket; the ticket flow itself is wired in Milestone 5.
"""

from collections.abc import Callable
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smartdesk.graph import prompts
from smartdesk.graph.state import Intent, IntentClassification, SmartDeskState
from smartdesk.rag import answer as rag_answer
from smartdesk.rag.retriever import RetrievedChunk

RETRIEVE, GENERATE_ANSWER, ESCALATE = "retrieve", "generate_answer", "escalate"


class SupportsRetrieve(Protocol):
    def retrieve(self, query: str, domain: str | None = None) -> list[RetrievedChunk]: ...


def _reply(text: str) -> Callable[[SmartDeskState], dict]:
    def node(state: SmartDeskState) -> dict:
        return {"messages": [AIMessage(content=text)]}

    return node


def _latest_question(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _make_classify_node(llm: BaseChatModel) -> Callable[[SmartDeskState], dict]:
    classifier = llm.with_structured_output(IntentClassification)

    def classify_intent(state: SmartDeskState) -> dict:
        result = classifier.invoke(
            [SystemMessage(content=prompts.INTENT_SYSTEM_PROMPT), *state["messages"]]
        )
        assert isinstance(result, IntentClassification)
        question = _latest_question(state["messages"])
        # A rewrite only helps follow-ups; on the first question it can only drift.
        is_follow_up = sum(isinstance(m, HumanMessage) for m in state["messages"]) > 1
        query = (result.search_query.strip() if is_follow_up else "") or question
        return {
            "intent": result.intent.value,
            "domain": None if result.domain == "unknown" else result.domain,
            "search_query": query if result.intent == Intent.KNOWLEDGE_QUESTION else None,
            "retrieved": [],
            "citations": [],
            "escalation_reason": None,
        }

    return classify_intent


def _route_by_intent(state: SmartDeskState) -> str:
    intent = state.get("intent") or Intent.OUT_OF_SCOPE.value
    return RETRIEVE if intent == Intent.KNOWLEDGE_QUESTION.value else intent


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


def _make_answer_node(llm: BaseChatModel) -> Callable[[SmartDeskState], dict]:
    def generate_answer(state: SmartDeskState) -> dict:
        question = state.get("search_query") or _latest_question(state["messages"])
        result = rag_answer.generate_answer(llm, question, state["retrieved"])
        if not result.grounded:
            return {"escalation_reason": result.reason}
        return {
            "messages": [AIMessage(content=rag_answer.render(result))],
            "citations": [c.to_dict() for c in result.citations],
        }

    return generate_answer


def _route_after_answer(state: SmartDeskState) -> str:
    return ESCALATE if state.get("escalation_reason") else END


def _escalate(state: SmartDeskState) -> dict:
    team = prompts.ESCALATION_TEAM.get(state.get("domain") or "", prompts.ESCALATION_DEFAULT_TEAM)
    return {"messages": [AIMessage(content=prompts.ESCALATION_REPLY.format(team=team))]}


def build_graph(
    llm: BaseChatModel,
    retriever: SupportsRetrieve,
    *,
    min_similarity: float,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    builder = StateGraph(SmartDeskState)

    builder.add_node("classify_intent", _make_classify_node(llm))
    builder.add_node(Intent.GREETING.value, _reply(prompts.GREETING_REPLY))
    builder.add_node(Intent.OUT_OF_SCOPE.value, _reply(prompts.OUT_OF_SCOPE_REPLY))
    builder.add_node(Intent.CREATE_TICKET.value, _reply(prompts.CREATE_TICKET_PLACEHOLDER_REPLY))
    builder.add_node(Intent.TICKET_STATUS.value, _reply(prompts.TICKET_STATUS_PLACEHOLDER_REPLY))
    builder.add_node(RETRIEVE, _make_retrieve_node(retriever, min_similarity))
    builder.add_node(GENERATE_ANSWER, _make_answer_node(llm))
    builder.add_node(ESCALATE, _escalate)

    direct_replies = [Intent.GREETING, Intent.OUT_OF_SCOPE, Intent.CREATE_TICKET, Intent.TICKET_STATUS]
    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges(
        "classify_intent", _route_by_intent, {RETRIEVE: RETRIEVE, **{i.value: i.value for i in direct_replies}}
    )
    builder.add_conditional_edges(RETRIEVE, _route_after_retrieve, {ESCALATE: ESCALATE, GENERATE_ANSWER: GENERATE_ANSWER})
    builder.add_conditional_edges(GENERATE_ANSWER, _route_after_answer, {ESCALATE: ESCALATE, END: END})
    for node in [*(i.value for i in direct_replies), ESCALATE]:
        builder.add_edge(node, END)

    return builder.compile(checkpointer=checkpointer)
