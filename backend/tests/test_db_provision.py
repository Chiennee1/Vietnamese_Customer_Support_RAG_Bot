import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.provision_runtime_role import (
    _quoted_identifier,
    _quoted_literal,
    _validate_provisioning_configuration,
)


def test_runtime_role_identifier_rejects_sql_metacharacters() -> None:
    assert _quoted_identifier("app_runtime") == '"app_runtime"'

    with pytest.raises(ValueError):
        _quoted_identifier('app_runtime"; DROP SCHEMA public; --')


def test_runtime_role_password_is_quoted_as_one_sql_literal() -> None:
    assert _quoted_literal("safe'password") == "'safe''password'"


def test_production_provisioning_requires_migration_only_secrets() -> None:
    settings = Settings(
        app_env="production",
        app_secret=SecretStr("safe-app-secret"),
        jwt_secret=SecretStr("safe-jwt-secret"),
        database_url=SecretStr("postgresql+asyncpg://app_runtime:runtime@db:5432/support_rag"),
        agent_database_url=SecretStr("postgresql+asyncpg://app_agent:agent@db:5432/support_rag"),
        migration_database_url=None,
        runtime_db_password=SecretStr(""),
        agent_db_password=SecretStr(""),
    )

    with pytest.raises(ValueError, match="migration database URL"):
        _validate_provisioning_configuration(settings)


def test_production_provisioning_accepts_three_distinct_roles() -> None:
    settings = Settings(
        app_env="production",
        app_secret=SecretStr("safe-app-secret"),
        jwt_secret=SecretStr("safe-jwt-secret"),
        database_url=SecretStr("postgresql+asyncpg://app_runtime:runtime@db:5432/support_rag"),
        agent_database_url=SecretStr("postgresql+asyncpg://app_agent:agent@db:5432/support_rag"),
        migration_database_url=SecretStr(
            "postgresql+asyncpg://migrator:migration@db:5432/support_rag"
        ),
        runtime_db_password=SecretStr("safe-runtime-password"),
        agent_db_password=SecretStr("safe-agent-password"),
    )

    _validate_provisioning_configuration(settings)
