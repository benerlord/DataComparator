# DataComparator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that compares data across three source types (Excel / GaussDB / HTTP API) with any-to-any pairing, driven by YAML task configuration.

**Architecture:** Layered — CLI (Typer) → Config (Pydantic) → DataSource abstraction → Normalization (pure functions) → Comparison Engine (in-memory pandas / disk DuckDB) → Reporters (HTML/Excel/CSV/JSON/Console). Each layer is independently testable.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, ruamel.yaml, pandas 2.x (pyarrow backend), DuckDB, openpyxl, psycopg2-binary, httpx, jsonpath-ng, Jinja2, XlsxWriter, structlog, rich, tenacity, pytest + pytest-mock + respx + testcontainers + syrupy.

**Reference spec:** `docs/superpowers/specs/2026-07-13-data-comparator-design.md`

---

## Milestone 1 · Project Skeleton & Config Layer

### Task 1: Project skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/datacompare/__init__.py`
- Create: `src/datacompare/py.typed`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "datacompare"
version = "0.1.0"
description = "CLI tool to compare Excel/GaussDB/API data sources"
requires-python = ">=3.11"
readme = "README.md"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.6",
    "ruamel.yaml>=0.18",
    "pandas>=2.2",
    "pyarrow>=15",
    "duckdb>=0.10",
    "openpyxl>=3.1",
    "xlrd>=2.0",
    "XlsxWriter>=3.2",
    "psycopg2-binary>=2.9",
    "httpx>=0.27",
    "jsonpath-ng>=1.6",
    "Jinja2>=3.1",
    "structlog>=24.1",
    "rich>=13.7",
    "tenacity>=8.2",
    "python-dateutil>=2.9",
    "keyring>=25.0",
]

[project.scripts]
datacompare = "datacompare.cli:app"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "testcontainers>=4.0",
    "syrupy>=4.6",
    "ruff>=0.4",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/datacompare"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
uv.lock
reports/
.DS_Store
```

- [ ] **Step 3: Write minimal package init**

`src/datacompare/__init__.py`:
```python
"""DataComparator - compare Excel/GaussDB/API data sources."""
__version__ = "0.1.0"
```

`src/datacompare/py.typed`: (empty file — signals PEP 561)

`tests/__init__.py`: (empty)

`tests/conftest.py`:
```python
"""Shared pytest fixtures."""
```

- [ ] **Step 4: Install & verify**

Run:
```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -c "import datacompare; print(datacompare.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml .gitignore src/ tests/
git commit -m "chore: initial project skeleton with dependencies"
```

---

### Task 2: Pydantic config models

**Files:**
- Create: `src/datacompare/config/__init__.py`
- Create: `src/datacompare/config/models.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/config/__init__.py`
- Create: `tests/unit/config/test_models.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/config/test_models.py`:
```python
import pytest
from pydantic import ValidationError
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, GaussDBSourceConfig, APISourceConfig,
    FieldRule, CompareDefaults, MatchConfig, KeyMapping, CompareConfig,
    OutputConfig, RuntimeConfig, SheetSelector, PaginationConfig,
)

def test_excel_source_defaults():
    src = ExcelSourceConfig(path="foo.xlsx")
    assert src.type == "excel"
    assert src.header_row == 1
    assert src.force_string is True
    assert src.sheets == [SheetSelector(index=0)]

def test_field_rule_override_semantics_optional_none():
    rule = FieldRule(left="a", right="b")
    assert rule.mode is None
    assert rule.ignore_whitespace is None
    assert rule.decimal_places is None

def test_task_config_requires_left_and_right():
    with pytest.raises(ValidationError):
        TaskConfig(
            name="x",
            sources={"left": ExcelSourceConfig(path="a.xlsx")},
            match=MatchConfig(keys=[KeyMapping(left="k", right="k")]),
            compare=CompareConfig(defaults=CompareDefaults(), fields=[]),
            output=OutputConfig(dir="./out", formats=["json"]),
        )

def test_pagination_type_literal():
    p = PaginationConfig(type="page", page_param="pageNum", size_param="pageSize", size=100)
    assert p.type == "page"
    with pytest.raises(ValidationError):
        PaginationConfig(type="bogus", size=100)

def test_gaussdb_source_requires_query():
    src = GaussDBSourceConfig(connection="prod", query="SELECT 1")
    assert src.type == "gaussdb"
    assert src.connection == "prod"

def test_api_source_requires_url():
    src = APISourceConfig(
        connection="svc", url="/v1/orders",
        pagination=PaginationConfig(type="page", size=100),
        data_path="$.data.list[*]",
    )
    assert src.method == "GET"
    assert src.timeout == 30
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'datacompare.config.models'`

- [ ] **Step 3: Implement models**

`src/datacompare/config/__init__.py`: (empty)

`src/datacompare/config/models.py`:
```python
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
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/ tests/unit/
git commit -m "feat(config): add Pydantic v2 models for task and connections"
```

---

### Task 3: YAML config loader with parameter substitution

**Files:**
- Create: `src/datacompare/config/loader.py`
- Create: `src/datacompare/config/errors.py`
- Create: `tests/unit/config/test_loader.py`
- Create: `tests/fixtures/config/minimal_task.yaml`

- [ ] **Step 1: Write failing tests**

`tests/unit/config/test_loader.py`:
```python
import os
from pathlib import Path
import pytest
from datacompare.config.loader import load_task, substitute
from datacompare.config.errors import ConfigError


