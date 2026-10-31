"""Minimal SmartDesk LangGraph workflow: classify intent, then route.

    START -> classify_intent -> {greeting | knowledge_question | create_ticket
                                 | ticket_status | out_of_scope} -> END

Only routing is real at this stage; the knowledge, ticket and status nodes
return placeholder replies until their milestones replace them.
"""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smartdesk.graph import prompts
from smartdesk.graph.state import Intent, IntentClassification, SmartDeskState


def _reply(text: str) -> Callable[[SmartDeskState], dict]:
    def node(state: SmartDeskState) -> dict:
        return {"messages": [AIMessage(content=text)]}

    return node


def _make_classify_node(llm: BaseChatModel) -> Callable[[SmartDeskState], dict]:
    classifier = llm.with_structured_output(IntentClassification)

    def classify_intent(state: SmartDeskState) -> dict:
        result = classifier.invoke(
            [SystemMessage(content=prompts.INTENT_SYSTEM_PROMPT), *state["messages"]]
        )
        assert isinstance(result, IntentClassification)
        return {"intent": result.intent.value}

    return classify_intent


def _route_by_intent(state: SmartDeskState) -> str:
    return state.get("intent") or Intent.OUT_OF_SCOPE.value


def build_graph(
    llm: BaseChatModel, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    builder = StateGraph(SmartDeskState)

    builder.add_node("classify_intent", _make_classify_node(llm))
    builder.add_node(Intent.GREETING.value, _reply(prompts.GREETING_REPLY))
    builder.add_node(Intent.OUT_OF_SCOPE.value, _reply(prompts.OUT_OF_SCOPE_REPLY))
    builder.add_node(Intent.KNOWLEDGE_QUESTION.value, _reply(prompts.KNOWLEDGE_PLACEHOLDER_REPLY))
    builder.add_node(Intent.CREATE_TICKET.value, _reply(prompts.CREATE_TICKET_PLACEHOLDER_REPLY))
    builder.add_node(Intent.TICKET_STATUS.value, _reply(prompts.TICKET_STATUS_PLACEHOLDER_REPLY))

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges(
        "classify_intent", _route_by_intent, {intent.value: intent.value for intent in Intent}
    )
    for intent in Intent:
        builder.add_edge(intent.value, END)

    return builder.compile(checkpointer=checkpointer)
