from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.models import import_all_models


def test_core_schema_contains_all_required_tables() -> None:
    import_all_models()

    assert set(Base.metadata.tables) == {
        "users",
        "products",
        "product_variants",
        "inventory",
        "orders",
        "order_items",
        "warranties",
        "knowledge_documents",
        "knowledge_chunks",
        "conversations",
        "messages",
        "tool_executions",
        "support_tickets",
        "feedback",
    }


def test_postgres_schema_compiles_without_raw_runtime_sql() -> None:
    import_all_models()
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]

    for table in Base.metadata.sorted_tables:
        compiled = str(CreateTable(table).compile(dialect=dialect))
        assert "password_hash" in compiled or table.name != "users"