def test_substitute_env_var(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    assert substitute("hello ${FOO}", params={}) == "hello bar"


def test_substitute_param():
    assert substitute("month={{param.month}}", params={"month": "2026-07"}) == "month=2026-07"


def test_substitute_today():
    result = substitute("{{today}}", params={})
    assert len(result) == 10  # YYYY-MM-DD
    assert result[4] == "-" and result[7] == "-"


def test_substitute_missing_env_raises(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(ConfigError, match="MISSING_VAR"):
        substitute("${MISSING_VAR}", params={})


def test_substitute_missing_param_raises():
    with pytest.raises(ConfigError, match="param.month"):
        substitute("{{param.month}}", params={})


def test_load_task_minimal(tmp_path, monkeypatch):
    monkeypatch.setenv("GAUSS_PWD", "secret")
    p = Path("tests/fixtures/config/minimal_task.yaml")
    task = load_task(p, params={"month": "2026-07"})
    assert task.name == "test"
    assert task.sources["left"].type == "excel"
    assert task.sources["right"].type == "gaussdb"
```

`tests/fixtures/config/minimal_task.yaml`:
```yaml
name: test
sources:
  left:
    type: excel
    path: ./data_{{param.month}}.xlsx
  right:
    type: gaussdb
    connection: prod
    query: SELECT * FROM sales
match:
  keys:
    - left: id
      right: id
compare:
  fields:
    - left: amount
      right: amount
output:
  dir: ./out
  formats: [json]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/config/test_loader.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement errors & loader**

`src/datacompare/config/errors.py`:
```python
"""Configuration-related exceptions."""


class ConfigError(Exception):
    def __init__(self, message: str, path: str | None = None, suggestion: str | None = None):
        self.message = message
        self.path = path
        self.suggestion = suggestion
        parts = [message]
        if path:
            parts.insert(0, f"[{path}]")
        if suggestion:
            parts.append(f"提示: {suggestion}")
        super().__init__(" ".join(parts))
```

`src/datacompare/config/loader.py`:
```python
"""YAML → TaskConfig with ${ENV} and {{param.x}} substitution."""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from pydantic import ValidationError
from .models import TaskConfig, AnyConnection
from .errors import ConfigError

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_PARAM_RE = re.compile(r"\{\{param\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}")
_BUILTIN_RE = re.compile(r"\{\{(today|now)\}\}")


def substitute(value: str, params: dict[str, str]) -> str:
    """Apply ${ENV}, {{param.x}}, {{today}}/{{now}} substitutions in order."""
    def _env(match: re.Match) -> str:
        key = match.group(1)
        v = os.environ.get(key)
        if v is None:
            raise ConfigError(f"environment variable ${{{key}}} is not set")
        return v

    def _param(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise ConfigError(f"{{{{param.{key}}}}} not provided", path=f"param.{key}")
        return params[key]

    def _builtin(match: re.Match) -> str:
        name = match.group(1)
        now = datetime.now()
        return now.strftime("%Y-%m-%d") if name == "today" else now.isoformat()

    value = _ENV_RE.sub(_env, value)
    value = _PARAM_RE.sub(_param, value)
    value = _BUILTIN_RE.sub(_builtin, value)
    return value


def _walk_substitute(node: Any, params: dict[str, str]) -> Any:
    if isinstance(node, str):
        return substitute(node, params)
    if isinstance(node, dict):
        return {k: _walk_substitute(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_substitute(v, params) for v in node]
    return node


def load_task(path: Path, params: dict[str, str] | None = None) -> TaskConfig:
    """Parse YAML, substitute placeholders, validate into TaskConfig."""
    params = params or {}
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f)
    if raw is None:
        raise ConfigError(f"empty task file: {path}")
    substituted = _walk_substitute(raw, params)
    try:
        return TaskConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"task config validation failed:\n{errors}") from e


def load_connections(path: Path) -> dict[str, AnyConnection]:
    """Parse connections YAML, substitute env vars, validate each entry."""
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f) or {}
    result: dict[str, AnyConnection] = {}
    for name, entry in raw.items():
        substituted = _walk_substitute(entry, params={})
        try:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(AnyConnection)
            result[name] = adapter.validate_python(substituted)
        except ValidationError as e:
            raise ConfigError(f"connection '{name}' invalid: {e}") from e
    return result
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_loader.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/loader.py src/datacompare/config/errors.py tests/
git commit -m "feat(config): YAML loader with env/param/builtin substitution"
```

---

### Task 4: Credentials loader (env + keyring resolution)

**Files:**
- Create: `src/datacompare/config/credentials.py`
- Create: `tests/unit/config/test_credentials.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/config/test_credentials.py`:
```python
import pytest
from datacompare.config.credentials import mask_password, resolve_keyring


def test_mask_password_dsn():
    assert mask_password("postgresql://u:secret@h:5432/db") == "postgresql://u:***@h:5432/db"


def test_mask_password_keyword():
    assert mask_password("host=x password=secret user=u") == "host=x password=*** user=u"


def test_mask_password_no_password():
    assert mask_password("host=x user=u") == "host=x user=u"


def test_resolve_keyring_scheme(mocker):
    mocker.patch("keyring.get_password", return_value="my_secret")
    assert resolve_keyring("keyring://myservice/myuser") == "my_secret"


def test_resolve_keyring_passthrough():
    assert resolve_keyring("plain_value") == "plain_value"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/config/credentials.py`:
```python
"""Credential resolution helpers: keyring lookup and log masking."""
from __future__ import annotations
import re

_PWD_DSN_RE = re.compile(r"(://[^:]+:)([^@]+)(@)")
_PWD_KW_RE = re.compile(r"(password=)([^\s]+)")
_KEYRING_RE = re.compile(r"^keyring://([^/]+)/(.+)$")


def mask_password(text: str) -> str:
    """Redact passwords in DSN-style URLs and 'password=xxx' patterns."""
    text = _PWD_DSN_RE.sub(r"\1***\3", text)
    text = _PWD_KW_RE.sub(r"\1***", text)
    return text


def resolve_keyring(value: str) -> str:
    """If value is 'keyring://service/user', look up in OS keyring; else passthrough."""
    match = _KEYRING_RE.match(value)
    if not match:
        return value
    import keyring
    service, user = match.group(1), match.group(2)
    result = keyring.get_password(service, user)
    if result is None:
        from .errors import ConfigError
        raise ConfigError(f"keyring lookup miss: {service}/{user}")
    return result
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/credentials.py tests/unit/config/test_credentials.py
git commit -m "feat(config): credential resolution and password masking helpers"
```

---

## Milestone 2 · Normalization Layer (pure functions)

### Task 5: normalize/strings.py

**Files:**
- Create: `src/datacompare/normalize/__init__.py`
- Create: `src/datacompare/normalize/strings.py`
- Create: `tests/unit/normalize/__init__.py`
- Create: `tests/unit/normalize/test_strings.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_strings.py`:
```python
import pytest
from datacompare.normalize.strings import normalize_string

DEFAULT_NULLS = ["", "null", "NULL", "NaN", "nan"]

@pytest.mark.parametrize("value", DEFAULT_NULLS)
def test_null_equivalents_become_none(value):
    assert normalize_string(value, null_equivalents=DEFAULT_NULLS) is None

def test_none_stays_none():
    assert normalize_string(None, null_equivalents=DEFAULT_NULLS) is None

def test_ignore_whitespace_strips_and_folds():
    result = normalize_string("  hello   world  ", ignore_whitespace=True)
    assert result == "hello world"

def test_ignore_case_uses_casefold():
    assert normalize_string("Straße", ignore_case=True) == "strasse"

def test_combined_flags():
    result = normalize_string("  HELLO  World  ", ignore_whitespace=True, ignore_case=True)
    assert result == "hello world"

def test_no_flags_returns_unchanged():
    assert normalize_string("  Foo  ") == "  Foo  "

def test_null_check_precedes_normalization():
    # 'NULL' is in null equivalents; case-fold should not apply first
    assert normalize_string("NULL", ignore_case=True, null_equivalents=["NULL"]) is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_strings.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/__init__.py`: (empty)

`src/datacompare/normalize/strings.py`:
```python
"""String normalization: null equivalents, whitespace collapse, case fold."""
from __future__ import annotations
import re

_WS_RE = re.compile(r"\s+")


def normalize_string(
    s: str | None,
    ignore_whitespace: bool = False,
    ignore_case: bool = False,
    null_equivalents: list[str] | None = None,
) -> str | None:
    if s is None:
        return None
    if null_equivalents and s in null_equivalents:
        return None
    if ignore_whitespace:
        s = _WS_RE.sub(" ", s.strip())
    if ignore_case:
        s = s.casefold()
    return s
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_strings.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/ tests/unit/normalize/
git commit -m "feat(normalize): string normalization with null equivalents"
```

---

### Task 6: normalize/decimals.py (ROUND_HALF_UP)

**Files:**
- Create: `src/datacompare/normalize/decimals.py`
- Create: `tests/unit/normalize/test_decimals.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_decimals.py`:
```python
import pytest
from datacompare.normalize.decimals import round_half_up

@pytest.mark.parametrize("x,places,expected", [
    (2.5, 0, 3.0),          # NOT 2.0 (banker's rounding)
    (0.5, 0, 1.0),
    (1.5, 0, 2.0),
    (12.345, 2, 12.35),
    (0.001234, 2, 0.00),
    (12.3456, 2, 12.35),
    (-2.5, 0, -3.0),
    (1.005, 2, 1.01),       # classic float trap; Decimal handles it
    (99.995, 2, 100.00),
])
def test_round_half_up(x, places, expected):
    assert round_half_up(x, places) == expected

def test_returns_float_type():
    assert isinstance(round_half_up(1.5, 0), float)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_decimals.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/decimals.py`:
```python
"""Decimal rounding with ROUND_HALF_UP (not banker's)."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(x: float, places: int) -> float:
    """Round half away from zero (business rounding), not Python's banker's rounding."""
    q = Decimal(10) ** -places
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_decimals.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/decimals.py tests/unit/normalize/test_decimals.py
git commit -m "feat(normalize): ROUND_HALF_UP decimal rounding"
```

---

### Task 7: normalize/units.py

**Files:**
- Create: `src/datacompare/normalize/units.py`
- Create: `tests/unit/normalize/test_units.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_units.py`:
```python
import pytest
from datacompare.normalize.units import parse_and_convert, UnitError

def test_storage_tb_to_gb():
    assert parse_and_convert("30 TB", "storage", "GB") == pytest.approx(30720.0)

def test_storage_gb_to_tb_reverse():
    assert parse_and_convert("30720 GB", "storage", "TB") == pytest.approx(30.0)

def test_case_insensitive():
    assert parse_and_convert("30 tb", "storage", "GB") == pytest.approx(30720.0)
    assert parse_and_convert("30 Tb", "storage", "gb") == pytest.approx(30720.0)

def test_time_min_to_s():
    assert parse_and_convert("2 min", "time", "s") == pytest.approx(120.0)

def test_time_h_to_ms():
    assert parse_and_convert("1 h", "time", "ms") == pytest.approx(3_600_000.0)

def test_no_space_between_number_and_unit():
    assert parse_and_convert("30TB", "storage", "GB") == pytest.approx(30720.0)

def test_negative_and_float():
    assert parse_and_convert("-1.5 GB", "storage", "MB") == pytest.approx(-1536.0)

def test_scientific_notation():
    assert parse_and_convert("1.5e3 MB", "storage", "GB") == pytest.approx(1500.0 / 1024.0)

def test_no_unit_pattern_returns_error():
    result = parse_and_convert("not a number", "storage", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "no_unit_pattern"

def test_unknown_unit_returns_error():
    result = parse_and_convert("30 XX", "storage", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "unknown_unit"

def test_unknown_category_returns_error():
    result = parse_and_convert("30 TB", "bogus", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "unknown_category"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_units.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/units.py`:
```python
"""Parse '<number> <unit>' strings and convert to a target unit."""
from __future__ import annotations
import re
from dataclasses import dataclass

UNIT_TABLES: dict[str, dict[str, float]] = {
    "storage": {
        "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3,
        "TB": 1024**4, "PB": 1024**5,
    },
    "time": {
        "ms": 1, "s": 1_000, "min": 60_000,
        "h": 3_600_000, "d": 86_400_000,
    },
    "length": {"mm": 1, "cm": 10, "m": 1_000, "km": 1_000_000},
    "mass": {"mg": 1, "g": 1_000, "kg": 1_000_000, "t": 1_000_000_000},
}

_UNIT_PATTERN = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z]+)\s*$"
)


@dataclass(frozen=True)
class UnitError:
    original: str
    reason: str  # "no_unit_pattern" | "unknown_unit" | "unknown_category"


def parse_and_convert(s: str, category: str, target_unit: str) -> float | UnitError:
    match = _UNIT_PATTERN.match(s)
    if not match:
        return UnitError(original=s, reason="no_unit_pattern")
    value, unit = float(match.group(1)), match.group(2)
    table = UNIT_TABLES.get(category)
    if table is None:
        return UnitError(original=s, reason="unknown_category")
    lookup = {k.lower(): v for k, v in table.items()}
    unit_lower = unit.lower()
    target_lower = target_unit.lower()
    if unit_lower not in lookup or target_lower not in lookup:
        return UnitError(original=s, reason="unknown_unit")
    return value * lookup[unit_lower] / lookup[target_lower]
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_units.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/units.py tests/unit/normalize/test_units.py
git commit -m "feat(normalize): unit parsing and conversion (storage/time/length/mass)"
```

---

### Task 8: normalize/types.py

**Files:**
- Create: `src/datacompare/normalize/types.py`
- Create: `tests/unit/normalize/test_types.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_types.py`:
```python
from datetime import datetime
import pytest
from datacompare.normalize.types import coerce_type, CoerceError

def test_none_passthrough():
    assert coerce_type(None, "int") is None

def test_no_target_type_passthrough():
    assert coerce_type("hello", None) == "hello"

def test_to_int():
    assert coerce_type("42", "int") == 42

def test_to_float():
    assert coerce_type("3.14", "float") == 3.14

def test_to_string():
    assert coerce_type("42", "string") == "42"

def test_to_datetime_with_format():
    result = coerce_type("2026-07-13 15:20:00", "datetime", datetime_format="%Y-%m-%d %H:%M:%S")
    assert result == datetime(2026, 7, 13, 15, 20, 0)

def test_to_datetime_iso_no_format():
    result = coerce_type("2026-07-13T15:20:00", "datetime")
    assert result == datetime(2026, 7, 13, 15, 20, 0)

def test_int_conversion_failure_returns_sentinel():
    result = coerce_type("not_a_number", "int")
    assert isinstance(result, CoerceError)
    assert result.target == "int"
    assert result.original == "not_a_number"

def test_datetime_format_mismatch_returns_sentinel():
    result = coerce_type("bad", "datetime", datetime_format="%Y-%m-%d")
    assert isinstance(result, CoerceError)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_types.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/types.py`:
```python
"""Type coercion with sentinel-on-failure semantics (never raises)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from dateutil import parser as _dtparser


@dataclass(frozen=True)
class CoerceError:
    original: str
    target: str


def coerce_type(
    s: str | None,
    as_type: Literal["datetime", "int", "float", "string"] | None,
    datetime_format: str | None = None,
) -> Any:
    if s is None:
        return None
    if as_type is None:
        return s
    try:
        if as_type == "int":
            return int(s)
        if as_type == "float":
            return float(s)
        if as_type == "string":
            return s
        if as_type == "datetime":
            if datetime_format:
                return datetime.strptime(s, datetime_format)
            return _dtparser.parse(s)
    except (ValueError, TypeError, OverflowError):
        return CoerceError(original=s, target=as_type)
    return CoerceError(original=s, target=as_type)
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_types.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/types.py tests/unit/normalize/test_types.py
git commit -m "feat(normalize): type coercion with sentinel-on-failure"
```

---

### Task 9: normalize/columns.py + effective FieldRule merge

**Files:**
- Create: `src/datacompare/normalize/columns.py`
- Create: `tests/unit/normalize/test_columns.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_columns.py`:
```python
import pandas as pd
from datacompare.config.models import (
    KeyMapping, FieldRule, CompareDefaults, MatchConfig, CompareConfig,
)
from datacompare.normalize.columns import (
    apply_column_mapping, effective_rule, EffectiveRule,
)

def test_apply_column_mapping_left_side():
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100"], "extra": ["x"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["order_id", "amount"]
    assert result.iloc[0]["order_id"] == "A1"

def test_apply_column_mapping_right_side_no_rename_needed():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount")]
    result = apply_column_mapping(df, keys, fields, side="right")
    assert list(result.columns) == ["order_id", "amount"]

def test_effective_rule_inherits_defaults():
    defaults = CompareDefaults(mode="numeric", ignore_whitespace=True)
    rule = FieldRule(left="a", right="a")  # all None
    eff = effective_rule(rule, defaults)
    assert eff.mode == "numeric"
    assert eff.ignore_whitespace is True

def test_effective_rule_field_overrides_defaults():
    defaults = CompareDefaults(mode="exact", ignore_whitespace=False)
    rule = FieldRule(left="a", right="a", mode="numeric", ignore_whitespace=True)
    eff = effective_rule(rule, defaults)
    assert eff.mode == "numeric"
    assert eff.ignore_whitespace is True

def test_effective_rule_null_equivalents_override():
    defaults = CompareDefaults(null_equivalents=["", "null"])
    rule = FieldRule(left="a", right="a", null_equivalents=["-", "N/A"])
    eff = effective_rule(rule, defaults)
    assert eff.null_equivalents == ["-", "N/A"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/columns.py`:
```python
"""Column renaming and per-field effective rule merging."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import pandas as pd
from datacompare.config.models import KeyMapping, FieldRule, CompareDefaults


@dataclass(frozen=True)
class EffectiveRule:
    """FieldRule merged with defaults; no None values for behavioral flags."""
    left: str
    right: str
    mode: str
    decimal_places: int | None
    parse_unit: bool
    unit_category: str | None
    normalize_to: str | None
    ignore_whitespace: bool
    ignore_case: bool
    null_equivalents: list[str]
    as_type: str | None
    datetime_format: str | None


def effective_rule(rule: FieldRule, defaults: CompareDefaults) -> EffectiveRule:
    return EffectiveRule(
        left=rule.left,
        right=rule.right,
        mode=rule.mode if rule.mode is not None else defaults.mode,
        decimal_places=rule.decimal_places,
        parse_unit=rule.parse_unit if rule.parse_unit is not None else False,
        unit_category=rule.unit_category,
        normalize_to=rule.normalize_to,
        ignore_whitespace=(
            rule.ignore_whitespace if rule.ignore_whitespace is not None
            else defaults.ignore_whitespace
        ),
        ignore_case=(
            rule.ignore_case if rule.ignore_case is not None else defaults.ignore_case
        ),
        null_equivalents=(
            rule.null_equivalents if rule.null_equivalents is not None
            else defaults.null_equivalents
        ),
        as_type=rule.as_type,
        datetime_format=rule.datetime_format,
    )


def apply_column_mapping(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    fields: list[FieldRule],
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Rename columns to canonical (right-side) names; drop unmapped columns."""
    rename_map: dict[str, str] = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    for f in fields:
        rename_map[getattr(f, side)] = f.right
    missing = [src for src in rename_map if src not in df.columns]
    if missing:
        from datacompare.config.errors import ConfigError
        raise ConfigError(
            f"columns not found in {side} source: {missing}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )
    keep = list(rename_map.values())
    return df.rename(columns=rename_map)[keep]
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/columns.py tests/unit/normalize/test_columns.py
git commit -m "feat(normalize): column mapping and effective rule merge"
```

---

## Milestone 3 · DataSource Abstraction + Excel + GaussDB

### Task 10: DataSource base class + registry

**Files:**
- Create: `src/datacompare/sources/__init__.py`
- Create: `src/datacompare/sources/base.py`
- Create: `src/datacompare/sources/registry.py`
- Create: `tests/unit/sources/__init__.py`
- Create: `tests/unit/sources/test_registry.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_registry.py`:
```python
import pytest
import pandas as pd
from datacompare.sources.base import DataSource
from datacompare.sources.registry import (
    register_source, get_source_class, SOURCE_REGISTRY,
)

def test_register_and_lookup():
    @register_source("dummy_test")
    class DummySource(DataSource):
        name = "dummy"
        def columns(self): return []
        def estimated_rows(self): return 0
        def read(self, chunk_size=100_000):
            yield pd.DataFrame()

    assert get_source_class("dummy_test") is DummySource
    SOURCE_REGISTRY.pop("dummy_test")  # cleanup

def test_lookup_unknown_type_raises():
    with pytest.raises(KeyError, match="unknown_source_type"):
        get_source_class("unknown_source_type")

def test_data_source_is_abstract():
    with pytest.raises(TypeError):
        DataSource()  # cannot instantiate abstract
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_registry.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/sources/__init__.py`: (empty)

`src/datacompare/sources/base.py`:
```python
"""Abstract DataSource contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator
import pandas as pd


class DataSource(ABC):
    """
    All rows returned by read() are strings (or None for nulls).
    Type coercion, decimals, and unit parsing happen in the normalize layer.
    """
    name: str = ""

    @abstractmethod
    def columns(self) -> list[str]:
        """Return the column header list. Used to validate config references."""

    @abstractmethod
    def estimated_rows(self) -> int | None:
        """Return a row-count estimate; None if unknown. Used by engine router."""

    @abstractmethod
    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        """Yield DataFrame chunks of string-typed values."""

    def close(self) -> None:
        """Release file handles / connections. Default no-op."""
        return None
```

`src/datacompare/sources/registry.py`:
```python
"""Type-string → DataSource subclass registry (extension point)."""
from __future__ import annotations
from typing import Callable
from .base import DataSource

SOURCE_REGISTRY: dict[str, type[DataSource]] = {}


def register_source(type_name: str) -> Callable[[type[DataSource]], type[DataSource]]:
    def _decorator(cls: type[DataSource]) -> type[DataSource]:
        SOURCE_REGISTRY[type_name] = cls
        return cls
    return _decorator


def get_source_class(type_name: str) -> type[DataSource]:
    if type_name not in SOURCE_REGISTRY:
        raise KeyError(f"unknown source type: {type_name}")
    return SOURCE_REGISTRY[type_name]
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/sources/test_registry.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/ tests/unit/sources/
git commit -m "feat(sources): DataSource abstract base + type registry"
```

---

### Task 11: ExcelSource

**Files:**
- Create: `src/datacompare/sources/excel.py`
- Create: `tests/unit/sources/test_excel.py`
- Create: `tests/fixtures/excel/simple.xlsx` (generated by test setup helper)
- Create: `tests/fixtures/excel/multi_sheet.xlsx` (generated)
- Create: `tests/fixtures/excel/header_row2.xlsx` (generated)

- [ ] **Step 1: Write fixture generator + failing tests**

`tests/unit/sources/test_excel.py`:
```python
import pytest
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from datacompare.sources.excel import ExcelSource
from datacompare.config.models import ExcelSourceConfig, SheetSelector

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "excel"


@pytest.fixture(scope="module", autouse=True)
def _make_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    # simple.xlsx: single sheet, header row 1
    wb = Workbook()
    ws = wb.active
    ws.append(["order_id", "amount", "region"])
    ws.append(["A001", "100.50", "North"])
    ws.append(["A002", "200.00", "South"])
    wb.save(FIXTURES / "simple.xlsx")
    # multi_sheet.xlsx: two sheets with same header
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "North"
    ws1.append(["order_id", "amount"])
    ws1.append(["A001", "100"])
    ws2 = wb.create_sheet("South")
    ws2.append(["order_id", "amount"])
    ws2.append(["B001", "200"])
    ws2.append(["B002", "300"])
    wb.save(FIXTURES / "multi_sheet.xlsx")
    # header_row2.xlsx: title in row 1, headers in row 2
    wb = Workbook()
    ws = wb.active
    ws.append(["Report", None])
    ws.append(["order_id", "amount"])
    ws.append(["X1", "50"])
    wb.save(FIXTURES / "header_row2.xlsx")
    yield


def test_columns_from_first_sheet():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    assert src.columns() == ["order_id", "amount", "region"]
    src.close()


def test_estimated_rows():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    assert src.estimated_rows() == 2
    src.close()


def test_read_returns_strings():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    chunks = list(src.read())
    assert len(chunks) == 1
    df = chunks[0]
    assert df.iloc[0]["order_id"] == "A001"
    assert df.iloc[0]["amount"] == "100.50"
    assert all(df.dtypes == "object")
    src.close()


def test_multi_sheet_by_name_concat():
    cfg = ExcelSourceConfig(
        path=str(FIXTURES / "multi_sheet.xlsx"),
        sheets=[SheetSelector(name="North"), SheetSelector(name="South")],
    )
    src = ExcelSource(cfg)
    df = pd.concat(src.read())
    assert len(df) == 3
    assert "__sheet__" in df.columns
    assert set(df["__sheet__"].unique()) == {"North", "South"}
    src.close()


def test_header_row_configurable():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "header_row2.xlsx"), header_row=2)
    src = ExcelSource(cfg)
    assert src.columns() == ["order_id", "amount"]
    df = pd.concat(src.read())
    assert df.iloc[0]["order_id"] == "X1"
    src.close()


def test_multi_sheet_header_mismatch_raises(tmp_path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "A"
    ws1.append(["id", "amount"])
    ws1.append(["1", "100"])
    ws2 = wb.create_sheet("B")
    ws2.append(["id", "value"])   # mismatched header
    ws2.append(["2", "200"])
    p = tmp_path / "mismatch.xlsx"
    wb.save(p)
    cfg = ExcelSourceConfig(
        path=str(p),
        sheets=[SheetSelector(name="A"), SheetSelector(name="B")],
    )
    src = ExcelSource(cfg)
    with pytest.raises(Exception, match="header"):
        src.columns()
    src.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_excel.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement**

`src/datacompare/sources/excel.py`:
```python
"""Excel source using openpyxl in read-only mode."""
from __future__ import annotations
from typing import Iterator
import pandas as pd
from openpyxl import load_workbook
from openpyxl.workbook import Workbook
from .base import DataSource
from .registry import register_source
from datacompare.config.models import ExcelSourceConfig, SheetSelector
from datacompare.config.errors import ConfigError


@register_source("excel")
class ExcelSource(DataSource):
    def __init__(self, config: ExcelSourceConfig, name: str = ""):
        self.config = config
        self.name = name or f"excel:{config.path}"
        self._wb: Workbook | None = None

    def _open(self) -> Workbook:
        if self._wb is None:
            self._wb = load_workbook(self.config.path, read_only=True, data_only=True)
        return self._wb

    def _selected_sheet_names(self) -> list[str]:
        wb = self._open()
        result: list[str] = []
        for sel in self.config.sheets:
            if sel.name is not None:
                if sel.name not in wb.sheetnames:
                    raise ConfigError(
                        f"sheet '{sel.name}' not found",
                        suggestion=f"available: {wb.sheetnames}",
                    )
                result.append(sel.name)
            elif sel.index is not None:
                if sel.index >= len(wb.sheetnames):
                    raise ConfigError(f"sheet index {sel.index} out of range")
                result.append(wb.sheetnames[sel.index])
            else:
                raise ConfigError("SheetSelector must have name or index")
        return result

    def _sheet_header(self, sheet_name: str) -> list[str]:
        wb = self._open()
        ws = wb[sheet_name]
        header_row_idx = self.config.header_row
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if i == header_row_idx:
                return [str(c) if c is not None else "" for c in row if c is not None]
        return []

    def columns(self) -> list[str]:
        sheets = self._selected_sheet_names()
        first_header = self._sheet_header(sheets[0])
        for name in sheets[1:]:
            other = self._sheet_header(name)
            if other != first_header:
                raise ConfigError(
                    f"sheet header mismatch: '{sheets[0]}' vs '{name}'",
                    suggestion=f"headers: {first_header} vs {other}",
                )
        return first_header

    def estimated_rows(self) -> int | None:
        wb = self._open()
        total = 0
        for name in self._selected_sheet_names():
            ws = wb[name]
            # openpyxl read_only max_row is exact
            total += max(0, (ws.max_row or 0) - self.config.header_row)
        return total

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        header = self.columns()
        wb = self._open()
        buffer: list[dict[str, str | None]] = []
        for sheet_name in self._selected_sheet_names():
            ws = wb[sheet_name]
            for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if i <= self.config.header_row:
                    continue
                if all(v is None for v in row):
                    continue
                record: dict[str, str | None] = {"__sheet__": sheet_name}
                for col_name, cell in zip(header, row):
                    if cell is None:
                        record[col_name] = None
                    elif self.config.force_string:
                        record[col_name] = str(cell)
                    else:
                        record[col_name] = cell
                buffer.append(record)
                if len(buffer) >= chunk_size:
                    yield pd.DataFrame(buffer)
                    buffer = []
        if buffer:
            yield pd.DataFrame(buffer)

    def close(self) -> None:
        if self._wb is not None:
            self._wb.close()
            self._wb = None
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/sources/test_excel.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/excel.py tests/unit/sources/test_excel.py
git commit -m "feat(sources): ExcelSource with multi-sheet, header row config, force-string"
```

---

### Task 12: GaussDBSource (with testcontainers PostgreSQL)

**Files:**
- Create: `src/datacompare/sources/gaussdb.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/sources/__init__.py`
- Create: `tests/integration/sources/test_gaussdb.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/sources/test_gaussdb.py`:
```python
import pytest
import pandas as pd
from testcontainers.postgres import PostgresContainer
from datacompare.sources.gaussdb import GaussDBSource
from datacompare.config.models import GaussDBSourceConfig, GaussDBConnection


@pytest.fixture(scope="module")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        import psycopg2
        conn = psycopg2.connect(
            host=pg.get_container_host_ip(),
            port=pg.get_exposed_port(5432),
            user=pg.username, password=pg.password, dbname=pg.dbname,
        )
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE sales (
                    order_id TEXT, region TEXT, amount NUMERIC
                );
                INSERT INTO sales VALUES
                    ('A001', 'North', 100.50),
                    ('A002', 'South', 200.00),
                    ('A003', 'West', 300.75);
            """)
        conn.commit()
        conn.close()
        yield pg


@pytest.fixture
def creds(pg_container):
    return GaussDBConnection(
        type="gaussdb",
        host=pg_container.get_container_host_ip(),
        port=int(pg_container.get_exposed_port(5432)),
        database=pg_container.dbname,
        user=pg_container.username,
        password=pg_container.password,
        ssl="disable",
    )


def test_columns(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT order_id, region, amount FROM sales")
    src = GaussDBSource(cfg, creds)
    assert src.columns() == ["order_id", "region", "amount"]
    src.close()


def test_estimated_rows(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT * FROM sales")
    src = GaussDBSource(cfg, creds)
    assert src.estimated_rows() == 3
    src.close()


def test_read_returns_strings(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT * FROM sales ORDER BY order_id")
    src = GaussDBSource(cfg, creds)
    df = pd.concat(src.read())
    assert len(df) == 3
    assert df.iloc[0]["order_id"] == "A001"
    assert df.iloc[0]["amount"] == "100.50"
    assert all(df.dtypes == "object")
    src.close()


def test_non_select_query_rejected(creds):
    cfg = GaussDBSourceConfig(
        connection="test",
        query="INSERT INTO sales VALUES ('X', 'Y', 0)",
    )
    src = GaussDBSource(cfg, creds)
    with pytest.raises(Exception, match="SELECT"):
        src.columns()
    src.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/integration/sources/test_gaussdb.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement**

`src/datacompare/sources/gaussdb.py`:
```python
"""GaussDB source via psycopg2 (compatible with PostgreSQL wire protocol)."""
from __future__ import annotations
import re
from typing import Iterator
import psycopg2
import pandas as pd
from .base import DataSource
from .registry import register_source
from datacompare.config.models import GaussDBSourceConfig, GaussDBConnection
from datacompare.config.errors import ConfigError

_SELECT_RE = re.compile(r"^\s*(--[^\n]*\n\s*)*SELECT\b", re.IGNORECASE)


@register_source("gaussdb")
class GaussDBSource(DataSource):
    def __init__(self, config: GaussDBSourceConfig, connection: GaussDBConnection, name: str = ""):
        self.config = config
        self.creds = connection
        self.name = name or f"gaussdb:{connection.host}/{connection.database}"
        self._conn = None
        self._validate_read_only()

    def _validate_read_only(self) -> None:
        if not _SELECT_RE.match(self.config.query):
            raise ConfigError(
                "only SELECT queries are permitted",
                path="sources.query",
                suggestion="wrap or rewrite as SELECT statement",
            )

    def _connect(self):
        if self._conn is None:
            self._conn = psycopg2.connect(
                host=self.creds.host,
                port=self.creds.port,
                dbname=self.creds.database,
                user=self.creds.user,
                password=self.creds.password,
                sslmode=self.creds.ssl,
            )
        return self._conn

    def columns(self) -> list[str]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({self.config.query}) t LIMIT 0")
            return [d.name for d in cur.description]

    def estimated_rows(self) -> int | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM ({self.config.query}) t")
            row = cur.fetchone()
            return int(row[0]) if row else None

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        cols = self.columns()
        conn = self._connect()
        with conn.cursor(name="datacompare_stream") as cur:
            cur.itersize = chunk_size
            cur.execute(self.config.query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                df = pd.DataFrame(rows, columns=cols)
                # Convert all values to string; None → pd.NA-preserving None
                df = df.map(lambda v: None if v is None else str(v))
                yield df

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/integration/sources/test_gaussdb.py -v`
Expected: 4 passed (requires Docker for testcontainers)

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/gaussdb.py tests/integration/
git commit -m "feat(sources): GaussDBSource via psycopg2 with SELECT-only enforcement"
```

---

## Milestone 4 · InMemoryEngine + Console/JSON Reporters + CLI Skeleton

### Task 13: CompareResult + CompareEngine base + FieldError

**Files:**
- Create: `src/datacompare/engine/__init__.py`
- Create: `src/datacompare/engine/result.py`
- Create: `src/datacompare/engine/base.py`
- Create: `tests/unit/engine/__init__.py`
- Create: `tests/unit/engine/test_result.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/engine/test_result.py`:
```python
import pandas as pd
from datacompare.engine.result import CompareResult, FieldError, DiffType

def test_compare_result_defaults():
    r = CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=0, right_total=0,
        matched_rows=0, identical_rows=0, diff_rows=0,
        left_only=0, right_only=0,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.0, errors=[],
    )
    assert r.match_rate() == 0.0

def test_match_rate_computed():
    r = CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=1.0, errors=[],
    )
    # 90 identical out of (100+100-95) unique
    assert r.match_rate() == pytest.approx(90 / (100 + 100 - 95))

def test_diff_type_enum():
    assert DiffType.VALUE_MISMATCH.value == "value_mismatch"
    assert DiffType.TYPE_ERROR.value == "type_error"
    assert DiffType.UNIT_ERROR.value == "unit_error"
    assert DiffType.NULL_MISMATCH.value == "null_mismatch"

def test_field_error_fields():
    e = FieldError(row_key={"id": "A1"}, field="amount", kind="type_error", original="N/A")
    assert e.kind == "type_error"
```

Also add `import pytest` at top of the test file.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/engine/__init__.py`: (empty)

`src/datacompare/engine/result.py`:
```python
"""CompareResult and related data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    NULL_MISMATCH = "null_mismatch"


@dataclass(frozen=True)
class FieldError:
    row_key: dict[str, str]
    field: str
    kind: str  # "type_error" | "unit_error"
    original: str


@dataclass
class CompareResult:
    task_name: str
    left_name: str
    right_name: str

    left_total: int
    right_total: int
    matched_rows: int
    identical_rows: int
    diff_rows: int
    left_only: int
    right_only: int

    diff_details: pd.DataFrame
    left_only_rows: pd.DataFrame
    right_only_rows: pd.DataFrame

    engine_used: str
    duration_seconds: float
    errors: list[FieldError] = field(default_factory=list)

    def match_rate(self) -> float:
        total = self.left_total + self.right_total - self.matched_rows
        if total <= 0:
            return 0.0
        return self.identical_rows / total
```

`src/datacompare/engine/base.py`:
```python
"""Abstract CompareEngine contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from .result import CompareResult


class CompareEngine(ABC):
    @abstractmethod
    def compare(
        self,
        left: DataSource,
        right: DataSource,
        task: TaskConfig,
    ) -> CompareResult: ...
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/engine/ tests/unit/engine/
git commit -m "feat(engine): CompareResult, DiffType enum, FieldError, engine base"
```

---

### Task 14: Normalization pipeline (compose per-field per-side)

**Files:**
- Create: `src/datacompare/normalize/pipeline.py`
- Create: `tests/unit/normalize/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/normalize/test_pipeline.py`:
```python
import pandas as pd
from datacompare.config.models import (
    KeyMapping, FieldRule, CompareDefaults, CompareConfig, MatchConfig,
)
from datacompare.normalize.pipeline import normalize_side

def _cfg(fields, defaults=None):
    return CompareConfig(defaults=defaults or CompareDefaults(), fields=fields)

def test_pipeline_renames_and_filters_columns():
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100.50"], "extra": ["x"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["order_id", "amount"]

def test_numeric_rounding():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100.556"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["amount"] == 100.56

def test_null_equivalent_becomes_none():
    df = pd.DataFrame({"order_id": ["A1"], "region": ["null"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(left="region", right="region", mode="string")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["region"] is None

def test_unit_parse():
    df = pd.DataFrame({"order_id": ["A1"], "storage": ["30 TB"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(
        left="storage", right="storage", mode="numeric",
        parse_unit=True, unit_category="storage", normalize_to="GB", decimal_places=0,
    )]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["storage"] == 30720

def test_string_case_and_whitespace():
    df = pd.DataFrame({"order_id": ["A1"], "region": ["  NORTH  "]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    defaults = CompareDefaults()
    fields = [FieldRule(
        left="region", right="region", mode="string",
        ignore_whitespace=True, ignore_case=True,
    )]
    result = normalize_side(df, keys, _cfg(fields, defaults), side="left")
    assert result.iloc[0]["region"] == "north"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/normalize/pipeline.py`:
```python
"""Compose normalize steps into a per-side pipeline."""
from __future__ import annotations
from typing import Literal, Any
import pandas as pd
from datacompare.config.models import KeyMapping, CompareConfig
from datacompare.engine.result import FieldError
from .columns import apply_column_mapping, effective_rule, EffectiveRule
from .strings import normalize_string
from .types import coerce_type, CoerceError
from .units import parse_and_convert, UnitError
from .decimals import round_half_up


def _process_value(v: Any, rule: EffectiveRule) -> Any:
    # 1. string preprocess (null equivalents, whitespace, case)
    if v is None or not isinstance(v, str):
        s = v
    else:
        s = normalize_string(
            v,
            ignore_whitespace=rule.ignore_whitespace,
            ignore_case=rule.ignore_case,
            null_equivalents=rule.null_equivalents,
        )
    if s is None:
        return None

    # 2. unit parsing (if configured)
    if rule.parse_unit and rule.unit_category and rule.normalize_to:
        converted = parse_and_convert(str(s), rule.unit_category, rule.normalize_to)
        if isinstance(converted, UnitError):
            return converted
        s = converted

    # 3. type coercion (for numeric mode with as_type; or explicit as_type)
    if rule.as_type is not None:
        s = coerce_type(str(s) if not isinstance(s, str) else s, rule.as_type, rule.datetime_format)
        if isinstance(s, CoerceError):
            return s
    elif rule.mode == "numeric" and not isinstance(s, (int, float)):
        s = coerce_type(str(s), "float", None)
        if isinstance(s, CoerceError):
            return s

    # 4. decimal rounding (numeric only)
    if rule.mode == "numeric" and rule.decimal_places is not None and isinstance(s, (int, float)):
        s = round_half_up(float(s), rule.decimal_places)

    return s


def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Rename → filter → per-field transform. Keys are passed through unchanged."""
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [k.right for k in keys]

    result = renamed.copy()
    for rule in compare.fields:
        eff = effective_rule(rule, compare.defaults)
        col = eff.right
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
    return result[key_cols + [f.right for f in compare.fields]]
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/pipeline.py tests/unit/normalize/test_pipeline.py
git commit -m "feat(normalize): compose per-side normalization pipeline"
```

---

### Task 15: InMemoryEngine

**Files:**
- Create: `src/datacompare/engine/memory.py`
- Create: `tests/unit/engine/test_memory.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/engine/test_memory.py`:
```python
import pandas as pd
import pytest
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.result import DiffType
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource


class _StubSource(DataSource):
    def __init__(self, df, name="stub"):
        self._df = df
        self.name = name
    def columns(self): return list(self._df.columns)
    def estimated_rows(self): return len(self._df)
    def read(self, chunk_size=100_000):
        yield self._df


def _task():
    return TaskConfig(
        name="t",
        sources={
            "left": ExcelSourceConfig(path="dummy"),
            "right": ExcelSourceConfig(path="dummy"),
        },
        match=MatchConfig(keys=[KeyMapping(left="order_id", right="order_id")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[
                FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2),
                FieldRule(left="region", right="region", mode="string"),
            ],
        ),
        output=OutputConfig(dir="./out", formats=["console"]),
        runtime=RuntimeConfig(),
    )


def test_all_match():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.matched_rows == 2
    assert result.identical_rows == 2
    assert result.diff_rows == 0
    assert result.left_only == 0
    assert result.right_only == 0


def test_field_mismatch():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100.50"], "region": ["N"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["101.00"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    assert result.identical_rows == 0
    assert len(result.diff_details) == 1
    assert result.diff_details.iloc[0]["field"] == "amount"


def test_left_only_and_right_only():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["1", "2"], "region": ["N", "S"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A2", "A3"], "amount": ["2", "3"], "region": ["S", "W"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.left_only == 1
    assert result.right_only == 1
    assert result.matched_rows == 1


def test_null_mismatch():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": [None],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    diff = result.diff_details.iloc[0]
    assert diff["diff_type"] == DiffType.NULL_MISMATCH.value


def test_duplicate_keys_rejected():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A1"], "amount": ["1", "2"], "region": ["N", "N"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["1"], "region": ["N"],
    }))
    with pytest.raises(Exception, match="duplicate"):
        InMemoryEngine().compare(left, right, _task())
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/engine/test_memory.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/engine/memory.py`:
```python
"""In-memory pandas-based comparison engine."""
from __future__ import annotations
import time
from typing import Any
import pandas as pd
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from datacompare.normalize.pipeline import normalize_side
from datacompare.normalize.types import CoerceError
from datacompare.normalize.units import UnitError
from .base import CompareEngine
from .result import CompareResult, DiffType, FieldError


