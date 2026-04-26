"""Structured audit event emission for service-layer actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from ..util.logging import emit_structured, get_logger, get_request_id
from ..util.redact import redact_string, redact_value


@dataclass(slots=True, frozen=True)
class AuditEvent:
    """A single structured audit event."""

    action: str
    status: str = "success"
    actor: str | None = None
    resource: str | None = None
    details: dict[str, Any] | None = None
    request_id: str | None = None
    duration_ms: float | None = None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a redacted, JSON-serializable payload."""

        payload: dict[str, Any] = {
            "action": self.action,
            "status": self.status,
            "timestamp": self.timestamp or datetime.now(tz=timezone.utc).isoformat(),
        }
        if self.actor is not None:
            payload["actor"] = redact_string(self.actor)
        if self.resource is not None:
            payload["resource"] = redact_string(self.resource)
        if self.details:
            payload["details"] = redact_value(self.details)
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        return payload


class AuditService:
    """Emit structured audit logs without leaking secrets."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or get_logger("db_mcp_server.audit")

    def emit(
        self,
        action: str,
        *,
        status: str = "success",
        actor: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
        level: int = logging.INFO,
    ) -> AuditEvent:
        """Emit a structured audit event and return the recorded payload."""

        event = AuditEvent(
            action=action,
            status=status,
            actor=actor,
            resource=resource,
            details=details,
            request_id=request_id or get_request_id(),
            duration_ms=duration_ms,
        )
        emit_structured(self._logger, "audit", level=level, **event.to_dict())
        return event

    def record(
        self,
        action: str,
        *,
        status: str = "success",
        actor: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
        level: int = logging.INFO,
    ) -> AuditEvent:
        """Alias for :meth:`emit` with a more audit-oriented name."""

        return self.emit(
            action,
            status=status,
            actor=actor,
            resource=resource,
            details=details,
            request_id=request_id,
            duration_ms=duration_ms,
            level=level,
        )

    def success(
        self,
        action: str,
        *,
        actor: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
    ) -> AuditEvent:
        """Record a successful audit event."""

        return self.emit(
            action,
            status="success",
            actor=actor,
            resource=resource,
            details=details,
            request_id=request_id,
            duration_ms=duration_ms,
            level=logging.INFO,
        )

    def failure(
        self,
        action: str,
        *,
        actor: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
    ) -> AuditEvent:
        """Record a failed audit event."""

        return self.emit(
            action,
            status="failure",
            actor=actor,
            resource=resource,
            details=details,
            request_id=request_id,
            duration_ms=duration_ms,
            level=logging.WARNING,
        )
