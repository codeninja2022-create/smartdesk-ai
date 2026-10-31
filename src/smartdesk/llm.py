"""OpenAI model factories.

Model names come from configuration so they can be changed without code edits.
`max_retries` gives exponential-backoff retries inside the OpenAI client;
the explicit fallback model / canned response is added in Milestone 6.
"""

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from smartdesk.config import Settings


def get_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.openai_api_key,
    )


def get_embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.openai_api_key,
    )