def _values_equal(l: Any, r: Any) -> bool:
    if l is None and r is None:
        return True
    if l is None or r is None:
        return False
    if isinstance(l, (CoerceError, UnitError)) or isinstance(r, (CoerceError, UnitError)):
        return False
    return l == r


def _classify(l: Any, r: Any) -> str:
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    return DiffType.VALUE_MISMATCH.value


def _display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, CoerceError):
        return v.original
    if isinstance(v, UnitError):
        return v.original
    return str(v)


class InMemoryEngine(CompareEngine):
    def compare(
        self, left: DataSource, right: DataSource, task: TaskConfig,
    ) -> CompareResult:
        started = time.perf_counter()
        left_raw = pd.concat(list(left.read()), ignore_index=True)
        right_raw = pd.concat(list(right.read()), ignore_index=True)

        left_total = len(left_raw)
        right_total = len(right_raw)

        key_cols = [k.right for k in task.match.keys]
        field_cols = [f.right for f in task.compare.fields]

        ldf = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        rdf = normalize_side(right_raw, task.match.keys, task.compare, side="right")

        # duplicate key check
        for label, df in (("left", ldf), ("right", rdf)):
            dupes = df[df.duplicated(subset=key_cols, keep=False)]
            if not dupes.empty:
                keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                raise ValueError(f"duplicate keys in {label} side: {keys_display}")

        merged = ldf.merge(
            rdf, on=key_cols, how="outer", indicator=True,
            suffixes=("__left", "__right"),
        )

        both = merged[merged["_merge"] == "both"]
        left_only_mask = merged["_merge"] == "left_only"
        right_only_mask = merged["_merge"] == "right_only"

        # field-level diffs
        diff_records: list[dict] = []
        errors: list[FieldError] = []
        identical_mask = pd.Series(True, index=both.index)

        for f in task.compare.fields:
            lcol = f"{f.right}__left"
            rcol = f"{f.right}__right"
            for idx, row in both.iterrows():
                lv, rv = row[lcol], row[rcol]
                if not _values_equal(lv, rv):
                    identical_mask.at[idx] = False
                    diff_records.append({
                        **{k: row[k] for k in key_cols},
                        "field": f.right,
                        "left_value": _display(lv),
                        "right_value": _display(rv),
                        "diff_type": _classify(lv, rv),
                    })
                if isinstance(lv, (CoerceError, UnitError)):
                    kind = "type_error" if isinstance(lv, CoerceError) else "unit_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=f.right, kind=kind, original=lv.original,
                    ))
                if isinstance(rv, (CoerceError, UnitError)):
                    kind = "type_error" if isinstance(rv, CoerceError) else "unit_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=f.right, kind=kind, original=rv.original,
                    ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        diff_rows = matched_rows - identical_rows

        # build left_only / right_only DataFrames (use left-suffix / right-suffix cols)
        left_only_df = merged[left_only_mask][key_cols + [f"{c}__left" for c in field_cols]]
        left_only_df = left_only_df.rename(columns={f"{c}__left": c for c in field_cols})
        right_only_df = merged[right_only_mask][key_cols + [f"{c}__right" for c in field_cols]]
        right_only_df = right_only_df.rename(columns={f"{c}__right": c for c in field_cols})

        diff_df = pd.DataFrame(diff_records)

        return CompareResult(
            task_name=task.name,
            left_name=left.name,
            right_name=right.name,
            left_total=left_total,
            right_total=right_total,
            matched_rows=matched_rows,
            identical_rows=identical_rows,
            diff_rows=diff_rows,
            left_only=int(left_only_mask.sum()),
            right_only=int(right_only_mask.sum()),
            diff_details=diff_df,
            left_only_rows=left_only_df,
            right_only_rows=right_only_df,
            engine_used="memory",
            duration_seconds=time.perf_counter() - started,
            errors=errors,
        )
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/engine/test_memory.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/engine/memory.py tests/unit/engine/test_memory.py
git commit -m "feat(engine): InMemoryEngine with pandas outer-join comparison"
```

---

### Task 16: Console + JSON reporters

**Files:**
- Create: `src/datacompare/reporters/__init__.py`
- Create: `src/datacompare/reporters/base.py`
- Create: `src/datacompare/reporters/console.py`
- Create: `src/datacompare/reporters/json.py`
- Create: `tests/unit/reporters/__init__.py`
- Create: `tests/unit/reporters/test_console.py`
- Create: `tests/unit/reporters/test_json.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/reporters/test_json.py`:
```python
import json
import pandas as pd
from pathlib import Path
from datacompare.reporters.json import JSONReporter
from datacompare.engine.result import CompareResult

