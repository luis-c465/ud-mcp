from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, Result, URL

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
)

_DEFAULT_POOL_SIZE = 5
_DEFAULT_MAX_OVERFLOW = 0
_DEFAULT_POOL_TIMEOUT = 30
_DEFAULT_POOL_RECYCLE = 1_800


def build_engine(url: str | URL, **engine_kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine with conservative defaults.

    The defaults are intentionally small so backend adapters can share a common
    baseline while still overriding pool behavior when a dialect requires it.
    """

    engine_kwargs = dict(engine_kwargs)
    engine_kwargs.setdefault("pool_pre_ping", True)
    engine_kwargs.setdefault("hide_parameters", True)

    if "poolclass" not in engine_kwargs:
        engine_kwargs.setdefault("pool_size", _DEFAULT_POOL_SIZE)
        engine_kwargs.setdefault("max_overflow", _DEFAULT_MAX_OVERFLOW)
        engine_kwargs.setdefault("pool_timeout", _DEFAULT_POOL_TIMEOUT)
        engine_kwargs.setdefault("pool_recycle", _DEFAULT_POOL_RECYCLE)

    return create_engine(url, **engine_kwargs)


class SQLAlchemyAdapterBase:
    """Reusable SQLAlchemy-backed adapter implementation.

    Backend adapters can inherit from this class and override the protected hook
    methods to adjust query execution, reflection, identifier handling, or
    result normalization for dialect-specific behavior.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        backend_type: str,
        connection_name: str | None = None,
        description: str | None = None,
        catalog: str | None = None,
        schema: str | None = None,
        read_only: bool = True,
        allow_full_permissions: bool = False,
        backend_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.engine = engine
        self.backend_type = backend_type
        self.connection_name = connection_name
        self.description = description
        self.catalog = catalog
        self.schema = schema
        self.read_only = read_only
        self.allow_full_permissions = allow_full_permissions
        self.backend_metadata = dict(backend_metadata or {})

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    def connection_descriptor(self) -> ConnectionDescriptor:
        """Return a safe, backend-neutral description of the adapter."""

        return ConnectionDescriptor(
            name=self.connection_name or self.backend_type,
            backend_type=self.backend_type,
            description=self.description,
            catalog=self.catalog,
            schema=self.schema,
            read_only=self.read_only,
            allow_full_permissions=self.allow_full_permissions,
            object_type="connection",
            backend_metadata=self._connection_backend_metadata(),
        )

    def test_connection(self) -> ConnectionTestResult:
        start = perf_counter()
        try:
            with self.engine.connect() as connection:
                connection.execute(text(self._test_query()))
            elapsed_ms = (perf_counter() - start) * 1_000
            return ConnectionTestResult(
                ok=True,
                connection=self.connection_descriptor(),
                message="Connection succeeded.",
                elapsed_ms=elapsed_ms,
                backend_metadata=self._connection_backend_metadata(),
            )
        except Exception as exc:  # pragma: no cover - backend failures are environment specific
            elapsed_ms = (perf_counter() - start) * 1_000
            return ConnectionTestResult(
                ok=False,
                connection=self.connection_descriptor(),
                message="Connection failed.",
                error_code=exc.__class__.__name__,
                elapsed_ms=elapsed_ms,
                backend_metadata=self._connection_backend_metadata(),
            )

    def list_schemas(self) -> list[SchemaInfo]:
        inspector = self._inspector()
        schemas: list[SchemaInfo] = []
        for name in self._safe_call(inspector.get_schema_names, default=[]):
            schemas.append(self._schema_info(name))
        return schemas

    def list_tables(
        self,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> list[TableInfo]:
        inspector = self._inspector()
        tables: list[TableInfo] = []
        seen: set[tuple[str | None, str | None, str]] = set()

        for name in self._safe_call(inspector.get_table_names, catalog=catalog, schema=schema, default=[]):
            tables.append(self._table_info(catalog, schema, name, object_type="table", is_view=False))
            seen.add((catalog, schema, name))

        if include_views:
            for name in self._safe_call(inspector.get_view_names, catalog=catalog, schema=schema, default=[]):
                key = (catalog, schema, name)
                if key in seen:
                    continue
                tables.append(self._table_info(catalog, schema, name, object_type="view", is_view=True))
                seen.add(key)

            get_materialized_views = getattr(inspector, "get_materialized_view_names", None)
            if callable(get_materialized_views):
                for name in self._safe_call(get_materialized_views, catalog=catalog, schema=schema, default=[]):
                    key = (catalog, schema, name)
                    if key in seen:
                        continue
                    tables.append(
                        self._table_info(catalog, schema, name, object_type="materialized_view", is_view=True)
                    )
                    seen.add(key)

        return tables

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription:
        inspector = self._inspector()
        columns_data = self._safe_call(inspector.get_columns, table_name=table, schema=schema, catalog=catalog, default=[])
        pk_data = self._safe_call(
            inspector.get_pk_constraint,
            table_name=table,
            schema=schema,
            catalog=catalog,
            default={},
        )
        fk_data = self._safe_call(inspector.get_foreign_keys, table_name=table, schema=schema, catalog=catalog, default=[])
        table_info = self._table_info(catalog, schema, table, object_type=self._table_object_type(catalog, schema, table), is_view=self._is_view(catalog, schema, table))
        primary_keys = list(pk_data.get("constrained_columns") or [])
        columns = self._columns_from_reflection(
            columns_data,
            catalog=catalog,
            schema=schema,
            table=table,
            primary_keys=primary_keys,
        )
        return TableDescription(
            table=table_info,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=list(fk_data or []),
            backend_metadata={
                **self._backend_metadata,
                "dialect": self.dialect_name,
                "table": table,
            },
        )

    def run_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> QueryResult:
        start = perf_counter()
        statement = text(sql)
        limit = self._query_row_limit(options)

        with self.engine.connect() as connection:
            execution_connection = connection.execution_options(**self._query_execution_options(options))
            result = execution_connection.execute(statement, params or {})
            rows, truncated = self._fetch_rows(result, limit=limit)
            elapsed_ms = (perf_counter() - start) * 1_000
            return self._query_result_from_rows(
                result,
                rows,
                truncated=truncated,
                elapsed_ms=elapsed_ms,
            )

    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult:
        explain_sql = self._build_explain_sql(sql, options)
        query_result = self.run_query(explain_sql, params, options)
        return ExplainResult(
            **query_result.model_dump(),
            plan_text=self._extract_plan_text(query_result),
            plan_format=self._explain_plan_format(),
            source_query=sql,
        )

    def _connection_backend_metadata(self) -> dict[str, Any]:
        return {
            **self._backend_metadata,
            "dialect": self.dialect_name,
            "driver": getattr(self.engine.dialect, "driver", None),
        }

    def _backend_metadata_for_object(self, object_type: str, name: str, schema: str | None = None) -> dict[str, Any]:
        return {
            **self._backend_metadata,
            "dialect": self.dialect_name,
            "object_type": object_type,
            "name": name,
            "schema": schema,
        }

    def _connection_descriptor(self) -> ConnectionDescriptor:
        return self.connection_descriptor()

    def _test_query(self) -> str:
        return "SELECT 1"

    def _query_row_limit(self, options: QueryOptions) -> int | None:
        return options.max_rows

    def _query_execution_options(self, options: QueryOptions) -> dict[str, Any]:
        return {}

    def _build_explain_sql(self, sql: str, options: QueryOptions) -> str:
        return f"EXPLAIN {sql}"

    def _explain_plan_format(self) -> str:
        return "text"

    def _extract_plan_text(self, result: QueryResult) -> str | None:
        if not result.rows:
            return None
        if len(result.rows) == 1 and len(result.rows[0]) == 1:
            value = result.rows[0][0]
            return None if value is None else str(value)
        lines = ["\t".join("" if value is None else str(value) for value in row) for row in result.rows]
        return "\n".join(lines)

    def _inspector(self):
        return inspect(self.engine)

    def _schema_info(self, name: str) -> SchemaInfo:
        return SchemaInfo(
            catalog=self.catalog,
            schema=name,
            name=name,
            description=None,
            backend_metadata=self._backend_metadata_for_object("schema", name, schema=name),
        )

    def _table_info(
        self,
        catalog: str | None,
        schema: str | None,
        name: str,
        *,
        object_type: str,
        is_view: bool,
    ) -> TableInfo:
        return TableInfo(
            catalog=catalog,
            schema=schema,
            name=name,
            object_type=object_type,
            is_view=is_view,
            backend_metadata=self._backend_metadata_for_object(object_type, name, schema=schema),
        )

    def _table_object_type(self, catalog: str | None, schema: str, table: str) -> str:
        if self._is_materialized_view(catalog, schema, table):
            return "materialized_view"
        if self._is_view(catalog, schema, table):
            return "view"
        return "table"

    def _is_view(self, catalog: str | None, schema: str, table: str) -> bool:
        inspector = self._inspector()
        view_names = set(self._safe_call(inspector.get_view_names, catalog=catalog, schema=schema, default=[]))
        return table in view_names

    def _is_materialized_view(self, catalog: str | None, schema: str, table: str) -> bool:
        inspector = self._inspector()
        get_materialized_views = getattr(inspector, "get_materialized_view_names", None)
        if not callable(get_materialized_views):
            return False
        materialized_view_names = set(self._safe_call(get_materialized_views, catalog=catalog, schema=schema, default=[]))
        return table in materialized_view_names

    def _columns_from_reflection(
        self,
        columns_data: Sequence[Mapping[str, Any]],
        *,
        catalog: str | None,
        schema: str,
        table: str,
        primary_keys: Sequence[str],
    ) -> list[ColumnInfo]:
        primary_key_names = set(primary_keys)
        columns: list[ColumnInfo] = []
        for index, column in enumerate(columns_data, start=1):
            name = str(column.get("name"))
            data_type = column.get("type")
            columns.append(
                ColumnInfo(
                    catalog=catalog,
                    schema=schema,
                    table=table,
                    name=name,
                    data_type=None if data_type is None else str(data_type),
                    ordinal_position=index,
                    nullable=column.get("nullable"),
                    default=None if column.get("default") is None else str(column.get("default")),
                    description=column.get("comment"),
                    length=column.get("length"),
                    precision=column.get("precision"),
                    scale=column.get("scale"),
                    is_primary_key=name in primary_key_names,
                    backend_metadata={
                        **self._backend_metadata,
                        "dialect": self.dialect_name,
                        "column_name": name,
                    },
                )
            )
        return columns

    def _fetch_rows(self, result: Result[Any], *, limit: int | None) -> tuple[list[list[Any]], bool]:
        if limit is None:
            rows = [list(row) for row in result.fetchall()]
            return rows, False

        fetched = result.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows = [list(row) for row in fetched[:limit]]
        return rows, truncated

    def _query_result_from_rows(
        self,
        result: Result[Any],
        rows: list[list[Any]],
        *,
        truncated: bool,
        elapsed_ms: float,
    ) -> QueryResult:
        return QueryResult(
            columns=self._columns_from_result(result),
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            warnings=[],
            query_id=self._query_id_from_result(result),
            statement_type=self._statement_type_from_result(result),
            backend_metadata={
                **self._backend_metadata,
                "dialect": self.dialect_name,
            },
        )

    def _columns_from_result(self, result: Result[Any]) -> list[ColumnInfo]:
        keys = list(result.keys())
        columns: list[ColumnInfo] = []
        for index, name in enumerate(keys, start=1):
            columns.append(
                ColumnInfo(
                    name=str(name),
                    ordinal_position=index,
                    backend_metadata={
                        **self._backend_metadata,
                        "dialect": self.dialect_name,
                        "result_column": str(name),
                    },
                )
            )
        return columns

    def _query_id_from_result(self, result: Result[Any]) -> str | None:
        return None

    def _statement_type_from_result(self, result: Result[Any]) -> str | None:
        return None

    def _safe_call(self, func: Any, /, *args: Any, default: Any = None, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except NotImplementedError:
            return default
        except AttributeError:
            return default


__all__ = [
    "SQLAlchemyAdapterBase",
    "build_engine",
]
