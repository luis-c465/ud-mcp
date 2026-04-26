"""Policy enforcement helpers for SQL and metadata access."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..config.models import ConnectionConfigBase, DefaultsConfig, PermissionMode
from .errors import QueryBlockedError
from .sql_parser import SqlAnalysis, parse_sql


class PolicyReason(StrEnum):
    """Machine-readable reasons for a policy decision."""

    MULTI_STATEMENT_NOT_ALLOWED = "multi_statement_not_allowed"
    DESTRUCTIVE_SQL_BLOCKED = "destructive_sql_blocked"
    FULL_PERMISSION_REQUIRED = "full_permission_required"
    READ_ONLY_CONNECTION = "read_only_connection"
    INVALID_SQL = "invalid_sql"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Structured policy outcome."""

    allowed: bool
    reason: PolicyReason | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def raise_forbidden(self) -> None:
        """Raise a typed policy error when the decision is not allowed."""

        if self.allowed:
            return
        payload = dict(self.details)
        if self.reason is not None:
            payload.setdefault("reason", self.reason.value)
        raise QueryBlockedError(self.message or "Query blocked by policy", details=payload)


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """Combined parsed SQL and policy decision."""

    analysis: SqlAnalysis
    decision: PolicyDecision

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    @property
    def reason(self) -> PolicyReason | None:
        return self.decision.reason

    @property
    def message(self) -> str:
        return self.decision.message

    @property
    def details(self) -> dict[str, Any]:
        return self.decision.details

    def raise_forbidden(self) -> None:
        self.decision.raise_forbidden()


class PolicyEngine:
    """Policy engine that gates SQL and metadata access."""

    def __init__(self, defaults: DefaultsConfig) -> None:
        self._defaults = defaults

    @property
    def defaults(self) -> DefaultsConfig:
        return self._defaults

    def evaluate_query(
        self,
        sql: str,
        *,
        connection: ConnectionConfigBase,
        permission_mode: PermissionMode | None = None,
        allow_multiple_statements: bool | None = None,
        block_destructive_sql: bool | None = None,
        dialect: str | None = None,
    ) -> PolicyEvaluation:
        """Parse and evaluate a SQL query against the configured policy."""

        analysis = parse_sql(sql, dialect=dialect)
        decision = self.evaluate_analysis(
            analysis,
            connection=connection,
            permission_mode=permission_mode,
            allow_multiple_statements=allow_multiple_statements,
            block_destructive_sql=block_destructive_sql,
        )
        return PolicyEvaluation(analysis=analysis, decision=decision)

    def evaluate_analysis(
        self,
        analysis: SqlAnalysis,
        *,
        connection: ConnectionConfigBase,
        permission_mode: PermissionMode | None = None,
        allow_multiple_statements: bool | None = None,
        block_destructive_sql: bool | None = None,
    ) -> PolicyDecision:
        """Evaluate an existing SQL analysis payload."""

        resolved_permission_mode = permission_mode or self._defaults.permission_mode
        resolved_allow_multiple = (
            self._defaults.allow_multiple_statements
            if allow_multiple_statements is None
            else allow_multiple_statements
        )
        resolved_block_destructive = (
            self._defaults.block_destructive_sql
            if block_destructive_sql is None
            else block_destructive_sql
        )

        details = _base_details(
            analysis,
            connection=connection,
            permission_mode=resolved_permission_mode,
            allow_multiple_statements=resolved_allow_multiple,
            block_destructive_sql=resolved_block_destructive,
        )

        if not analysis.is_single_statement and not resolved_allow_multiple:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.MULTI_STATEMENT_NOT_ALLOWED,
                message="Multiple SQL statements are not allowed",
                details=details,
            )

        if resolved_permission_mode == "readonly" and analysis.has_destructive:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.DESTRUCTIVE_SQL_BLOCKED,
                message="Destructive SQL is not allowed in readonly mode",
                details=details,
            )

        if analysis.has_destructive and resolved_block_destructive:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.DESTRUCTIVE_SQL_BLOCKED,
                message="Destructive SQL is blocked by policy",
                details=details,
            )

        if resolved_permission_mode == "full" and not connection.allow_full_permissions:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.FULL_PERMISSION_REQUIRED,
                message="Full permissions are not allowed for this connection",
                details=details,
            )

        if resolved_permission_mode == "full" and connection.read_only:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.READ_ONLY_CONNECTION,
                message="Connection is read-only",
                details=details,
            )

        return PolicyDecision(allowed=True, details=details)

    def evaluate_metadata_request(
        self,
        *,
        connection: ConnectionConfigBase,
        permission_mode: PermissionMode | None = None,
        operation: str = "metadata",
    ) -> PolicyDecision:
        """Evaluate a metadata request before any adapter call is made."""

        resolved_permission_mode = permission_mode or self._defaults.permission_mode
        details: dict[str, Any] = {
            "operation": operation,
            "permission_mode": resolved_permission_mode,
            "connection_read_only": connection.read_only,
            "connection_allow_full_permissions": connection.allow_full_permissions,
        }

        if resolved_permission_mode == "full" and not connection.allow_full_permissions:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.FULL_PERMISSION_REQUIRED,
                message="Full permissions are not allowed for this connection",
                details=details,
            )

        if resolved_permission_mode == "full" and connection.read_only:
            return PolicyDecision(
                allowed=False,
                reason=PolicyReason.READ_ONLY_CONNECTION,
                message="Connection is read-only",
                details=details,
            )

        return PolicyDecision(allowed=True, details=details)


def _base_details(
    analysis: SqlAnalysis,
    *,
    connection: ConnectionConfigBase,
    permission_mode: PermissionMode,
    allow_multiple_statements: bool,
    block_destructive_sql: bool,
) -> dict[str, Any]:
    return {
        "statement_count": analysis.statement_count,
        "is_single_statement": analysis.is_single_statement,
        "is_multi_statement": analysis.is_multi_statement,
        "sql_kind": analysis.kind.value,
        "statement_kinds": [kind.value for kind in analysis.statement_kinds],
        "has_read_only": analysis.has_read_only,
        "has_explain_like": analysis.has_explain_like,
        "has_destructive": analysis.has_destructive,
        "permission_mode": permission_mode,
        "allow_multiple_statements": allow_multiple_statements,
        "block_destructive_sql": block_destructive_sql,
        "connection_read_only": connection.read_only,
        "connection_allow_full_permissions": connection.allow_full_permissions,
    }


__all__ = [
    "PolicyDecision",
    "PolicyEngine",
    "PolicyEvaluation",
    "PolicyReason",
]