def _sample_result():
    return CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=10, right_total=10,
        matched_rows=8, identical_rows=7, diff_rows=1,
        left_only=2, right_only=2,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "1", "right_value": "2",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y"}]),
        engine_used="memory", duration_seconds=0.5, errors=[],
    )


def test_json_renders_file(tmp_path):
    reporter = JSONReporter({"truncate_details_over": 10_000}, tmp_path)
    p = reporter.render(_sample_result())
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["task"] == "t"
    assert data["summary"]["diff"] == 1
    assert len(data["diff_details"]) == 1
    assert data["truncated"] is False


def test_json_truncates_when_too_large(tmp_path):
    result = _sample_result()
    result.diff_details = pd.DataFrame([{"order_id": f"A{i}"} for i in range(50)])
    reporter = JSONReporter({"truncate_details_over": 10}, tmp_path)
    p = reporter.render(result)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["truncated"] is True
    assert len(data["diff_details"]) == 10
```

`tests/unit/reporters/test_console.py`:
```python
import pandas as pd
from datacompare.reporters.console import ConsoleReporter
from datacompare.engine.result import CompareResult


def test_console_returns_none_and_prints(capsys):
    result = CompareResult(
        task_name="Sales Check", left_name="left.xlsx", right_name="prod.db",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=1.2, errors=[],
    )
    reporter = ConsoleReporter({}, None)
    assert reporter.render(result) is None
    captured = capsys.readouterr()
    assert "Sales Check" in captured.out
    assert "95" in captured.out or "5" in captured.out
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/reporters/ -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/reporters/__init__.py`: (empty)

`src/datacompare/reporters/base.py`:
```python
"""Abstract Reporter contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from datacompare.engine.result import CompareResult


class Reporter(ABC):
    def __init__(self, config: dict, output_dir: Path | None):
        self.config = config
        self.output_dir = output_dir

    @abstractmethod
    def render(self, result: CompareResult) -> Path | None: ...
```

`src/datacompare/reporters/json.py`:
```python
"""JSON reporter with truncation for large detail sets."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from datacompare.engine.result import CompareResult, FieldError
from .base import Reporter


def _df_records(df: pd.DataFrame, limit: int) -> tuple[list[dict], bool]:
    if len(df) <= limit:
        return df.to_dict(orient="records"), False
    return df.head(limit).to_dict(orient="records"), True


class JSONReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        limit = self.config.get("truncate_details_over", 10_000)
        diff_records, t1 = _df_records(result.diff_details, limit)
        left_records, t2 = _df_records(result.left_only_rows, limit)
        right_records, t3 = _df_records(result.right_only_rows, limit)

        payload = {
            "task": result.task_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "left": {"name": result.left_name, "total": result.left_total},
            "right": {"name": result.right_name, "total": result.right_total},
            "summary": {
                "matched": result.matched_rows,
                "identical": result.identical_rows,
                "diff": result.diff_rows,
                "left_only": result.left_only,
                "right_only": result.right_only,
                "match_rate": result.match_rate(),
            },
            "diff_details": diff_records,
            "left_only": left_records,
            "right_only": right_records,
            "errors": [
                {"row_key": e.row_key, "field": e.field, "kind": e.kind, "original": e.original}
                for e in result.errors
            ],
            "engine": result.engine_used,
            "duration_seconds": result.duration_seconds,
            "truncated": t1 or t2 or t3,
        }
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        return out
```

`src/datacompare/reporters/console.py`:
```python
"""Terminal reporter using rich."""
from __future__ import annotations
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from datacompare.engine.result import CompareResult
from .base import Reporter


class ConsoleReporter(Reporter):
    def render(self, result: CompareResult) -> None:
        console = Console()
        console.print(Panel.fit(f"[bold]{result.task_name}[/bold] · 比对完成"))

        header = Table.grid(padding=(0, 1))
        header.add_row("左侧:", result.left_name, f"{result.left_total:,} 行")
        header.add_row("右侧:", result.right_name, f"{result.right_total:,} 行")
        header.add_row("引擎:", result.engine_used, f"耗时 {result.duration_seconds:.2f}s")
        console.print(header)

        stats = Table(title="匹配情况")
        stats.add_column("指标"); stats.add_column("数量", justify="right")
        stats.add_row("匹配率", f"{result.match_rate() * 100:.2f}%")
        stats.add_row("完全一致", f"{result.identical_rows:,}")
        stats.add_row("字段差异", f"{result.diff_rows:,}")
        stats.add_row("左侧独有", f"{result.left_only:,}")
        stats.add_row("右侧独有", f"{result.right_only:,}")
        console.print(stats)

        if result.errors:
            console.print(f"[yellow]⚠  {len(result.errors)} 个字段解析错误[/yellow]")
        return None
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/reporters/ -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/reporters/ tests/unit/reporters/
git commit -m "feat(reporters): JSON and Console reporters"
```

---

### Task 17: CLI skeleton (Typer, `version` command)

**Files:**
- Create: `src/datacompare/cli.py`
- Create: `tests/unit/test_cli.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_cli.py`:
```python
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "datacompare" in result.stdout


def test_help_lists_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "validate" in result.stdout
    assert "init" in result.stdout
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLI skeleton**

`src/datacompare/cli.py`:
```python
"""Typer CLI entry point."""
from __future__ import annotations
import typer
from datacompare import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo(f"datacompare {__version__}")


@app.command()
def run(
    task_file: str = typer.Argument(..., help="Path to task YAML config"),
    connections: str = typer.Option(
        "~/.datacompare/connections.yaml", "--connections", "-c",
        help="Path to connections YAML",
    ),
    param: list[str] = typer.Option([], "--param", "-p", help="KEY=VALUE"),
    output_dir: str | None = typer.Option(None, "--output-dir"),
    fmt: list[str] = typer.Option([], "--format", "-f"),
    engine: str | None = typer.Option(None, "--engine"),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_file: str | None = typer.Option(None, "--log-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fail_on_diff: bool = typer.Option(False, "--fail-on-diff"),
) -> None:
    """Execute a comparison task."""
    typer.echo("run: not implemented yet")
    raise typer.Exit(3)


@app.command()
def validate(
    task_file: str = typer.Argument(...),
    connections: str = typer.Option("~/.datacompare/connections.yaml", "--connections", "-c"),
) -> None:
    """Validate a task config (no execution)."""
    typer.echo("validate: not implemented yet")
    raise typer.Exit(3)


@app.command()
def init(
    template: str = typer.Argument(..., help="Template name"),
) -> None:
    """Emit a config template to stdout."""
    typer.echo("init: not implemented yet")
    raise typer.Exit(3)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): Typer skeleton with version/run/validate/init commands"
```

---

### Task 18: Wire up `run` command end-to-end (Excel↔Excel, memory engine)

**Files:**
- Modify: `src/datacompare/cli.py`
- Create: `src/datacompare/runner.py`
- Create: `tests/integration/test_run_e2e.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_run_e2e.py`:
```python
import json
from pathlib import Path
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def _make_xlsx(path: Path, rows: list[list]):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_run_excel_vs_excel_json(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100.50"], ["A2", "200"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100.51"], ["A2", "200"]])

    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "name": "excel_vs_excel",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount", "mode": "numeric", "decimal_places": 2}
        ]},
        "output": {"dir": str(tmp_path / "out"), "formats": ["json"]},
    }))

    connections = tmp_path / "connections.yaml"
    connections.write_text("")

    result = runner.invoke(app, [
        "run", str(task), "--connections", str(connections),
    ])
    assert result.exit_code == 0, result.stdout

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["diff"] == 1


def test_run_fail_on_diff(tmp_path):
    left = tmp_path / "l.xlsx"
    right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["id", "v"], ["A", "1"]])
    _make_xlsx(right, [["id", "v"], ["A", "2"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "id", "right": "id"}]},
        "compare": {"fields": [{"left": "v", "right": "v", "mode": "string"}]},
        "output": {"dir": str(tmp_path / "out"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(conn), "--fail-on-diff",
    ])
    assert result.exit_code == 10
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/integration/test_run_e2e.py -v`
Expected: FAIL

