from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Result, URL

from db_mcp_server.config.models import SnowflakeConnectionConfig
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


class SnowflakeAdapter:
    """Snowflake adapter backed by SQLAlchemy."""

    backend_type = "snowflake"

    def __init__(
        self,
        config: SnowflakeConnectionConfig,
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
                        "SELECT CURRENT_ACCOUNT() AS account, CURRENT_REGION() AS region, CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS warehouse, CURRENT_DATABASE() AS catalog, CURRENT_SCHEMA() AS schema_name"
                    )
                ).mappings().one()
                connection_descriptor = ConnectionDescriptor(
                    name=self._connection_name,
                    backend_type=self.backend_type,
                    description=self._config.description,
                    catalog=self._as_text(row.get("catalog"), default=self._config.database),
                    schema=self._as_text(row.get("schema_name"), default=self._config.schema_),
                    read_only=self._config.read_only,
                    allow_full_permissions=self._config.allow_full_permissions,
                    backend_metadata={
                        "account": self._secret("account"),
                        "warehouse": self._secret("warehouse"),
                        "role": self._secret_optional("role"),
                        "dialect": self._engine.dialect.name,
                    },
                )
                return ConnectionTestResult(
                    ok=True,
                    connection=connection_descriptor,
                    message="Connection successful.",
                    elapsed_ms=self._elapsed_ms(started),
                    backend_metadata={
                        "dialect": self._engine.dialect.name,
                        "account": self._as_text(row.get("account")),
                        "region": self._as_text(row.get("region")),
                        "role": self._as_text(row.get("role")),
                        "warehouse": self._as_text(row.get("warehouse")),
                    },
                )
        except Exception as exc:
            return ConnectionTestResult(
                ok=False,
                message=str(exc),
                error_code=exc.__class__.__name__,
                elapsed_ms=self._elapsed_ms(started),
                backend_metadata={"dialect": self._engine.dialect.name},
            )

    def list_schemas(self) -> list[SchemaInfo]:
        database = self._database_name()
        with self._engine.connect() as connection:
            rows = self._fetch_all(connection, self._schema_query(database))
        return [self._schema_info_from_row(row) for row in rows]

    def list_tables(
        self,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> list[TableInfo]:
        database = self._database_name(catalog)
        with self._engine.connect() as connection:
            rows = self._fetch_all(
                connection,
                self._table_query(database, schema=schema, include_views=include_views),
                params={"schema": schema} if schema is not None else None,
            )
        return [self._table_info_from_row(row) for row in rows]

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription:
        database = self._database_name(catalog)
        with self._engine.connect() as connection:
            table_rows = self._fetch_all(
                connection,
                self._table_metadata_query(database),
                params={"schema": schema, "table": table},
            )
            column_rows = self._fetch_all(
                connection,
                self._describe_columns_query(database),
                params={"schema": schema, "table": table},
            )
            pk_rows = self._fetch_all(
                connection,
                self._primary_keys_query(database),
                params={"schema": schema, "table": table},
            )

        table_info = self._table_info_from_metadata_rows(table_rows, catalog=database, schema=schema, table=table)
        primary_keys = [self._as_text(row.get("column_name")) for row in pk_rows if self._as_text(row.get("column_name"))]
        primary_key_set = set(primary_keys)
        columns = [
            self._column_info_from_row(row, primary_keys=primary_key_set, catalog=database, schema=schema, table=table)
            for row in column_rows
        ]
        return TableDescription(
            table=table_info,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=[],
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
            query_id = self._query_id(result)

        return self._build_query_result(
            sql=sql,
            rows=rows,
            columns=columns,
            options=options,
            elapsed_ms=self._elapsed_ms(started),
            query_id=query_id,
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
            },
        )

    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult:
        started = self._now_ms()
        explain_sql = f"EXPLAIN USING TEXT {sql}"
        with self._engine.connect() as connection:
            result = connection.execute(text(explain_sql), params or {})
            columns = [ColumnInfo(name=str(name)) for name in result.keys()]
            rows = self._fetch_rows(result)
            query_id = self._query_id(result)

        plan_text = self._rows_to_text(rows)
        query_result = self._build_query_result(
            sql=explain_sql,
            rows=rows,
            columns=columns,
            options=options,
            elapsed_ms=self._elapsed_ms(started),
            query_id=query_id,
            backend_metadata={
                "backend_type": self.backend_type,
                "dialect": self._engine.dialect.name,
                "explain_mode": "text",
                "source_query": sql,
            },
        )
        return ExplainResult(
            **query_result.model_dump(),
            plan_text=plan_text,
            plan_format="text",
            source_query=sql,
        )

    def _build_url(self) -> URL:
        account = self._secret("account")
        user = self._secret("user")
        password = self._secret("password")
        warehouse = self._secret("warehouse")
        query: dict[str, str] = {"warehouse": warehouse}
        role = self._secret_optional("role")
        if role:
            query["role"] = role

        return URL.create(
            "snowflake",
            username=user,
            password=password,
            host=account,
            database=self._config.database,
            query=query,
        )

    def _secret(self, name: str) -> str:
        try:
            value = self._secrets[name]
        except KeyError as exc:  # pragma: no cover - configuration error path
            raise KeyError(f"Missing resolved secret {name!r} for Snowflake adapter.") from exc
        return value

    def _secret_optional(self, name: str) -> str | None:
        return self._secrets.get(name)

    def _database_name(self, catalog: str | None = None) -> str:
        database = catalog or self._config.database or self._current_database()
        if not database:
            raise ValueError("Snowflake metadata operations require a database name.")
        return database

    def _current_database(self) -> str | None:
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT CURRENT_DATABASE() AS catalog")).mappings().one()
        return self._as_text(row.get("catalog"))

    def _schema_query(self, database: str) -> str:
        return (
            f"SELECT catalog_name AS catalog, schema_name AS schema_name, comment AS description "
            f"FROM {self._qualified_information_schema(database, 'SCHEMATA')} "
            "WHERE schema_name <> 'INFORMATION_SCHEMA' "
            "ORDER BY schema_name"
        )

    def _table_query(self, database: str, *, schema: str | None, include_views: bool) -> str:
        type_clause = "table_type IN ('BASE TABLE', 'VIEW', 'MATERIALIZED VIEW', 'TEMPORARY')" if include_views else "table_type IN ('BASE TABLE', 'TEMPORARY')"
        schema_clause = "AND (:schema IS NULL OR table_schema = :schema)" if schema is not None else ""
        return (
            "SELECT table_catalog AS catalog, table_schema AS schema_name, table_name AS name, table_type AS table_type, "
            "comment AS description, "
            "CASE WHEN table_type = 'VIEW' THEN TRUE ELSE FALSE END AS is_view, "
            "CASE WHEN table_type = 'TEMPORARY' THEN TRUE ELSE FALSE END AS is_temporary, "
            "CASE WHEN table_type = 'VIEW' THEN FALSE ELSE TRUE END AS is_insertable "
            f"FROM {self._qualified_information_schema(database, 'TABLES')} "
            f"WHERE {type_clause} {schema_clause} "
            "ORDER BY table_schema, table_name"
        )

    def _table_metadata_query(self, database: str) -> str:
        return (
            "SELECT table_catalog AS catalog, table_schema AS schema_name, table_name AS name, table_type AS table_type, "
            "comment AS description, "
            "CASE WHEN table_type = 'VIEW' THEN TRUE ELSE FALSE END AS is_view, "
            "CASE WHEN table_type = 'TEMPORARY' THEN TRUE ELSE FALSE END AS is_temporary, "
            "CASE WHEN table_type = 'VIEW' THEN FALSE ELSE TRUE END AS is_insertable "
            f"FROM {self._qualified_information_schema(database, 'TABLES')} "
            "WHERE table_schema = :schema AND table_name = :table"
        )

    def _describe_columns_query(self, database: str) -> str:
        return (
            "SELECT table_catalog AS catalog, table_schema AS schema_name, table_name AS table_name, column_name AS column_name, "
            "data_type AS data_type, ordinal_position AS ordinal_position, "
            "CASE WHEN is_nullable = 'YES' THEN TRUE ELSE FALSE END AS nullable, "
            "column_default AS default_value, comment AS description, "
            "character_maximum_length AS length, numeric_precision AS precision, numeric_scale AS scale "
            f"FROM {self._qualified_information_schema(database, 'COLUMNS')} "
            "WHERE table_schema = :schema AND table_name = :table "
            "ORDER BY ordinal_position"
        )

    def _primary_keys_query(self, database: str) -> str:
        return (
            "SELECT kcu.column_name AS column_name, kcu.ordinal_position AS ordinal_position "
            f"FROM {self._qualified_information_schema(database, 'TABLE_CONSTRAINTS')} tc "
            f"JOIN {self._qualified_information_schema(database, 'KEY_COLUMN_USAGE')} kcu "
            "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema AND tc.table_name = kcu.table_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = :schema AND tc.table_name = :table "
            "ORDER BY kcu.ordinal_position"
        )

    def _qualified_information_schema(self, database: str, object_name: str) -> str:
        return f"{self._quote_identifier(database)}.INFORMATION_SCHEMA.{self._quote_identifier(object_name)}"

    def _schema_info_from_row(self, row: Mapping[str, Any]) -> SchemaInfo:
        return SchemaInfo(
            catalog=self._as_text(row.get("catalog")),
            schema=self._as_text(row.get("schema_name"), default=self._as_text(row.get("name"))) or "",
            name=self._as_text(row.get("schema_name"), default=self._as_text(row.get("name"))) or "",
            description=self._as_text(row.get("description")),
            backend_metadata=self._row_backend_metadata(row),
        )

    def _table_info_from_row(self, row: Mapping[str, Any]) -> TableInfo:
        object_type = self._map_table_type(self._as_text(row.get("table_type")))
        return TableInfo(
            catalog=self._as_text(row.get("catalog")),
            schema=self._as_text(row.get("schema_name")),
            name=self._as_text(row.get("name")) or "",
            object_type=object_type,
            description=self._as_text(row.get("description")),
            is_view=object_type == "view",
            is_insertable=self._normalize_bool(row.get("is_insertable")) if row.get("is_insertable") is not None else object_type != "view",
            is_temporary=self._normalize_bool(row.get("is_temporary")),
            backend_metadata=self._row_backend_metadata(row),
        )

    def _table_info_from_metadata_rows(
        self,
        rows: list[Mapping[str, Any]],
        *,
        catalog: str,
        schema: str,
        table: str,
    ) -> TableInfo:
        row = rows[0] if rows else {}
        object_type = self._map_table_type(self._as_text(row.get("table_type")))
        return TableInfo(
            catalog=self._as_text(row.get("catalog"), default=catalog),
            schema=self._as_text(row.get("schema_name"), default=schema),
            name=self._as_text(row.get("name"), default=table) or table,
            object_type=object_type,
            description=self._as_text(row.get("description")),
            is_view=object_type == "view",
            is_insertable=self._normalize_bool(row.get("is_insertable")) if row.get("is_insertable") is not None else object_type != "view",
            is_temporary=self._normalize_bool(row.get("is_temporary")),
            backend_metadata=self._row_backend_metadata(row),
        )

    def _column_info_from_row(
        self,
        row: Mapping[str, Any],
        *,
        primary_keys: set[str],
        catalog: str,
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
        query_id: str | None,
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
            query_id=query_id,
            statement_type=self._statement_type(sql),
            backend_metadata=backend_metadata,
        )

    def _fetch_all(self, connection: Connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = connection.execute(text(statement), params or {})
        return [dict(row) for row in result.mappings().all()]

    def _fetch_rows(self, result: Result[Any]) -> list[list[Any]]:
        return [list(row) for row in result.fetchall()]

    def _query_id(self, result: Result[Any]) -> str | None:
        cursor = getattr(result, "cursor", None)
        return getattr(cursor, "sfqid", None)

    def _rows_to_text(self, rows: list[list[Any]]) -> str | None:
        if not rows:
            return None
        lines: list[str] = []
        for row in rows:
            line = " ".join(str(cell) for cell in row if cell is not None).rstrip()
            if line:
                lines.append(line)
        return "\n".join(lines) if lines else None

    def _row_backend_metadata(self, row: Mapping[str, Any]) -> dict[str, Any]:
        excluded = {
            "catalog",
            "schema_name",
            "name",
            "table_name",
            "column_name",
            "data_type",
            "ordinal_position",
            "nullable",
            "default_value",
            "description",
            "length",
            "precision",
            "scale",
            "table_type",
            "is_view",
            "is_insertable",
            "is_temporary",
        }
        return {key: value for key, value in row.items() if key not in excluded}

    def _map_table_type(self, table_type: str | None) -> str:
        value = (table_type or "table").strip().upper()
        if value == "VIEW":
            return "view"
        if value == "MATERIALIZED VIEW":
            return "materialized_view"
        if value == "BASE TABLE" or value == "TABLE" or value == "TEMPORARY":
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
        return '"' + value.replace('"', '""') + '"'

    def _elapsed_ms(self, started_ms: float) -> float:
        return self._now_ms() - started_ms

    def _now_ms(self) -> float:
        from time import perf_counter

        return perf_counter() * 1000.0


def create_adapter(
    config: SnowflakeConnectionConfig,
    secrets: Mapping[str, str] | None = None,
    connection_name: str | None = None,
) -> SnowflakeAdapter:
    return SnowflakeAdapter(config=config, secrets=secrets, connection_name=connection_name)


build_adapter = create_adapter


__all__ = ["SnowflakeAdapter", "build_adapter", "create_adapter"]
