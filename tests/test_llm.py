from smartdesk.llm import get_chat_model, get_embeddings


def test_chat_model_uses_configured_settings(make_settings):
    settings = make_settings(
        SMARTDESK_LLM_MODEL="gpt-4o", SMARTDESK_LLM_TIMEOUT_SECONDS="12", SMARTDESK_LLM_MAX_RETRIES="4"
    )
    model = get_chat_model(settings)
    assert model.model_name == "gpt-4o"
    assert model.temperature == 0.0
    assert model.request_timeout == 12.0
    assert model.max_retries == 4


def test_embeddings_use_configured_model(make_settings):
    embeddings = get_embeddings(make_settings(SMARTDESK_EMBEDDING_MODEL="text-embedding-3-large"))
    assert embeddings.model == "text-embedding-3-large"