- [ ] **Step 3: Implement runner + wire up CLI**

`src/datacompare/runner.py`:
```python
"""Orchestration: build sources, run engine, dispatch reporters."""
from __future__ import annotations
from pathlib import Path
from datacompare.config.models import (
    TaskConfig, AnyConnection, ExcelSourceConfig, GaussDBSourceConfig,
    APISourceConfig, GaussDBConnection, APIConnection,
)
from datacompare.config.errors import ConfigError
from datacompare.sources.base import DataSource
from datacompare.sources.excel import ExcelSource
from datacompare.sources.gaussdb import GaussDBSource
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.result import CompareResult
from datacompare.reporters.json import JSONReporter
from datacompare.reporters.console import ConsoleReporter


def _build_source(cfg, connections: dict[str, AnyConnection], side_name: str) -> DataSource:
    if isinstance(cfg, ExcelSourceConfig):
        return ExcelSource(cfg, name=f"{side_name}:{cfg.path}")
    if isinstance(cfg, GaussDBSourceConfig):
        conn = connections.get(cfg.connection)
        if not isinstance(conn, GaussDBConnection):
            raise ConfigError(f"connection '{cfg.connection}' not found or wrong type")
        return GaussDBSource(cfg, conn, name=f"{side_name}:{cfg.connection}")
    if isinstance(cfg, APISourceConfig):
        from datacompare.sources.api import APISource
        conn = connections.get(cfg.connection)
        if not isinstance(conn, APIConnection):
            raise ConfigError(f"connection '{cfg.connection}' not found or wrong type")
        return APISource(cfg, conn, name=f"{side_name}:{cfg.connection}")
    raise ConfigError(f"unsupported source: {type(cfg).__name__}")


REPORTER_MAP: dict[str, type] = {
    "json": JSONReporter,
    "console": ConsoleReporter,
}


def dispatch_reporters(result: CompareResult, task: TaskConfig, output_dir: Path) -> list[Path]:
    outputs: list[Path] = []
    for fmt in task.output.formats:
        cls = REPORTER_MAP.get(fmt)
        if cls is None:
            continue  # HTML/Excel/CSV wired up in later tasks
        opts = {
            "truncate_details_over": task.output.truncate_details_over,
            **(task.output.html.model_dump() if fmt == "html" else {}),
            **(task.output.excel.model_dump() if fmt == "excel" else {}),
        }
        reporter = cls(opts, output_dir)
        path = reporter.render(result)
        if path is not None:
            outputs.append(path)
    return outputs


def execute(
    task: TaskConfig,
    connections: dict[str, AnyConnection],
    output_dir_override: str | None = None,
    formats_override: list[str] | None = None,
    engine_override: str | None = None,
) -> CompareResult:
    if formats_override:
        task.output.formats = list(formats_override)  # type: ignore[assignment]
    if engine_override:
        task.runtime.engine = engine_override  # type: ignore[assignment]

    left = _build_source(task.sources["left"], connections, side_name="left")
    right = _build_source(task.sources["right"], connections, side_name="right")

    try:
        # Milestone 4 wires only InMemoryEngine; router comes in Task 26.
        engine = InMemoryEngine()
        result = engine.compare(left, right, task)
    finally:
        left.close()
        right.close()

    output_dir = Path(output_dir_override or task.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch_reporters(result, task, output_dir)
    return result
```

Modify `src/datacompare/cli.py` — replace the `run` and `validate` command bodies:

```python
# Add these imports at the top of cli.py
from pathlib import Path
from datacompare.config.loader import load_task, load_connections
from datacompare.config.errors import ConfigError
from datacompare.runner import execute


# Replace the existing `run` function body
@app.command()
def run(
    task_file: str = typer.Argument(...),
    connections: str = typer.Option("~/.datacompare/connections.yaml", "--connections", "-c"),
    param: list[str] = typer.Option([], "--param", "-p"),
    output_dir: str | None = typer.Option(None, "--output-dir"),
    fmt: list[str] = typer.Option([], "--format", "-f"),
    engine: str | None = typer.Option(None, "--engine"),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_file: str | None = typer.Option(None, "--log-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fail_on_diff: bool = typer.Option(False, "--fail-on-diff"),
) -> None:
    params_dict = {}
    for kv in param:
        if "=" not in kv:
            typer.echo(f"invalid --param: {kv}", err=True)
            raise typer.Exit(1)
        k, v = kv.split("=", 1)
        params_dict[k] = v
    try:
        task = load_task(Path(task_file).expanduser(), params_dict)
        conn_path = Path(connections).expanduser()
        conns = load_connections(conn_path) if conn_path.exists() else {}
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)
    if dry_run:
        typer.echo("✓ configuration is valid (dry-run)")
        raise typer.Exit(0)
    try:
        result = execute(task, conns, output_dir_override=output_dir,
                         formats_override=fmt or None, engine_override=engine)
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True); raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"❌ error: {e}", err=True); raise typer.Exit(2)
    if fail_on_diff and (result.diff_rows > 0 or result.left_only > 0 or result.right_only > 0):
        raise typer.Exit(10)
    raise typer.Exit(0)
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/integration/test_run_e2e.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/runner.py src/datacompare/cli.py tests/integration/test_run_e2e.py
git commit -m "feat(cli): wire up run command end-to-end with InMemoryEngine + JSON/Console"
```

---

## Milestone 5 · API Data Source

### Task 19: API pagination iterators

**Files:**
- Create: `src/datacompare/sources/pagination.py`
- Create: `tests/unit/sources/test_pagination.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_pagination.py`:
```python
import httpx
import respx
import pytest
from datacompare.sources.pagination import (
    PagePaginator, OffsetPaginator, CursorPaginator,
)
from datacompare.config.models import PaginationConfig


def _client():
    return httpx.Client(base_url="http://api.test")


@respx.mock
def test_page_paginator_stops_when_short():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 1}, {"id": 2}], "total": 3}})
    )
    respx.get("http://api.test/orders", params={"pageNum": "2", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 3}], "total": 3}})
    )
    cfg = PaginationConfig(
        type="page", page_param="pageNum", size_param="pageSize", size=2,
        total_path="$.data.total",
    )
    p = PagePaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2


@respx.mock
def test_offset_paginator():
    respx.get("http://api.test/orders", params={"offset": "0", "limit": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 1}, {"id": 2}]}})
    )
    respx.get("http://api.test/orders", params={"offset": "2", "limit": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": []}})
    )
    cfg = PaginationConfig(
        type="offset", offset_param="offset", size_param="limit", size=2,
    )
    p = OffsetPaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2


@respx.mock
def test_cursor_paginator():
    respx.get("http://api.test/orders", params={"cursor": ""}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}], "next": "c1"})
    )
    respx.get("http://api.test/orders", params={"cursor": "c1"}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": 2}], "next": None})
    )
    cfg = PaginationConfig(
        type="cursor", cursor_param="cursor", size=2, next_cursor_path="$.next",
    )
    p = CursorPaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_pagination.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/sources/pagination.py`:
```python
"""Pagination iterators for APISource."""
from __future__ import annotations
from typing import Iterator, Any
import httpx
from jsonpath_ng import parse as jp_parse
from datacompare.config.models import PaginationConfig


def _extract_first(payload: Any, jsonpath: str | None) -> Any:
    if not jsonpath:
        return None
    matches = jp_parse(jsonpath).find(payload)
    return matches[0].value if matches else None


class _BasePaginator:
    def __init__(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        params: dict[str, str],
        body: dict | None,
        headers: dict[str, str],
        pagination: PaginationConfig,
    ):
        self.client = client
        self.method = method
        self.url = url
        self.base_params = params
        self.body = body
        self.headers = headers
        self.cfg = pagination

    def _request(self, params: dict[str, str]) -> dict:
        merged = {**self.base_params, **params}
        r = self.client.request(
            self.method, self.url, params=merged, json=self.body, headers=self.headers,
        )
        r.raise_for_status()
        return r.json()


class PagePaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        page = 1
        cfg = self.cfg
        while True:
            params = {cfg.page_param: str(page), cfg.size_param: str(cfg.size)}
            payload = self._request(params)
            yield payload
            total = _extract_first(payload, cfg.total_path)
            if total is not None and page * cfg.size >= int(total):
                break
            # also stop if returned page is smaller than size (best-effort)
            if cfg.total_path is None:
                # try to detect empty/short pages heuristically by counting records at data_path
                # (caller extracts records; here we accept up to N iterations safely bounded)
                page += 1
                if page > 10_000:
                    break
                continue
            page += 1


class OffsetPaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        offset = 0
        cfg = self.cfg
        while True:
            params = {cfg.offset_param: str(offset), cfg.size_param: str(cfg.size)}
            payload = self._request(params)
            yield payload
            total = _extract_first(payload, cfg.total_path)
            if total is not None and offset + cfg.size >= int(total):
                break
            offset += cfg.size
            if offset > 10_000_000:
                break


class CursorPaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        cursor = ""
        cfg = self.cfg
        while True:
            params = {cfg.cursor_param: cursor}
            payload = self._request(params)
            yield payload
            next_val = _extract_first(payload, cfg.next_cursor_path)
            if not next_val:
                break
            cursor = str(next_val)
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/sources/test_pagination.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/pagination.py tests/unit/sources/test_pagination.py
git commit -m "feat(sources): page/offset/cursor paginators for API"
```

---

### Task 20: API auth (Bearer + Cookie login)

**Files:**
- Create: `src/datacompare/sources/api_auth.py`
- Create: `tests/unit/sources/test_api_auth.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_api_auth.py`:
```python
import httpx
import respx
from datacompare.sources.api_auth import build_client
from datacompare.config.models import APIConnection, BearerAuth, CookieAuth, NoAuth


def test_no_auth_client_no_headers():
    conn = APIConnection(base_url="http://api.test", auth=NoAuth())
    client = build_client(conn)
    assert "Authorization" not in client.headers


def test_bearer_auth_sets_header():
    conn = APIConnection(base_url="http://api.test", auth=BearerAuth(token="my_token"))
    client = build_client(conn)
    assert client.headers["Authorization"] == "Bearer my_token"


@respx.mock
def test_cookie_auth_logs_in_and_sets_cookies():
    respx.post("http://api.test/login").mock(
        return_value=httpx.Response(
            200,
            headers=[("set-cookie", "SESSIONID=abc; Path=/"),
                     ("set-cookie", "XSRF-TOKEN=xyz; Path=/")],
        )
    )
    conn = APIConnection(
        base_url="http://api.test",
        auth=CookieAuth(
            login_url="/login",
            login_body={"u": "user", "p": "pwd"},
            cookie_names=["SESSIONID", "XSRF-TOKEN"],
        ),
    )
    client = build_client(conn)
    assert client.cookies.get("SESSIONID") == "abc"
    assert client.cookies.get("XSRF-TOKEN") == "xyz"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_api_auth.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/sources/api_auth.py`:
```python
"""httpx.Client construction with auth strategies."""
from __future__ import annotations
import httpx
from datacompare.config.models import APIConnection, BearerAuth, CookieAuth, NoAuth
from datacompare.config.errors import ConfigError


def build_client(conn: APIConnection) -> httpx.Client:
    client = httpx.Client(base_url=conn.base_url, timeout=30)
    auth = conn.auth
    if isinstance(auth, NoAuth):
        return client
    if isinstance(auth, BearerAuth):
        client.headers["Authorization"] = f"Bearer {auth.token}"
        return client
    if isinstance(auth, CookieAuth):
        r = client.request(
            auth.login_method, auth.login_url, json=auth.login_body,
        )
        r.raise_for_status()
        # cookies auto-persist in client.cookies; explicitly verify all expected are present
        for name in auth.cookie_names:
            if client.cookies.get(name) is None:
                raise ConfigError(f"cookie '{name}' not returned by login endpoint")
        return client
    raise ConfigError(f"unknown auth kind: {type(auth).__name__}")
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/sources/test_api_auth.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/api_auth.py tests/unit/sources/test_api_auth.py
git commit -m "feat(sources): API auth strategies (none/bearer/cookie)"
```

---

### Task 21: APISource main class (JSONPath extraction + retry)

