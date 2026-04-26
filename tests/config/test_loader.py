from __future__ import annotations

from pathlib import Path

import pytest

from db_mcp_server.config.loader import ConfigParseError, ConfigValidationError, load_config, load_config_text


def test_load_config_reads_yaml_file_and_validates_model(tmp_path: Path) -> None:
    config_path = tmp_path / "db-mcp.yaml"
    config_path.write_text(
        """
server:
  name: example-server
  transport: stdio
  log_level: debug
connections:
  primary:
    type: sqlserver
    description: Primary warehouse
    read_only: true
    allow_full_permissions: false
    dsn_env: PRIMARY_DSN
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.server.name == "example-server"
    assert config.server.transport == "stdio"
    assert config.server.log_level == "debug"
    assert list(config.connections) == ["primary"]
    connection = config.connections["primary"]
    assert connection.type == "sqlserver"
    assert connection.description == "Primary warehouse"
    assert connection.read_only is True
    assert connection.allow_full_permissions is False
    assert connection.dsn_env == "PRIMARY_DSN"


@pytest.mark.parametrize(
    ("text", "expected_error"),
    [
        ("[]", ConfigParseError),
        (
            """
connections:
  primary:
    type: sqlserver
    description: broken
""",
            ConfigValidationError,
        ),
    ],
)
def test_load_config_text_reports_invalid_top_level_or_schema(text: str, expected_error: type[Exception]) -> None:
    with pytest.raises(expected_error):
        load_config_text(text, source="inline-config")
