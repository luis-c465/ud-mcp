from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Result

from db_mcp_server.config.models import SqlServerConnectionConfig
from db_mcp_server.models import (
    ColumnInfo,
    ConnectionDescriptor,
    ConnectionTestResult,
    ExplainResult,
    QueryOptions,
    QueryResult,
    ResultWarning,
    SchemaInfo,
    TableDescription,
    TableInfo,
    TruncationWarning,
)


class SqlServerAdapter:
    """SQL Server adapter backed by SQLAlchemy."""

    backend_type = "sqlserver"

    def __init__(
        self,
        config: SqlServerConnectionConfig,
        secrets: Mapping[str, str] | None = None,
        connection_name: str | None = None,
    ) -> None:
        self._config = config
        self._secrets = dict(secrets or {})
        self._connection_name = connection_name or self.backend_type
        self._engine = create_engine(self._build_url(), future=True, pool_pre_ping=True)

    def test_connection(self) -> ConnectionTestResult:
        started = self._now_ms()
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT DB_NAME() AS catalog, SCHEMA_NAME() AS schema_name, SYSTEM_USER AS current_user, @@VERSION AS version"
                    )
                ).mappings().one()
                connection_descriptor = ConnectionDescriptor(
                    name=self._connection_name,
                    backend_type=self.backend_type,
                    description=self._config.description,
                    catalog=self._as_text(row.get("catalog")),
                    schema=self._as_text(row.get("schema_name")),
                    read_only=self._config.read_only,
                    allow_full_permissions=self._config.allow_full_permissions,
                    backend_metadata={
                        "driver": self._config.driver,
                        "dialect": self._engine.dialect.name,
                        "current_user": self._as_text(row.get("current_user")),
                    },
                )
                return ConnectionTestResult(
                    ok=True,
                    connection=connection_descriptor,
                    message="Connection successful.",
                    elapsed_ms=self._elapsed_ms(started),
                    backend_metadata={
                        "driver": self._config.driver,
                        "dialect": self._engine.dialect.name,
                        "version": self._as_text(row.get("version")),
                    },
                )
        except Exception as exc:
            return ConnectionTestResult(
                ok=False,
                message=str(exc),
                error_code=exc.__class__.__name__,
                elapsed_ms=self._elapsed_ms(started),
                backend_metadata={
                    "driver": self._config.driver,
                    "dialect": self._engine.dialect.name,
                },
            )

    def list_schemas(self) -> list[SchemaInfo]:
        with self._engine.connect() as connection:
            rows = self._fetch_all(
                connection,
                self._schema_query(),
            )
        catalog = self._current_catalog()
        return [
            SchemaInfo(
                catalog=self._as_text(row.get("catalog"), default=catalog),
                schema=self._as_text(row.get("schema_name"), default=self._as_text(row.get("name"))),
                name=self._as_text(row.get("schema_name"), default=self._as_text(row.get("name"))) or "",
                description=self._as_text(row.get("description")),
                backend_metadata=self._row_backend_metadata(row),
            )
            for row in rows
        ]

    def list_tables(
        self,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> list[TableInfo]:
        with self._engine.connect() as connection:
            rows = self._fetch_all(
                connection,
                self._table_query(catalog=catalog, schema=schema, include_views=include_views),
                params={"schema": schema} if schema is not None else None,
            )
        return [self._table_info_from_row(row) for row in rows]

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription:
        with self._engine.connect() as connection:
            column_rows = self._fetch_all(
                connection,
                self._describe_columns_query(catalog=catalog, schema=schema, table=table),
                params={"schema": schema, "table": table},
            )
            pk_rows = self._fetch_all(
                connection,
                self._primary_keys_query(catalog=catalog, schema=schema, table=table),
                params={"schema": schema, "table": table},
            )
            fk_rows = self._fetch_all(
                connection,
                self._foreign_keys_query(catalog=catalog, schema=schema, table=table),
                params={"schema": schema, "table": table},
            )

        table_info = self._table_info_from_description(catalog=catalog, schema=schema, table=table, column_rows=column_rows)
        primary_keys = [self._as_text(row.get("column_name")) for row in pk_rows if self._as_text(row.get("column_name"))]
        columns = [
            self._column_info_from_row(row, primary_keys=set(primary_keys), catalog=catalog, schema=schema, table=table)
            for row in column_rows
        ]
        return TableDescription(
            table=table_info,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=[dict(row) for row in fk_rows],
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
            },
        )

    def run_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> QueryResult:
        started = self._now_ms()
        with self._engine.connect() as connection:
            result = connection.execute(text(sql), params or {})
            columns = [ColumnInfo(name=str(name)) for name in result.keys()]
            rows = self._fetch_rows(result)

        return self._build_query_result(
            sql=sql,
            rows=rows,
            columns=columns,
            options=options,
            elapsed_ms=self._elapsed_ms(started),
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
            },
        )

    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult:
        started = self._now_ms()
        with self._engine.connect() as connection:
            connection.exec_driver_sql("SET SHOWPLAN_TEXT ON")
            try:
                result = connection.execute(text(sql), params or {})
                columns = [ColumnInfo(name=str(name)) for name in result.keys()]
                rows = self._fetch_rows(result)
            finally:
                connection.exec_driver_sql("SET SHOWPLAN_TEXT OFF")

        plan_text = self._rows_to_text(rows)
        query_result = self._build_query_result(
            sql=sql,
            rows=rows,
            columns=columns,
            options=options,
            elapsed_ms=self._elapsed_ms(started),
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
                "explain_mode": "showplan_text",
            },
        )
        return ExplainResult(
            **query_result.model_dump(),
            plan_text=plan_text,
            plan_format="text",
            source_query=sql,
        )

    def _build_url(self) -> URL:
        dsn = self._secret("dsn")
        driver = self._config.driver or "pyodbc"
        if driver.lower() == "pyodbc":
            return URL.create("mssql+pyodbc", query={"odbc_connect": dsn})
        return URL.create(f"mssql+{driver}", query={"odbc_connect": dsn})

    def _secret(self, name: str) -> str:
        try:
            value = self._secrets[name]
        except KeyError as exc:  # pragma: no cover - configuration error path
            raise KeyError(f"Missing resolved secret {name!r} for SQL Server adapter.") from exc
        return value

    def _current_catalog(self) -> str | None:
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT DB_NAME() AS catalog")).mappings().one()
        return self._as_text(row.get("catalog"))

    def _schema_query(self) -> str:
        database = self._current_catalog()
        if database:
            quoted_database = self._quote_identifier(database)
            escaped_database = database.replace("'", "''")
            return f"SELECT name AS schema_name, '{escaped_database}' AS catalog, NULL AS description FROM {quoted_database}.sys.schemas ORDER BY name"
        return "SELECT name AS schema_name, DB_NAME() AS catalog, NULL AS description FROM sys.schemas ORDER BY name"

    def _table_query(self, *, catalog: str | None, schema: str | None, include_views: bool) -> str:
        source = self._information_schema_prefix(catalog)
        view_clause = "TABLE_TYPE IN ('BASE TABLE', 'VIEW')" if include_views else "TABLE_TYPE = 'BASE TABLE'"
        schema_clause = "AND (:schema IS NULL OR TABLE_SCHEMA = :schema)" if schema is not None else ""
        return (
            "SELECT TABLE_CATALOG AS catalog, TABLE_SCHEMA AS schema_name, TABLE_NAME AS name, TABLE_TYPE AS table_type, "
            "CASE WHEN TABLE_TYPE = 'VIEW' THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS is_view, "
            "CASE WHEN TABLE_TYPE = 'BASE TABLE' THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS is_insertable, "
            "CAST(NULL AS bit) AS is_temporary, "
            "CAST(NULL AS nvarchar(max)) AS description "
            f"FROM {source} "
            f"WHERE {view_clause} {schema_clause} "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )

    def _describe_columns_query(self, *, catalog: str | None, schema: str, table: str) -> str:
        source = self._information_schema_prefix(catalog)
        return (
            "SELECT TABLE_CATALOG AS catalog, TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name, COLUMN_NAME AS column_name, "
            "DATA_TYPE AS data_type, ORDINAL_POSITION AS ordinal_position, "
            "CASE WHEN IS_NULLABLE = 'YES' THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS nullable, "
            "COLUMN_DEFAULT AS default_value, CAST(NULL AS nvarchar(max)) AS description, "
            "CHARACTER_MAXIMUM_LENGTH AS length, NUMERIC_PRECISION AS precision, NUMERIC_SCALE AS scale "
            f"FROM {source}.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
            "ORDER BY ORDINAL_POSITION"
        )

    def _primary_keys_query(self, *, catalog: str | None, schema: str, table: str) -> str:
        source = self._information_schema_prefix(catalog)
        return (
            "SELECT kcu.COLUMN_NAME AS column_name, kcu.ORDINAL_POSITION AS ordinal_position "
            f"FROM {source}.TABLE_CONSTRAINTS tc "
            f"JOIN {source}.KEY_COLUMN_USAGE kcu ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA AND tc.TABLE_NAME = kcu.TABLE_NAME "
            "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' AND tc.TABLE_SCHEMA = :schema AND tc.TABLE_NAME = :table "
            "ORDER BY kcu.ORDINAL_POSITION"
        )

    def _foreign_keys_query(self, *, catalog: str | None, schema: str, table: str) -> str:
        source = self._information_schema_prefix(catalog)
        return (
            "SELECT kcu.COLUMN_NAME AS column_name, ccu.TABLE_SCHEMA AS referenced_schema, ccu.TABLE_NAME AS referenced_table, ccu.COLUMN_NAME AS referenced_column "
            f"FROM {source}.TABLE_CONSTRAINTS tc "
            f"JOIN {source}.KEY_COLUMN_USAGE kcu ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA AND tc.TABLE_NAME = kcu.TABLE_NAME "
            f"JOIN {source}.REFERENTIAL_CONSTRAINTS rc ON tc.CONSTRAINT_NAME = rc.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA "
            f"JOIN {source}.KEY_COLUMN_USAGE ccu ON rc.UNIQUE_CONSTRAINT_NAME = ccu.CONSTRAINT_NAME AND rc.UNIQUE_CONSTRAINT_SCHEMA = ccu.CONSTRAINT_SCHEMA AND kcu.ORDINAL_POSITION = ccu.ORDINAL_POSITION "
            "WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY' AND tc.TABLE_SCHEMA = :schema AND tc.TABLE_NAME = :table "
            "ORDER BY kcu.ORDINAL_POSITION"
        )

    def _information_schema_prefix(self, catalog: str | None) -> str:
        database = catalog or self._current_catalog()
        if database:
            return f"{self._quote_identifier(database)}.INFORMATION_SCHEMA"
        return "INFORMATION_SCHEMA"

    def _table_info_from_row(self, row: Mapping[str, Any]) -> TableInfo:
        object_type = self._map_table_type(self._as_text(row.get("table_type")))
        schema = self._as_text(row.get("schema_name"))
        name = self._as_text(row.get("name"))
        return TableInfo(
            catalog=self._as_text(row.get("catalog")),
            schema=schema,
            name=name or "",
            object_type=object_type,
            description=self._as_text(row.get("description")),
            is_view=object_type == "view",
            is_insertable=self._normalize_bool(row.get("is_insertable")) if row.get("is_insertable") is not None else object_type != "view",
            is_temporary=self._normalize_bool(row.get("is_temporary")),
            backend_metadata=self._row_backend_metadata(row),
        )

    def _table_info_from_description(
        self,
        *,
        catalog: str | None,
        schema: str,
        table: str,
        column_rows: list[Mapping[str, Any]],
    ) -> TableInfo:
        first_row = column_rows[0] if column_rows else {}
        return TableInfo(
            catalog=self._as_text(first_row.get("catalog"), default=catalog),
            schema=self._as_text(first_row.get("schema_name"), default=schema),
            name=self._as_text(first_row.get("table_name"), default=table) or table,
            object_type="table",
            description=self._as_text(first_row.get("table_comment")),
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
            },
        )

    def _column_info_from_row(
        self,
        row: Mapping[str, Any],
        *,
        primary_keys: set[str],
        catalog: str | None,
        schema: str,
        table: str,
    ) -> ColumnInfo:
        name = self._as_text(row.get("column_name")) or ""
        return ColumnInfo(
            catalog=self._as_text(row.get("catalog"), default=catalog),
            schema=self._as_text(row.get("schema_name"), default=schema),
            table=self._as_text(row.get("table_name"), default=table),
            name=name,
            data_type=self._as_text(row.get("data_type")),
            ordinal_position=self._normalize_int(row.get("ordinal_position")),
            nullable=self._normalize_bool(row.get("nullable")),
            default=self._as_text(row.get("default_value")),
            description=self._as_text(row.get("description")),
            length=self._normalize_int(row.get("length")),
            precision=self._normalize_int(row.get("precision")),
            scale=self._normalize_int(row.get("scale")),
            is_primary_key=name in primary_keys,
            backend_metadata=self._row_backend_metadata(row),
        )

    def _build_query_result(
        self,
        *,
        sql: str,
        rows: list[list[Any]],
        columns: list[ColumnInfo],
        options: QueryOptions,
        elapsed_ms: float | None,
        backend_metadata: dict[str, Any],
    ) -> QueryResult:
        normalized_rows = list(rows)
        warnings: list[ResultWarning] = []
        truncated = False
        if options.max_rows is not None and options.max_rows >= 0 and len(normalized_rows) > options.max_rows:
            truncated = True
            total_rows = len(normalized_rows)
            normalized_rows = normalized_rows[: options.max_rows]
            warnings.append(
                TruncationWarning(
                    message=f"Result truncated to {options.max_rows} rows.",
                    limit_type="rows",
                    limit=options.max_rows,
                    actual=total_rows,
                    truncated_rows=total_rows - options.max_rows,
                )
            )

        return QueryResult(
            columns=columns,
            rows=normalized_rows,
            row_count=len(normalized_rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            warnings=warnings,
            query_id=None,
            statement_type=self._statement_type(sql),
            backend_metadata=backend_metadata,
        )

    def _fetch_all(self, connection: Connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = connection.execute(text(statement), params or {})
        return [dict(row) for row in result.mappings().all()]

    def _fetch_rows(self, result: Result[Any]) -> list[list[Any]]:
        return [list(row) for row in result.fetchall()]

    def _rows_to_text(self, rows: list[list[Any]]) -> str | None:
        if not rows:
            return None
        lines: list[str] = []
        for row in rows:
            lines.append(" ".join(str(cell) for cell in row if cell is not None).rstrip())
        return "\n".join(lines)

    def _row_backend_metadata(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"catalog", "schema_name", "name", "table_name", "column_name", "data_type", "ordinal_position", "nullable", "default_value", "description", "length", "precision", "scale", "table_type", "is_view", "is_insertable", "is_temporary"}}

    def _map_table_type(self, table_type: str | None) -> str:
        value = (table_type or "table").strip().upper()
        if value == "VIEW":
            return "view"
        if value == "MATERIALIZED VIEW":
            return "materialized_view"
        if value == "TABLE" or value == "BASE TABLE":
            return "table"
        return "unknown"

    def _statement_type(self, sql: str) -> str | None:
        stripped = sql.strip()
        if not stripped:
            return None
        return stripped.split(None, 1)[0].upper()

    def _normalize_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text_value = str(value).strip().lower()
        if text_value in {"true", "t", "yes", "y", "1"}:
            return True
        if text_value in {"false", "f", "no", "n", "0"}:
            return False
        return None

    def _normalize_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _as_text(self, value: Any, default: str | None = None) -> str | None:
        if value is None:
            return default
        text_value = str(value).strip()
        if not text_value:
            return default
        return text_value

    def _quote_identifier(self, value: str) -> str:
        return "[" + value.replace("]", "]]") + "]"

    def _elapsed_ms(self, started_ms: float) -> float:
        return self._now_ms() - started_ms

    def _now_ms(self) -> float:
        from time import perf_counter

        return perf_counter() * 1000.0


def create_adapter(
    config: SqlServerConnectionConfig,
    secrets: Mapping[str, str] | None = None,
    connection_name: str | None = None,
) -> SqlServerAdapter:
    return SqlServerAdapter(config=config, secrets=secrets, connection_name=connection_name)


build_adapter = create_adapter


__all__ = ["SqlServerAdapter", "build_adapter", "create_adapter"]