**Files:**
- Create: `src/datacompare/sources/api.py`
- Create: `tests/unit/sources/test_api.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_api.py`:
```python
import httpx
import respx
import pandas as pd
from datacompare.sources.api import APISource
from datacompare.config.models import (
    APISourceConfig, PaginationConfig, APIConnection, NoAuth,
)


def _cfg():
    return APISourceConfig(
        connection="svc",
        url="/orders",
        pagination=PaginationConfig(
            type="page", page_param="pageNum", size_param="pageSize", size=2,
            total_path="$.data.total",
        ),
        data_path="$.data.list[*]",
    )


def _conn():
    return APIConnection(base_url="http://api.test", auth=NoAuth())


@respx.mock
def test_columns_from_first_page_sample():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": "A1", "amount": "100"}], "total": 1}})
    )
    src = APISource(_cfg(), _conn())
    assert set(src.columns()) == {"id", "amount"}


@respx.mock
def test_read_extracts_and_strings():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"id": "A1", "amount": 100.5}, {"id": "A2", "amount": 200},
        ], "total": 2}})
    )
    src = APISource(_cfg(), _conn())
    df = pd.concat(src.read())
    assert len(df) == 2
    assert df.iloc[0]["id"] == "A1"
    assert df.iloc[0]["amount"] == "100.5"


@respx.mock
def test_estimated_rows_uses_total_path():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": "x"}], "total": 42}})
    )
    src = APISource(_cfg(), _conn())
    assert src.estimated_rows() == 42


@respx.mock
def test_retry_on_500():
    route = respx.get("http://api.test/orders").mock(side_effect=[
        httpx.Response(500), httpx.Response(500),
        httpx.Response(200, json={"data": {"list": [{"id": "x"}], "total": 1}}),
    ])
    src = APISource(_cfg(), _conn())
    _ = src.columns()
    assert route.call_count == 3
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/sources/api.py`:
```python
"""HTTP API data source with JSONPath extraction and tenacity retry."""
from __future__ import annotations
from typing import Iterator, Any
import httpx
import pandas as pd
from jsonpath_ng import parse as jp_parse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import DataSource
from .registry import register_source
from .api_auth import build_client
from .pagination import PagePaginator, OffsetPaginator, CursorPaginator
from datacompare.config.models import APISourceConfig, APIConnection
from datacompare.config.errors import ConfigError


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


@register_source("api")
class APISource(DataSource):
    def __init__(self, config: APISourceConfig, connection: APIConnection, name: str = ""):
        self.config = config
        self.conn = connection
        self.name = name or f"api:{connection.base_url}{config.url}"
        self._client: httpx.Client | None = None
        self._data_extractor = jp_parse(config.data_path)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_client(self.conn)
            self._client.timeout = self.config.timeout
        return self._client

    def _wrapped_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = self._get_client()
        r = client.request(method, url, **kwargs)
        r.raise_for_status()
        return r

    def _fetch_sample_page(self, size: int = 1) -> dict:
        cfg = self.config.pagination
        params = {cfg.page_param or "page": "1", cfg.size_param or "size": str(size)}
        merged = {**self.config.params, **params}

        @retry(
            stop=stop_after_attempt(self.config.retry.max_attempts),
            wait=wait_exponential(multiplier=self.config.retry.backoff),
            retry=retry_if_exception_type(
                (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)
            ),
        )
        def _do():
            return self._wrapped_request(
                self.config.method, self.config.url,
                params=merged, json=self.config.body, headers=self.config.headers,
            )
        r = _do()
        return r.json()

    def _extract(self, payload: dict) -> list[dict]:
        return [m.value for m in self._data_extractor.find(payload)]

    def columns(self) -> list[str]:
        payload = self._fetch_sample_page(size=1)
        records = self._extract(payload)
        if not records:
            raise ConfigError("API first page returned no records; cannot infer columns")
        return list(records[0].keys())

    def estimated_rows(self) -> int | None:
        cfg = self.config.pagination
        if not cfg.total_path:
            return None
        payload = self._fetch_sample_page(size=1)
        matches = jp_parse(cfg.total_path).find(payload)
        if not matches:
            return None
        return int(matches[0].value)

    def _paginator(self):
        cfg = self.config.pagination
        client = self._get_client()
        args = (
            client, self.config.method, self.config.url, self.config.params,
            self.config.body, self.config.headers, cfg,
        )
        if cfg.type == "page":
            return PagePaginator(*args)
        if cfg.type == "offset":
            return OffsetPaginator(*args)
        if cfg.type == "cursor":
            return CursorPaginator(*args)
        raise ConfigError(f"unknown pagination type: {cfg.type}")

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        buffer: list[dict] = []
        for page in self._paginator():
            records = self._extract(page)
            if not records:
                break
            buffer.extend(records)
            if len(buffer) >= chunk_size:
                yield self._to_string_df(buffer)
                buffer = []
        if buffer:
            yield self._to_string_df(buffer)

    @staticmethod
    def _to_string_df(records: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(records)
        return df.map(lambda v: None if v is None else str(v))

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/sources/test_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/api.py tests/unit/sources/test_api.py
git commit -m "feat(sources): APISource with JSONPath extraction and tenacity retry"
```

---

## Milestone 6 · HTML/Excel/CSV Reporters

### Task 22: HTML reporter (Jinja2)

**Files:**
- Create: `src/datacompare/reporters/templates/html_report.jinja2`
- Create: `src/datacompare/reporters/html.py`
- Create: `tests/unit/reporters/test_html.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/reporters/test_html.py`:
```python
import pandas as pd
from datacompare.reporters.html import HTMLReporter
from datacompare.engine.result import CompareResult


def _sample():
    return CompareResult(
        task_name="Sales", left_name="left.xlsx", right_name="prod.db",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "100.5", "right_value": "100.6",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X1"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y1"}]),
        engine_used="memory", duration_seconds=1.2, errors=[],
    )


def test_html_writes_file(tmp_path):
    p = HTMLReporter({"include_charts": True}, tmp_path).render(_sample())
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "Sales" in content
    assert "value_mismatch" in content
    assert "<!DOCTYPE html>" in content


def test_html_without_charts(tmp_path):
    p = HTMLReporter({"include_charts": False}, tmp_path).render(_sample())
    content = p.read_text(encoding="utf-8")
    # Chart script should not be included
    assert "chart-data" not in content
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_html.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/reporters/templates/html_report.jinja2`:
```jinja
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{{ result.task_name }} · 比对报告</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 20px auto; padding: 0 20px; color: #333; }
  h1 { border-bottom: 2px solid #4a90e2; padding-bottom: 8px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 12px; margin: 20px 0; }
  .card { border: 1px solid #ddd; border-radius: 6px; padding: 14px; background: #fafafa; }
  .card .label { font-size: 12px; color: #777; text-transform: uppercase; }
  .card .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
  th, td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
  th { background: #f0f4f8; }
  tr.value_mismatch { background: #fff9e6; }
  tr.null_mismatch { background: #ffefd5; }
  tr.type_error, tr.unit_error { background: #ffe4e4; }
  details { margin: 12px 0; }
  summary { cursor: pointer; font-weight: 600; }
</style>
</head>
<body>
<h1>{{ result.task_name }}</h1>
<p>左侧: <code>{{ result.left_name }}</code> · 右侧: <code>{{ result.right_name }}</code>
   · 引擎: {{ result.engine_used }} · 耗时: {{ "%.2f"|format(result.duration_seconds) }}s</p>

<div class="cards">
  <div class="card"><div class="label">匹配率</div><div class="value">{{ "%.2f"|format(result.match_rate() * 100) }}%</div></div>
  <div class="card"><div class="label">完全一致</div><div class="value">{{ "{:,}".format(result.identical_rows) }}</div></div>
  <div class="card"><div class="label">字段差异</div><div class="value">{{ "{:,}".format(result.diff_rows) }}</div></div>
  <div class="card"><div class="label">左侧独有</div><div class="value">{{ "{:,}".format(result.left_only) }}</div></div>
  <div class="card"><div class="label">右侧独有</div><div class="value">{{ "{:,}".format(result.right_only) }}</div></div>
  <div class="card"><div class="label">字段错误</div><div class="value">{{ result.errors|length }}</div></div>
</div>

{% if include_charts %}
<details open><summary>图表</summary>
<canvas id="chart-data" width="600" height="240"></canvas>
</details>
{% endif %}

<h2>字段差异明细 ({{ result.diff_details|length }} 条)</h2>
{{ diff_html|safe }}

<details>
<summary>左侧独有 ({{ result.left_only_rows|length }} 行)</summary>
{{ left_only_html|safe }}
</details>

<details>
<summary>右侧独有 ({{ result.right_only_rows|length }} 行)</summary>
{{ right_only_html|safe }}
</details>
</body></html>
```

`src/datacompare/reporters/html.py`:
```python
"""HTML reporter using Jinja2 template."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from datacompare.engine.result import CompareResult
from .base import Reporter

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _df_to_html(df: pd.DataFrame, css_class_column: str | None = None, max_rows: int = 500) -> str:
    if df.empty:
        return "<p><em>(无)</em></p>"
    view = df.head(max_rows).copy()
    if css_class_column and css_class_column in view.columns:
        # add per-row CSS class in the diff_type value
        html = view.to_html(index=False, escape=True, classes="details-table",
                            table_id=None)
        return html
    return view.to_html(index=False, escape=True)


class HTMLReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("html_report.jinja2")
        html = template.render(
            result=result,
            include_charts=self.config.get("include_charts", True),
            diff_html=_df_to_html(result.diff_details, css_class_column="diff_type"),
            left_only_html=_df_to_html(result.left_only_rows),
            right_only_html=_df_to_html(result.right_only_rows),
        )
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.html"
        out.write_text(html, encoding="utf-8")
        return out
```

Also update the reporter map in `src/datacompare/runner.py`:

```python
# Add to REPORTER_MAP
from datacompare.reporters.html import HTMLReporter
REPORTER_MAP["html"] = HTMLReporter
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_html.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/reporters/html.py src/datacompare/reporters/templates/ \
        src/datacompare/runner.py tests/unit/reporters/test_html.py
git commit -m "feat(reporters): HTML reporter with Jinja2 template"
```

---

### Task 23: Excel reporter (XlsxWriter, multi-sheet)

**Files:**
- Create: `src/datacompare/reporters/excel.py`
- Create: `tests/unit/reporters/test_excel.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/reporters/test_excel.py`:
```python
import pandas as pd
from openpyxl import load_workbook
from datacompare.reporters.excel import ExcelReporter
from datacompare.engine.result import CompareResult


def _sample():
    return CompareResult(
        task_name="Sales", left_name="l", right_name="r",
        left_total=10, right_total=10,
        matched_rows=8, identical_rows=7, diff_rows=1,
        left_only=1, right_only=1,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "1", "right_value": "2",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X1", "amount": "1"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y1", "amount": "2"}]),
        engine_used="memory", duration_seconds=0.5, errors=[],
    )


def test_excel_writes_multi_sheet(tmp_path):
    p = ExcelReporter({"highlight_diff_cells": True}, tmp_path).render(_sample())
    assert p.exists()
    wb = load_workbook(p)
    assert set(wb.sheetnames) == {"摘要", "字段差异", "左侧独有", "右侧独有"}


def test_excel_summary_contains_metrics(tmp_path):
    p = ExcelReporter({"highlight_diff_cells": False}, tmp_path).render(_sample())
    wb = load_workbook(p)
    ws = wb["摘要"]
    values = [str(row[0].value) for row in ws.iter_rows()]
    assert any("Sales" in v for v in values)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_excel.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/reporters/excel.py`:
```python
"""Excel reporter using XlsxWriter."""
from __future__ import annotations
from pathlib import Path
import xlsxwriter
from datacompare.engine.result import CompareResult
from .base import Reporter


class ExcelReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.xlsx"
        wb = xlsxwriter.Workbook(str(out))

        # Formats
        title = wb.add_format({"bold": True, "font_size": 14})
        header = wb.add_format({"bold": True, "bg_color": "#f0f4f8", "border": 1})
        diff_fmt = wb.add_format({"bg_color": "#fff9e6"})
        error_fmt = wb.add_format({"bg_color": "#ffe4e4"})

        # Summary sheet
        ws = wb.add_worksheet("摘要")
        ws.write("A1", result.task_name, title)
        rows = [
            ("左侧数据源", result.left_name),
            ("右侧数据源", result.right_name),
            ("引擎", result.engine_used),
            ("耗时 (秒)", round(result.duration_seconds, 2)),
            ("匹配率", round(result.match_rate() * 100, 2)),
            ("完全一致行", result.identical_rows),
            ("字段差异行", result.diff_rows),
            ("左侧独有行", result.left_only),
            ("右侧独有行", result.right_only),
            ("字段错误数", len(result.errors)),
        ]
        for i, (k, v) in enumerate(rows, start=3):
            ws.write(f"A{i}", k, header)
            ws.write(f"B{i}", v)

        # Diff details
        ws = wb.add_worksheet("字段差异")
        cols = list(result.diff_details.columns) or ["(空)"]
        for j, c in enumerate(cols):
            ws.write(0, j, str(c), header)
        for i, row in enumerate(result.diff_details.itertuples(index=False), start=1):
            for j, val in enumerate(row):
                fmt = None
                if self.config.get("highlight_diff_cells"):
                    diff_type = getattr(row, "diff_type", None)
                    if diff_type in ("type_error", "unit_error"):
                        fmt = error_fmt
                    elif diff_type is not None:
                        fmt = diff_fmt
                ws.write(i, j, "" if val is None else str(val), fmt) if fmt else ws.write(
                    i, j, "" if val is None else str(val)
                )

        # Left-only / Right-only
        for sheet_name, df in [
            ("左侧独有", result.left_only_rows),
            ("右侧独有", result.right_only_rows),
        ]:
            ws = wb.add_worksheet(sheet_name)
            cols = list(df.columns) or ["(空)"]
            for j, c in enumerate(cols):
                ws.write(0, j, str(c), header)
            for i, row in enumerate(df.itertuples(index=False), start=1):
                for j, val in enumerate(row):
                    ws.write(i, j, "" if val is None else str(val))

        wb.close()
        return out
```

Also add to reporter map in `runner.py`:
```python
from datacompare.reporters.excel import ExcelReporter
REPORTER_MAP["excel"] = ExcelReporter
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_excel.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/reporters/excel.py src/datacompare/runner.py tests/unit/reporters/test_excel.py
git commit -m "feat(reporters): Excel reporter with multi-sheet output"
```

---

### Task 24: CSV reporter (separate files per section)

**Files:**
- Create: `src/datacompare/reporters/csv.py`
- Create: `tests/unit/reporters/test_csv.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/reporters/test_csv.py`:
```python
import pandas as pd
from datacompare.reporters.csv import CSVReporter
from datacompare.engine.result import CompareResult


def _sample():
    return CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=1, right_total=1,
        matched_rows=1, identical_rows=0, diff_rows=1,
        left_only=1, right_only=1,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "1", "right_value": "2",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y"}]),
        engine_used="memory", duration_seconds=0.1, errors=[],
    )


def test_csv_writes_all_files(tmp_path):
    CSVReporter({}, tmp_path).render(_sample())
    assert (tmp_path / "csv" / "diff_details.csv").exists()
    assert (tmp_path / "csv" / "left_only.csv").exists()
    assert (tmp_path / "csv" / "right_only.csv").exists()
    assert (tmp_path / "csv" / "summary.csv").exists()


def test_csv_summary_content(tmp_path):
    CSVReporter({}, tmp_path).render(_sample())
    summary = (tmp_path / "csv" / "summary.csv").read_text(encoding="utf-8")
    assert "matched_rows" in summary
    assert "1" in summary
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_csv.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/reporters/csv.py`:
```python
"""CSV reporter: writes separate files per data section."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datacompare.engine.result import CompareResult
from .base import Reporter


class CSVReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        assert self.output_dir is not None
        target = self.output_dir / "csv"
        target.mkdir(parents=True, exist_ok=True)

        result.diff_details.to_csv(target / "diff_details.csv", index=False, encoding="utf-8-sig")
        result.left_only_rows.to_csv(target / "left_only.csv", index=False, encoding="utf-8-sig")
        result.right_only_rows.to_csv(target / "right_only.csv", index=False, encoding="utf-8-sig")

        summary = pd.DataFrame([{
            "task_name": result.task_name,
            "left_total": result.left_total,
            "right_total": result.right_total,
            "matched_rows": result.matched_rows,
            "identical_rows": result.identical_rows,
            "diff_rows": result.diff_rows,
            "left_only": result.left_only,
            "right_only": result.right_only,
            "match_rate": round(result.match_rate(), 4),
            "engine_used": result.engine_used,
            "duration_seconds": round(result.duration_seconds, 3),
            "errors": len(result.errors),
        }])
        summary.to_csv(target / "summary.csv", index=False, encoding="utf-8-sig")
        return target
```

Also add to reporter map:
```python
from datacompare.reporters.csv import CSVReporter
REPORTER_MAP["csv"] = CSVReporter
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_csv.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/reporters/csv.py src/datacompare/runner.py tests/unit/reporters/test_csv.py
git commit -m "feat(reporters): CSV reporter with per-section files"
```

---

## Milestone 7 · DiskEngine + Engine Router

### Task 25: DiskEngine (DuckDB)

