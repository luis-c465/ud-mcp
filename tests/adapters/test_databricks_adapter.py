from __future__ import annotations

import pytest

from db_mcp_server.adapters.databricks import DatabricksAdapter
from db_mcp_server.config.models import DatabricksConnectionConfig


def _build_adapter(*, catalog: str | None = None, schema: str | None = None) -> DatabricksAdapter:
    config = DatabricksConnectionConfig(
        server_hostname_env="DATABRICKS_SERVER_HOSTNAME",
        http_path_env="DATABRICKS_HTTP_PATH",
        token_env="DATABRICKS_TOKEN",
        catalog=catalog,
        schema=schema,
    )
    return DatabricksAdapter(config=config, secrets={"server_hostname": "dummy", "http_path": "dummy", "token": "dummy"})


def test_list_tables_sql_uses_catalog_scoped_fallback_and_excludes_is_temporary() -> None:
    adapter = _build_adapter(catalog="main", schema="analytics")

    statements = adapter._list_tables_sql(catalog="main", schema="analytics", include_views=False)

    assert len(statements) == 2
    assert "FROM system.information_schema.tables" in statements[0]
    assert "FROM `main`.information_schema.`tables`" in statements[1]
    assert "table_catalog = 'main'" in statements[0]
    assert "table_schema = 'analytics'" in statements[0]
    assert "UPPER(table_type) NOT LIKE '%VIEW%'" in statements[0]
    assert "is_temporary" not in statements[0]
    assert "is_temporary" not in statements[1]


def test_describe_sql_uses_catalog_scoped_fallback_and_excludes_is_temporary() -> None:
    adapter = _build_adapter(catalog="main", schema="analytics")

    table_statements = adapter._describe_table_sql(catalog="main", schema="analytics", table="orders")
    column_statements = adapter._describe_columns_sql(catalog="main", schema="analytics", table="orders")

    assert "FROM system.information_schema.tables" in table_statements[0]
    assert "FROM `main`.information_schema.`tables`" in table_statements[1]
    assert "is_temporary" not in table_statements[0]
    assert "is_temporary" not in table_statements[1]

    assert "FROM system.information_schema.columns" in column_statements[0]
    assert "FROM `main`.information_schema.`columns`" in column_statements[1]


def test_table_info_from_row_allows_rows_without_is_temporary() -> None:
    adapter = _build_adapter()

    info = adapter._table_info_from_row(
        ["main", "analytics", "orders", "MANAGED", "Orders table", "YES"],
        started=0.0,
    )

    assert info.catalog == "main"
    assert info.schema == "analytics"
    assert info.name == "orders"
    assert info.is_insertable is True
    assert info.is_temporary is None


def test_describe_table_info_allows_rows_without_is_temporary() -> None:
    adapter = _build_adapter()

    adapter._run_metadata_query = lambda _statements: (
        [["main", "analytics", "orders", "MANAGED", "Orders table", "YES"]],
        "statement",
    )

    info = adapter._describe_table_info("main", "analytics", "orders")

    assert info.catalog == "main"
    assert info.schema == "analytics"
    assert info.name == "orders"
    assert info.is_insertable is True
    assert info.is_temporary is None


def test_metadata_sources_without_catalog_keep_unqualified_fallback() -> None:
    adapter = _build_adapter()

    sources = adapter._metadata_sources("tables", catalog=None)

    assert sources == ("system.information_schema.tables", "information_schema.tables")


def test_show_sql_builders_quote_catalog_and_schema_names() -> None:
    adapter = _build_adapter()

    assert adapter._show_schemas_sql("hive_metastore") == "SHOW SCHEMAS IN `hive_metastore`"
    assert adapter._show_tables_sql(catalog="hive_metastore", schema="default") == "SHOW TABLES IN `hive_metastore`.`default`"


def test_list_schemas_falls_back_to_show_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _build_adapter(catalog="hive_metastore")

    def fail_metadata(_statements: tuple[str, ...]) -> tuple[list[list[object]], str]:
        raise RuntimeError("information schema unavailable")

    def fake_run_query(sql: str, _params: dict[str, object]) -> tuple[list[object], list[list[object]]]:
        assert sql == "SHOW SCHEMAS IN `hive_metastore`"
        return [], [["default"], ["sales"]]

    monkeypatch.setattr(adapter, "_run_metadata_query", fail_metadata)
    monkeypatch.setattr(adapter, "_run_query", fake_run_query)

    schemas = adapter.list_schemas()

    assert [(item.catalog, item.schema) for item in schemas] == [
        ("hive_metastore", "default"),
        ("hive_metastore", "sales"),
    ]


def test_list_tables_falls_back_to_show_tables_for_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _build_adapter(catalog="hive_metastore")

    def fail_metadata(_statements: tuple[str, ...]) -> tuple[list[list[object]], str]:
        raise RuntimeError("information schema unavailable")

    def fake_run_query(sql: str, _params: dict[str, object]) -> tuple[list[object], list[list[object]]]:
        assert sql == "SHOW TABLES IN `hive_metastore`.`default`"
        return [], [["default", "orders", False], ["default", "temp_view", True]]

    monkeypatch.setattr(adapter, "_run_metadata_query", fail_metadata)
    monkeypatch.setattr(adapter, "_run_query", fake_run_query)

    tables = adapter.list_tables(catalog="hive_metastore", schema="default", include_views=False)

    assert [(item.catalog, item.schema, item.name, item.is_temporary) for item in tables] == [
        ("hive_metastore", "default", "orders", False),
        ("hive_metastore", "default", "temp_view", True),
    ]


def test_list_tables_falls_back_to_show_tables_across_catalog_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _build_adapter(catalog="hive_metastore")
    seen_sql: list[str] = []

    def fail_metadata(_statements: tuple[str, ...]) -> tuple[list[list[object]], str]:
        raise RuntimeError("information schema unavailable")

    def fake_run_query(sql: str, _params: dict[str, object]) -> tuple[list[object], list[list[object]]]:
        seen_sql.append(sql)
        if sql == "SHOW SCHEMAS IN `hive_metastore`":
            return [], [["default"], ["analytics"]]
        if sql == "SHOW TABLES IN `hive_metastore`.`default`":
            return [], [["default", "orders", False]]
        if sql == "SHOW TABLES IN `hive_metastore`.`analytics`":
            return [], [["analytics", "events", False]]
        raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(adapter, "_run_metadata_query", fail_metadata)
    monkeypatch.setattr(adapter, "_run_query", fake_run_query)

    tables = adapter.list_tables(catalog="hive_metastore", schema=None, include_views=False)

    assert seen_sql == [
        "SHOW SCHEMAS IN `hive_metastore`",
        "SHOW TABLES IN `hive_metastore`.`default`",
        "SHOW TABLES IN `hive_metastore`.`analytics`",
    ]
    assert [(item.catalog, item.schema, item.name) for item in tables] == [
        ("hive_metastore", "default", "orders"),
        ("hive_metastore", "analytics", "events"),
    ]
