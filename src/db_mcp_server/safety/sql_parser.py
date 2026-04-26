"""SQL parsing and classification helpers used by safety checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlglot import exp, parse

from .errors import InvalidSqlError


class SqlStatementKind(StrEnum):
    """Normalized top-level SQL categories."""

    READ_ONLY = "readonly"
    DESTRUCTIVE = "destructive"
    EXPLAIN_LIKE = "explain_like"
    OTHER = "other"


def _expression_types(*names: str) -> tuple[type[exp.Expression], ...]:
    """Return the subset of SQLGlot expression types available in this version."""

    types: list[type[exp.Expression]] = []
    for name in names:
        candidate = getattr(exp, name, None)
        if isinstance(candidate, type):
            types.append(candidate)
    return tuple(types)


_READ_ONLY_TYPES: Final[tuple[type[exp.Expression], ...]] = _expression_types(
    "Select",
    "Union",
    "Intersect",
    "Except",
    "Values",
    "Describe",
    "Show",
    "Explain",
)

_DESTRUCTIVE_TYPES: Final[tuple[type[exp.Expression], ...]] = _expression_types(
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Alter",
    "Drop",
    "Truncate",
)

_EXPLAIN_LIKE_TYPES: Final[tuple[type[exp.Expression], ...]] = _expression_types(
    "Explain",
    "Describe",
    "Show",
)


@dataclass(frozen=True, slots=True)
class SqlAnalysis:
    """Structured result produced after parsing a SQL string."""

    sql: str
    dialect: str | None
    statements: tuple[exp.Expression, ...]
    statement_kinds: tuple[SqlStatementKind, ...]
    statement_count: int
    is_single_statement: bool
    is_multi_statement: bool
    kind: SqlStatementKind
    has_read_only: bool
    has_explain_like: bool
    has_destructive: bool


def parse_sql(sql: str, *, dialect: str | None = None) -> SqlAnalysis:
    """Parse SQL into a typed analysis payload.

    The parser is intentionally conservative: invalid or empty SQL raises
    :class:`InvalidSqlError`, and the returned classification preserves both the
    per-statement kinds and the overall top-level kind.
    """

    raw_sql = sql.strip()
    if not raw_sql:
        raise InvalidSqlError("SQL is empty", details={"reason": "empty_sql"})

    try:
        statements = tuple(parse(raw_sql, read=dialect) if dialect else parse(raw_sql))
    except Exception as exc:  # pragma: no cover - exercised through parser behavior
        raise InvalidSqlError(
            "SQL could not be parsed",
            details={"reason": "parse_error", "dialect": dialect},
            cause=exc,
        ) from exc

    if not statements:
        raise InvalidSqlError("SQL is empty", details={"reason": "empty_sql"})

    statement_kinds = tuple(classify_statement(statement) for statement in statements)
    has_read_only = any(kind is SqlStatementKind.READ_ONLY for kind in statement_kinds)
    has_explain_like = any(kind is SqlStatementKind.EXPLAIN_LIKE for kind in statement_kinds)
    has_destructive = any(kind is SqlStatementKind.DESTRUCTIVE for kind in statement_kinds)

    return SqlAnalysis(
        sql=raw_sql,
        dialect=dialect,
        statements=statements,
        statement_kinds=statement_kinds,
        statement_count=len(statements),
        is_single_statement=len(statements) == 1,
        is_multi_statement=len(statements) > 1,
        kind=_aggregate_kind(statement_kinds),
        has_read_only=has_read_only,
        has_explain_like=has_explain_like,
        has_destructive=has_destructive,
    )


def classify_statement(statement: exp.Expression) -> SqlStatementKind:
    """Classify a parsed SQLGlot statement."""

    if isinstance(statement, _DESTRUCTIVE_TYPES):
        return SqlStatementKind.DESTRUCTIVE
    if isinstance(statement, _EXPLAIN_LIKE_TYPES):
        return SqlStatementKind.EXPLAIN_LIKE
    if isinstance(statement, _READ_ONLY_TYPES):
        return SqlStatementKind.READ_ONLY
    if isinstance(statement, getattr(exp, "Command", ())):
        command_name = str(getattr(statement, "name", "") or statement.text("this") or "").strip().upper()
        if command_name in {"EXPLAIN", "DESCRIBE", "DESC", "SHOW"}:
            return SqlStatementKind.EXPLAIN_LIKE
        if command_name in {"INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE"}:
            return SqlStatementKind.DESTRUCTIVE
    return SqlStatementKind.OTHER


def is_single_statement(sql: str, *, dialect: str | None = None) -> bool:
    """Return ``True`` when the SQL string parses to exactly one statement."""

    return parse_sql(sql, dialect=dialect).is_single_statement


def _aggregate_kind(statement_kinds: tuple[SqlStatementKind, ...]) -> SqlStatementKind:
    """Collapse per-statement kinds into a single top-level kind."""

    unique_kinds = set(statement_kinds)
    if unique_kinds == {SqlStatementKind.READ_ONLY}:
        return SqlStatementKind.READ_ONLY
    if unique_kinds == {SqlStatementKind.EXPLAIN_LIKE}:
        return SqlStatementKind.EXPLAIN_LIKE
    if SqlStatementKind.DESTRUCTIVE in unique_kinds:
        return SqlStatementKind.DESTRUCTIVE
    if unique_kinds == {SqlStatementKind.OTHER}:
        return SqlStatementKind.OTHER
    return SqlStatementKind.OTHER


__all__ = [
    "SqlAnalysis",
    "SqlStatementKind",
    "classify_statement",
    "is_single_statement",
    "parse_sql",
]