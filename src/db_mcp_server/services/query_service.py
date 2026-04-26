"""Query orchestration service for validated adapter execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from ..config.models import PermissionMode
from ..models import ColumnInfo, ExplainResult, QueryOptions, QueryResult, ResultWarning, TruncationWarning
from ..safety.errors import DbMcpError, normalize_exception
from .audit_service import AuditService
from .connection_registry import ConnectionRegistry
from .result_formatter import ResultFormatter
from .validation_service import ValidationService


class QueryService:
    """Validate, execute, normalize, and audit query operations."""

    def __init__(
        self,
        validation_service: ValidationService,
        registry: ConnectionRegistry,
        result_formatter: ResultFormatter | None = None,
        audit_service: AuditService | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.validation_service = validation_service
        self.registry = registry
        self.result_formatter = result_formatter or ResultFormatter()
        self.audit_service = audit_service or AuditService()
        self._env = dict(env or {})

    def run_query(
        self,
        connection_name: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        options: QueryOptions | None = None,
        *,
        permission_mode: PermissionMode | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
        max_bytes: int | None = None,
        dialect: str | None = None,
        request_id: str | None = None,
        actor: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> QueryResult:
        """Validate and execute a SQL query, returning a normalized result."""

        started = perf_counter()
        validated = None
        adapter = None
        adapter_result: Any = None
        normalized_result: QueryResult | None = None
        connection_descriptor = None
        effective_env = self._effective_env(env)
        execution_options = self._resolve_query_options(
            options,
            permission_mode=permission_mode,
            timeout_ms=timeout_ms,
            max_rows=max_rows,
            max_bytes=max_bytes,
        )

        try:
            validated = self.validation_service.validate_query_request(
                connection_name,
                sql,
                permission_mode=execution_options.permission_mode,
                timeout_ms=execution_options.timeout_ms,
                max_rows=execution_options.max_rows,
                max_bytes=execution_options.max_bytes,
                dialect=dialect,
            )
            execution_options = self._execution_options_from_validation(validated, fallback=execution_options)
            connection_descriptor = self.registry.describe_connection(connection_name)
            adapter = self.registry.get_adapter(connection_name, env=effective_env)
            adapter_result = adapter.run_query(validated.sql, dict(params or {}), execution_options)
            normalized_result = self._normalize_query_result(
                adapter_result,
                connection_name=connection_name,
                backend_type=connection_descriptor.type,
                fallback_statement_type=self._statement_type_from_analysis(getattr(validated, "analysis", None)),
            )
        except Exception as exc:
            error = exc if isinstance(exc, DbMcpError) else normalize_exception(exc)
            self._audit_failure(
                "run_query",
                operation="run_query",
                connection_name=connection_name,
                request_id=request_id,
                actor=actor,
                started=started,
                validation=validated,
                connection_descriptor=connection_descriptor,
                error=error,
            )
            raise error from exc

        self._audit_success(
            "run_query",
            operation="run_query",
            connection_name=connection_name,
            request_id=request_id,
            actor=actor,
            started=started,
            validation=validated,
            connection_descriptor=connection_descriptor,
            result=normalized_result,
        )
        return normalized_result

    def explain_query(
        self,
        connection_name: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        options: QueryOptions | None = None,
        *,
        permission_mode: PermissionMode | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
        max_bytes: int | None = None,
        dialect: str | None = None,
        request_id: str | None = None,
        actor: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExplainResult:
        """Validate and explain a SQL query, returning a normalized plan payload."""

        started = perf_counter()
        validated = None
        adapter = None
        adapter_result: Any = None
        normalized_result: ExplainResult | None = None
        connection_descriptor = None
        effective_env = self._effective_env(env)
        execution_options = self._resolve_query_options(
            options,
            permission_mode=permission_mode,
            timeout_ms=timeout_ms,
            max_rows=max_rows,
            max_bytes=max_bytes,
        )

        try:
            validated = self.validation_service.validate_query_request(
                connection_name,
                sql,
                permission_mode=execution_options.permission_mode,
                timeout_ms=execution_options.timeout_ms,
                max_rows=execution_options.max_rows,
                max_bytes=execution_options.max_bytes,
                dialect=dialect,
            )
            execution_options = self._execution_options_from_validation(validated, fallback=execution_options)
            connection_descriptor = self.registry.describe_connection(connection_name)
            adapter = self.registry.get_adapter(connection_name, env=effective_env)
            adapter_result = adapter.explain_query(validated.sql, dict(params or {}), execution_options)
            normalized_result = self._normalize_explain_result(
                adapter_result,
                connection_name=connection_name,
                backend_type=connection_descriptor.type,
                fallback_statement_type=self._statement_type_from_analysis(getattr(validated, "analysis", None), explain=True),
                source_query=validated.sql,
            )
        except Exception as exc:
            error = exc if isinstance(exc, DbMcpError) else normalize_exception(exc)
            self._audit_failure(
                "explain_query",
                operation="explain_query",
                connection_name=connection_name,
                request_id=request_id,
                actor=actor,
                started=started,
                validation=validated,
                connection_descriptor=connection_descriptor,
                error=error,
            )
            raise error from exc

        self._audit_success(
            "explain_query",
            operation="explain_query",
            connection_name=connection_name,
            request_id=request_id,
            actor=actor,
            started=started,
            validation=validated,
            connection_descriptor=connection_descriptor,
            result=normalized_result,
        )
        return normalized_result

    def _resolve_query_options(
        self,
        options: QueryOptions | None,
        *,
        permission_mode: PermissionMode | None,
        timeout_ms: int | None,
        max_rows: int | None,
        max_bytes: int | None,
    ) -> QueryOptions:
        base = options.model_dump() if options is not None else {}
        return QueryOptions(
            permission_mode=permission_mode if permission_mode is not None else base.get("permission_mode"),
            timeout_ms=timeout_ms if timeout_ms is not None else base.get("timeout_ms"),
            max_rows=max_rows if max_rows is not None else base.get("max_rows"),
            max_bytes=max_bytes if max_bytes is not None else base.get("max_bytes"),
            allow_multiple_statements=base.get("allow_multiple_statements"),
        )

    def _execution_options_from_validation(self, validated: Any, *, fallback: QueryOptions) -> QueryOptions:
        limits = getattr(validated, "limits", None)
        return QueryOptions(
            permission_mode=self._policy_detail(getattr(validated, "policy", None), "permission_mode")
            or fallback.permission_mode,
            timeout_ms=self._coerce_int(getattr(limits, "timeout_ms", None), default=fallback.timeout_ms),
            max_rows=self._coerce_int(getattr(limits, "max_rows", None), default=fallback.max_rows),
            max_bytes=self._coerce_int(getattr(limits, "max_bytes", None), default=fallback.max_bytes),
            allow_multiple_statements=self._policy_detail(getattr(validated, "policy", None), "allow_multiple_statements")
            if self._policy_detail(getattr(validated, "policy", None), "allow_multiple_statements") is not None
            else fallback.allow_multiple_statements,
        )

    def _normalize_query_result(
        self,
        value: Any,
        *,
        connection_name: str,
        backend_type: str | None,
        fallback_statement_type: str | None,
    ) -> QueryResult:
        payload = self._payload_from_value(value)
        columns = self._normalize_columns(payload.get("columns"))
        rows = self.result_formatter.normalize_rows(payload.get("rows"), columns=[column.name for column in columns])
        warnings = self._normalize_warnings(payload.get("warnings"))
        backend_metadata = self._normalize_backend_metadata(payload.get("backend_metadata"), backend_type=backend_type)
        statement_type = self._coerce_text(payload.get("statement_type")) or self._coerce_text(backend_metadata.get("statement_type")) or fallback_statement_type
        query_id = self._coerce_text(payload.get("query_id")) or self._coerce_text(backend_metadata.get("query_id"))

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=self._coerce_int(payload.get("row_count"), default=len(rows)),
            truncated=bool(payload.get("truncated", False)),
            elapsed_ms=self._coerce_float(payload.get("elapsed_ms")),
            warnings=warnings,
            query_id=query_id,
            statement_type=statement_type,
            backend_metadata=backend_metadata,
        )

    def _normalize_explain_result(
        self,
        value: Any,
        *,
        connection_name: str,
        backend_type: str | None,
        fallback_statement_type: str | None,
        source_query: str,
    ) -> ExplainResult:
        payload = self._payload_from_value(value)
        query_result = self._normalize_query_result(
            value,
            connection_name=connection_name,
            backend_type=backend_type,
            fallback_statement_type=fallback_statement_type,
        )

        plan_text = self._coerce_text(
            payload.get("plan_text")
            if "plan_text" in payload
            else payload.get("plan")
            if "plan" in payload
            else None
        )
        if plan_text is None and query_result.rows:
            plan_text = self._rows_to_text(query_result.rows)

        return ExplainResult(
            **query_result.model_dump(exclude_computed_fields=True),
            plan_text=plan_text,
            plan_format=self._coerce_plan_format(payload.get("plan_format")),
            source_query=self._coerce_text(payload.get("source_query")) or source_query,
        )

    def _normalize_columns(self, columns: Any) -> list[ColumnInfo]:
        if columns is None:
            return []

        normalized: list[ColumnInfo] = []
        for index, column in enumerate(self._ensure_sequence(columns), start=1):
            if isinstance(column, ColumnInfo):
                normalized.append(column)
                continue

            mapping = self._payload_from_value(column)
            normalized.append(
                ColumnInfo(
                    catalog=self._coerce_text(mapping.get("catalog")),
                    schema=self._coerce_text(mapping.get("schema")),
                    table=self._coerce_text(mapping.get("table")),
                    name=self._coerce_text(
                        mapping.get("name")
                        or mapping.get("column_name")
                        or mapping.get("columnName")
                        or mapping.get("label")
                    )
                    or f"column_{index}",
                    data_type=self._coerce_text(
                        mapping.get("data_type")
                        or mapping.get("dataType")
                        or mapping.get("type")
                        or mapping.get("db_type")
                        or mapping.get("dbType")
                    ),
                    ordinal_position=self._coerce_int(
                        mapping.get("ordinal_position")
                        or mapping.get("ordinalPosition")
                        or mapping.get("position")
                        or index,
                        default=index,
                    ),
                    nullable=self._coerce_bool(mapping.get("nullable") or mapping.get("is_nullable") or mapping.get("isNullable")),
                    default=self._coerce_text(mapping.get("default") or mapping.get("default_value") or mapping.get("defaultValue")),
                    description=self._coerce_text(mapping.get("description") or mapping.get("comment")),
                    length=self._coerce_int(mapping.get("length") or mapping.get("display_size") or mapping.get("displaySize")),
                    precision=self._coerce_int(mapping.get("precision")),
                    scale=self._coerce_int(mapping.get("scale")),
                    backend_metadata=self._normalize_backend_metadata(
                        mapping.get("backend_metadata"),
                        backend_type=self._coerce_text(mapping.get("backend_type")),
                    ),
                )
            )
        return normalized

    def _normalize_warnings(self, warnings: Any) -> list[ResultWarning]:
        if warnings is None:
            return []

        normalized: list[ResultWarning] = []
        for warning in self._ensure_sequence(warnings):
            if isinstance(warning, ResultWarning):
                normalized.append(warning)
                continue
            if isinstance(warning, TruncationWarning):
                normalized.append(warning)
                continue

            mapping = self._payload_from_value(warning)
            message = self._coerce_text(mapping.get("message") or mapping.get("warning") or mapping.get("detail") or mapping.get("description"))
            if message is None:
                message = str(warning)
            code = self._coerce_text(mapping.get("code") or mapping.get("warning_code") or mapping.get("warningCode")) or "WARNING"
            details = self._collect_details(
                mapping,
                exclude={
                    "code",
                    "warning_code",
                    "warningCode",
                    "message",
                    "warning",
                    "detail",
                    "description",
                },
            )
            if self._coerce_text(mapping.get("limit_type")) is not None:
                normalized.append(
                    TruncationWarning(
                        message=message,
                        details=details,
                        limit_type=self._coerce_text(mapping.get("limit_type")),
                        limit=self._coerce_int(mapping.get("limit")),
                        actual=self._coerce_int(mapping.get("actual")),
                        truncated_rows=self._coerce_int(mapping.get("truncated_rows")),
                        truncated_bytes=self._coerce_int(mapping.get("truncated_bytes")),
                    )
                )
                continue

            normalized.append(ResultWarning(code=code, message=message, details=details))
        return normalized

    def _normalize_backend_metadata(self, metadata: Any, *, backend_type: str | None) -> dict[str, Any]:
        normalized = self.result_formatter.normalize_backend_metadata(metadata, backend_type=backend_type)
        return normalized.as_dict()

    def _audit_success(
        self,
        action: str,
        *,
        connection_name: str,
        request_id: str | None,
        actor: str | None,
        started: float,
        validation: Any,
        connection_descriptor: Any,
        result: QueryResult | ExplainResult,
        operation: str,
    ) -> None:
        self.audit_service.success(
            action,
            actor=actor,
            resource=connection_name,
            request_id=request_id,
            duration_ms=(perf_counter() - started) * 1000.0,
            details=self._audit_details(
                connection_name=connection_name,
                validation=validation,
                connection_descriptor=connection_descriptor,
                result=result,
                outcome="success",
                operation=operation,
            ),
        )

    def _audit_failure(
        self,
        action: str,
        *,
        connection_name: str,
        request_id: str | None,
        actor: str | None,
        started: float,
        validation: Any,
        connection_descriptor: Any,
        error: DbMcpError,
        operation: str,
    ) -> None:
        self.audit_service.failure(
            action,
            actor=actor,
            resource=connection_name,
            request_id=request_id,
            duration_ms=(perf_counter() - started) * 1000.0,
            details=self._audit_details(
                connection_name=connection_name,
                validation=validation,
                connection_descriptor=connection_descriptor,
                error=error,
                outcome="failure",
                operation=operation,
            ),
        )

    def _audit_details(
        self,
        *,
        connection_name: str,
        validation: Any,
        connection_descriptor: Any,
        result: QueryResult | ExplainResult | None = None,
        error: DbMcpError | None = None,
        outcome: str,
        operation: str,
    ) -> dict[str, Any]:
        analysis = getattr(validation, "analysis", None)
        policy = getattr(validation, "policy", None)
        details: dict[str, Any] = {
            "tool": "query_service",
            "operation": operation,
            "connection_name": connection_name,
            "connection_type": self._coerce_text(getattr(connection_descriptor, "type", None)),
            "statement_type": self._coerce_text(getattr(result, "statement_type", None))
            or self._statement_type_from_analysis(analysis),
            "sql_kind": self._coerce_text(getattr(analysis, "kind", None).value if analysis is not None else None),
            "permission_mode": self._policy_detail(policy, "permission_mode"),
            "policy": self._policy_payload(policy),
            "outcome": outcome,
        }
        if result is not None:
            details.update(
                {
                    "row_count": result.row_count,
                    "truncated": result.truncated,
                    "elapsed_ms": result.elapsed_ms,
                }
            )
        if error is not None:
            details["error"] = error.to_dict()
        return {key: value for key, value in details.items() if value is not None}

    def _policy_payload(self, policy: Any) -> dict[str, Any] | None:
        if policy is None:
            return None
        return {
            "allowed": getattr(policy, "allowed", None),
            "reason": self._coerce_text(getattr(getattr(policy, "reason", None), "value", None)),
            "message": self._coerce_text(getattr(policy, "message", None)),
            "details": self._collect_details(getattr(policy, "details", {}) or {}, exclude=set()),
        }

    def _policy_detail(self, policy: Any, name: str) -> Any:
        if policy is None:
            return None
        details = getattr(policy, "details", None)
        if isinstance(details, Mapping):
            return details.get(name)
        return None

    def _statement_type_from_analysis(self, analysis: Any, *, explain: bool = False) -> str | None:
        if explain:
            return "EXPLAIN"
        statements = getattr(analysis, "statements", None)
        if not statements:
            return self._coerce_text(getattr(getattr(analysis, "kind", None), "value", None))
        first_statement = statements[0]
        statement_name = type(first_statement).__name__.upper()
        return statement_name or self._coerce_text(getattr(getattr(analysis, "kind", None), "value", None))

    def _effective_env(self, env: Mapping[str, str] | None) -> Mapping[str, str] | None:
        if env is None:
            return self._env or None
        if not self._env:
            return dict(env)
        merged = dict(self._env)
        merged.update(env)
        return merged

    def _payload_from_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
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

    def _ensure_sequence(self, value: Any) -> Sequence[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return value
        return [value]

    def _rows_to_text(self, rows: Sequence[Sequence[Any]]) -> str | None:
        if not rows:
            return None
        lines = ["\t".join("" if cell is None else str(cell) for cell in row) for row in rows]
        text = "\n".join(line for line in lines if line)
        return text or None

    def _coerce_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_int(self, value: Any, *, default: int | None = None) -> int | None:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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

    def _coerce_plan_format(self, value: Any) -> str:
        text = self._coerce_text(value)
        if text in {"text", "table", "json"}:
            return text
        return "text"


__all__ = ["QueryService"]
