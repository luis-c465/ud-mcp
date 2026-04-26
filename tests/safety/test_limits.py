from __future__ import annotations

import pytest

from db_mcp_server.config.models import DefaultsConfig
from db_mcp_server.safety.limits import resolve_query_limits, truncate_bytes, truncate_sequence


def test_resolve_query_limits_uses_defaults_and_overrides() -> None:
    defaults = DefaultsConfig(timeout_ms=10_000, max_rows=25, max_bytes=128)

    resolved = resolve_query_limits(defaults, timeout_ms=2_500, max_rows=None, max_bytes=64)

    assert resolved.timeout_ms == 2_500
    assert resolved.max_rows == 25
    assert resolved.max_bytes == 64


@pytest.mark.parametrize(
    ("items", "max_rows", "expected_data", "expected_truncated"),
    [
        ([1, 2, 3], 5, [1, 2, 3], False),
        ([1, 2, 3, 4], 2, [1, 2], True),
    ],
)
def test_truncate_sequence_returns_data_and_metadata(
    items: list[int],
    max_rows: int,
    expected_data: list[int],
    expected_truncated: bool,
) -> None:
    result = truncate_sequence(items, max_rows)

    assert result.data == expected_data
    assert (result.truncation is not None) is expected_truncated

    if expected_truncated:
        assert result.truncation is not None
        assert result.truncation.truncated is True
        assert result.truncation.reason == "max_rows_exceeded"
        assert result.truncation.limit_name == "max_rows"
        assert result.truncation.limit_value == max_rows
        assert result.truncation.original_count == len(items)
        assert result.truncation.returned_count == len(expected_data)
    else:
        assert result.truncation is None


@pytest.mark.parametrize(
    ("data", "max_bytes", "expected_data", "expected_truncated"),
    [
        (b"abcdef", 10, b"abcdef", False),
        (b"abcdef", 3, b"abc", True),
        ("abcdef", 4, "abcd", True),
    ],
)
def test_truncate_bytes_returns_data_and_metadata(
    data: bytes | str,
    max_bytes: int,
    expected_data: bytes | str,
    expected_truncated: bool,
) -> None:
    result = truncate_bytes(data, max_bytes)

    assert result.data == expected_data
    assert (result.truncation is not None) is expected_truncated

    if expected_truncated:
        assert result.truncation is not None
        assert result.truncation.truncated is True
        assert result.truncation.reason == "max_bytes_exceeded"
        assert result.truncation.limit_name == "max_bytes"
        assert result.truncation.limit_value == max_bytes
        assert result.truncation.returned_bytes == len(expected_data)
        if isinstance(data, bytes):
            assert result.truncation.original_bytes == len(data)
        else:
            assert result.truncation.original_bytes == len(data.encode("utf-8"))
    else:
        assert result.truncation is None
