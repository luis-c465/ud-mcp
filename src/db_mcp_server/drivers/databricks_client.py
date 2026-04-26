from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from db_mcp_server.config.models import DatabricksConnectionConfig
from db_mcp_server.safety.errors import BackendError


_SECRET_FIELD_NAMES: tuple[str, str, str] = ("server_hostname", "http_path", "token")


def build_connection_kwargs(
    config: DatabricksConnectionConfig,
    secrets: Mapping[str, str],
    *,
    connection_name: str | None = None,
) -> dict[str, Any]:
    """Build ``databricks.sql.connect`` keyword arguments from resolved inputs."""

    server_hostname = _require_secret(secrets, "server_hostname", connection_name=connection_name)
    http_path = _require_secret(secrets, "http_path", connection_name=connection_name)
    access_token = _require_secret(
        secrets,
        "token",
        connection_name=connection_name,
        alternate_keys=("access_token",),
    )

    kwargs: dict[str, Any] = {
        "server_hostname": server_hostname,
        "http_path": http_path,
        "access_token": access_token,
    }

    if config.catalog is not None:
        kwargs["catalog"] = config.catalog
    if config.schema_ is not None:
        kwargs["schema"] = config.schema_

    return kwargs


def create_connection(
    config: DatabricksConnectionConfig,
    secrets: Mapping[str, str],
    *,
    connection_name: str | None = None,
):
    """Create a native Databricks SQL connector connection."""

    try:
        from databricks import sql
    except ImportError as exc:  # pragma: no cover - dependency availability is environment specific
        raise BackendError(
            "The databricks-sql-connector package is not installed.",
            details={"backend_type": "databricks", "package": "databricks-sql-connector"},
            cause=exc,
        ) from exc

    return sql.connect(**build_connection_kwargs(config, secrets, connection_name=connection_name))


@dataclass(slots=True)
class DatabricksClient:
    """Lightweight wrapper around resolved Databricks SQL connection inputs."""

    config: DatabricksConnectionConfig
    secrets: Mapping[str, str]
    connection_name: str | None = None

    def connection_kwargs(self) -> dict[str, Any]:
        return build_connection_kwargs(self.config, self.secrets, connection_name=self.connection_name)

    def connect(self):
        return create_connection(self.config, self.secrets, connection_name=self.connection_name)


def create_client(
    config: DatabricksConnectionConfig,
    secrets: Mapping[str, str],
    *,
    connection_name: str | None = None,
) -> DatabricksClient:
    """Return a client wrapper that opens per-request Databricks SQL connections."""

    return DatabricksClient(config=config, secrets=dict(secrets), connection_name=connection_name)


def _require_secret(
    secrets: Mapping[str, str],
    field_name: str,
    *,
    connection_name: str | None = None,
    alternate_keys: tuple[str, ...] = (),
) -> str:
    for key in (field_name, *alternate_keys):
        value = secrets.get(key)
        if value is not None and value != "":
            return value

    raise BackendError(
        f"Missing resolved Databricks secret for field {field_name!r}.",
        details={
            "backend_type": "databricks",
            "connection_name": connection_name,
            "field_name": field_name,
            "expected_fields": [field_name, *alternate_keys],
        },
    )


__all__ = [
    "DatabricksClient",
    "build_connection_kwargs",
    "create_client",
    "create_connection",
]
