import pytest

from smartdesk.llm import get_chat_model, get_embeddings, get_resilient_chat_model

pytestmark = pytest.mark.rubric("F2")


def test_chat_model_uses_configured_settings(make_settings):
    settings = make_settings(
        SMARTDESK_LLM_MODEL="gpt-4o", SMARTDESK_LLM_TIMEOUT_SECONDS="12", SMARTDESK_LLM_MAX_RETRIES="4"
    )
    model = get_chat_model(settings)
    assert model.model_name == "gpt-4o"
    assert model.temperature == 0.0
    assert model.request_timeout == 12.0
    assert model.max_retries == 4


def test_every_request_has_an_explicit_timeout_by_default(make_settings):
    model = get_chat_model(make_settings())
    assert model.request_timeout == 30.0
    assert model.max_retries == 2


def test_embeddings_use_configured_model(make_settings):
    embeddings = get_embeddings(make_settings(SMARTDESK_EMBEDDING_MODEL="text-embedding-3-large"))
    assert embeddings.model == "text-embedding-3-large"


def test_env_example_documents_gpt_4o_as_the_fallback(make_settings):
    from pathlib import Path

    lines = Path(__file__).parents[1].joinpath(".env.example").read_text(encoding="utf-8").splitlines()
    assert "SMARTDESK_LLM_FALLBACK_MODEL=gpt-4o" in lines

    llm = get_resilient_chat_model(make_settings(SMARTDESK_LLM_FALLBACK_MODEL="gpt-4o"))
    assert llm.primary.model_name == "gpt-4o-mini" and llm.fallback.model_name == "gpt-4o"
    assert llm.fallback.request_timeout == 30.0 and llm.fallback.max_retries == 2
