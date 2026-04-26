from __future__ import annotations

from db_mcp_server.services.result_formatter import ResultColumn, ResultFormatter, ResultWarning


def test_result_formatter_normalizes_query_payloads() -> None:
    formatter = ResultFormatter()

    result = formatter.format_query_result(
        columns=[
            {"name": "id", "type": "INTEGER", "nullable": False, "display_size": "10", "backend_type": "driver", "source": "native"},
            "name",
        ],
        rows=[
            {"id": 1, "name": "Alice"},
            (2, "Bob"),
        ],
        warnings=[
            {"message": "truncated", "code": "WARN_TRUNCATED", "extra": True},
            "plain warning",
        ],
        backend_metadata={
            "backend": "sqlserver",
            "queryId": "abc-123",
            "statementType": "SELECT",
            "extra": "value",
        },
        elapsed_ms=12,
        truncated=True,
        connection_name="primary",
        statement_type="SELECT",
        backend_type="sqlserver",
    )

    assert result.row_count == 2
    assert result.truncated is True
    assert result.elapsed_ms == 12
    assert result.connection_name == "primary"
    assert result.statement_type == "SELECT"
    assert result.columns == [
        ResultColumn(
            name="id",
            type="INTEGER",
            nullable=False,
            display_size=10,
            backend_metadata={"backend_type": "driver", "source": "native"},
        ),
        ResultColumn(name="name"),
    ]
    assert result.rows == [[1, "Alice"], [2, "Bob"]]
    assert result.warnings == [
        ResultWarning(message="truncated", code="WARN_TRUNCATED", details={"extra": True}),
        ResultWarning(message="plain warning"),
    ]
    assert result.backend_metadata == {
        "backend_type": "sqlserver",
        "query_id": "abc-123",
        "statement_type": "SELECT",
        "extra": "value",
    }


def test_result_formatter_formats_explain_result() -> None:
    formatter = ResultFormatter()

    result = formatter.format_explain_result(
        plan={"steps": ["scan", "filter"]},
        warnings=["slow explain"],
        backend_metadata={"backend_type": "sqlserver", "statement_type": "EXPLAIN"},
        elapsed_ms=7,
        connection_name="primary",
    )

    assert result.plan == {"steps": ["scan", "filter"]}
    assert result.elapsed_ms == 7
    assert result.connection_name == "primary"
    assert result.statement_type == "EXPLAIN"
    assert result.warnings == [ResultWarning(message="slow explain")]
    assert result.backend_metadata == {"backend_type": "sqlserver", "statement_type": "EXPLAIN"}
