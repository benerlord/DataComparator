"""Pydantic v2 models for task and connection configuration."""
from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class SheetSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    index: int | None = None


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


class ExcelSourceConfig(SourceConfig):
    type: Literal["excel"] = "excel"
    path: str
    sheets: list[SheetSelector] = Field(default_factory=lambda: [SheetSelector(index=0)])
    header_row: int = 1
    force_string: bool = True


class GaussDBSourceConfig(SourceConfig):
    type: Literal["gaussdb"] = "gaussdb"
    connection: str
    query: str


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = 3
    backoff: float = 1.5


class PaginationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["page", "offset", "cursor"]
    page_param: str | None = None
    size_param: str | None = None
    size: int
    total_path: str | None = None
    offset_param: str | None = None
    cursor_param: str | None = None
    next_cursor_path: str | None = None


class APISourceConfig(SourceConfig):
    type: Literal["api"] = "api"
    connection: str
    method: Literal["GET", "POST"] = "GET"
    url: str
    params: dict[str, str] = Field(default_factory=dict)
    body: dict | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    pagination: PaginationConfig
    data_path: str
    timeout: int = 30
    retry: RetryConfig = Field(default_factory=RetryConfig)


AnySourceConfig = ExcelSourceConfig | GaussDBSourceConfig | APISourceConfig


class KeyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    right: str
    left_regex: str | None = None
    right_regex: str | None = None

    @field_validator("left_regex", "right_regex")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            pattern = re.compile(v)
        except re.error as e:
            raise ValueError(f"invalid regex {v!r}: {e}")
        if pattern.groups > 1:
            raise ValueError(
                f"regex {v!r} has {pattern.groups} capture groups; "
                "must have 0 or 1. Use non-capturing (?:...) for grouping without capture."
            )
        return v


class MatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[KeyMapping] = Field(min_length=1)


class CompareDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["exact", "numeric", "string"] = "exact"
    ignore_whitespace: bool = False
    ignore_case: bool = False
    null_equivalents: list[str] = Field(default_factory=lambda: ["", "null", "NULL", "NaN", "nan"])


class FieldRule(BaseModel):
    """Field-level rule. `None` on behavioral flags = inherit from CompareDefaults.

    Each side must provide exactly one of `<side>` (column name) or
    `<side>_literal` (constant string or null broadcast to every row).
    "Provided" is judged by Pydantic's `model_fields_set` so `left_literal: null`
    is distinguishable from "left_literal not written". Do NOT rewrite this
    check as `value is None`.
    """
    model_config = ConfigDict(extra="forbid")
    left: str | None = None
    right: str | None = None
    left_literal: str | None = None
    right_literal: str | None = None
    mode: Literal["exact", "numeric", "string"] | None = None
    decimal_places: int | None = None
    parse_unit: bool | None = None
    unit_category: str | None = None
    normalize_to: str | None = None
    ignore_whitespace: bool | None = None
    ignore_case: bool | None = None
    null_equivalents: list[str] | None = None
    as_type: Literal["datetime", "int", "float", "string"] | None = None
    datetime_format: str | None = None

    @model_validator(mode="after")
    def _check_source_specifiers(self):
        for side in ("left", "right"):
            col_set = side in self.model_fields_set
            lit_set = f"{side}_literal" in self.model_fields_set
            if not col_set and not lit_set:
                raise ValueError(
                    f"field must specify '{side}' or '{side}_literal'"
                )
            if col_set and lit_set:
                raise ValueError(
                    f"cannot specify both '{side}' and '{side}_literal'"
                )
        return self


class CompareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: CompareDefaults = Field(default_factory=CompareDefaults)
    fields: list[FieldRule]
    exclude: list[str] = Field(default_factory=list)


class HTMLOptions(BaseModel):
    include_charts: bool = True


