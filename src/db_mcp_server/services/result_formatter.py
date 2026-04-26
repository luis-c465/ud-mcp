"""Normalize backend results into stable shared response models."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db_mcp_server.models import ColumnInfo, ExplainResult, QueryResult, ResultWarning

ResultColumn = ColumnInfo


class BackendMetadata(BaseModel):
    """Normalized backend metadata before flattening into shared result models."""

    model_config = ConfigDict(extra="forbid")

    backend_type: str | None = None
    query_id: str | None = None
    statement_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.backend_type is not None:
            payload["backend_type"] = self.backend_type
        if self.query_id is not None:
            payload["query_id"] = self.query_id
        if self.statement_type is not None:
            payload["statement_type"] = self.statement_type
        payload.update(self.details)
        return payload


class ResultFormatter:
    """Convert backend-native structures into shared models."""

    def normalize_columns(self, columns: Sequence[Any] | None) -> list[ResultColumn]:
        if not columns:
            return []
        return [self._normalize_column(column, index=index) for index, column in enumerate(columns, start=1)]

    def normalize_rows(
        self,
        rows: Iterable[Any] | None,
        *,
        columns: Sequence[ResultColumn] | Sequence[str] | None = None,
    ) -> list[list[Any]]:
        if rows is None:
            return []

        column_names = self._column_names(columns)
        normalized: list[list[Any]] = []
        for row in rows:
            normalized.append(self._normalize_row(row, column_names=column_names))
        return normalized

    def normalize_warnings(self, warnings: Iterable[Any] | None) -> list[ResultWarning]:
        if warnings is None:
            return []
        return [self._normalize_warning(warning) for warning in warnings]

    def normalize_backend_metadata(
        self,
        metadata: Any,
        *,
        backend_type: str | None = None,
    ) -> BackendMetadata:
        if isinstance(metadata, BackendMetadata):
            normalized = metadata
        elif metadata is None:
            normalized = BackendMetadata(backend_type=backend_type)
        elif isinstance(metadata, Mapping):
            normalized = BackendMetadata(
                backend_type=self._pick_str(metadata, ("backend_type", "backend", "dialect")) or backend_type,
                query_id=self._pick_str(metadata, ("query_id", "queryId", "statement_id", "statementId")),
                statement_type=self._pick_str(metadata, ("statement_type", "statementType")),
                details=self._collect_details(
                    metadata,
                    exclude={
                        "backend_type",
                        "backend",
                        "dialect",
                        "query_id",
                        "queryId",
                        "statement_id",
                        "statementId",
                        "statement_type",
                        "statementType",
                    },
                ),
            )
        else:
            details = self._object_to_mapping(metadata)
            normalized = BackendMetadata(
                backend_type=backend_type,
                query_id=self._pick_str(details, ("query_id", "queryId", "statement_id", "statementId")),
                statement_type=self._pick_str(details, ("statement_type", "statementType")),
                details=details,
            )

        if normalized.backend_type is None and backend_type is not None:
            normalized = normalized.model_copy(update={"backend_type": backend_type})
        return normalized

    def format_query_result(
        self,
        *,
        rows: Iterable[Any] | None = None,
        columns: Sequence[Any] | None = None,
        warnings: Iterable[Any] | None = None,
        backend_metadata: Any = None,
        elapsed_ms: int | float | None = None,
        truncated: bool = False,
        row_count: int | None = None,
        connection_name: str | None = None,
        statement_type: str | None = None,
        backend_type: str | None = None,
    ) -> QueryResult:
        normalized_columns = self.normalize_columns(columns)
        normalized_rows = self.normalize_rows(rows, columns=normalized_columns)
        normalized_warnings = self.normalize_warnings(warnings)
        normalized_backend_metadata = self.normalize_backend_metadata(backend_metadata, backend_type=backend_type)

        return QueryResult(
            columns=normalized_columns,
            rows=normalized_rows,
            row_count=len(normalized_rows) if row_count is None else row_count,
            truncated=truncated,
            elapsed_ms=None if elapsed_ms is None else float(elapsed_ms),
            warnings=normalized_warnings,
            query_id=normalized_backend_metadata.query_id,
            statement_type=statement_type or normalized_backend_metadata.statement_type,
            connection_name=connection_name,
            backend_metadata=normalized_backend_metadata.as_dict(),
        )

    def format_explain_result(
        self,
        *,
        plan: Any,
        warnings: Iterable[Any] | None = None,
        backend_metadata: Any = None,
        elapsed_ms: int | float | None = None,
        connection_name: str | None = None,
        statement_type: str | None = "EXPLAIN",
        backend_type: str | None = None,
        source_query: str | None = None,
    ) -> ExplainResult:
        normalized_backend_metadata = self.normalize_backend_metadata(backend_metadata, backend_type=backend_type)
        plan_text, plan_format = self._normalize_plan(plan)
        return ExplainResult(
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            elapsed_ms=None if elapsed_ms is None else float(elapsed_ms),
            warnings=self.normalize_warnings(warnings),
            query_id=normalized_backend_metadata.query_id,
            statement_type=statement_type or normalized_backend_metadata.statement_type or "EXPLAIN",
            connection_name=connection_name,
            backend_metadata=normalized_backend_metadata.as_dict(),
            plan_text=plan_text,
            plan_format=plan_format,
            source_query=source_query,
        )

    def _normalize_column(self, column: Any, *, index: int) -> ResultColumn:
        if isinstance(column, ColumnInfo):
            return column
        if isinstance(column, str):
            return ColumnInfo(name=column)

        mapping = self._object_to_mapping(column)
        name = self._pick_str(mapping, ("name", "column_name", "columnName", "label")) or f"column_{index}"
        return ColumnInfo(
            catalog=self._pick_str(mapping, ("catalog",)),
            schema=self._pick_str(mapping, ("schema", "schema_name", "schemaName")),
            table=self._pick_str(mapping, ("table", "table_name", "tableName")),
            name=name,
            data_type=self._pick_str(mapping, ("type", "data_type", "dataType", "db_type", "dbType")),
            ordinal_position=self._pick_int(mapping, ("ordinal_position", "ordinalPosition", "position")),
            nullable=self._pick_bool(mapping, ("nullable", "is_nullable", "isNullable")),
            description=self._pick_str(mapping, ("description", "comment")),
            length=self._pick_int(mapping, ("display_size", "displaySize", "size", "length")),
            precision=self._pick_int(mapping, ("precision",)),
            scale=self._pick_int(mapping, ("scale",)),
            backend_metadata=self._collect_details(
                mapping,
                exclude={
                    "catalog",
                    "schema",
                    "schema_name",
                    "schemaName",
                    "table",
                    "table_name",
                    "tableName",
                    "name",
                    "column_name",
                    "columnName",
                    "label",
                    "type",
                    "data_type",
                    "dataType",
                    "db_type",
                    "dbType",
                    "nullable",
                    "is_nullable",
                    "isNullable",
                    "precision",
                    "scale",
                    "display_size",
                    "displaySize",
                    "size",
                    "length",
                    "ordinal_position",
                    "ordinalPosition",
                    "position",
                    "description",
                    "comment",
                },
            ),
        )

    def _normalize_row(self, row: Any, *, column_names: Sequence[str] | None = None) -> list[Any]:
        if isinstance(row, Mapping):
            if column_names:
                return [row.get(column_name) for column_name in column_names]
            return list(row.values())

        if isinstance(row, (list, tuple)):
            return list(row)

        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            return list(row)

        return [row]

    def _normalize_warning(self, warning: Any) -> ResultWarning:
        if isinstance(warning, ResultWarning):
            return warning
        if isinstance(warning, str):
            return ResultWarning(code="warning", message=warning)

        mapping = self._object_to_mapping(warning)
        message = self._pick_str(mapping, ("message", "warning", "detail", "description")) or str(warning)
        code = self._pick_str(mapping, ("code", "warning_code", "warningCode")) or "warning"
        return ResultWarning(
            code=code,
            message=message,
            details=self._collect_details(
                mapping,
                exclude={"message", "warning", "detail", "description", "code", "warning_code", "warningCode"},
            ),
        )

    def _normalize_plan(self, plan: Any) -> tuple[str | None, str]:
        if plan is None:
            return None, "text"
        if isinstance(plan, str):
            return plan, "text"
        if isinstance(plan, Mapping):
            return json.dumps(dict(plan), sort_keys=True), "json"
        if isinstance(plan, Sequence) and not isinstance(plan, (str, bytes, bytearray)):
            return "\n".join("\t".join("" if cell is None else str(cell) for cell in self._normalize_row(row)) for row in plan), "table"
        return str(plan), "text"

    def _column_names(self, columns: Sequence[ResultColumn] | Sequence[str] | None) -> list[str] | None:
        if not columns:
            return None
        first = columns[0]
        if isinstance(first, ColumnInfo):
            return [column.name for column in columns]  # type: ignore[union-attr]
        return [str(column) for column in columns]

    def _object_to_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        if hasattr(value, "__dict__"):
            return {key: item for key, item in vars(value).items() if not key.startswith("_")}
        return {"value": value}

    def _collect_details(self, mapping: Mapping[str, Any], *, exclude: set[str]) -> dict[str, Any]:
        return {key: value for key, value in mapping.items() if key not in exclude}

    def _pick_str(self, mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return str(value)
        return None

    def _pick_int(self, mapping: Mapping[str, Any], keys: Sequence[str]) -> int | None:
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _pick_bool(self, mapping: Mapping[str, Any], keys: Sequence[str]) -> bool | None:
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


__all__ = [
    "BackendMetadata",
    "ExplainResult",
    "QueryResult",
    "ResultColumn",
    "ResultFormatter",
    "ResultWarning",
]
