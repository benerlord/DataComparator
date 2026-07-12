"""Pydantic v2 models for task and connection configuration."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


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
    """Field-level rule. `None` = inherit from CompareDefaults."""
    model_config = ConfigDict(extra="forbid")
    left: str
    right: str
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
class GaussDBConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["gaussdb"] = "gaussdb"
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    ssl: Literal["disable", "require", "verify-ca"] = "require"


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


AnyConnection = GaussDBConnection | APIConnection
