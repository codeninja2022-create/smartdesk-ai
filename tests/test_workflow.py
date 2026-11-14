import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk.graph import build_graph, prompts
from smartdesk.graph.state import Intent, IntentClassification
from smartdesk.graph.workflow import ESCALATE, GENERATE_ANSWER, RETRIEVE
from smartdesk.rag.answer import GroundedAnswer
from tests.conftest import FakeLLM, FakeRetriever, make_chunk

pytestmark = pytest.mark.rubric("D1", "M7-INTENT")

MIN_SIMILARITY = 0.35
DIRECT_REPLY = {
    Intent.GREETING: prompts.GREETING_REPLY,
    Intent.OUT_OF_SCOPE: prompts.OUT_OF_SCOPE_REPLY,
    Intent.UNCLEAR: prompts.CLARIFY_REPLY,
    Intent.PROVIDE_INFO: prompts.CLARIFY_REPLY,  # nothing was asked, so there is nothing to answer
    Intent.CANCEL: prompts.NOTHING_TO_CANCEL,
}


def graph_for(llm, retriever=None, checkpointer=None):
    return build_graph(
        llm, retriever or FakeRetriever(), min_similarity=MIN_SIMILARITY, checkpointer=checkpointer
    )


def ask(graph, text, config=None):
    return graph.invoke({"messages": [HumanMessage(content=text)]}, config)


def insufficient(messages):
    return GroundedAnswer(evidence="none", sufficient=False, answer="", cited_passages=[])


def test_graph_has_rag_ticket_and_status_nodes():
    nodes = set(graph_for(FakeLLM({})).get_graph().nodes)
    assert {
        "classify_intent", "greeting", "out_of_scope", "clarify", "cancel_flow", "email_locked",
        RETRIEVE, GENERATE_ANSWER, ESCALATE,
        "collect_ticket", "present_ticket", "review_ticket", "submit_ticket", "check_status",
    } <= nodes


@pytest.mark.rubric("D3")
@pytest.mark.parametrize("intent", list(DIRECT_REPLY))
def test_direct_intents_reply_without_retrieval(intent):
    retriever = FakeRetriever()
    result = ask(graph_for(FakeLLM({"msg": intent}), retriever), "msg")

    assert result["intent"] == intent.value
    assert type(result["intent"]) is str  # checkpoint-safe built-in type
    assert result["messages"][-1].content == DIRECT_REPLY[intent]
    assert retriever.calls == []


def test_classifier_gets_system_prompt_first():
    llm = FakeLLM({"hi": Intent.GREETING})
    ask(graph_for(llm), "hi")

    sent = llm.calls[0]
    assert isinstance(sent[0], SystemMessage)
    assert sent[0].content == prompts.INTENT_SYSTEM_PROMPT
    assert sent[-1].content == "hi"


@pytest.mark.rubric("A4", "M7-GROUND")
def test_knowledge_question_returns_grounded_answer_with_sources():
    retriever = FakeRetriever([make_chunk("it-vpn-setup", 0.62, title="VPN Setup", section="Install the client")])
    llm = FakeLLM({"How do I set up the VPN?": IntentClassification(intent=Intent.KNOWLEDGE_QUESTION, domain="IT")})

    result = ask(graph_for(llm, retriever), "How do I set up the VPN?")

    assert retriever.calls == [("How do I set up the VPN?", "IT")]
    assert result["messages"][-1].content == (
        "Do the thing [1].\n\nSources:\n[1] VPN Setup > Install the client (it-vpn-setup)"
    )
    assert result["citations"] == [
        {"number": 1, "doc_id": "it-vpn-setup", "title": "VPN Setup", "section": "Install the client"}
    ]
    assert result["escalation_reason"] is None
    assert result["retrieved"][0]["similarity"] == 0.62


def test_answer_step_sees_numbered_passages_and_the_question():
    retriever = FakeRetriever([make_chunk("it-vpn-setup"), make_chunk("it-vpn-troubleshooting")])
    llm = FakeLLM({"vpn?": Intent.KNOWLEDGE_QUESTION})
    ask(graph_for(llm, retriever), "vpn?")

    system, human = llm.answer_calls[0]
    assert isinstance(system, SystemMessage)
    assert '<passage number="1" source="it-vpn-setup">' in human.content
    assert '<passage number="2" source="it-vpn-troubleshooting">' in human.content
    assert human.content.endswith("Employee question: vpn?")


