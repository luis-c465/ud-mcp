from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, model_validator

_MODEL_CONFIG: ClassVar[ConfigDict] = ConfigDict(extra="forbid", populate_by_name=True)


class ObjectMetadata(BaseModel):
    """Shared backend-neutral identity fields for catalog/schema objects."""

    model_config = _MODEL_CONFIG

    catalog: str | None = None
    schema_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    name: str
    object_type: str
    description: str | None = None
    backend_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_name


class SchemaInfo(ObjectMetadata):
    """Metadata for a schema namespace."""

    object_type: Literal["schema"] = "schema"


class TableInfo(ObjectMetadata):
    """Metadata for a table or view."""

    object_type: Literal["table", "view", "materialized_view", "unknown"] = "table"
    is_view: bool = False
    is_insertable: bool | None = None
    is_temporary: bool | None = None


class ColumnInfo(BaseModel):
    """Metadata for a column in a described table."""

    model_config = _MODEL_CONFIG

    catalog: str | None = None
    schema_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    table: str | None = None
    name: str
    object_type: Literal["column"] = "column"
    data_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("data_type", "dataType", "type", "db_type", "dbType"),
    )
    ordinal_position: int | None = None
    nullable: bool | None = None
    default: str | None = None
    description: str | None = Field(default=None, validation_alias=AliasChoices("description", "comment"))
    length: int | None = Field(
        default=None,
        validation_alias=AliasChoices("length", "display_size", "displaySize", "size"),
    )
    precision: int | None = None
    scale: int | None = None
    is_primary_key: bool | None = None
    backend_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_name

    @computed_field
    @property
    def display_size(self) -> int | None:
        return self.length


class TableDescription(BaseModel):
    """Full metadata for a table, including its columns."""

    model_config = _MODEL_CONFIG

    table: TableInfo
    columns: list[ColumnInfo] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = Field(default_factory=list)
    backend_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _inflate_table_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "table" in value:
            return value

        table_keys = {"catalog", "schema", "schema_name", "name", "object_type", "description", "backend_metadata", "is_view", "is_insertable", "is_temporary"}
        if not any(key in value for key in table_keys):
            return value

        table_payload = {key: value[key] for key in table_keys if key in value}
        remaining = {key: item for key, item in value.items() if key not in table_keys}
        return {"table": table_payload, **remaining}

    @computed_field
    @property
    def catalog(self) -> str | None:
        return self.table.catalog

    @computed_field
    @property
    def schema(self) -> str | None:
        return self.table.schema

    @computed_field
    @property
    def name(self) -> str:
        return self.table.name

    @computed_field
    @property
    def object_type(self) -> str:
        return self.table.object_type

    @computed_field
    @property
    def description(self) -> str | None:
        return self.table.description


__all__ = ["ColumnInfo", "ObjectMetadata", "SchemaInfo", "TableDescription", "TableInfo"]
