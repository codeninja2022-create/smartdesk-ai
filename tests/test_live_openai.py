"""Live checks against the real OpenAI API and the local ChromaDB index.

Run with SMARTDESK_LIVE_TESTS=1. The end-to-end RAG tests also need the index
(`python -m smartdesk.kb.ingest`) and are skipped when it is empty.
"""

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk.config import Settings
from smartdesk.graph import build_graph, prompts
from smartdesk.graph.state import Intent
from smartdesk.llm import get_chat_model, get_embeddings
from smartdesk.rag.retriever import build_retriever
from tests.conftest import FakeRetriever

pytestmark = pytest.mark.openai_live


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # reads the real .env


@pytest.fixture(scope="module")
def rag_graph(settings):
    retriever = build_retriever(settings)
    if retriever.collection.count() == 0:
        pytest.skip("ChromaDB index is empty; run `python -m smartdesk.kb.ingest`")
    return build_graph(
        get_chat_model(settings), retriever, min_similarity=settings.rag_min_similarity, checkpointer=InMemorySaver()
    )


def ask(graph, text, thread):
    return graph.invoke({"messages": [HumanMessage(content=text)]}, {"configurable": {"thread_id": thread}})


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Hi there!", Intent.GREETING),
        ("How do I reset my password?", Intent.KNOWLEDGE_QUESTION),
        ("How many sick leaves do I get per year?", Intent.KNOWLEDGE_QUESTION),
        ("Please open a support ticket for my broken laptop.", Intent.CREATE_TICKET),
        ("What's the status of my ticket?", Intent.TICKET_STATUS),
        ("Who won the cricket world cup?", Intent.OUT_OF_SCOPE),
    ],
)
def test_live_intent_classification(settings, message, expected):
    graph = build_graph(get_chat_model(settings), FakeRetriever([]), min_similarity=settings.rag_min_similarity)
    result = graph.invoke({"messages": [HumanMessage(content=message)]})
    assert result["intent"] == expected.value


def test_live_embedding_dimensions(settings):
    vector = get_embeddings(settings).embed_query("How do I connect to the VPN?")
    assert len(vector) == 1536


def test_live_answerable_question_is_answered_with_a_kb_citation(rag_graph):
    result = ask(rag_graph, "How many sick leaves do I get per year?", "live-answer")

    assert result["escalation_reason"] is None
    assert "hr-leave-policy" in {c["doc_id"] for c in result["citations"]}
    reply = result["messages"][-1].content
    assert "8" in reply and "Sources:" in reply


def test_live_gap_question_escalates_instead_of_answering(rag_graph):
    result = ask(rag_graph, "My external monitor keeps flickering. How do I fix it?", "live-gap")

    assert result["escalation_reason"] is not None
    assert result["citations"] == []
    assert result["messages"][-1].content == prompts.ESCALATION_REPLY.format(team="IT team")


def test_live_follow_up_question_is_resolved_against_the_earlier_turn(rag_graph):
    ask(rag_graph, "How do I set up the VPN on Windows?", "live-follow-up")
    result = ask(rag_graph, "And what about on a Mac?", "live-follow-up")

    assert "vpn" in result["search_query"].lower()
    assert "it-vpn-setup" in {c["doc_id"] for c in result["citations"]}
