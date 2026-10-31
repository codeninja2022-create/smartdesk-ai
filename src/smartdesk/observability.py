"""Langfuse tracing with sensitive-data redaction.

Tracing is optional: when Langfuse keys are not configured, `get_callbacks`
returns an empty list and the app runs normally without sending any traces.
"""

import logging

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from smartdesk.config import Settings
from smartdesk.redaction import langfuse_mask

logger = logging.getLogger(__name__)

_client: Langfuse | None = None


def init_langfuse(settings: Settings) -> Langfuse | None:
    """Create the process-wide Langfuse client with the redaction mask installed.

    The client must exist before any `CallbackHandler` is built: the handler
    looks it up by public key, so its traces go through the same mask.
    """
    global _client
    if not settings.langfuse_enabled:
        return None
    if _client is None:
        assert settings.langfuse_secret_key is not None  # guaranteed by langfuse_enabled
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
            mask=langfuse_mask,
        )
        logger.info("Langfuse tracing enabled (host=%s)", settings.langfuse_host)
    return _client


def get_callbacks(settings: Settings) -> list[BaseCallbackHandler]:
    """LangChain callbacks to pass via `config={"callbacks": ...}`."""
    if init_langfuse(settings) is None:
        return []
    return [CallbackHandler(public_key=settings.langfuse_public_key)]


def flush() -> None:
    """Send buffered traces; call before a short-lived process exits."""
    if _client is not None:
        _client.flush()
