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
    assert "password" not in rendered


def test_production_rejects_default_secrets() -> None:
    try:
        Settings(
            app_env="production",
            app_secret=SecretStr("change-me"),
            jwt_secret=SecretStr("change-me"),
            database_url=SecretStr(
                "postgresql+asyncpg://app:password@db:5432/support_rag"
            ),
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
        "postgresql+asyncpg://"
        "app:password@postgres.railway.internal:5432/support_rag"
    )


def test_legacy_postgres_url_is_normalized_for_asyncpg() -> None:
    settings = Settings(
        database_url=SecretStr("postgres://app:password@db:5432/support_rag")
    )

    assert settings.database_url.get_secret_value() == (
        "postgresql+asyncpg://app:password@db:5432/support_rag"
    )
