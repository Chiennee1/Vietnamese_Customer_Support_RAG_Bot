"""Provision separate web-runtime and read-only agent PostgreSQL roles."""

import asyncio
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings, get_settings

ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def _quoted_identifier(value: str) -> str:
    if not ROLE_PATTERN.fullmatch(value):
        raise ValueError("runtime database role is not a safe identifier")
    return f'"{value}"'


def _quoted_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_provisioning_configuration(settings: Settings) -> None:
    if settings.app_env != "production":
        return
    if settings.migration_database_url is None:
        raise ValueError("Production role provisioning requires a migration database URL")
    migration_url = settings.migration_database_url.get_secret_value()
    database_urls = {
        settings.database_url.get_secret_value(),
        settings.agent_database_url.get_secret_value(),
        migration_url,
    }
    if len(database_urls) != 3:
        raise ValueError("Production provisioning requires three distinct database URLs")
    insecure_passwords = {
        "",
        "change-me",
        "local-runtime-password",
        "local-agent-password",
    }
    if (
        settings.runtime_db_password.get_secret_value() in insecure_passwords
        or settings.agent_db_password.get_secret_value() in insecure_passwords
    ):
        raise ValueError("Production role provisioning requires non-default role passwords")


async def provision_runtime_role(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    _validate_provisioning_configuration(resolved)
    runtime_role = _quoted_identifier(resolved.runtime_db_role)
    runtime_password = _quoted_literal(resolved.runtime_db_password.get_secret_value())
    agent_role = _quoted_identifier(resolved.agent_db_role)
    agent_password = _quoted_literal(resolved.agent_db_password.get_secret_value())
    engine = create_async_engine(
        resolved.effective_migration_database_url,
        pool_pre_ping=True,
    )
    try:
        async with engine.begin() as connection:
            for role_name, role, password in (
                (
                    resolved.runtime_db_role,
                    runtime_role,
                    runtime_password,
                ),
                (
                    resolved.agent_db_role,
                    agent_role,
                    agent_password,
                ),
            ):
                exists = await connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                    {"role": role_name},
                )
                statement = (
                    f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB "
                    f"NOCREATEROLE NOINHERIT PASSWORD {password}"
                    if exists is None
                    else (
                        f"ALTER ROLE {role} NOSUPERUSER NOCREATEDB "
                        f"NOCREATEROLE NOINHERIT PASSWORD {password}"
                    )
                )
                await connection.execute(text(statement))

            database_name = str(await connection.scalar(text("SELECT current_database()")))
            quoted_database = '"' + database_name.replace('"', '""') + '"'
            statements = (
                "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
                f"GRANT CONNECT ON DATABASE {quoted_database} TO {runtime_role}",
                f"GRANT USAGE ON SCHEMA public TO {runtime_role}",
                (
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    f"IN SCHEMA public TO {runtime_role}"
                ),
                (f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {runtime_role}"),
                (
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
                    f"TO {runtime_role}"
                ),
                (
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT USAGE, SELECT ON SEQUENCES TO {runtime_role}"
                ),
                f"GRANT CONNECT ON DATABASE {quoted_database} TO {agent_role}",
                f"GRANT USAGE ON SCHEMA public TO {agent_role}",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {agent_role}",
                (
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT SELECT ON TABLES TO {agent_role}"
                ),
            )
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(provision_runtime_role())
