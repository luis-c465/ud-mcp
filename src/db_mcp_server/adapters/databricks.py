from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from db_mcp_server.config.models import DatabricksConnectionConfig
from db_mcp_server.drivers.databricks_client import DatabricksClient, create_client
from db_mcp_server.models import (
    ColumnInfo,
    ConnectionDescriptor,
    ConnectionTestResult,
    ExplainResult,
    QueryOptions,
    QueryResult,
    SchemaInfo,
    TableDescription,
    TableInfo,
    TruncationWarning,
)


class DatabricksAdapter:
    """Database adapter backed by the native Databricks SQL connector."""

    def __init__(
        self,
        config: DatabricksConnectionConfig,
        secrets: Mapping[str, str],
        connection_name: str | None = None,
    ) -> None:
        if not isinstance(config, DatabricksConnectionConfig):
            raise TypeError("config must be a DatabricksConnectionConfig.")
        if not isinstance(secrets, Mapping):
            raise TypeError("secrets must be a mapping of resolved secret values.")

        self.config = config
        self.connection_name = connection_name
        self._client: DatabricksClient = create_client(
            config,
            secrets,
            connection_name=connection_name,
        )

    def test_connection(self) -> ConnectionTestResult:
        started = perf_counter()
        with self._client.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchall()

        return ConnectionTestResult(
            ok=True,
            connection=self._connection_descriptor(),
            message="Connection succeeded.",
            elapsed_ms=self._elapsed_ms(started),
            backend_metadata=self._backend_metadata(),
        )

    def list_schemas(self) -> list[SchemaInfo]:
        started = perf_counter()
        rows, _ = self._run_metadata_query(
            (
                "SELECT catalog_name, schema_name, comment "
                "FROM system.information_schema.schemata "
                "ORDER BY catalog_name, schema_name",
                "SELECT catalog_name, schema_name, comment "
                "FROM information_schema.schemata "
                "ORDER BY catalog_name, schema_name",
            )
        )
        return [
            SchemaInfo(
                catalog=self._string_or_none(row[0]),
                schema=self._string_or_none(row[1]),
                name=self._string_or_none(row[1]) or self._string_or_none(row[0]) or "schema",
                description=self._string_or_none(row[2]),
                backend_metadata=self._backend_metadata(
                    query_kind="list_schemas",
                    elapsed_ms=self._elapsed_ms(started),
                    raw_row=row,
                ),
            )
            for row in rows
        ]

    def list_tables(
        self,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> list[TableInfo]:
        started = perf_counter()
        rows, _ = self._run_metadata_query(
            self._list_tables_sql(catalog=catalog, schema=schema, include_views=include_views)
        )
        return [self._table_info_from_row(row, started=started) for row in rows]

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription:
        started = perf_counter()
        table_catalog = catalog or self.config.catalog
        table_schema = schema or self.config.schema_
        table_name = table

        table_info = self._describe_table_info(table_catalog, table_schema, table_name)
        columns = self._describe_columns(table_catalog, table_schema, table_name)

        return TableDescription(
            table=table_info,
            columns=columns,
            backend_metadata=self._backend_metadata(
                query_kind="describe_table",
                catalog=table_catalog,
                schema=table_schema,
                table=table_name,
                elapsed_ms=self._elapsed_ms(started),
            ),
        )

    def run_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> QueryResult:
        started = perf_counter()
        columns, rows = self._run_query(sql, params)
        warnings: list[TruncationWarning] = []
        truncated = False

        if options.max_rows is not None and options.max_rows >= 0 and len(rows) > options.max_rows:
            truncated = True
            warnings.append(
                TruncationWarning(
                    limit_type="rows",
                    limit=options.max_rows,
                    actual=len(rows),
                    truncated_rows=len(rows) - options.max_rows,
                )
            )
            rows = rows[: options.max_rows]

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=self._elapsed_ms(started),
            warnings=warnings,
            query_id=None,
            statement_type="QUERY",
            backend_metadata=self._backend_metadata(query_kind="query", sql=sql),
        )

    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult:
        started = perf_counter()
        explain_sql = f"EXPLAIN {sql}"
        columns, rows = self._run_query(explain_sql, params)
        plan_text = self._rows_to_plan_text(rows)

        return ExplainResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=False,
            elapsed_ms=self._elapsed_ms(started),
            warnings=[],
            query_id=None,
            statement_type="EXPLAIN",
            backend_metadata=self._backend_metadata(query_kind="explain", sql=sql),
            plan_text=plan_text,
            plan_format="text",
            source_query=sql,
        )

    def _run_query(self, sql: str, params: dict[str, Any]) -> tuple[list[ColumnInfo], list[list[Any]]]:
        with self._client.connect() as connection:
            with connection.cursor() as cursor:
                if params:
                    cursor.execute(sql, parameters=params)
                else:
                    cursor.execute(sql)

                description = list(cursor.description or [])
                columns = [self._column_info_from_description(column, position) for position, column in enumerate(description, start=1)]
                rows = [self._normalize_row(row) for row in cursor.fetchall()] if description else []
                return columns, rows

    def _run_metadata_query(self, statements: Sequence[str]) -> tuple[list[list[Any]], str]:
        last_error: Exception | None = None
        for statement in statements:
            try:
                columns, rows = self._run_query(statement, {})
                return rows, statement
            except Exception as exc:  # pragma: no cover - backend-specific fallback path
                last_error = exc
                continue

        assert last_error is not None
        raise last_error

    def _list_tables_sql(
        self,
        *,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> tuple[str, str]:
        effective_catalog = catalog or self.config.catalog
        effective_schema = schema or self.config.schema_

        where_clauses: list[str] = []
        if effective_catalog is not None:
            where_clauses.append(f"table_catalog = {self._sql_literal(effective_catalog)}")
        if effective_schema is not None:
            where_clauses.append(f"table_schema = {self._sql_literal(effective_schema)}")
        if not include_views:
            where_clauses.append("UPPER(table_type) NOT LIKE '%VIEW%'")

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        return (
            "SELECT table_catalog, table_schema, table_name, table_type, comment, is_insertable_into, is_temporary "
            "FROM system.information_schema.tables"
            f"{where_sql}"
            " ORDER BY table_catalog, table_schema, table_name",
            "SELECT table_catalog, table_schema, table_name, table_type, comment, is_insertable_into, is_temporary "
            "FROM information_schema.tables"
            f"{where_sql}"
            " ORDER BY table_catalog, table_schema, table_name",
        )

    def _describe_table_info(self, catalog: str | None, schema: str | None, table: str) -> TableInfo:
        rows, _ = self._run_metadata_query(
            self._describe_table_sql(catalog=catalog, schema=schema, table=table)
        )
        if not rows:
            return TableInfo(
                catalog=catalog,
                schema=schema,
                name=table,
                object_type="unknown",
                backend_metadata=self._backend_metadata(query_kind="describe_table", catalog=catalog, schema=schema, table=table),
            )

        row = rows[0]
        table_type = self._string_or_none(row[3])
        return TableInfo(
            catalog=self._string_or_none(row[0]) or catalog,
            schema=self._string_or_none(row[1]) or schema,
            name=self._string_or_none(row[2]) or table,
            object_type=self._table_object_type(table_type),
            description=self._string_or_none(row[4]),
            is_view=self._is_view_type(table_type),
            is_insertable=self._coerce_bool(row[5]),
            is_temporary=self._coerce_bool(row[6]),
            backend_metadata=self._backend_metadata(
                query_kind="describe_table",
                catalog=catalog,
                schema=schema,
                table=table,
                table_type=table_type,
                raw_row=row,
            ),
        )

    def _describe_table_sql(self, *, catalog: str | None, schema: str | None, table: str) -> tuple[str, str]:
        where_clauses: list[str] = [f"table_name = {self._sql_literal(table)}"]
        if catalog is not None:
            where_clauses.append(f"table_catalog = {self._sql_literal(catalog)}")
        if schema is not None:
            where_clauses.append(f"table_schema = {self._sql_literal(schema)}")

        where_sql = " WHERE " + " AND ".join(where_clauses)
        return (
            "SELECT table_catalog, table_schema, table_name, table_type, comment, is_insertable_into, is_temporary "
            "FROM system.information_schema.tables"
            f"{where_sql}"
            " ORDER BY table_catalog, table_schema, table_name",
            "SELECT table_catalog, table_schema, table_name, table_type, comment, is_insertable_into, is_temporary "
            "FROM information_schema.tables"
            f"{where_sql}"
            " ORDER BY table_catalog, table_schema, table_name",
        )

    def _describe_columns(self, catalog: str | None, schema: str | None, table: str) -> list[ColumnInfo]:
        rows, _ = self._run_metadata_query(
            self._describe_columns_sql(catalog=catalog, schema=schema, table=table)
        )
        return [self._column_info_from_metadata_row(row) for row in rows]

    def _describe_columns_sql(self, *, catalog: str | None, schema: str | None, table: str) -> tuple[str, str]:
        where_clauses: list[str] = [f"table_name = {self._sql_literal(table)}"]
        if catalog is not None:
            where_clauses.append(f"table_catalog = {self._sql_literal(catalog)}")
        if schema is not None:
            where_clauses.append(f"table_schema = {self._sql_literal(schema)}")

        where_sql = " WHERE " + " AND ".join(where_clauses)
        return (
            "SELECT table_catalog, table_schema, table_name, column_name, ordinal_position, data_type, is_nullable, "
            "column_default, comment, character_maximum_length, numeric_precision, numeric_scale "
            "FROM system.information_schema.columns"
            f"{where_sql}"
            " ORDER BY ordinal_position",
            "SELECT table_catalog, table_schema, table_name, column_name, ordinal_position, data_type, is_nullable, "
            "column_default, comment, character_maximum_length, numeric_precision, numeric_scale "
            "FROM information_schema.columns"
            f"{where_sql}"
            " ORDER BY ordinal_position",
        )

    def _column_info_from_description(self, column: Any, position: int) -> ColumnInfo:
        name = self._description_value(column, 0) or f"column_{position}"
        return ColumnInfo(
            name=self._string_or_none(name) or f"column_{position}",
            data_type=self._string_or_none(self._description_value(column, 1)),
            ordinal_position=position,
            nullable=self._coerce_bool(self._description_value(column, 6)),
            precision=self._coerce_int(self._description_value(column, 4)),
            scale=self._coerce_int(self._description_value(column, 5)),
            backend_metadata={
                "backend_type": "databricks",
                "connection_name": self.connection_name,
                "display_size": self._coerce_int(self._description_value(column, 2)),
                "internal_size": self._coerce_int(self._description_value(column, 3)),
            },
        )

    def _column_info_from_metadata_row(self, row: Sequence[Any]) -> ColumnInfo:
        return ColumnInfo(
            catalog=self._string_or_none(row[0]),
            schema=self._string_or_none(row[1]),
            table=self._string_or_none(row[2]),
            name=self._string_or_none(row[3]) or "",
            data_type=self._string_or_none(row[5]),
            ordinal_position=self._coerce_int(row[4]),
            nullable=self._coerce_bool(row[6]),
            default=self._string_or_none(row[7]),
            description=self._string_or_none(row[8]),
            length=self._coerce_int(row[9]),
            precision=self._coerce_int(row[10]),
            scale=self._coerce_int(row[11]),
            backend_metadata=self._backend_metadata(query_kind="describe_table", raw_row=row),
        )

    def _table_info_from_row(self, row: Sequence[Any], *, started: float) -> TableInfo:
        table_type = self._string_or_none(row[3])
        return TableInfo(
            catalog=self._string_or_none(row[0]),
            schema=self._string_or_none(row[1]),
            name=self._string_or_none(row[2]) or "",
            object_type=self._table_object_type(table_type),
            description=self._string_or_none(row[4]),
            is_view=self._is_view_type(table_type),
            is_insertable=self._coerce_bool(row[5]),
            is_temporary=self._coerce_bool(row[6]),
            backend_metadata=self._backend_metadata(
                query_kind="list_tables",
                table_type=table_type,
                raw_row=row,
                elapsed_ms=self._elapsed_ms(started),
            ),
        )

    def _rows_to_plan_text(self, rows: Sequence[Sequence[Any]]) -> str | None:
        if not rows:
            return None

        rendered_rows = [self._render_row(row) for row in rows]
        plan_text = "\n".join(rendered_rows).strip()
        return plan_text or None

    def _render_row(self, row: Sequence[Any]) -> str:
        if len(row) == 1:
            return self._string_or_none(row[0]) or ""
        return "\t".join("" if value is None else str(value) for value in row)

    def _normalize_row(self, row: Any) -> list[Any]:
        if isinstance(row, list):
            return row
        if isinstance(row, tuple):
            return list(row)
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            return list(row)
        return [row]

    def _description_value(self, column: Any, index: int) -> Any:
        if isinstance(column, Sequence) and not isinstance(column, (str, bytes, bytearray)):
            if index < len(column):
                return column[index]
            return None
        return getattr(column, self._description_attribute_name(index), None)

    def _description_attribute_name(self, index: int) -> str:
        return (
            "name"
            if index == 0
            else "type_code"
            if index == 1
            else "display_size"
            if index == 2
            else "internal_size"
            if index == 3
            else "precision"
            if index == 4
            else "scale"
            if index == 5
            else "null_ok"
        )

    def _table_object_type(self, table_type: str | None) -> str:
        if table_type is None:
            return "unknown"

        upper = table_type.upper()
        if "MATERIALIZED" in upper and "VIEW" in upper:
            return "materialized_view"
        if "VIEW" in upper:
            return "view"
        if "TABLE" in upper:
            return "table"
        if upper in {"MANAGED", "EXTERNAL"}:
            return "table"
        return "unknown"

    def _is_view_type(self, table_type: str | None) -> bool:
        return bool(table_type and "VIEW" in table_type.upper())

    def _connection_descriptor(self) -> ConnectionDescriptor:
        return ConnectionDescriptor(
            name=self.connection_name or "databricks",
            backend_type="databricks",
            description=self.config.description,
            catalog=self.config.catalog,
            schema=self.config.schema_,
            read_only=self.config.read_only,
            allow_full_permissions=self.config.allow_full_permissions,
            backend_metadata=self._backend_metadata(),
        )

    def _backend_metadata(self, **details: Any) -> dict[str, Any]:
        metadata = {"backend_type": "databricks"}
        if self.connection_name is not None:
            metadata["connection_name"] = self.connection_name
        metadata.update(details)
        return metadata

    def _elapsed_ms(self, started: float) -> float:
        return (perf_counter() - started) * 1000.0

    def _sql_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _coerce_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "t", "yes", "y", "1"}:
            return True
        if text in {"false", "f", "no", "n", "0"}:
            return False
        return None

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


DatabricksSqlAdapter = DatabricksAdapter


def create_adapter(
    config: DatabricksConnectionConfig,
    secrets: Mapping[str, str],
    connection_name: str | None = None,
) -> DatabricksAdapter:
    """Factory used by the connection registry to build Databricks adapters."""

    return DatabricksAdapter(config=config, secrets=secrets, connection_name=connection_name)


def build_adapter(
    config: DatabricksConnectionConfig,
    secrets: Mapping[str, str],
    connection_name: str | None = None,
) -> DatabricksAdapter:
    """Compatibility alias for :func:`create_adapter`."""

    return create_adapter(config=config, secrets=secrets, connection_name=connection_name)


__all__ = [
    "DatabricksAdapter",
    "DatabricksSqlAdapter",
    "build_adapter",
    "create_adapter",
]