class ExcelOptions(BaseModel):
    highlight_diff_cells: bool = True


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dir: str
    formats: list[Literal["html", "excel", "csv", "json", "console"]]
    html: HTMLOptions = Field(default_factory=HTMLOptions)
    excel: ExcelOptions = Field(default_factory=ExcelOptions)
    truncate_details_over: int = 10_000


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["auto", "memory", "disk"] = "auto"
    memory_threshold_rows: int = 500_000
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"


class TaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    sources: dict[Literal["left", "right"], AnySourceConfig]
    match: MatchConfig
    compare: CompareConfig
    output: OutputConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    def model_post_init(self, __context) -> None:
        if set(self.sources.keys()) != {"left", "right"}:
            raise ValueError("sources must contain exactly 'left' and 'right' keys")


# Connection (credential) models
class GaussDBAConnection(BaseModel):
    """GaussDB A / DWS / openGauss / GaussDB 100 PG-compat mode — via psycopg2."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["gaussdb"] = "gaussdb"
    variant: Literal["a"] = "a"
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    ssl: Literal["disable", "require", "verify-ca"] = "require"


class GaussDBTConnection(BaseModel):
    """GaussDB T (OLTP) — via JDBC + JayDeBeApi."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["gaussdb"] = "gaussdb"
    variant: Literal["t"]
    jdbc_url: str = Field(min_length=1)
    jdbc_jar_path: str = Field(min_length=1)
    jdbc_driver_class: str = Field(min_length=1)
    user: str
    password: str
    jdbc_properties: dict[str, str] = Field(default_factory=dict)


# Union type: usable in isinstance checks (Python 3.10+) and type annotations.
GaussDBConnection = GaussDBAConnection | GaussDBTConnection

# For Pydantic validation dispatch: left-to-right union matching.
# GaussDBAConnection (extra="forbid") is tried first; if T-specific fields
# (e.g. jdbc_url) are present it fails validation and Pydantic falls through
# to GaussDBTConnection. When "variant" is absent the default "a" applies.
_GaussDBConnectionValidated = GaussDBAConnection | GaussDBTConnection


class BearerAuth(BaseModel):
    kind: Literal["bearer"] = "bearer"
    token: str


class CookieAuth(BaseModel):
    kind: Literal["cookie"] = "cookie"
    login_url: str
    login_method: Literal["POST", "GET"] = "POST"
    login_body: dict[str, str] = Field(default_factory=dict)
    cookie_names: list[str]


class NoAuth(BaseModel):
    kind: Literal["none"] = "none"


AnyAPIAuth = BearerAuth | CookieAuth | NoAuth


class APIConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["api"] = "api"
    base_url: str
    auth: AnyAPIAuth = Field(default_factory=NoAuth)


AnyConnection = _GaussDBConnectionValidated | APIConnection


# ---------- Batch (multi-task) mode -----------------------------------------

class BatchTaskOverride(BaseModel):
    """Sub-task entry inside a BatchConfig. Freeform pre-merge; validated
    as a full TaskConfig after deep-merging with batch defaults.
    """
    model_config = ConfigDict(extra="allow")
    name: str


class BatchConfig(BaseModel):
    """Top-level batch document. Presence of 'tasks:' triggers multi mode."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    on_error: Literal["continue", "fail_fast"] = "continue"
    # All "defaults" blocks — pre-merge freeform dicts, validated per sub-task after merge.
    sources: dict[str, dict] | None = None
    match: dict | None = None
    compare: dict | None = None
    output: dict | None = None
    runtime: dict | None = None
    tasks: list[BatchTaskOverride] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def _unique_names(cls, v: list[BatchTaskOverride]) -> list[BatchTaskOverride]:
        names = [t.name for t in v]
        seen: set[str] = set()
        dups: list[str] = []
        for n in names:
            if n in seen:
                dups.append(n)
            seen.add(n)
        if dups:
            raise ValueError(f"sub-task names must be unique; duplicates: {dups}")
        return v
