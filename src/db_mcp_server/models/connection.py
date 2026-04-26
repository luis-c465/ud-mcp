from __future__ import annotations

from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .result import ResultWarning

_MODEL_CONFIG: ClassVar[ConfigDict] = ConfigDict(extra="forbid", populate_by_name=True)


class ConnectionDescriptor(BaseModel):
    """Backend-neutral descriptor for a configured connection."""

    model_config = _MODEL_CONFIG

    name: str
    backend_type: str = Field(
        validation_alias=AliasChoices("backend_type", "type"),
        serialization_alias="backend_type",
    )
    description: str | None = None
    catalog: str | None = None
    schema_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    read_only: bool = True
    allow_full_permissions: bool = False
    object_type: str = "connection"
    backend_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.backend_type

    @property
    def schema(self) -> str | None:
        return self.schema_name


class ConnectionTestResult(BaseModel):
    """Normalized result returned when testing a connection."""

    model_config = _MODEL_CONFIG

    ok: bool
    connection: ConnectionDescriptor | None = None
    message: str | None = None
    error_code: str | None = None
    elapsed_ms: float | None = None
    warnings: list[ResultWarning] = Field(default_factory=list)
    backend_metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ConnectionDescriptor", "ConnectionTestResult"]
