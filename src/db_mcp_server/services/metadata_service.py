"""Metadata orchestration helpers for schemas, tables, and table descriptions."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from typing import Any

from db_mcp_server.models import ColumnInfo, SchemaInfo, TableDescription, TableInfo
from db_mcp_server.safety.errors import BackendError, UnknownConnectionError
from db_mcp_server.services.connection_registry import ConnectionRegistry, DatabaseAdapter

TableColumnInfo = ColumnInfo


class MetadataService:
    """Validate metadata requests and delegate to backend adapters."""

    def __init__(self, registry: ConnectionRegistry) -> None:
        self.registry = registry

    def list_schemas(self, connection_name: str) -> list[SchemaInfo]:
        adapter = self._get_adapter(connection_name)
        result = self._call_adapter(adapter.list_schemas)
        return [self._normalize_schema(item) for item in self._ensure_sequence(result)]

    def list_tables(
        self,
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        include_views: bool = False,
    ) -> list[TableInfo]:
        adapter = self._get_adapter(connection_name)
        result = self._call_adapter(adapter.list_tables, catalog, schema, include_views)
        return [self._normalize_table(item) for item in self._ensure_sequence(result)]

    def describe_table(
        self,
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        table: str | None = None,
    ) -> TableDescription:
        self._require_connection(connection_name)
        catalog = self._require_optional_text(catalog, field_name="catalog")
        schema = self._require_optional_text(schema, field_name="schema")
        table = self._require_optional_text(table, field_name="table")

        adapter = self._get_adapter(connection_name)
        result = self._call_adapter(adapter.describe_table, catalog, schema, table)
        return self._normalize_table_description(result, catalog=catalog, schema=schema, name=table)

    def _get_adapter(self, connection_name: str) -> DatabaseAdapter:
        self._require_connection(connection_name)
        try:
            return self.registry.get_adapter(connection_name)
        except UnknownConnectionError:
            raise
        except Exception as exc:  # pragma: no cover - backend-specific lookup failure
            raise BackendError(
                f"Failed to resolve metadata adapter for connection {connection_name!r}.",
                details={"connection_name": connection_name},
                cause=exc,
            ) from exc

    def _require_connection(self, connection_name: str) -> None:
        self._require_text(connection_name, field_name="connection_name")
        self.registry.get_connection(connection_name)

    def _require_text(self, value: str | None, *, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required.")
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")
        value = value.strip()
        if not value:
            raise ValueError(f"{field_name} is required.")
        return value

    def _require_optional_text(self, value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None
        return self._require_text(value, field_name=field_name)

    def _call_adapter(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(result)
            raise RuntimeError("Asynchronous metadata adapters are not supported from a running event loop.")
        return result

    def _ensure_sequence(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
        return [value]

    def _normalize_schema(self, value: Any) -> SchemaInfo:
        if isinstance(value, SchemaInfo):
            return value
        mapping = self._object_to_mapping(value)
        return SchemaInfo(
            catalog=self._pick_str(mapping, ("catalog", "database")),
            schema=self._pick_str(mapping, ("schema", "schema_name", "schemaName")),
            name=self._pick_str(mapping, ("name", "schema", "schema_name", "schemaName")) or self._fallback_name(mapping),
            object_type=self._pick_str(mapping, ("object_type", "objectType")) or "schema",
            description=self._pick_str(mapping, ("description", "comment")),
            backend_metadata=self._collect_details(
                mapping,
                exclude={"catalog", "database", "schema", "schema_name", "schemaName", "name", "object_type", "objectType", "description", "comment"},
            ),
        )

    def _normalize_table(self, value: Any) -> TableInfo:
        if isinstance(value, TableInfo):
            return value
        mapping = self._object_to_mapping(value)
        object_type = self._pick_str(mapping, ("object_type", "objectType", "table_type", "tableType")) or "table"
        return TableInfo(
            catalog=self._pick_str(mapping, ("catalog", "database")),
            schema=self._pick_str(mapping, ("schema", "schema_name", "schemaName")),
            name=self._pick_str(mapping, ("name", "table", "table_name", "tableName")) or self._fallback_name(mapping),
            object_type=object_type,
            description=self._pick_str(mapping, ("description", "comment")),
            is_view=object_type in {"view", "materialized_view"},
            backend_metadata=self._collect_details(
                mapping,
                exclude={"catalog", "database", "schema", "schema_name", "schemaName", "name", "table", "table_name", "tableName", "object_type", "objectType", "table_type", "tableType", "description", "comment"},
            ),
        )

    def _normalize_table_description(self, value: Any, *, catalog: str | None, schema: str | None, name: str | None) -> TableDescription:
        if isinstance(value, TableDescription):
            return value
        mapping = self._object_to_mapping(value)
        columns = mapping.get("columns") or mapping.get("column_list") or mapping.get("fields") or []
        table_info = TableInfo(
            catalog=self._pick_str(mapping, ("catalog", "database")) or catalog,
            schema=self._pick_str(mapping, ("schema", "schema_name", "schemaName")) or schema,
            name=self._pick_str(mapping, ("name", "table", "table_name", "tableName")) or (name or self._fallback_name(mapping)),
            object_type=self._pick_str(mapping, ("object_type", "objectType", "table_type", "tableType")) or "table",
            description=self._pick_str(mapping, ("description", "comment")),
        )
        return TableDescription(
            table=table_info,
            columns=[self._normalize_column(column, table_info=table_info) for column in self._ensure_sequence(columns)],
            primary_keys=[str(item) for item in self._ensure_sequence(mapping.get("primary_keys") or [])],
            foreign_keys=[self._object_to_mapping(item) for item in self._ensure_sequence(mapping.get("foreign_keys") or [])],
            backend_metadata=self._collect_details(
                mapping,
                exclude={
                    "catalog",
                    "database",
                    "schema",
                    "schema_name",
                    "schemaName",
                    "name",
                    "table",
                    "table_name",
                    "tableName",
                    "object_type",
                    "objectType",
                    "table_type",
                    "tableType",
                    "description",
                    "comment",
                    "columns",
                    "column_list",
                    "fields",
                    "primary_keys",
                    "foreign_keys",
                },
            ),
        )

    def _normalize_column(self, value: Any, *, table_info: TableInfo | None = None) -> ColumnInfo:
        if isinstance(value, ColumnInfo):
            return value
        mapping = self._object_to_mapping(value)
        return ColumnInfo(
            catalog=self._pick_str(mapping, ("catalog",)) or (table_info.catalog if table_info is not None else None),
            schema=self._pick_str(mapping, ("schema", "schema_name", "schemaName")) or (table_info.schema if table_info is not None else None),
            table=self._pick_str(mapping, ("table", "table_name", "tableName")) or (table_info.name if table_info is not None else None),
            name=self._pick_str(mapping, ("name", "column_name", "columnName", "field_name", "fieldName")) or self._fallback_name(mapping),
            data_type=self._pick_str(mapping, ("type", "data_type", "dataType", "db_type", "dbType")),
            nullable=self._pick_bool(mapping, ("nullable", "is_nullable", "isNullable")),
            default=self._pick_str(mapping, ("default", "default_value", "defaultValue")),
            description=self._pick_str(mapping, ("comment", "description")),
            ordinal_position=self._pick_int(mapping, ("ordinal_position", "ordinalPosition", "position", "column_position")),
            backend_metadata=self._collect_details(
                mapping,
                exclude={"catalog", "schema", "schema_name", "schemaName", "table", "table_name", "tableName", "name", "column_name", "columnName", "field_name", "fieldName", "type", "data_type", "dataType", "db_type", "dbType", "nullable", "is_nullable", "isNullable", "default", "default_value", "defaultValue", "comment", "description", "ordinal_position", "ordinalPosition", "position", "column_position"},
            ),
        )

    def _object_to_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(by_alias=True)
            if isinstance(dumped, Mapping):
                return dict(dumped)
        if hasattr(value, "__dict__"):
            return {key: item for key, item in vars(value).items() if not key.startswith("_")}
        return {"value": value}

    def _collect_details(self, mapping: Mapping[str, Any], *, exclude: set[str]) -> dict[str, Any]:
        return {key: value for key, value in mapping.items() if key not in exclude}

    def _pick_str(self, mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return str(value)
        return None

    def _pick_bool(self, mapping: Mapping[str, Any], keys: tuple[str, ...]) -> bool | None:
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    return True
                if lowered in {"false", "no", "0"}:
                    return False
        return None

    def _pick_int(self, mapping: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _fallback_name(self, mapping: Mapping[str, Any]) -> str:
        return str(mapping.get("value", "unknown"))


__all__ = [
    "MetadataService",
    "SchemaInfo",
    "TableColumnInfo",
    "TableDescription",
    "TableInfo",
]
