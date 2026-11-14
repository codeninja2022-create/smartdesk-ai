import pytest
from pydantic import ValidationError

from smartdesk.config import Settings

pytestmark = pytest.mark.rubric("F3")


def test_defaults(make_settings):
    settings = make_settings()
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.llm_temperature == 0.0
    assert settings.llm_max_retries == 2
    assert settings.langfuse_enabled is False


def test_model_names_are_configurable(make_settings):
    settings = make_settings(
        SMARTDESK_LLM_MODEL="gpt-4o", SMARTDESK_EMBEDDING_MODEL="text-embedding-3-large"
    )
    assert settings.llm_model == "gpt-4o"
    assert settings.embedding_model == "text-embedding-3-large"


def test_secrets_are_hidden_in_repr(make_settings):
    settings = make_settings(LANGFUSE_PUBLIC_KEY="pk-lf-abc", LANGFUSE_SECRET_KEY="sk-lf-supersecret")
    text = repr(settings) + str(settings)
    assert "sk-test-0000000000000000000000" not in text
    assert "sk-lf-supersecret" not in text


def test_missing_openai_key_fails(clean_env):
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("public_key", "secret_key", "expected"),
    [("pk-lf-abc", "sk-lf-xyz", True), ("pk-lf-abc", "", False), ("", "sk-lf-xyz", False)],
)
def test_langfuse_enabled_requires_both_keys(make_settings, public_key, secret_key, expected):
    settings = make_settings(LANGFUSE_PUBLIC_KEY=public_key, LANGFUSE_SECRET_KEY=secret_key)
    assert settings.langfuse_enabled is expected


def test_invalid_numeric_setting_fails(make_settings):
    with pytest.raises(ValidationError):
        make_settings(SMARTDESK_LLM_MAX_RETRIES="-1")
