"""Connection lookup and adapter factory helpers."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db_mcp_server.adapters.base import DatabaseAdapter
from db_mcp_server.config.models import Config, ConnectionConfig, ConnectionConfigBase
from db_mcp_server.config.secrets import resolve_env_secret_values, secret_refs_from_mapping
from db_mcp_server.models.connection import ConnectionDescriptor
from db_mcp_server.safety.errors import BackendError, ConnectionFailedError, UnknownConnectionError, normalize_exception


class ResolvedConnection(BaseModel):
    """Configuration and resolved secrets for adapter construction."""

    model_config = ConfigDict(extra="forbid")

    name: str
    config: ConnectionConfig
    secrets: dict[str, str] = Field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.config.type


AdapterFactory = Callable[..., DatabaseAdapter]


class ConnectionRegistry:
    """Resolve configured connections and build backend adapters lazily."""

    def __init__(
        self,
        config: Config | Mapping[str, ConnectionConfig],
        *,
        adapter_factories: Mapping[str, AdapterFactory] | None = None,
    ) -> None:
        if isinstance(config, Mapping):
            self._config = Config(connections=dict(config))
        else:
            self._config = config
        self._adapter_factories = dict(adapter_factories or {})

    @property
    def config(self) -> Config:
        return self._config

    def list_connections(self) -> list[ConnectionDescriptor]:
        """Return safe summaries for all configured connections."""

        return [self._descriptor_from_config(name, connection) for name, connection in self._config.connections.items()]

    def connection_names(self) -> list[str]:
        return list(self._config.connections)

    def get_connection(self, name: str) -> ConnectionConfig:
        """Fetch a configured connection by name."""

        return self._get_connection_config(name)

    def get_connection_config(self, name: str) -> ConnectionConfig:
        """Compatibility alias for :meth:`get_connection`."""

        return self.get_connection(name)

    def describe_connection(self, name: str) -> ConnectionDescriptor:
        """Return a safe, backend-neutral summary for one connection."""

        connection = self._get_connection_config(name)
        return self._descriptor_from_config(name, connection)

    def resolve_secrets(
        self,
        name: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Resolve environment-backed secrets for a connection."""

        connection = self._get_connection_config(name)
        secret_refs = secret_refs_from_mapping(connection.model_dump(by_alias=True, exclude_none=True))
        return resolve_env_secret_values(secret_refs, connection_name=name, env=env)

    def resolve_connection(
        self,
        name: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> ResolvedConnection:
        """Return the connection config together with resolved secret values."""

        connection = self._get_connection_config(name)
        secrets = self.resolve_secrets(name, env=env)
        return ResolvedConnection(name=name, config=connection, secrets=secrets)

    def create_adapter(
        self,
        name: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> DatabaseAdapter:
        """Instantiate the backend adapter for a configured connection."""

        resolved = self.resolve_connection(name, env=env)
        factory = self._get_adapter_factory(resolved.config.type)
        try:
            adapter = self._invoke_factory(factory, resolved)
        except UnknownConnectionError:
            raise
        except Exception as exc:  # pragma: no cover - backend specific failure path
            raise normalize_exception(
                exc,
                message=f"Failed to create adapter for connection {name!r}.",
                details={"connection_name": name, "backend_type": resolved.config.type},
            ) from exc

        if not isinstance(adapter, DatabaseAdapter):
            raise BackendError(
                f"Adapter factory for connection {name!r} returned an invalid object.",
                details={"connection_name": name, "backend_type": resolved.config.type},
            )
        return adapter

    def get_adapter(
        self,
        name: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> DatabaseAdapter:
        """Compatibility alias for :meth:`create_adapter`."""

        return self.create_adapter(name, env=env)

    def _get_connection_config(self, name: str) -> ConnectionConfig:
        try:
            return self._config.connections[name]
        except KeyError as exc:
            raise UnknownConnectionError(
                f"Unknown connection {name!r}.",
                details={"connection_name": name},
                cause=exc,
            ) from exc

    def _descriptor_from_config(self, name: str, connection: ConnectionConfigBase) -> ConnectionDescriptor:
        return ConnectionDescriptor(
            name=name,
            backend_type=connection.type,
            description=connection.description,
            read_only=connection.read_only,
            allow_full_permissions=connection.allow_full_permissions,
        )

    def _get_adapter_factory(self, backend_type: str) -> AdapterFactory:
        if backend_type in self._adapter_factories:
            return self._adapter_factories[backend_type]
        return _load_adapter_factory(backend_type)

    def _invoke_factory(self, factory: AdapterFactory, resolved: ResolvedConnection) -> DatabaseAdapter:
        attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
            ((), {"config": resolved.config, "secrets": resolved.secrets, "connection_name": resolved.name}),
            ((resolved.config,), {}),
            ((resolved.name, resolved.config, resolved.secrets), {}),
            ((resolved.name, resolved.config), {}),
            ((resolved.config, resolved.secrets), {}),
            (
                (),
                {
                    **resolved.config.model_dump(by_alias=True, exclude_none=True),
                    **resolved.secrets,
                    "connection_name": resolved.name,
                },
            ),
        )

        last_error: Exception | None = None
        for args, kwargs in attempts:
            try:
                adapter = factory(*args, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue

            if inspect.isclass(adapter):
                try:
                    adapter = adapter(**kwargs) if kwargs else adapter(*args)
                except TypeError as exc:
                    last_error = exc
                    continue
            return adapter

        raise ConnectionFailedError(
            f"Could not instantiate adapter for connection {resolved.name!r}.",
            details={"connection_name": resolved.name, "backend_type": resolved.config.type},
            cause=last_error,
        )


@lru_cache(maxsize=None)
def _load_adapter_factory(backend_type: str) -> AdapterFactory:
    module_name = _ADAPTER_MODULES.get(backend_type)
    if module_name is None:
        raise BackendError(
            f"Unsupported backend type {backend_type!r}.",
            details={"backend_type": backend_type},
        )

    module = importlib.import_module(module_name)
    factory = _find_factory_in_module(module, backend_type)
    if factory is None:
        raise BackendError(
            f"No adapter factory found for backend type {backend_type!r}.",
            details={"backend_type": backend_type, "module": module_name},
        )
    return factory


def _find_factory_in_module(module: Any, backend_type: str) -> AdapterFactory | None:
    candidate_names = tuple(_ADAPTER_FACTORY_NAMES.get(backend_type, ()))
    for name in candidate_names:
        factory = getattr(module, name, None)
        if callable(factory):
            return factory

    for name, value in vars(module).items():
        if not callable(value):
            continue
        lowered = name.lower()
        if "adapter" in lowered or lowered.startswith("create_") or lowered.startswith("build_"):
            return value
    return None


_ADAPTER_MODULES: dict[str, str] = {
    "sqlserver": "db_mcp_server.adapters.sqlserver",
    "snowflake": "db_mcp_server.adapters.snowflake",
    "databricks": "db_mcp_server.adapters.databricks",
}

_ADAPTER_FACTORY_NAMES: dict[str, tuple[str, ...]] = {
    "sqlserver": ("SqlServerAdapter", "SQLServerAdapter", "create_adapter", "build_adapter"),
    "snowflake": ("SnowflakeAdapter", "create_adapter", "build_adapter"),
    "databricks": ("DatabricksAdapter", "DatabricksSqlAdapter", "create_adapter", "build_adapter"),
}


__all__ = [
    "AdapterFactory",
    "ConnectionDescriptor",
    "ConnectionRegistry",
    "DatabaseAdapter",
    "ResolvedConnection",
]
