import os
from collections.abc import Callable, Iterator

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableLambda

from smartdesk.config import Settings
from smartdesk.graph.state import Intent, IntentClassification
from smartdesk.rag.answer import GroundedAnswer
from smartdesk.rag.retriever import RetrievedChunk

_SMARTDESK_ENV_PREFIXES = ("OPENAI_", "SMARTDESK_", "LANGFUSE_", "JIRA_")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Remove any real SmartDesk/OpenAI/Langfuse/Jira variables from the environment."""
    for name in list(os.environ):
        if name.startswith(_SMARTDESK_ENV_PREFIXES):
            monkeypatch.delenv(name)
    yield monkeypatch


@pytest.fixture
def make_settings(clean_env: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Build Settings from explicit values only, never from the real .env file."""

    def factory(**env: str) -> Settings:
        clean_env.setenv("OPENAI_API_KEY", "sk-test-0000000000000000000000")
        for name, value in env.items():
            clean_env.setenv(name, value)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    return factory


class FakeLLM:
    """Stands in for a chat model.

    Intent classification returns the scripted intent for the latest user
    message. The answer step returns `answer_fn(messages)`, which by default
    answers from passage 1 with a citation.
    """

    def __init__(
        self,
        intents_by_text: dict[str, Intent | IntentClassification],
        answer_fn: Callable[[list[BaseMessage]], GroundedAnswer] | None = None,
    ) -> None:
        self.intents_by_text = intents_by_text
        self.answer_fn = answer_fn or (
            lambda messages: GroundedAnswer(
                evidence='[1] "..."', sufficient=True, answer="Do the thing [1].", cited_passages=[1]
            )
        )
        self.calls: list[list[BaseMessage]] = []
        self.answer_calls: list[list[BaseMessage]] = []

    def with_structured_output(self, schema: type) -> RunnableLambda:
        if schema is IntentClassification:
            def classify(messages: list[BaseMessage]) -> IntentClassification:
                self.calls.append(list(messages))
                scripted = self.intents_by_text[messages[-1].content]
                return scripted if isinstance(scripted, IntentClassification) else IntentClassification(intent=scripted)

            return RunnableLambda(classify)

        assert schema is GroundedAnswer

        def answer(messages: list[BaseMessage]) -> GroundedAnswer:
            self.answer_calls.append(list(messages))
            return self.answer_fn(messages)

        return RunnableLambda(answer)




def make_chunk(doc_id: str = "it-vpn-setup", similarity: float = 0.6, **overrides) -> RetrievedChunk:
    fields = dict(
        chunk_id=f"{doc_id}#section-steps",
        doc_id=doc_id,
        title=doc_id.replace("-", " ").title(),
        section="Steps",
        domain="HR" if doc_id.startswith(("hr-", "onb-", "pay-")) else "IT",
        text=f"{doc_id} > Steps\n\nDo the thing.",
        similarity=similarity,
    )
    fields.update(overrides)
    return RetrievedChunk(**fields)


class FakeRetriever:
    """Returns scripted chunks and records each query and domain hint."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = [make_chunk()] if chunks is None else chunks
        self.calls: list[tuple[str, str | None]] = []

    def retrieve(self, query: str, domain: str | None = None) -> list[RetrievedChunk]:
        self.calls.append((query, domain))
        return list(self.chunks)


def _jira_configured() -> bool:
    try:
        return Settings().jira_configured  # type: ignore[call-arg]  # reads the real .env
    except ValueError:  # e.g. OPENAI_API_KEY missing
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = os.getenv("SMARTDESK_LIVE_TESTS") == "1"
    skip_openai = pytest.mark.skip(reason="set SMARTDESK_LIVE_TESTS=1 to call the real OpenAI API")
    if not live:
        skip_jira = pytest.mark.skip(reason="set SMARTDESK_LIVE_TESTS=1 (and JIRA_* credentials) to call real Jira")
    elif not _jira_configured():
        skip_jira = pytest.mark.skip(reason="Jira credentials are not configured (JIRA_* in .env)")
    else:
        skip_jira = None
    for item in items:
        if "openai_live" in item.keywords and not live:
            item.add_marker(skip_openai)
        if "jira_live" in item.keywords and skip_jira is not None:
            item.add_marker(skip_jira)
