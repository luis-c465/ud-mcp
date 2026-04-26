from __future__ import annotations

import pytest
from sqlglot import parse_one

from db_mcp_server.safety.sql_parser import (
    SqlStatementKind,
    classify_statement,
    is_single_statement,
    parse_sql,
)


@pytest.mark.parametrize(
    ("sql", "expected_kind"),
    [
        ("SELECT 1", SqlStatementKind.READ_ONLY),
        ("EXPLAIN SELECT 1", SqlStatementKind.EXPLAIN_LIKE),
        ("INSERT INTO demo VALUES (1)", SqlStatementKind.DESTRUCTIVE),
    ],
)
def test_classify_statement_recognizes_statement_kinds(sql: str, expected_kind: SqlStatementKind) -> None:
    statement = parse_one(sql)

    assert classify_statement(statement) is expected_kind


def test_parse_sql_detects_single_statement_and_classifies_read_only_sql() -> None:
    analysis = parse_sql("  SELECT 1 AS value  ")

    assert analysis.sql == "SELECT 1 AS value"
    assert analysis.statement_count == 1
    assert analysis.is_single_statement is True
    assert analysis.is_multi_statement is False
    assert analysis.kind is SqlStatementKind.READ_ONLY
    assert analysis.has_read_only is True
    assert analysis.has_explain_like is False
    assert analysis.has_destructive is False
    assert analysis.statement_kinds == (SqlStatementKind.READ_ONLY,)
    assert is_single_statement("SELECT 1 AS value") is True


def test_parse_sql_detects_multi_statement_sql() -> None:
    analysis = parse_sql("SELECT 1; SELECT 2")

    assert analysis.statement_count == 2
    assert analysis.is_single_statement is False
    assert analysis.is_multi_statement is True
    assert analysis.statement_kinds == (
        SqlStatementKind.READ_ONLY,
        SqlStatementKind.READ_ONLY,
    )
    assert analysis.kind is SqlStatementKind.READ_ONLY
    assert is_single_statement("SELECT 1; SELECT 2") is False
