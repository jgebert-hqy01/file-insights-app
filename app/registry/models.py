"""Pydantic models for the sources and queries registries.

These models are the single source of truth for what a source or query is
allowed to declare. Validators here enforce the read-only, parameterized-SQL
rules from the build brief so a half-defined query fails fast, in CI, rather
than at runtime.
"""
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FULLY_QUALIFIED_VIEW_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
)
_READ_ONLY_PREFIX_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|REPLACE|PUT|REMOVE)\b",
    re.IGNORECASE,
)
_PARAMETER_TOKEN_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def is_read_only_sql(sql: str) -> bool:
    """The single definition of "read-only" for this app's SQL.

    Used both by the QueryDefinition validator (at definition time) and by
    db/client.py (again, defensively, immediately before execution) so the
    two checks can never drift out of sync with each other.
    """
    return bool(_READ_ONLY_PREFIX_RE.match(sql)) and not _FORBIDDEN_KEYWORD_RE.search(sql)


class ColumnDefinition(BaseModel):
    name: str
    data_type: str


class SourceDefinition(BaseModel):
    name: str
    fully_qualified_view: str
    filename_column: Optional[str] = None
    columns: List[ColumnDefinition] = Field(default_factory=list)
    sensitive_columns: List[str] = Field(default_factory=list)
    description: str

    @field_validator("name", "description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("fully_qualified_view")
    @classmethod
    def _valid_fully_qualified_view(cls, v: str) -> str:
        if not _FULLY_QUALIFIED_VIEW_RE.match(v):
            raise ValueError(
                "fully_qualified_view must be 'catalog.schema.view' using plain identifiers"
            )
        return v

    @field_validator("filename_column")
    @classmethod
    def _valid_filename_column(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _IDENTIFIER_RE.match(v):
            raise ValueError("filename_column must be a plain SQL identifier")
        return v

    @model_validator(mode="after")
    def _sensitive_columns_are_known(self) -> "SourceDefinition":
        known = {c.name for c in self.columns}
        unknown = set(self.sensitive_columns) - known
        if unknown:
            raise ValueError(f"sensitive_columns not found in columns: {sorted(unknown)}")
        return self


class ParameterType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DATE = "date"
    DATE_RANGE = "date_range"


class ParameterControl(str, Enum):
    SELECT = "select"
    MULTISELECT = "multiselect"
    DATE_RANGE = "date_range"
    NUMBER = "number"


class QueryParameter(BaseModel):
    name: str
    label: str
    type: ParameterType
    control: ParameterControl
    required: bool = False
    allowed_values: Optional[List[Any]] = None
    lookup_query: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _IDENTIFIER_RE.match(v):
            raise ValueError("parameter name must be a plain identifier")
        return v

    @field_validator("label")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must not be blank")
        return v


class QueryDefinition(BaseModel):
    name: str
    title: str
    description: str
    category: str
    source: str
    sql: str
    run_on_load: bool = False
    parameters: List[QueryParameter] = Field(default_factory=list)
    row_cap: Optional[int] = None
    additional_sensitive_columns: List[str] = Field(default_factory=list)
    unmasked_columns: List[str] = Field(default_factory=list)

    @field_validator("name", "title", "description", "category", "source")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("sql")
    @classmethod
    def _sql_is_read_only(cls, v: str) -> str:
        if not _READ_ONLY_PREFIX_RE.match(v):
            raise ValueError("sql must start with SELECT or WITH")
        if _FORBIDDEN_KEYWORD_RE.search(v):
            raise ValueError("sql contains a disallowed statement keyword")
        return v

    def sql_parameter_names(self) -> Set[str]:
        return set(_PARAMETER_TOKEN_RE.findall(self.sql))

    @model_validator(mode="after")
    def _filename_is_bound(self) -> "QueryDefinition":
        if "filename" not in self.sql_parameter_names():
            raise ValueError("sql must bind :filename")
        return self

    @model_validator(mode="after")
    def _parameters_match_sql(self) -> "QueryDefinition":
        declared = {p.name for p in self.parameters} | {"filename"}
        used = self.sql_parameter_names()
        undeclared = used - declared
        if undeclared:
            raise ValueError(f"sql references undeclared parameters: {sorted(undeclared)}")
        unused = declared - used - {"filename"}
        if unused:
            raise ValueError(f"parameters declared but not used in sql: {sorted(unused)}")
        return self
