from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .metadata import ColumnInfo


class ResultWarning(BaseModel):
    """Structured warning emitted during execution or normalization."""

    model_config = ConfigDict(extra="forbid")

    code: str = "warning"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TruncationWarning(ResultWarning):
    """Warning that a result set was truncated to fit configured limits."""

    code: Literal["truncation"] = "truncation"
    limit_type: Literal["rows", "bytes", "cells"] | None = None
    limit: int | None = None
    actual: int | None = None
    truncated_rows: int | None = None
    truncated_bytes: int | None = None


class QueryResult(BaseModel):
    """Normalized row-oriented result returned by run_query."""

    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnInfo] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float | None = None
    warnings: list[ResultWarning] = Field(default_factory=list)
    query_id: str | None = None
    statement_type: str | None = None
    connection_name: str | None = None
    backend_metadata: dict[str, Any] = Field(default_factory=dict)


class ExplainResult(QueryResult):
    """Normalized result returned by explain_query."""

    plan_text: str | None = None
    plan_format: Literal["text", "table", "json"] = "text"
    source_query: str | None = None

    @computed_field
    @property
    def plan(self) -> Any:
        if self.plan_format == "json" and self.plan_text is not None:
            try:
                return json.loads(self.plan_text)
            except json.JSONDecodeError:
                return self.plan_text
        return self.plan_text


__all__ = ["ExplainResult", "QueryResult", "ResultWarning", "TruncationWarning"]
