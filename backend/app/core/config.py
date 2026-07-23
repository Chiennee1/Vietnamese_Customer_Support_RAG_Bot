from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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
        "postgresql+asyncpg://app:password@localhost:5432/support_rag"
    )
    jwt_secret: SecretStr = SecretStr("change-me")
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    openai_api_key: SecretStr = SecretStr("")
    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-5-mini"
    llm_max_output_tokens: int = Field(default=700, ge=100, le=10_000)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
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
        return self

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
