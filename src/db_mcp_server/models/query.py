from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class QueryOptions(BaseModel):
    """Execution options applied by the adapter or service layer."""

    model_config = ConfigDict(extra="forbid")

    permission_mode: Literal["readonly", "full"] | None = None
    timeout_ms: int | None = None
    max_rows: int | None = None
    max_bytes: int | None = None
    allow_multiple_statements: bool | None = None


__all__ = ["QueryOptions"]