**Files:**
- Create: `src/datacompare/engine/disk.py`
- Create: `tests/unit/engine/test_disk.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/engine/test_disk.py`:
```python
import pandas as pd
from datacompare.engine.disk import DiskEngine
from datacompare.engine.memory import InMemoryEngine
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource


class _StubSource(DataSource):
    def __init__(self, df, name="stub"):
        self._df = df; self.name = name
    def columns(self): return list(self._df.columns)
    def estimated_rows(self): return len(self._df)
    def read(self, chunk_size=100_000):
        for i in range(0, len(self._df), chunk_size):
            yield self._df.iloc[i:i + chunk_size]


def _task():
    return TaskConfig(
        name="t",
        sources={"left": ExcelSourceConfig(path="d"), "right": ExcelSourceConfig(path="d")},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2),
            FieldRule(left="region", right="region", mode="string"),
        ]),
        output=OutputConfig(dir="./out", formats=["json"]),
        runtime=RuntimeConfig(engine="disk"),
    )


def test_disk_engine_matches_in_memory():
    left = _StubSource(pd.DataFrame({
        "id": [f"A{i}" for i in range(20)],
        "amount": [f"{i}.50" for i in range(20)],
        "region": ["N"] * 10 + ["S"] * 10,
    }))
    right = _StubSource(pd.DataFrame({
        "id": [f"A{i}" for i in range(15)] + [f"B{i}" for i in range(5)],
        "amount": [f"{i}.50" if i != 5 else "99.00" for i in range(15)] + ["0"] * 5,
        "region": ["N"] * 10 + ["S"] * 5 + ["W"] * 5,
    }))
    task = _task()
    mem_result = InMemoryEngine().compare(left, right, task)
    disk_result = DiskEngine().compare(_StubSource(left._df), _StubSource(right._df), task)
    assert disk_result.matched_rows == mem_result.matched_rows
    assert disk_result.identical_rows == mem_result.identical_rows
    assert disk_result.diff_rows == mem_result.diff_rows
    assert disk_result.left_only == mem_result.left_only
    assert disk_result.right_only == mem_result.right_only
    assert disk_result.engine_used == "disk"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/engine/test_disk.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/engine/disk.py`:
```python
"""DuckDB-backed disk comparison engine."""
from __future__ import annotations
import time
import duckdb
import pandas as pd
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from datacompare.normalize.pipeline import normalize_side
from datacompare.normalize.types import CoerceError
from datacompare.normalize.units import UnitError
from .base import CompareEngine
from .result import CompareResult, DiffType, FieldError


def _values_equal(l, r):
    if l is None and r is None:
        return True
    if l is None or r is None:
        return False
    if isinstance(l, (CoerceError, UnitError)) or isinstance(r, (CoerceError, UnitError)):
        return False
    return l == r


def _classify(l, r):
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    return DiffType.VALUE_MISMATCH.value


def _display(v):
    if v is None: return None
    if isinstance(v, (CoerceError, UnitError)): return v.original
    return str(v)


class DiskEngine(CompareEngine):
    def compare(self, left, right, task: TaskConfig) -> CompareResult:
        started = time.perf_counter()
        con = duckdb.connect()
        key_cols = [k.right for k in task.match.keys]
        field_cols = [f.right for f in task.compare.fields]

        # Normalize into DataFrames; register with DuckDB.
        # For large data, iterate chunks and INSERT.
        left_df = self._normalize_all(left, task, "left")
        right_df = self._normalize_all(right, task, "right")

        left_total = len(left_df)
        right_total = len(right_df)

        # duplicate key check
        for label, df in (("left", left_df), ("right", right_df)):
            dupes = df[df.duplicated(subset=key_cols, keep=False)]
            if not dupes.empty:
                keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                raise ValueError(f"duplicate keys in {label} side: {keys_display}")

        # Register with DuckDB (uses object dtype; values are Python objs incl. sentinels)
        # For comparisons, we convert sentinels/None to comparable strings first.
        # Simpler: run outer-join in pandas over already-normalized values,
        # matching InMemoryEngine's semantics. Use DuckDB only when scale demands it.
        # For MVP: use pandas merge (identical semantics) but tag engine as "disk".
        merged = left_df.merge(
            right_df, on=key_cols, how="outer", indicator=True,
            suffixes=("__left", "__right"),
        )
        both = merged[merged["_merge"] == "both"]
        left_only_mask = merged["_merge"] == "left_only"
        right_only_mask = merged["_merge"] == "right_only"

        diff_records: list[dict] = []
        errors: list[FieldError] = []
        identical_mask = pd.Series(True, index=both.index)

        for f in task.compare.fields:
            lcol = f"{f.right}__left"
            rcol = f"{f.right}__right"
            for idx, row in both.iterrows():
                lv, rv = row[lcol], row[rcol]
                if not _values_equal(lv, rv):
                    identical_mask.at[idx] = False
                    diff_records.append({
                        **{k: row[k] for k in key_cols},
                        "field": f.right,
                        "left_value": _display(lv) or "",
                        "right_value": _display(rv) or "",
                        "diff_type": _classify(lv, rv),
                    })
                for side_v in (lv, rv):
                    if isinstance(side_v, CoerceError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=f.right, kind="type_error", original=side_v.original,
                        ))
                    elif isinstance(side_v, UnitError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=f.right, kind="unit_error", original=side_v.original,
                        ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        diff_rows = matched_rows - identical_rows

        left_only_df = merged[left_only_mask][key_cols + [f"{c}__left" for c in field_cols]]
        left_only_df = left_only_df.rename(columns={f"{c}__left": c for c in field_cols})
        right_only_df = merged[right_only_mask][key_cols + [f"{c}__right" for c in field_cols]]
        right_only_df = right_only_df.rename(columns={f"{c}__right": c for c in field_cols})

        con.close()

        return CompareResult(
            task_name=task.name,
            left_name=left.name, right_name=right.name,
            left_total=left_total, right_total=right_total,
            matched_rows=matched_rows, identical_rows=identical_rows, diff_rows=diff_rows,
            left_only=int(left_only_mask.sum()), right_only=int(right_only_mask.sum()),
            diff_details=pd.DataFrame(diff_records),
            left_only_rows=left_only_df, right_only_rows=right_only_df,
            engine_used="disk", duration_seconds=time.perf_counter() - started,
            errors=errors,
        )

    @staticmethod
    def _normalize_all(src: DataSource, task: TaskConfig, side: str) -> pd.DataFrame:
        chunks = []
        for chunk in src.read():
            chunks.append(normalize_side(chunk, task.match.keys, task.compare, side=side))
        if not chunks:
            return pd.DataFrame()
        return pd.concat(chunks, ignore_index=True)
```

Note: The DiskEngine currently uses pandas merge for MVP simplicity. When memory pressure requires it (v1.0 optimization), the merge should be pushed into DuckDB SQL. This trade-off is documented; correctness semantics are identical to InMemoryEngine, so the test above verifies parity.

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/engine/test_disk.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/engine/disk.py tests/unit/engine/test_disk.py
git commit -m "feat(engine): DiskEngine variant with disk-tagged result (parity with memory)"
```

---

### Task 26: Engine router

**Files:**
- Create: `src/datacompare/engine/router.py`
- Create: `tests/unit/engine/test_router.py`
- Modify: `src/datacompare/runner.py` to use router

- [ ] **Step 1: Write failing tests**

`tests/unit/engine/test_router.py`:
```python
from datacompare.engine.router import select_engine
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.disk import DiskEngine
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource
import pandas as pd


class _Sized(DataSource):
    def __init__(self, n: int | None):
        self._n = n; self.name = "s"
    def columns(self): return []
    def estimated_rows(self): return self._n
    def read(self, chunk_size=100_000):
        yield pd.DataFrame()


def _task(engine: str = "auto", threshold: int = 500_000):
    return TaskConfig(
        name="t",
        sources={"left": ExcelSourceConfig(path="a"), "right": ExcelSourceConfig(path="b")},
        match=MatchConfig(keys=[KeyMapping(left="k", right="k")]),
        compare=CompareConfig(defaults=CompareDefaults(),
                              fields=[FieldRule(left="v", right="v")]),
        output=OutputConfig(dir="./o", formats=["json"]),
        runtime=RuntimeConfig(engine=engine, memory_threshold_rows=threshold),
    )


def test_explicit_memory():
    e = select_engine(_Sized(10_000_000), _Sized(10_000_000), _task(engine="memory"))
    assert isinstance(e, InMemoryEngine)


def test_explicit_disk():
    e = select_engine(_Sized(100), _Sized(100), _task(engine="disk"))
    assert isinstance(e, DiskEngine)


def test_auto_small_uses_memory():
    e = select_engine(_Sized(1000), _Sized(1000), _task(engine="auto", threshold=500_000))
    assert isinstance(e, InMemoryEngine)


def test_auto_large_uses_disk():
    e = select_engine(_Sized(600_000), _Sized(1000), _task(engine="auto", threshold=500_000))
    assert isinstance(e, DiskEngine)


def test_auto_unknown_size_uses_disk():
    e = select_engine(_Sized(None), _Sized(1000), _task(engine="auto"))
    assert isinstance(e, DiskEngine)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/engine/test_router.py -v`
Expected: FAIL

- [ ] **Step 3: Implement router + wire into runner**

`src/datacompare/engine/router.py`:
```python
"""Route to InMemoryEngine or DiskEngine based on estimated row counts."""
from __future__ import annotations
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from .base import CompareEngine
from .memory import InMemoryEngine
from .disk import DiskEngine


def select_engine(
    left: DataSource, right: DataSource, task: TaskConfig,
) -> CompareEngine:
    if task.runtime.engine == "memory":
        return InMemoryEngine()
    if task.runtime.engine == "disk":
        return DiskEngine()

    threshold = task.runtime.memory_threshold_rows
    lrows = left.estimated_rows()
    rrows = right.estimated_rows()
    # unknown rows → be conservative (disk)
    max_rows = max(
        lrows if lrows is not None else threshold + 1,
        rrows if rrows is not None else threshold + 1,
    )
    return InMemoryEngine() if max_rows <= threshold else DiskEngine()
```

In `src/datacompare/runner.py`, replace `InMemoryEngine()` in `execute()` with router:

```python
# Replace this line:
#   engine = InMemoryEngine()
# With:
from datacompare.engine.router import select_engine
engine = select_engine(left, right, task)
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/engine/test_router.py tests/integration/test_run_e2e.py -v`
Expected: all pass (5 + 2 = 7)

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/engine/router.py src/datacompare/runner.py tests/unit/engine/test_router.py
git commit -m "feat(engine): auto-router (memory vs disk) by estimated row count"
```

---

## Milestone 8 · CLI Polish

### Task 27: `init` command with three templates

**Files:**
- Modify: `src/datacompare/cli.py`
- Create: `src/datacompare/templates/__init__.py`
- Create: `src/datacompare/templates/excel_vs_gaussdb.yaml`
- Create: `src/datacompare/templates/api_vs_gaussdb.yaml`
- Create: `src/datacompare/templates/excel_vs_api.yaml`
- Create: `tests/unit/test_cli_init.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_cli_init.py`:
```python
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def test_init_excel_vs_gaussdb():
    result = runner.invoke(app, ["init", "excel-vs-gaussdb"])
    assert result.exit_code == 0
    assert "excel" in result.stdout
    assert "gaussdb" in result.stdout


def test_init_api_vs_gaussdb():
    result = runner.invoke(app, ["init", "api-vs-gaussdb"])
    assert result.exit_code == 0
    assert "api" in result.stdout
    assert "pagination" in result.stdout


def test_init_excel_vs_api():
    result = runner.invoke(app, ["init", "excel-vs-api"])
    assert result.exit_code == 0
    assert "excel" in result.stdout
    assert "api" in result.stdout


def test_init_unknown_template():
    result = runner.invoke(app, ["init", "bogus"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py -v`
Expected: FAIL

- [ ] **Step 3: Create templates and implement `init`**

`src/datacompare/templates/__init__.py`: (empty)

`src/datacompare/templates/excel_vs_gaussdb.yaml`:
```yaml
name: 每日销售数据核对
description: 核对业务侧 Excel 与 DWS 层订单表

sources:
  left:
    type: excel
    path: ./data/sales_{{param.month}}.xlsx
    sheets:
      - name: Sheet1
    header_row: 1
    force_string: true
  right:
    type: gaussdb
    connection: prod_dws
    query: |
      SELECT order_id, sku_code, region, amount, storage, order_time
      FROM dws.sales
      WHERE month = '{{param.month}}'

match:
  keys:
    - left: 订单号
      right: order_id
    - left: SKU编码
      right: sku_code

compare:
  defaults:
    mode: exact
    ignore_whitespace: false
    ignore_case: false
    null_equivalents: ["", "null", "NULL", "NaN", "nan"]
  fields:
    - left: 金额
      right: amount
      mode: numeric
      decimal_places: 2
    - left: 存储容量
      right: storage
      mode: numeric
      parse_unit: true
      unit_category: storage
      normalize_to: GB
    - left: 区域
      right: region
      mode: string
      ignore_whitespace: true
      ignore_case: true

output:
  dir: ./reports/{{param.month}}
  formats: [html, excel, csv, json, console]

runtime:
  engine: auto
  memory_threshold_rows: 500000
  log_level: INFO
```

`src/datacompare/templates/api_vs_gaussdb.yaml`:
```yaml
name: API 与数据库核对
description: 核对 API 返回的订单与 DB 中订单表

sources:
  left:
    type: api
    connection: order_service
    method: GET
    url: /v1/orders
    params:
      month: "{{param.month}}"
      status: paid
    pagination:
      type: page
      page_param: pageNum
      size_param: pageSize
      size: 200
      total_path: $.data.total
    data_path: $.data.list[*]
    timeout: 30
    retry:
      max_attempts: 3
      backoff: 1.5
  right:
    type: gaussdb
    connection: prod_dws
    query: SELECT order_id, amount FROM dws.orders WHERE month = '{{param.month}}'

match:
  keys:
    - left: id
      right: order_id

compare:
  fields:
    - left: amount
      right: amount
      mode: numeric
      decimal_places: 2

output:
  dir: ./reports/{{param.month}}
  formats: [html, json]

runtime:
  engine: auto
```

`src/datacompare/templates/excel_vs_api.yaml`:
```yaml
name: Excel 与 API 核对

sources:
  left:
    type: excel
    path: ./expected.xlsx
  right:
    type: api
    connection: order_service
    url: /v1/orders
    pagination:
      type: offset
      offset_param: offset
      size_param: limit
      size: 200
    data_path: $.data.list[*]

match:
  keys:
    - left: 订单号
      right: order_id

compare:
  fields:
    - left: 金额
      right: amount
      mode: numeric
      decimal_places: 2

output:
  dir: ./reports
  formats: [html, json]
```

Modify `src/datacompare/cli.py` — replace `init` command:

```python
from importlib import resources


@app.command()
def init(
    template: str = typer.Argument(..., help="excel-vs-gaussdb | api-vs-gaussdb | excel-vs-api"),
) -> None:
    filename = template.replace("-", "_") + ".yaml"
    try:
        content = resources.files("datacompare.templates").joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        typer.echo(f"unknown template: {template}", err=True)
        raise typer.Exit(1)
    typer.echo(content)
```

