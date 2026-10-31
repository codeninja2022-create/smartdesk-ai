import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk.graph import build_graph, prompts
from smartdesk.graph.state import Intent
from tests.conftest import FakeIntentLLM

EXPECTED_REPLY = {
    Intent.GREETING: prompts.GREETING_REPLY,
    Intent.OUT_OF_SCOPE: prompts.OUT_OF_SCOPE_REPLY,
    Intent.KNOWLEDGE_QUESTION: prompts.KNOWLEDGE_PLACEHOLDER_REPLY,
    Intent.CREATE_TICKET: prompts.CREATE_TICKET_PLACEHOLDER_REPLY,
    Intent.TICKET_STATUS: prompts.TICKET_STATUS_PLACEHOLDER_REPLY,
}


def test_graph_has_a_node_per_intent():
    graph = build_graph(FakeIntentLLM({}))
    assert {intent.value for intent in Intent} | {"classify_intent"} <= set(graph.get_graph().nodes)


@pytest.mark.parametrize("intent", list(Intent))
def test_routes_each_intent_to_its_node(intent):
    graph = build_graph(FakeIntentLLM({"msg": intent}))

    result = graph.invoke({"messages": [HumanMessage(content="msg")]})

    assert result["intent"] == intent.value
    assert type(result["intent"]) is str  # checkpoint-safe built-in type
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == EXPECTED_REPLY[intent]


def test_classifier_gets_system_prompt_first():
    llm = FakeIntentLLM({"hi": Intent.GREETING})
    build_graph(llm).invoke({"messages": [HumanMessage(content="hi")]})

    sent = llm.calls[0]
    assert isinstance(sent[0], SystemMessage)
    assert sent[0].content == prompts.INTENT_SYSTEM_PROMPT
    assert sent[-1].content == "hi"


def test_multi_turn_history_is_kept_per_thread():
    llm = FakeIntentLLM({"hi": Intent.GREETING, "what is the weather?": Intent.OUT_OF_SCOPE})
    graph = build_graph(llm, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    graph.invoke({"messages": [HumanMessage(content="hi")]}, config)
    result = graph.invoke({"messages": [HumanMessage(content="what is the weather?")]}, config)

    assert [m.content for m in result["messages"]] == [
        "hi",
        prompts.GREETING_REPLY,
        "what is the weather?",
        prompts.OUT_OF_SCOPE_REPLY,
    ]
    assert result["intent"] == Intent.OUT_OF_SCOPE.value
    # The second classification saw the earlier turns as context.
    assert [m.content for m in llm.calls[1][1:]] == ["hi", prompts.GREETING_REPLY, "what is the weather?"]


def test_threads_are_isolated():
    llm = FakeIntentLLM({"hi": Intent.GREETING})
    graph = build_graph(llm, checkpointer=InMemorySaver())

    graph.invoke({"messages": [HumanMessage(content="hi")]}, {"configurable": {"thread_id": "a"}})
    result = graph.invoke({"messages": [HumanMessage(content="hi")]}, {"configurable": {"thread_id": "b"}})

    assert len(result["messages"]) == 2