@pytest.mark.parametrize(
    ("chunks", "answer_fn", "reason"),
    [
        ([], None, "no_results"),
        ([make_chunk(similarity=0.20)], None, "low_similarity"),
        ([make_chunk(similarity=0.60)], insufficient, "insufficient_context"),
        (
            [make_chunk(similarity=0.60)],
            lambda m: GroundedAnswer(evidence="x", sufficient=True, answer="Made up [7].", cited_passages=[7]),
            "no_valid_citation",
        ),
    ],
)
@pytest.mark.rubric("A5", "M7-ESC")
def test_escalates_and_offers_a_ticket_when_the_kb_cannot_answer(chunks, answer_fn, reason):
    llm = FakeLLM(
        {"Can I take a sabbatical?": IntentClassification(intent=Intent.KNOWLEDGE_QUESTION, domain="HR")},
        answer_fn,
    )
    result = ask(graph_for(llm, FakeRetriever(chunks)), "Can I take a sabbatical?")

    assert result["escalation_reason"] == reason
    assert result["messages"][-1].content == prompts.ESCALATION_REPLY.format(team="HR team")
    assert result["citations"] == []
    # The LLM is only consulted when retrieval found something above the threshold.
    assert len(llm.answer_calls) == (1 if reason in {"insufficient_context", "no_valid_citation"} else 0)


def test_escalation_without_a_domain_names_the_help_desk():
    llm = FakeLLM({"q": Intent.KNOWLEDGE_QUESTION})
    result = ask(graph_for(llm, FakeRetriever([])), "q")
    assert result["messages"][-1].content == prompts.ESCALATION_REPLY.format(team="help desk team")


def test_first_question_is_searched_verbatim_even_if_the_router_rewrites_it():
    retriever = FakeRetriever()
    llm = FakeLLM({
        "When is payday?": IntentClassification(
            intent=Intent.KNOWLEDGE_QUESTION, domain="HR", search_query="When is payday at NovaTech Solutions?"
        )
    })
    ask(graph_for(llm, retriever), "When is payday?")
    assert retriever.calls == [("When is payday?", "HR")]


@pytest.mark.rubric("D2", "M7-MULTI")
def test_follow_up_uses_the_standalone_query_from_the_router():
    retriever = FakeRetriever()
    llm = FakeLLM({
        "How do I set up the VPN?": IntentClassification(intent=Intent.KNOWLEDGE_QUESTION, domain="IT"),
        "what about on Mac?": IntentClassification(
            intent=Intent.KNOWLEDGE_QUESTION, domain="IT", search_query="How do I set up the VPN on a Mac?"
        ),
    })
    graph = graph_for(llm, retriever, InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    ask(graph, "How do I set up the VPN?", config)
    ask(graph, "what about on Mac?", config)

    assert retriever.calls[1] == ("How do I set up the VPN on a Mac?", "IT")
    assert llm.answer_calls[1][1].content.endswith("Employee question: How do I set up the VPN on a Mac?")


def test_per_turn_rag_state_is_reset_on_the_next_turn():
    llm = FakeLLM({"vpn?": Intent.KNOWLEDGE_QUESTION, "hi": Intent.GREETING})
    graph = graph_for(llm, FakeRetriever(), InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    assert ask(graph, "vpn?", config)["citations"]
    result = ask(graph, "hi", config)

    assert (result["retrieved"], result["citations"], result["escalation_reason"]) == ([], [], None)
    assert result["search_query"] is None


def test_multi_turn_history_is_kept_per_thread():
    llm = FakeLLM({"hi": Intent.GREETING, "what is the weather?": Intent.OUT_OF_SCOPE})
    graph = graph_for(llm, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    ask(graph, "hi", config)
    result = ask(graph, "what is the weather?", config)

    assert [m.content for m in result["messages"]] == [
        "hi",
        prompts.GREETING_REPLY,
        "what is the weather?",
        prompts.OUT_OF_SCOPE_REPLY,
    ]
    assert all(isinstance(m, AIMessage) for m in result["messages"][1::2])
    # The second classification saw the earlier turns as context.
    assert [m.content for m in llm.calls[1][1:]] == ["hi", prompts.GREETING_REPLY, "what is the weather?"]


def test_threads_are_isolated():
    graph = graph_for(FakeLLM({"hi": Intent.GREETING}), checkpointer=InMemorySaver())

    ask(graph, "hi", {"configurable": {"thread_id": "a"}})
    result = ask(graph, "hi", {"configurable": {"thread_id": "b"}})

    assert len(result["messages"]) == 2