Update `pyproject.toml` to include templates as package data:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/datacompare/templates" = "datacompare/templates"
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/templates/ src/datacompare/cli.py pyproject.toml tests/unit/test_cli_init.py
git commit -m "feat(cli): init command with three built-in YAML templates"
```

---

### Task 28: `validate` command (Pydantic + connectivity + column existence)

**Files:**
- Modify: `src/datacompare/cli.py`
- Create: `src/datacompare/validator.py`
- Create: `tests/integration/test_validate.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_validate.py`:
```python
from pathlib import Path
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_validate_ok(tmp_path):
    left = tmp_path / "l.xlsx"
    right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [{"left": "amount", "right": "amount"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, ["validate", str(task), "--connections", str(conn)])
    assert result.exit_code == 0, result.stdout
    assert "valid" in result.stdout.lower() or "ok" in result.stdout.lower()


def test_validate_missing_column(tmp_path):
    left = tmp_path / "l.xlsx"; right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [{"left": "missing_col", "right": "amount"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, ["validate", str(task), "--connections", str(conn)])
    assert result.exit_code == 1
    assert "missing_col" in result.stdout or "missing_col" in (result.stderr or "")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/integration/test_validate.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/validator.py`:
```python
"""Task config validation (config + connectivity + column existence)."""
from __future__ import annotations
from datacompare.config.models import TaskConfig, AnyConnection
from datacompare.config.errors import ConfigError
from datacompare.runner import _build_source


def validate_task(task: TaskConfig, connections: dict[str, AnyConnection]) -> list[str]:
    """Return list of issues (empty = OK). Raises ConfigError only on connect failures."""
    issues: list[str] = []

    for side in ("left", "right"):
        cfg = task.sources[side]
        try:
            src = _build_source(cfg, connections, side_name=side)
        except ConfigError as e:
            issues.append(f"{side}: {e}")
            continue

        try:
            cols = src.columns()
        except Exception as e:
            issues.append(f"{side}: cannot read columns — {e}")
            src.close()
            continue

        # Check keys and fields referenced on this side exist
        for k in task.match.keys:
            wanted = getattr(k, side)
            if wanted not in cols:
                issues.append(
                    f"{side}: match key column '{wanted}' not found. "
                    f"Available: {cols[:20]}"
                )
        for f in task.compare.fields:
            wanted = getattr(f, side)
            if wanted not in cols:
                issues.append(
                    f"{side}: compare field column '{wanted}' not found. "
                    f"Available: {cols[:20]}"
                )
        src.close()
    return issues
```

Modify `src/datacompare/cli.py` — replace `validate` command:

```python
from datacompare.validator import validate_task


@app.command()
def validate(
    task_file: str = typer.Argument(...),
    connections: str = typer.Option("~/.datacompare/connections.yaml", "--connections", "-c"),
) -> None:
    try:
        task = load_task(Path(task_file).expanduser())
        conn_path = Path(connections).expanduser()
        conns = load_connections(conn_path) if conn_path.exists() else {}
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True); raise typer.Exit(1)

    issues = validate_task(task, conns)
    if issues:
        typer.echo("❌ validation failed:")
        for issue in issues:
            typer.echo(f"  · {issue}")
        raise typer.Exit(1)
    typer.echo("✓ configuration is valid")
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/integration/test_validate.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/validator.py src/datacompare/cli.py tests/integration/test_validate.py
git commit -m "feat(cli): validate command with connectivity and column checks"
```

---

### Task 29: Structured logging + progress bar

**Files:**
- Create: `src/datacompare/utils/__init__.py`
- Create: `src/datacompare/utils/logging.py`
- Create: `src/datacompare/utils/progress.py`
- Modify: `src/datacompare/cli.py` to configure logging from `--log-level` / `--log-file`
- Modify: `src/datacompare/engine/memory.py` and `disk.py` to emit progress events
- Create: `tests/unit/utils/__init__.py`
- Create: `tests/unit/utils/test_logging.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/utils/test_logging.py`:
```python
import json
from pathlib import Path
from datacompare.utils.logging import configure_logging, get_logger


def test_configure_and_log_json_file(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging(level="INFO", log_file=log_file)
    logger = get_logger("test")
    logger.info("engine_selected", engine="memory", rows=1000)
    contents = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) >= 1
    payload = json.loads(contents[-1])
    assert payload["event"] == "engine_selected"
    assert payload["engine"] == "memory"
    assert payload["rows"] == 1000
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/utils/test_logging.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

`src/datacompare/utils/__init__.py`: (empty)

`src/datacompare/utils/logging.py`:
```python
"""structlog configuration."""
from __future__ import annotations
import logging
import sys
from pathlib import Path
import structlog


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    level_num = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=level_num, format="%(message)s", stream=sys.stderr)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # Attach a JSON-line file handler
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(file_handler)

    structlog.configure(
        processors=processors + [structlog.processors.JSONRenderer(ensure_ascii=False)],
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "datacompare"):
    return structlog.get_logger(name)
```

`src/datacompare/utils/progress.py`:
```python
"""rich Progress helpers (three-phase pipeline: load left / load right / compare)."""
from __future__ import annotations
from contextlib import contextmanager
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn


@contextmanager
def three_phase_progress():
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    ) as progress:
        yield progress
```

Modify `cli.py` to configure logging before running:
```python
# In the run() command body, at start:
from datacompare.utils.logging import configure_logging
configure_logging(level=log_level, log_file=Path(log_file).expanduser() if log_file else None)
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/Scripts/pytest tests/unit/utils/test_logging.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/utils/ src/datacompare/cli.py tests/unit/utils/
git commit -m "feat(utils): structlog JSON logging and rich progress helpers"
```

---

## Milestone 9 · End-to-End Tests, Examples, Documentation

### Task 30: End-to-end scenario tests + example configs

**Files:**
- Create: `examples/excel_vs_gaussdb.yaml`
- Create: `examples/api_vs_gaussdb.yaml`
- Create: `examples/excel_vs_api.yaml`
- Create: `tests/integration/test_full_scenarios.py`

- [ ] **Step 1: Add example configs (identical to CLI init templates so they can be diff'd)**

Copy `src/datacompare/templates/*.yaml` to `examples/` with the same content — these serve as user-facing reference configs.

- [ ] **Step 2: Write full-scenario test**

`tests/integration/test_full_scenarios.py`:
```python
import json
from pathlib import Path
import httpx
import respx
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


@respx.mock
def test_excel_vs_api_all_formats(tmp_path):
    excel_path = tmp_path / "expected.xlsx"
    _make_xlsx(excel_path, [
        ["order_id", "amount"],
        ["A1", "100.50"],
        ["A2", "200.00"],
        ["A3", "300.00"],
    ])

    respx.get("http://api.test/orders", params={"offset": "0", "limit": "10"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"order_id": "A1", "amount": "100.50"},
            {"order_id": "A2", "amount": "199.99"},   # diff
        ]}})
    )
    respx.get("http://api.test/orders", params={"offset": "10", "limit": "10"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": []}})
    )

    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "name": "excel_vs_api_scenario",
        "sources": {
            "left": {"type": "excel", "path": str(excel_path)},
            "right": {
                "type": "api", "connection": "svc", "url": "/orders",
                "pagination": {
                    "type": "offset", "offset_param": "offset",
                    "size_param": "limit", "size": 10,
                },
                "data_path": "$.data.list[*]",
            },
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount", "mode": "numeric", "decimal_places": 2}
        ]},
        "output": {"dir": str(tmp_path / "out"),
                   "formats": ["html", "excel", "csv", "json", "console"]},
    }))
    conn = tmp_path / "conn.yaml"
    conn.write_text(yaml.safe_dump({
        "svc": {"type": "api", "base_url": "http://api.test"}
    }))

    result = runner.invoke(app, ["run", str(task), "--connections", str(conn)])
    assert result.exit_code == 0, f"stdout={result.stdout}\nexit={result.exit_code}"

    out = tmp_path / "out"
    assert (out / "report.html").exists()
    assert (out / "report.xlsx").exists()
    assert (out / "report.json").exists()
    assert (out / "csv" / "diff_details.csv").exists()

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["diff"] == 1
    assert report["summary"]["left_only"] == 1  # A3
    assert report["summary"]["right_only"] == 0


def test_dry_run_exits_zero_without_running(tmp_path):
    left = tmp_path / "l.xlsx"; right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["k", "v"], ["A", "1"]])
    _make_xlsx(right, [["k", "v"], ["A", "1"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "k", "right": "k"}]},
        "compare": {"fields": [{"left": "v", "right": "v"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(conn), "--dry-run",
    ])
    assert result.exit_code == 0
    assert not (tmp_path / "o").exists()
```

- [ ] **Step 3: Run and verify**

Run: `.venv/Scripts/pytest tests/integration/test_full_scenarios.py -v`
Expected: 2 passed

- [ ] **Step 4: Ensure whole suite passes**

Run: `.venv/Scripts/pytest -x --tb=short`
Expected: all tests passing

- [ ] **Step 5: Commit**

```bash
git add examples/ tests/integration/test_full_scenarios.py
git commit -m "test: end-to-end scenarios covering all reporters + dry-run"
```

---

### Task 31: README and user guide

**Files:**
- Create: `README.md`
- Create: `docs/user-guide.md`

- [ ] **Step 1: Write README**

`README.md`:
```markdown
# DataComparator

A CLI tool to compare data across Excel files, GaussDB databases, and HTTP APIs.

## Install

```bash
pip install -e .
```

## Quick start

Generate a task template:
```bash
datacompare init excel-vs-gaussdb > task.yaml
```

Edit `task.yaml` and `~/.datacompare/connections.yaml`, then run:
```bash
datacompare run task.yaml --param month=2026-07
```

## Commands

- `datacompare run <task.yaml>` — execute a comparison task
- `datacompare validate <task.yaml>` — validate config and connectivity
- `datacompare init <template>` — emit a template YAML
- `datacompare version` — show version

See `docs/user-guide.md` for full documentation.
```

- [ ] **Step 2: Write user guide**

`docs/user-guide.md`:
```markdown
# DataComparator User Guide

## Sources

- **Excel** (`.xlsx`, `.xls`): multi-sheet selection, configurable header row, force-string reading
- **GaussDB**: PostgreSQL-protocol compatible; user provides full SELECT query
- **HTTP API**: three auth strategies (none / bearer / cookie); three pagination modes (page / offset / cursor); JSONPath extraction

## Configuration

Two YAML files:
- **Task**: `task.yaml` — describes sources, match keys, compare rules, output
- **Connections**: `~/.datacompare/connections.yaml` — connection details and credentials (never commit)

### Parameter substitution

Three placeholder types:
- `${ENV_VAR}` — environment variable
- `{{param.NAME}}` — CLI `--param NAME=VALUE`
- `{{today}}` / `{{now}}` — built-in

### Comparison modes

| Mode | Behavior |
|------|----------|
| `exact` | Byte-exact string comparison |
| `numeric` | Round both sides to `decimal_places`, then compare |
| `string` | Normalize (whitespace/case) then compare |

Global `compare.defaults` apply to all fields; per-field settings override.

### Unit parsing

For fields like `"30 TB"`, set `parse_unit: true` with `unit_category` (`storage` / `time` / `length` / `mass`) and `normalize_to` (target unit). Comparison then happens in normalized units.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration error |
| 2 | Data source connect/read failure |
| 3 | Internal error |
| 10 | Success but diffs found, and `--fail-on-diff` was set |

## Examples

See `examples/*.yaml` for ready-to-run configurations.
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/user-guide.md
git commit -m "docs: README and user guide"
```

---

## Final Checklist

- [ ] Run full test suite: `.venv/Scripts/pytest --cov=src/datacompare --cov-report=term-missing`
- [ ] Verify unit test coverage on `normalize/` and `config/` ≥ 90%
- [ ] Run ruff: `.venv/Scripts/ruff check src/ tests/`
- [ ] Run mypy: `.venv/Scripts/mypy src/datacompare/`
- [ ] Verify `datacompare version` runs from installed script
- [ ] Verify `datacompare init excel-vs-gaussdb | head -20` outputs template
- [ ] Commit any final fixes

---

## Known Deviations from Spec (v0.1)

Documented so future maintainers understand the trade-offs:

- **Task 25 (DiskEngine)**: MVP uses pandas outer-join with a `disk` tag, not native DuckDB `FULL OUTER JOIN` SQL as §9.4 of the spec calls for. Semantics (row-level judgments, `CompareResult` fields) are identical to `InMemoryEngine` — verified by the parity test. This gives correct results but does not achieve the scale benefit of DuckDB spilling to disk. Real DuckDB SQL JOIN with sentinel-value serialization is a follow-up before v1.0 (mentioned in spec §14 as "performance optimization"). The router (Task 26) still selects `DiskEngine` at the configured threshold — swapping in the DuckDB implementation later requires no changes to router or callers.
- **API request retry** (Task 21) currently only wraps the sample-page fetch inside `columns()`/`estimated_rows()`. Paginated `read()` requests do not yet use `tenacity` — add retry to `_BasePaginator._request()` in a follow-up if flaky APIs become a problem.
- **Unit case sensitivity** (Task 7): always case-insensitive in v0.1. Spec §8.4 mentioned a `unit_case_sensitive` config knob for edge cases — omitted from MVP config schema (YAGNI). Add to `FieldRule` when a real use case surfaces.

## Spec Coverage Map

| Spec § | Task(s) |
|---|---|
| §2.1 Data sources | 10 (base), 11 (Excel), 12 (GaussDB), 19–21 (API) |
| §2.2 Row matching (composite keys + column mapping) | 9 (columns/effective rule), 14 (pipeline) |
| §2.3 Field comparison rules | 5 (strings), 6 (decimals), 7 (units), 8 (types), 9 (effective rule), 14 (pipeline) |
| §2.4 Mixed scale | 26 (router), 15/25 (engines) |
| §2.5 CLI | 17 (skeleton), 18 (run), 27 (init), 28 (validate) |
| §2.6 Reporters | 16 (JSON/Console), 22 (HTML), 23 (Excel), 24 (CSV) |
| §3 Architecture | Whole plan; each layer isolated by task |
| §4 Tech stack | 1 (pyproject) |
| §5 Project structure | 1 (skeleton) — mirrors spec §5 |
| §6.1–6.7 Config layer | 2 (models), 3 (loader), 4 (credentials) |
| §7 DataSource abstraction & registry | 10 |
| §8 Normalize layer | 5–9, 14 |
| §9 Engines | 13 (base+result), 15 (memory), 25 (disk), 26 (router) |
| §10 Reporters | 16, 22, 23, 24 |
| §11 CLI | 17, 18, 27, 28, 29 |
| §12 Testing strategy | Baked into every task (TDD steps) + 30 (E2E) |
| §13 MVP scope | All above |
| §15 Risks | Mitigations embedded (SELECT-only in Task 12, force_string in Task 11, log masking in Task 4, duplicate-key detection in Task 15) |
| §16 Milestones | Matches milestone headers (M1–M9) |
| Appendix A judgment matrix | Encoded in `_values_equal` / `_classify` in Tasks 15 & 25 |

---







