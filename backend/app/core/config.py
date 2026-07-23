from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "vietnamese-customer-support-rag"
    app_env: Literal["development", "test", "production"] = "development"
    app_secret: SecretStr = SecretStr("change-me")
    api_v1_prefix: str = "/api/v1"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://app_runtime:local-runtime-password@localhost:5432/support_rag"
    )
    agent_database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://app_agent:local-agent-password@localhost:5432/support_rag"
    )
    migration_database_url: SecretStr | None = None
    runtime_db_role: str = Field(
        default="app_runtime",
        pattern=r"^[a-z][a-z0-9_]{2,62}$",
    )
    runtime_db_password: SecretStr = SecretStr("local-runtime-password")
    agent_db_role: str = Field(
        default="app_agent",
        pattern=r"^[a-z][a-z0-9_]{2,62}$",
    )
    agent_db_password: SecretStr = SecretStr("local-agent-password")
    jwt_secret: SecretStr = SecretStr("change-me")
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    openai_api_key: SecretStr = SecretStr("")
    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-5-mini"
    llm_max_output_tokens: int = Field(default=700, ge=100, le=10_000)
    llm_input_cost_per_million_usd: float = Field(default=0.25, ge=0)
    llm_output_cost_per_million_usd: float = Field(default=2.0, ge=0)
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_base_seconds: float = Field(default=0.2, ge=0, le=5)
    provider_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    provider_circuit_recovery_seconds: float = Field(default=30, ge=0, le=600)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    tool_timeout_seconds: int = Field(default=8, ge=1, le=60)
    embedding_provider: Literal["openai"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    upload_dir: str = "uploads"
    max_upload_mb: int = 20
    max_pdf_pages: int = 200
    chunk_target_tokens: int = 500
    chunk_max_tokens: int = 700
    chunk_overlap_tokens: int = 80
    rag_candidate_k: int = 20
    rag_final_k: int = 6
    rag_minimum_score: float = 0.015
    rrf_rank_constant: int = 60
    request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_auth_per_window: int = Field(default=10, ge=1, le=10_000)
    rate_limit_chat_per_window: int = Field(default=30, ge=1, le=10_000)
    rate_limit_upload_per_window: int = Field(default=20, ge=1, le=10_000)
    rate_limit_general_per_window: int = Field(default=120, ge=1, le=10_000)
    conversation_retention_days: int = Field(default=30, ge=1, le=3650)
    retention_interval_seconds: int = Field(default=86_400, ge=60, le=604_800)

    @field_validator(
        "database_url",
        "agent_database_url",
        "migration_database_url",
        mode="before",
    )
    @classmethod
    def normalize_async_database_url(cls, value: object) -> object:
        if value is None:
            return None
        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        if raw_value.startswith("postgresql://"):
            raw_value = raw_value.replace(
                "postgresql://",
                "postgresql+asyncpg://",
                1,
            )
        elif raw_value.startswith("postgres://"):
            raw_value = raw_value.replace(
                "postgres://",
                "postgresql+asyncpg://",
                1,
            )
        return SecretStr(raw_value)

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> Self:
        if self.app_env != "production":
            return self
        insecure = {"", "change-me"}
        if (
            self.app_secret.get_secret_value() in insecure
            or self.jwt_secret.get_secret_value() in insecure
        ):
            raise ValueError("Production requires non-default application secrets")
        runtime_url = self.database_url.get_secret_value()
        agent_url = self.agent_database_url.get_secret_value()
        if runtime_url == agent_url:
            raise ValueError("Production runtime and agent database URLs must differ")
        if "local-runtime-password" in runtime_url or "local-agent-password" in agent_url:
            raise ValueError("Production database URLs must not use local passwords")
        return self

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_migration_database_url(self) -> str:
        if self.migration_database_url is not None:
            return self.migration_database_url.get_secret_value()
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
