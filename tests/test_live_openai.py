"""Live checks against the real OpenAI API. Run with SMARTDESK_LIVE_TESTS=1."""

import pytest
from langchain_core.messages import HumanMessage

from smartdesk.config import Settings
from smartdesk.graph import build_graph
from smartdesk.graph.state import Intent
from smartdesk.llm import get_chat_model, get_embeddings

pytestmark = pytest.mark.openai_live


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # reads the real .env


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
    graph = build_graph(get_chat_model(settings))
    result = graph.invoke({"messages": [HumanMessage(content=message)]})
    assert result["intent"] == expected.value


def test_live_embedding_dimensions(settings):
    vector = get_embeddings(settings).embed_query("How do I connect to the VPN?")
    assert len(vector) == 1536
