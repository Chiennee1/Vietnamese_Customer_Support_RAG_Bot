from pydantic import SecretStr

from app.core.config import Settings


def test_settings_do_not_expose_secret_values() -> None:
    settings = Settings(
        app_secret=SecretStr("super-secret"),
        jwt_secret=SecretStr("jwt-secret-value"),
        database_url=SecretStr("postgresql+asyncpg://app:password@db:5432/support_rag"),
    )

    rendered = repr(settings)

    assert "super-secret" not in rendered
    assert "jwt-secret-value" not in rendered
    assert "app:password@" not in rendered


def test_production_rejects_default_secrets() -> None:
    try:
        Settings(
            app_env="production",
            app_secret=SecretStr("change-me"),
            jwt_secret=SecretStr("change-me"),
            database_url=SecretStr("postgresql+asyncpg://app:password@db:5432/support_rag"),
        )
    except ValueError as error:
        assert "production" in str(error).lower()
    else:
        raise AssertionError("production settings accepted insecure default secrets")


def test_railway_postgres_url_is_normalized_for_asyncpg() -> None:
    settings = Settings(
        database_url=SecretStr(
            "postgresql://app:password@postgres.railway.internal:5432/support_rag"
        )
    )

    assert settings.database_url.get_secret_value() == (
        "postgresql+asyncpg://app:password@postgres.railway.internal:5432/support_rag"
    )


def test_legacy_postgres_url_is_normalized_for_asyncpg() -> None:
    settings = Settings(database_url=SecretStr("postgres://app:password@db:5432/support_rag"))

    assert settings.database_url.get_secret_value() == (
        "postgresql+asyncpg://app:password@db:5432/support_rag"
    )


def test_migration_url_is_separate_from_runtime_url() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://app_runtime:runtime@db:5432/support_rag"),
        migration_database_url=SecretStr("postgresql://app_migrator:migration@db:5432/support_rag"),
    )

    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://app_runtime:")
    assert settings.effective_migration_database_url.startswith(
        "postgresql+asyncpg://app_migrator:"
    )


def test_production_runtime_does_not_require_provisioning_secrets() -> None:
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

    assert settings.migration_database_url is None


def test_production_requires_distinct_runtime_and_agent_credentials() -> None:
    runtime_url = SecretStr("postgresql+asyncpg://app_runtime:runtime@db:5432/support_rag")
    try:
        Settings(
            app_env="production",
            app_secret=SecretStr("safe-app-secret"),
            jwt_secret=SecretStr("safe-jwt-secret"),
            database_url=runtime_url,
            agent_database_url=runtime_url,
        )
    except ValueError as error:
        assert "must differ" in str(error)
    else:
        raise AssertionError("production accepted shared runtime/agent credentials")
