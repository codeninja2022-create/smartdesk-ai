"""Environment-based configuration.

All settings come from environment variables (or a local `.env` file).
Secrets are held as `SecretStr` so they never appear in reprs or logs.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: SecretStr = Field(validation_alias="OPENAI_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", validation_alias="SMARTDESK_LLM_MODEL")
    embedding_model: str = Field(
        default="text-embedding-3-small", validation_alias="SMARTDESK_EMBEDDING_MODEL"
    )
    llm_temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, validation_alias="SMARTDESK_LLM_TEMPERATURE"
    )
    llm_timeout_seconds: float = Field(
        default=30.0, gt=0, validation_alias="SMARTDESK_LLM_TIMEOUT_SECONDS"
    )
    llm_max_retries: int = Field(default=2, ge=0, le=10, validation_alias="SMARTDESK_LLM_MAX_RETRIES")
    # Used when the primary model keeps failing; same timeout and retries. Unset = canned reply only
    # (gpt-4.1-mini was checked and is not available to the IK project).
    llm_fallback_model: str | None = Field(default=None, validation_alias="SMARTDESK_LLM_FALLBACK_MODEL")

    # Conversation guardrails
    router_history_turns: int = Field(default=4, ge=1, le=50, validation_alias="SMARTDESK_ROUTER_HISTORY_TURNS")
    max_input_chars: int = Field(default=2000, ge=1, le=20_000, validation_alias="SMARTDESK_MAX_INPUT_CHARS")

    @field_validator("llm_fallback_model", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    # Langfuse (optional)
    langfuse_public_key: str | None = Field(default=None, validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(default=None, validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )

    # Knowledge base and vector store
    kb_dir: Path = Field(default=Path("data/kb"), validation_alias="SMARTDESK_KB_DIR")
    chroma_dir: Path = Field(default=Path("data/chroma"), validation_alias="SMARTDESK_CHROMA_DIR")
    chroma_collection: str = Field(default="smartdesk_kb", validation_alias="SMARTDESK_CHROMA_COLLECTION")

    # RAG. Similarities are ranking scores, not probabilities. The threshold is a
    # pre-filter calibrated on data/eval/eval_set.jsonl (python -m smartdesk.rag.calibrate):
    # lowest answerable top-1 score (0.403) minus a 0.05 safety margin.
    rag_top_k: int = Field(default=5, ge=1, le=20, validation_alias="SMARTDESK_RAG_TOP_K")
    rag_min_similarity: float = Field(
        default=0.35, ge=0.0, le=1.0, validation_alias="SMARTDESK_RAG_MIN_SIMILARITY"
    )

    # Jira Cloud. All four connection values are required for ticket operations.
    jira_base_url: str | None = Field(default=None, validation_alias="JIRA_BASE_URL")
    jira_email: str | None = Field(default=None, validation_alias="JIRA_EMAIL")
    jira_api_token: SecretStr | None = Field(default=None, validation_alias="JIRA_API_TOKEN")
    jira_project_key: str | None = Field(default=None, validation_alias="JIRA_PROJECT_KEY")
    jira_issue_type: str = Field(default="Task", validation_alias="JIRA_ISSUE_TYPE")
    jira_timeout_seconds: float = Field(default=10.0, gt=0, validation_alias="JIRA_TIMEOUT_SECONDS")
    jira_max_retries: int = Field(default=2, ge=0, le=10, validation_alias="JIRA_MAX_RETRIES")  # reads only
    jira_max_create_attempts: int = Field(default=2, ge=1, le=5, validation_alias="JIRA_MAX_CREATE_ATTEMPTS")
    # Jira search is eventually consistent: a just-created issue can be missing for a few seconds.
    jira_reconcile_polls: int = Field(default=3, ge=1, le=10, validation_alias="JIRA_RECONCILE_POLLS")
    jira_reconcile_delay_seconds: float = Field(
        default=2.0, ge=0, validation_alias="JIRA_RECONCILE_DELAY_SECONDS"
    )

    # SQLite: ticket mappings and idempotency ops (M4), checkpoints (M5)
    db_path: Path = Field(default=Path("data/smartdesk.db"), validation_alias="SMARTDESK_DB_PATH")

    @property
    def jira_configured(self) -> bool:
        return bool(
            self.jira_base_url
            and self.jira_email
            and self.jira_project_key
            and self.jira_api_token
            and self.jira_api_token.get_secret_value()
        )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(
            self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_secret_key.get_secret_value()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()  # type: ignore[call-arg]  # fields are populated from the environment
