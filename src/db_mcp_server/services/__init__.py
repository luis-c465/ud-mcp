"""Service-layer helpers for the db-mcp-server package."""

from .connection_registry import AdapterFactory, ConnectionDescriptor, ConnectionRegistry, DatabaseAdapter, ResolvedConnection
from .metadata_service import MetadataService, SchemaInfo, TableColumnInfo, TableDescription, TableInfo
from .result_formatter import BackendMetadata, ExplainResult, QueryResult, ResultColumn, ResultFormatter, ResultWarning

__all__ = [
    "AdapterFactory",
    "BackendMetadata",
    "ConnectionDescriptor",
    "ConnectionRegistry",
    "DatabaseAdapter",
    "ExplainResult",
    "MetadataService",
    "QueryResult",
    "ResolvedConnection",
    "ResultColumn",
    "ResultFormatter",
    "ResultWarning",
    "SchemaInfo",
    "TableColumnInfo",
    "TableDescription",
    "TableInfo",
]
