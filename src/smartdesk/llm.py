"""OpenAI model factories.

Model names come from configuration so they can be changed without code edits.

Reliability, in layers:

1. Each request has a timeout (`SMARTDESK_LLM_TIMEOUT_SECONDS`) and the OpenAI
   client retries connection errors, timeouts, 429 and 5xx with exponential
   backoff and jitter, honouring `Retry-After` (`SMARTDESK_LLM_MAX_RETRIES`).
2. When those retries are exhausted, `ResilientChatModel` sends the same call to
   `SMARTDESK_LLM_FALLBACK_MODEL`, if one is configured.
3. If that fails too (or none is configured), the error reaches `ChatSession`,
   which replies with a safe canned message.
"""

from typing import Any, Protocol

import openai
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import ValidationError

from smartdesk.config import Settings

# Failures of the model service or of its structured output. Bugs in SmartDesk's own
# code are deliberately absent, so they are not masked by a second model.
FALLBACK_ERRORS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,  # includes APITimeoutError
    openai.RateLimitError,
    openai.InternalServerError,
    openai.PermissionDeniedError,  # e.g. the project has no access to the model
    openai.NotFoundError,  # e.g. the model does not exist
    OutputParserException,
    ValidationError,
)


class StructuredLLM(Protocol):
    """What the graph needs from a chat model."""

    def with_structured_output(self, schema: type) -> Runnable: ...


class ResilientChatModel:
    """A primary chat model with an optional fallback model for every structured call."""

    def __init__(self, primary: StructuredLLM, fallback: StructuredLLM | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def with_structured_output(self, schema: type) -> Runnable:
        runnable = self.primary.with_structured_output(schema)
        if self.fallback is None:
            return runnable
        return runnable.with_fallbacks(
            [self.fallback.with_structured_output(schema)], exceptions_to_handle=FALLBACK_ERRORS
        )


def get_chat_model(settings: Settings, model: str | None = None, **kwargs: Any) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.openai_api_key,
        **kwargs,
    )


def get_resilient_chat_model(settings: Settings, **kwargs: Any) -> ResilientChatModel:
    """The chat model SmartDesk runs on: primary plus the configured fallback, if any."""
    fallback = get_chat_model(settings, settings.llm_fallback_model, **kwargs) if settings.llm_fallback_model else None
    return ResilientChatModel(get_chat_model(settings, **kwargs), fallback)


def get_embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.openai_api_key,
    )
