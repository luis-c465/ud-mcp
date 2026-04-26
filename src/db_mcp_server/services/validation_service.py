"""Validation service used to gate requests before hitting adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config.models import ConnectionConfig, DatabaseConfig, PermissionMode
from ..safety.errors import UnknownConnectionError
from ..safety.limits import QueryLimits, resolve_query_limits
from ..safety.policies import PolicyDecision, PolicyEngine
from ..safety.sql_parser import SqlAnalysis, parse_sql


@dataclass(frozen=True, slots=True)
class ValidatedQueryRequest:
    """Validated query request ready for adapter execution."""

    connection_name: str
    connection: ConnectionConfig
    sql: str
    analysis: SqlAnalysis
    limits: QueryLimits
    policy: PolicyDecision


@dataclass(frozen=True, slots=True)
class ValidatedMetadataRequest:
    """Validated metadata request ready for adapter execution."""

    connection_name: str
    connection: ConnectionConfig
    operation: str
    policy: PolicyDecision


class ValidationService:
    """Validate requests using the configured safety policy and limits."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._policy_engine = PolicyEngine(config.defaults)

    @property
    def config(self) -> DatabaseConfig:
        return self._config

    def validate_query_request(
        self,
        connection_name: str,
        sql: str,
        *,
        permission_mode: PermissionMode | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
        max_bytes: int | None = None,
        dialect: str | None = None,
    ) -> ValidatedQueryRequest:
        """Validate a query request before the adapter is called."""

        connection = self._get_connection(connection_name)
        analysis = parse_sql(sql, dialect=dialect)
        decision = self._policy_engine.evaluate_analysis(
            analysis,
            connection=connection,
            permission_mode=permission_mode,
        )
        decision.raise_forbidden()
        limits = resolve_query_limits(
            self._config.defaults,
            timeout_ms=timeout_ms,
            max_rows=max_rows,
            max_bytes=max_bytes,
        )
        return ValidatedQueryRequest(
            connection_name=connection_name,
            connection=connection,
            sql=analysis.sql,
            analysis=analysis,
            limits=limits,
            policy=decision,
        )

    def validate_metadata_request(
        self,
        connection_name: str,
        operation: str,
        *,
        permission_mode: PermissionMode | None = None,
    ) -> ValidatedMetadataRequest:
        """Validate a metadata request before the adapter is called."""

        connection = self._get_connection(connection_name)
        decision = self._policy_engine.evaluate_metadata_request(
            connection=connection,
            permission_mode=permission_mode,
            operation=operation,
        )
        decision.raise_forbidden()
        return ValidatedMetadataRequest(
            connection_name=connection_name,
            connection=connection,
            operation=operation,
            policy=decision,
        )

    def validate_query(
        self,
        connection_name: str,
        sql: str,
        **kwargs: Any,
    ) -> ValidatedQueryRequest:
        """Compatibility wrapper around :meth:`validate_query_request`."""

        return self.validate_query_request(connection_name, sql, **kwargs)

    def validate_metadata(
        self,
        connection_name: str,
        operation: str,
        **kwargs: Any,
    ) -> ValidatedMetadataRequest:
        """Compatibility wrapper around :meth:`validate_metadata_request`."""

        return self.validate_metadata_request(connection_name, operation, **kwargs)

    def _get_connection(self, connection_name: str) -> ConnectionConfig:
        try:
            return self._config.connections[connection_name]
        except KeyError as exc:
            raise UnknownConnectionError(
                f"Unknown connection: {connection_name}",
                details={"connection_name": connection_name},
            ) from exc


__all__ = [
    "ValidatedMetadataRequest",
    "ValidatedQueryRequest",
    "ValidationService",
]
