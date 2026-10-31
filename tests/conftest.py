import os
from collections.abc import Callable, Iterator

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableLambda

from smartdesk.config import Settings
from smartdesk.graph.state import Intent, IntentClassification

_SMARTDESK_ENV_PREFIXES = ("OPENAI_", "SMARTDESK_", "LANGFUSE_")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Remove any real SmartDesk/OpenAI/Langfuse variables from the environment."""
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


class FakeIntentLLM:
    """Stands in for a chat model: returns a scripted intent per user message."""

    def __init__(self, intents_by_text: dict[str, Intent]) -> None:
        self.intents_by_text = intents_by_text
        self.calls: list[list[BaseMessage]] = []

    def with_structured_output(self, schema: type) -> RunnableLambda:
        assert schema is IntentClassification

        def classify(messages: list[BaseMessage]) -> IntentClassification:
            self.calls.append(list(messages))
            return IntentClassification(intent=self.intents_by_text[messages[-1].content])

        return RunnableLambda(classify)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live_openai = os.getenv("SMARTDESK_LIVE_TESTS") == "1"
    skip_openai = pytest.mark.skip(reason="set SMARTDESK_LIVE_TESTS=1 to call the real OpenAI API")
    for item in items:
        if "openai_live" in item.keywords and not live_openai:
            item.add_marker(skip_openai)
