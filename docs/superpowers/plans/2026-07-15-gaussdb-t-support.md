# GaussDB T Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GaussDB T (OLTP) support alongside the existing GaussDB A (psycopg2) support, via JDBC + JayDeBeApi, with zero breakage to current A users.

**Architecture:** Introduce a `GaussDBDriver` abstraction inside `sources/gaussdb.py`. Refactor existing psycopg2 code into `PostgresDriver`. Add new `JdbcDriver` in `sources/gaussdb_jdbc.py` (lazily imported). Pydantic discriminated union on `variant` field routes config → driver. `variant: a` is the default, preserving backward compatibility.

**Tech Stack:** Python 3.11+, Pydantic v2 discriminated union, JayDeBeApi 1.2+, JPype1 1.5+, JRE 8+ (only for T users), postgresql-42.x.jar (test-only, for validating JayDeBeApi wrapper).

**Reference spec:** `docs/superpowers/specs/2026-07-15-gaussdb-t-support-design.md`

---

## Milestone 1 · Config Model Split

### Task 1: Split GaussDBConnection into A/T with discriminated union

**Files:**
- Modify: `src/datacompare/config/models.py`
- Modify: `tests/integration/sources/test_gaussdb.py:14,43` (rename `GaussDBConnection` → `GaussDBAConnection`)
- Create: `tests/unit/config/test_gaussdb_discriminator.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/config/test_gaussdb_discriminator.py`:
```python
import pytest
from pydantic import TypeAdapter, ValidationError
from datacompare.config.models import (
    GaussDBAConnection, GaussDBTConnection, GaussDBConnection, AnyConnection,
)


def test_a_variant_defaults_when_omitted():
    """variant field defaults to 'a' when not provided (backward compat)"""
    data = {
        "type": "gaussdb", "host": "h", "database": "d",
        "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBAConnection)
    assert conn.variant == "a"
    assert conn.port == 5432
    assert conn.ssl == "require"


def test_a_variant_explicit():
    data = {
        "type": "gaussdb", "variant": "a",
        "host": "h", "database": "d", "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBAConnection)


def test_t_variant_requires_jdbc_fields():
    data = {"type": "gaussdb", "variant": "t", "user": "u", "password": "p"}
    with pytest.raises(ValidationError) as exc:
        TypeAdapter(AnyConnection).validate_python(data)
    errors = str(exc.value)
    assert "jdbc_url" in errors
    assert "jdbc_jar_path" in errors
    assert "jdbc_driver_class" in errors


def test_t_variant_complete():
    data = {
        "type": "gaussdb", "variant": "t",
        "jdbc_url": "jdbc:zenith:@//h:1611/svc",
        "jdbc_jar_path": "/opt/gsjdbc4.jar",
        "jdbc_driver_class": "com.huawei.gauss.jdbc.ZenithDriver",
        "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBTConnection)
    assert conn.jdbc_properties == {}


def test_t_variant_with_properties():
    data = {
        "type": "gaussdb", "variant": "t",
        "jdbc_url": "jdbc:zenith:@//h:1611/svc",
        "jdbc_jar_path": "/opt/gsjdbc4.jar",
        "jdbc_driver_class": "com.huawei.gauss.jdbc.ZenithDriver",
        "user": "u", "password": "p",
        "jdbc_properties": {"loginTimeout": "30", "fetchSize": "1000"},
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert conn.jdbc_properties["loginTimeout"] == "30"


def test_a_variant_rejects_jdbc_fields():
    """extra=forbid: A variant with jdbc_url should be rejected"""
    data = {
        "type": "gaussdb", "variant": "a",
        "host": "h", "database": "d", "user": "u", "password": "p",
        "jdbc_url": "jdbc:...",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)


def test_t_variant_rejects_host_field():
    """extra=forbid: T variant with host should be rejected"""
    data = {
        "type": "gaussdb", "variant": "t", "host": "h",
        "jdbc_url": "j", "jdbc_jar_path": "p", "jdbc_driver_class": "c",
        "user": "u", "password": "p",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)


def test_isinstance_check_works_on_union_type():
    """Python 3.10+ isinstance(x, X | Y) support — required by runner.py:27"""
    a = GaussDBAConnection(host="h", database="d", user="u", password="p")
    assert isinstance(a, GaussDBConnection)
    t = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path="p",
        jdbc_driver_class="c", user="u", password="p",
    )
    assert isinstance(t, GaussDBConnection)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/config/test_gaussdb_discriminator.py -v`
Expected: FAIL with `ImportError: cannot import name 'GaussDBAConnection'` (or similar)

- [ ] **Step 3: Update `src/datacompare/config/models.py`**

Locate the existing `GaussDBConnection` class (around line 150) and **replace it entirely** with:

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


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


# For Pydantic validation dispatch, wrap with discriminator.
_GaussDBConnectionValidated = Annotated[
    GaussDBAConnection | GaussDBTConnection,
    Field(discriminator="variant"),
]
```

Then update the `AnyConnection` definition (also in `models.py`) — replace:
```python
AnyConnection = GaussDBConnection | APIConnection
```
with:
```python
AnyConnection = _GaussDBConnectionValidated | APIConnection
```

- [ ] **Step 4: Migrate existing test file**

Edit `tests/integration/sources/test_gaussdb.py`:

Line 14: change `from datacompare.config.models import GaussDBSourceConfig, GaussDBConnection` to:
```python
from datacompare.config.models import GaussDBSourceConfig, GaussDBAConnection
```

Line 43 (the `return GaussDBConnection(` call inside `creds` fixture): change to:
```python
return GaussDBAConnection(
```

- [ ] **Step 5: Run all tests to verify no regression**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: All previously passing tests still pass; the 8 new discriminator tests pass. Total: previous_count + 8, and the GaussDB integration test still skips (no Docker) but at collection stage doesn't fail.

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_gaussdb_discriminator.py tests/integration/sources/test_gaussdb.py
git commit -m "feat(config): split GaussDB connection into A/T variants with discriminator"
```

---

## Milestone 2 · Optional Dependency

### Task 2: Add `[gaussdb-t]` optional dependency group

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Locate `[project.optional-dependencies]` section and add:
```toml
[project.optional-dependencies]
# existing dev = [...] stays
gaussdb-t = [
    "JayDeBeApi>=1.2.3",
    "JPype1>=1.5",
]
```

Then update the existing `dev` group so devs get the T deps automatically:
```toml
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "testcontainers>=4.0",
    "syrupy>=4.6",
    "ruff>=0.4",
    "mypy>=1.10",
    # New: also install the T-variant dependencies for full test coverage
    "JayDeBeApi>=1.2.3",
    "JPype1>=1.5",
]
```

- [ ] **Step 2: Reinstall to pick up new deps**

Run:
```bash
.venv/Scripts/pip install -e ".[dev]"
```
Expected: JayDeBeApi and JPype1 install successfully.

- [ ] **Step 3: Verify imports work**

Run:
```bash
.venv/Scripts/python -c "import jaydebeapi, jpype; print(jaydebeapi.__version__); print(jpype.__version__)"
```
Expected: Both versions printed, no errors.

- [ ] **Step 4: Verify existing test suite still passes**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: Same pass count as end of Task 1 (nothing new should have broken).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add [gaussdb-t] optional dependency for JayDeBeApi + JPype1"
```

---

## Milestone 3 · Driver Abstraction

### Task 3: Extract GaussDBDriver abstract + refactor into PostgresDriver

**Files:**
- Modify: `src/datacompare/sources/gaussdb.py`
- Create: `tests/unit/sources/test_gaussdb_driver_dispatch.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_gaussdb_driver_dispatch.py`:
```python
import pytest
from datacompare.config.models import (
    GaussDBSourceConfig, GaussDBAConnection, GaussDBTConnection,
)
from datacompare.sources.gaussdb import GaussDBSource, GaussDBDriver, PostgresDriver


def test_a_variant_creates_postgres_driver():
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    conn = GaussDBAConnection(host="h", database="d", user="u", password="p")
    src = GaussDBSource(cfg, conn)
    assert isinstance(src._driver, PostgresDriver)


def test_t_variant_creates_jdbc_driver():
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    conn = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path="p",
        jdbc_driver_class="c", user="u", password="p",
    )
    src = GaussDBSource(cfg, conn)
    # Lazy import: check class name to avoid importing JdbcDriver here
    assert type(src._driver).__name__ == "JdbcDriver"


def test_gaussdb_driver_is_abstract():
    with pytest.raises(TypeError):
        GaussDBDriver()  # abstract, cannot instantiate


def test_select_only_validation_still_enforced():
    cfg = GaussDBSourceConfig(connection="c", query="INSERT INTO t VALUES (1)")
    conn = GaussDBAConnection(host="h", database="d", user="u", password="p")
    from datacompare.config.errors import ConfigError
    with pytest.raises(ConfigError, match="SELECT"):
        GaussDBSource(cfg, conn)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_gaussdb_driver_dispatch.py -v`
Expected: FAIL with `ImportError: cannot import name 'GaussDBDriver'` (or similar).

- [ ] **Step 3: Rewrite `src/datacompare/sources/gaussdb.py`**

Replace the entire file with:

```python
"""GaussDB data source with pluggable driver (Postgres protocol / JDBC)."""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from typing import Iterator, Any
import psycopg2
import pandas as pd
from .base import DataSource
from .registry import register_source
from datacompare.config.models import (
    GaussDBSourceConfig, GaussDBAConnection, GaussDBTConnection,
)
from datacompare.config.errors import ConfigError

_SELECT_RE = re.compile(r"^\s*(--[^\n]*\n\s*)*SELECT\b", re.IGNORECASE)


class GaussDBDriver(ABC):
    """Abstraction over concrete database driver (psycopg2 or JDBC).

    Returns raw Python value tuples; GaussDBSource handles string coercion.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection (idempotent)."""

    @abstractmethod
    def close(self) -> None:
        """Release connection resources."""

    @abstractmethod
    def columns_for(self, query: str) -> list[str]:
        """Return column names for `query` without fetching data rows."""

    @abstractmethod
    def count_for(self, query: str) -> int:
        """Return SELECT COUNT(*) FROM (query) t."""

    @abstractmethod
    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple[Any, ...]]]:
        """Stream query results as chunks of raw row tuples."""


class PostgresDriver(GaussDBDriver):
    """psycopg2-based driver for GaussDB A / DWS / openGauss / GaussDB 100 PG-compat."""

    def __init__(self, creds: GaussDBAConnection):
        self.creds = creds
        self._conn = None

    def connect(self) -> None:
        if self._conn is None:
            self._conn = psycopg2.connect(
                host=self.creds.host, port=self.creds.port,
                dbname=self.creds.database, user=self.creds.user,
                password=self.creds.password, sslmode=self.creds.ssl,
            )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def columns_for(self, query: str) -> list[str]:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({query}) t LIMIT 0")
            return [d.name for d in cur.description]

    def count_for(self, query: str) -> int:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM ({query}) t")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple]]:
        self.connect()
        with self._conn.cursor(name="datacompare_stream") as cur:
            cur.itersize = chunk_size
            cur.execute(query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                yield rows


@register_source("gaussdb")
class GaussDBSource(DataSource):
    def __init__(self, config: GaussDBSourceConfig, connection, name: str = ""):
        self.config = config
        self.creds = connection
        self.name = name or f"gaussdb:{self._display_target()}"
        self._driver: GaussDBDriver = self._make_driver(connection)
        self._validate_read_only()

    @staticmethod
    def _make_driver(creds) -> GaussDBDriver:
        if isinstance(creds, GaussDBAConnection):
            return PostgresDriver(creds)
        if isinstance(creds, GaussDBTConnection):
            # Lazy import: only pull in JdbcDriver when actually needed,
            # so users who don't use variant=t are never forced to install jaydebeapi.
            from .gaussdb_jdbc import JdbcDriver
            return JdbcDriver(creds)
        raise ConfigError(f"unknown GaussDB variant: {type(creds).__name__}")

    def _display_target(self) -> str:
        if isinstance(self.creds, GaussDBAConnection):
            return f"{self.creds.host}/{self.creds.database}"
        return self.creds.jdbc_url

    def _validate_read_only(self) -> None:
        if not _SELECT_RE.match(self.config.query):
            raise ConfigError(
                "only SELECT queries are permitted",
                path="sources.query",
                suggestion="wrap or rewrite as SELECT statement",
            )

    def columns(self) -> list[str]:
        return self._driver.columns_for(self.config.query)

    def estimated_rows(self) -> int | None:
        return self._driver.count_for(self.config.query)

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        cols = self.columns()
        for rows in self._driver.fetch_chunks(self.config.query, chunk_size):
            df = pd.DataFrame(rows, columns=cols)
            df = df.map(lambda v: None if v is None else str(v))
            df = df.astype(object)
            yield df

    def close(self) -> None:
        self._driver.close()
```

- [ ] **Step 4: Run all tests to verify no regression**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: All existing tests still pass; the 4 new dispatch tests pass. The GaussDB integration test (`tests/integration/sources/test_gaussdb.py`) will still skip on machines without Docker but must not error at collection stage.

Note: `test_t_variant_creates_jdbc_driver` triggers the lazy import of `gaussdb_jdbc.py` which doesn't exist yet. Fix: create a minimal stub before running this test, or defer this specific test to Task 4. **Simpler approach**: create an empty `src/datacompare/sources/gaussdb_jdbc.py` now with just a class stub:

```python
"""Placeholder — replaced with full implementation in Task 4."""
from .gaussdb import GaussDBDriver

class JdbcDriver(GaussDBDriver):
    def __init__(self, creds):
        self.creds = creds
    def connect(self): raise NotImplementedError
    def close(self): pass
    def columns_for(self, q): raise NotImplementedError
    def count_for(self, q): raise NotImplementedError
    def fetch_chunks(self, q, n): raise NotImplementedError
```

This lets Task 3 tests pass (they only check `type(src._driver).__name__ == "JdbcDriver"`, not actual functionality).

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/gaussdb.py src/datacompare/sources/gaussdb_jdbc.py tests/unit/sources/test_gaussdb_driver_dispatch.py
git commit -m "refactor(sources): extract GaussDBDriver abstract with PostgresDriver + JdbcDriver stub"
```

---

## Milestone 4 · JdbcDriver Implementation

### Task 4: Implement JdbcDriver with JVM lifecycle + unit tests

**Files:**
- Modify: `src/datacompare/sources/gaussdb_jdbc.py` (replace stub with full implementation)
- Create: `tests/unit/sources/test_gaussdb_jdbc_unit.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/sources/test_gaussdb_jdbc_unit.py`:
```python
import sys
import pytest
from pathlib import Path
from datacompare.config.models import GaussDBTConnection
from datacompare.config.errors import ConfigError


def _creds(**overrides):
    base = dict(
        variant="t",
        jdbc_url="jdbc:zenith:@//h:1611/svc",
        jdbc_jar_path="/nonexistent.jar",
        jdbc_driver_class="com.huawei.gauss.jdbc.ZenithDriver",
        user="u", password="p",
    )
    base.update(overrides)
    return GaussDBTConnection(**base)


def test_missing_jar_raises_config_error(tmp_path):
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm
    missing = str(tmp_path / "missing.jar")
    with pytest.raises(ConfigError, match="JDBC JAR 不存在"):
        _ensure_jvm(missing)


def test_no_jaydebeapi_installed_gives_install_hint(mocker, tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")  # exists but empty (JAR content not validated in _ensure_jvm)
    mocker.patch.dict(sys.modules, {"jaydebeapi": None, "jpype": None})
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm
    with pytest.raises(ConfigError, match="pip install 'datacompare\\[gaussdb-t\\]'"):
        _ensure_jvm(str(jar))


def test_ensure_jvm_is_idempotent(mocker, tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    fake_jpype = mocker.MagicMock()
    # First call sees JVM not started; subsequent see it started
    fake_jpype.isJVMStarted.side_effect = [False, True, True]
    fake_jpype.getDefaultJVMPath.return_value = "/fake/libjvm.so"
    mocker.patch.dict(sys.modules, {"jaydebeapi": mocker.MagicMock(), "jpype": fake_jpype})

    # Force reimport so the freshly-mocked jpype is used
    if "datacompare.sources.gaussdb_jdbc" in sys.modules:
        del sys.modules["datacompare.sources.gaussdb_jdbc"]
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm

    _ensure_jvm(str(jar))
    _ensure_jvm(str(jar))
    _ensure_jvm(str(jar))
    assert fake_jpype.startJVM.call_count == 1


def test_url_properties_appended_no_existing_qs():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds(jdbc_properties={"loginTimeout": "30", "fetchSize": "1000"})
    driver = JdbcDriver(creds)
    url = driver._build_url_with_properties()
    assert url.startswith("jdbc:zenith:@//h:1611/svc?")
    assert "loginTimeout=30" in url
    assert "fetchSize=1000" in url
    assert url.count("?") == 1


def test_url_properties_appended_when_qs_exists():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds(
        jdbc_url="jdbc:zenith:@//h:1611/svc?existing=x",
        jdbc_properties={"loginTimeout": "30"},
    )
    driver = JdbcDriver(creds)
    url = driver._build_url_with_properties()
    assert url == "jdbc:zenith:@//h:1611/svc?existing=x&loginTimeout=30"


def test_url_no_properties_unchanged():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds()  # no jdbc_properties
    driver = JdbcDriver(creds)
    assert driver._build_url_with_properties() == "jdbc:zenith:@//h:1611/svc"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/sources/test_gaussdb_jdbc_unit.py -v`
Expected: Tests fail (either function not defined, or the stub raises NotImplementedError).

- [ ] **Step 3: Replace `src/datacompare/sources/gaussdb_jdbc.py` with full implementation**

```python
"""GaussDB T driver via JDBC + JayDeBeApi (embedded JVM).

JVM is a process-level singleton, lazily started on first T connection.
Users who only use variant=a never trigger JVM startup.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator, Any
from datacompare.config.models import GaussDBTConnection
from datacompare.config.errors import ConfigError
from .gaussdb import GaussDBDriver


# Module-level flag: JVM lifecycle spans the entire Python process.
_JVM_STARTED = False


def _ensure_jvm(jar_path: str) -> None:
    """Start JVM (if not already) and register the JDBC JAR on classpath.

    Idempotent: safe to call multiple times.
    """
    global _JVM_STARTED
    try:
        import jaydebeapi  # noqa: F401
        import jpype
    except ImportError as e:
        raise ConfigError(
            "GaussDB T (variant=t) 需要 JayDeBeApi + JPype，"
            "请安装：pip install 'datacompare[gaussdb-t]'"
        ) from e

    if not Path(jar_path).is_file():
        raise ConfigError(
            f"JDBC JAR 不存在：{jar_path}",
            path="connections.jdbc_jar_path",
            suggestion="从华为支持网站下载 gsjdbc4.jar 后填写正确路径",
        )

    if not jpype.isJVMStarted():
        jpype.startJVM(
            jpype.getDefaultJVMPath(),
            f"-Djava.class.path={jar_path}",
            convertStrings=True,
        )
        _JVM_STARTED = True
    else:
        # JVM already running: try to add this JAR to classpath (multi-T-connection case)
        try:
            jpype.addClassPath(jar_path)
        except AttributeError:
            # JPype < 1.0 doesn't have addClassPath; JAR must have been in initial classpath.
            pass


class JdbcDriver(GaussDBDriver):
    def __init__(self, creds: GaussDBTConnection):
        self.creds = creds
        self._conn = None

    def _build_url_with_properties(self) -> str:
        base = self.creds.jdbc_url
        if not self.creds.jdbc_properties:
            return base
        pairs = "&".join(f"{k}={v}" for k, v in self.creds.jdbc_properties.items())
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{pairs}"

    def connect(self) -> None:
        if self._conn is not None:
            return
        import jaydebeapi
        _ensure_jvm(self.creds.jdbc_jar_path)
        url = self._build_url_with_properties()
        self._conn = jaydebeapi.connect(
            self.creds.jdbc_driver_class,
            url,
            [self.creds.user, self.creds.password],
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _probe_columns(self, cur, query: str) -> list[str]:
        """Try WHERE 1=0 first (Oracle-style dialects); fall back to LIMIT 0."""
        try:
            cur.execute(f"SELECT * FROM ({query}) t WHERE 1=0")
        except Exception:
            cur.execute(f"SELECT * FROM ({query}) t LIMIT 0")
        return [d[0] for d in cur.description]

    def columns_for(self, query: str) -> list[str]:
        self.connect()
        cur = self._conn.cursor()
        try:
            return self._probe_columns(cur, query)
        finally:
            cur.close()

    def count_for(self, query: str) -> int:
        self.connect()
        cur = self._conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM ({query}) t")
            return int(cur.fetchone()[0])
        finally:
            cur.close()

    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple]]:
        self.connect()
        cur = self._conn.cursor()
        try:
            # Hint to JDBC driver about network fetch batch size (best-effort).
            try:
                cur._rs.setFetchSize(chunk_size)  # jaydebeapi cursor exposes ResultSet as _rs
            except Exception:
                pass
            cur.execute(query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                yield rows
        finally:
            cur.close()
```

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/Scripts/pytest tests/unit/sources/test_gaussdb_jdbc_unit.py -v`
Expected: 6 passed.

Also run the full suite: `.venv/Scripts/pytest tests/ -q`
Expected: All existing tests still pass; +6 new tests.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/sources/gaussdb_jdbc.py tests/unit/sources/test_gaussdb_jdbc_unit.py
git commit -m "feat(sources): implement JdbcDriver with JVM lifecycle management"
```

---

## Milestone 5 · Security: Extend Password Masking

### Task 5: Extend mask_password to JDBC URL formats

**Files:**
- Modify: `src/datacompare/config/credentials.py`
- Modify: `tests/unit/config/test_credentials.py`

- [ ] **Step 1: Add failing tests to existing test file**

Append to `tests/unit/config/test_credentials.py`:
```python
def test_mask_password_jdbc_userinfo():
    """JDBC URL with user:password@host form"""
    inp = "jdbc:zenith:@//user:secret@10.0.0.20:1611/svc"
    out = mask_password(inp)
    assert "secret" not in out
    assert "***" in out


def test_mask_password_jdbc_query_string():
    """JDBC URL with password=xxx as query parameter"""
    inp = "jdbc:zenith://host:1611/svc?user=u&password=secret&loginTimeout=30"
    out = mask_password(inp)
    assert "secret" not in out
    assert "password=***" in out


def test_mask_password_jdbc_pwd_query_variant():
    """Some JDBC drivers use pwd= instead of password="""
    inp = "jdbc:gaussdb://host/db?user=u&pwd=secret"
    out = mask_password(inp)
    assert "secret" not in out
    assert "pwd=***" in out


def test_mask_password_no_effect_on_plain_url():
    """URLs without embedded credentials pass through unchanged"""
    inp = "jdbc:postgresql://host:5432/db"
    assert mask_password(inp) == inp
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py -v`
Expected: 4 new tests fail (existing 5 pass).

- [ ] **Step 3: Extend `mask_password` in `src/datacompare/config/credentials.py`**

Locate the existing regex definitions and add two new patterns. Replace the file contents with:

```python
"""Credential resolution helpers: keyring lookup and log masking."""
from __future__ import annotations
import re

# postgresql://user:PASSWORD@host/db  →  postgresql://user:***@host/db
_PWD_DSN_RE = re.compile(r"(://[^:/@]+:)([^@/]+)(@)")
# password=PASSWORD → password=***
_PWD_KW_RE = re.compile(r"(password=)([^\s&]+)")
# pwd=PASSWORD → pwd=*** (alternate JDBC driver convention)
_PWD_KW_PWD_RE = re.compile(r"(\bpwd=)([^\s&]+)")

_KEYRING_RE = re.compile(r"^keyring://([^/]+)/(.+)$")


def mask_password(text: str) -> str:
    """Redact passwords in DSN-style URLs and query parameters.

    Handles:
    - postgresql://u:secret@h/db  (DSN userinfo)
    - jdbc:xxx://u:secret@h/db    (JDBC userinfo)
    - host=x password=secret user=u   (keyword form)
    - jdbc:xxx://h/db?password=secret (query string)
    - jdbc:xxx://h/db?pwd=secret      (query string, alternate key)
    """
    text = _PWD_DSN_RE.sub(r"\1***\3", text)
    text = _PWD_KW_RE.sub(r"\1***", text)
    text = _PWD_KW_PWD_RE.sub(r"\1***", text)
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

Note the change to `_PWD_DSN_RE`: added `/@` to the second character class negation to prevent it matching across path segments. Verify this doesn't break existing tests.

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py -v`
Expected: 9 passed (5 original + 4 new).

Full suite: `.venv/Scripts/pytest tests/ -q`
Expected: All pass, no regression.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/credentials.py tests/unit/config/test_credentials.py
git commit -m "feat(config): extend mask_password to handle JDBC URLs (userinfo, query string)"
```

---

## Milestone 6 · JDBC Integration Test via PostgreSQL

### Task 6: Validate JdbcDriver end-to-end using PG JDBC (no real GaussDB T needed)

**Files:**
- Create: `tests/integration/sources/test_gaussdb_jdbc_via_postgres.py`
- Modify: `.gitignore` (add `tests/fixtures/jars/`)

- [ ] **Step 1: Write test**

`tests/integration/sources/test_gaussdb_jdbc_via_postgres.py`:
```python
"""Integration test: exercise JdbcDriver via PostgreSQL JDBC driver.

Purpose: validate that JayDeBeApi + JVM lifecycle + fetch_chunks work correctly,
without needing an actual GaussDB T instance. The PostgreSQL JDBC driver is
Apache-2.0 licensed and downloaded on-demand.

Skipped when: Docker unavailable, jaydebeapi unavailable, or JVM unavailable.
"""
from __future__ import annotations
import os
import urllib.request
from pathlib import Path
import pytest

# Skip guards
docker = pytest.importorskip("docker")
try:
    _c = docker.from_env()
    _c.ping()
except Exception:
    pytest.skip("Docker daemon not available", allow_module_level=True)

try:
    import jaydebeapi  # noqa: F401
    import jpype  # noqa: F401
except ImportError:
    pytest.skip("jaydebeapi / jpype not installed", allow_module_level=True)

from testcontainers.postgres import PostgresContainer
from datacompare.sources.gaussdb_jdbc import JdbcDriver
from datacompare.config.models import GaussDBTConnection


PG_JDBC_JAR_URL = "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
PG_JDBC_JAR_NAME = "postgresql-42.7.4.jar"
JAR_CACHE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "jars"


@pytest.fixture(scope="module")
def pg_jdbc_jar():
    """Download PostgreSQL JDBC jar into tests/fixtures/jars/ (cached)."""
    JAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = JAR_CACHE_DIR / PG_JDBC_JAR_NAME
    if not target.exists():
        try:
            urllib.request.urlretrieve(PG_JDBC_JAR_URL, str(target))
        except Exception as e:
            pytest.skip(f"Cannot download PG JDBC jar: {e}")
    return target


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
def creds(pg_container, pg_jdbc_jar):
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return GaussDBTConnection(
        variant="t",
        jdbc_url=f"jdbc:postgresql://{host}:{port}/{pg_container.dbname}",
        jdbc_jar_path=str(pg_jdbc_jar),
        jdbc_driver_class="org.postgresql.Driver",
        user=pg_container.username,
        password=pg_container.password,
    )


def test_columns_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        cols = driver.columns_for("SELECT order_id, region, amount FROM sales")
        assert cols == ["order_id", "region", "amount"]
    finally:
        driver.close()


def test_count_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        assert driver.count_for("SELECT * FROM sales") == 3
    finally:
        driver.close()


def test_fetch_chunks_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        chunks = list(driver.fetch_chunks("SELECT * FROM sales ORDER BY order_id", chunk_size=2))
        # Chunks should sum to 3 rows total
        rows = [r for c in chunks for r in c]
        assert len(rows) == 3
        assert rows[0][0] == "A001"
    finally:
        driver.close()


def test_jdbc_properties_appended(creds):
    """URL with jdbc_properties should still connect (postgres driver accepts loginTimeout)."""
    creds_with_props = creds.model_copy(update={"jdbc_properties": {"loginTimeout": "10"}})
    driver = JdbcDriver(creds_with_props)
    try:
        driver.connect()  # Should succeed
        assert driver._conn is not None
    finally:
        driver.close()
```

- [ ] **Step 2: Add `.gitignore` entry**

Add this line to `.gitignore`:
```
tests/fixtures/jars/
```

(Rationale: 1MB+ JAR files shouldn't be committed; download-on-demand is cleaner.)

- [ ] **Step 3: Run test**

Run: `.venv/Scripts/pytest tests/integration/sources/test_gaussdb_jdbc_via_postgres.py -v`
Expected outcomes:
- **If Docker + Java available**: 4 passed (JAR downloaded first run, cached afterwards, ~3-8 seconds due to JVM cold start)
- **If Docker not running**: whole module skipped
- **If Java not installed**: `jpype.startJVM()` fails at first test — this indicates a real environment issue that user needs to resolve (install JRE 8+)

Full suite: `.venv/Scripts/pytest tests/ -q`
Expected: All pass (or skip cleanly).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/sources/test_gaussdb_jdbc_via_postgres.py .gitignore
git commit -m "test(sources): integration test for JdbcDriver via PostgreSQL JDBC (validates JayDeBeApi wrapper without real GaussDB T)"
```

---

## Milestone 7 · Init Template for T Variant

### Task 7: Add `excel-vs-gaussdb-t` init template

**Files:**
- Create: `src/datacompare/templates/excel_vs_gaussdb_t.yaml`
- Modify: `tests/unit/test_cli_init.py` (add test for new template)

- [ ] **Step 1: Add failing test**

Append to `tests/unit/test_cli_init.py`:
```python
def test_init_excel_vs_gaussdb_t():
    result = runner.invoke(app, ["init", "excel-vs-gaussdb-t"])
    assert result.exit_code == 0
    assert "variant: t" in result.stdout
    assert "jdbc_url" in result.stdout
    assert "jdbc_jar_path" in result.stdout
    assert "jdbc_driver_class" in result.stdout
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py::test_init_excel_vs_gaussdb_t -v`
Expected: FAIL — "unknown template: excel-vs-gaussdb-t" (exit code != 0).

- [ ] **Step 3: Create template file**

`src/datacompare/templates/excel_vs_gaussdb_t.yaml`:
```yaml
name: Excel 与 GaussDB T 核对
description: 核对业务侧 Excel 与 GaussDB T (OLTP) 库表

sources:
  left:
    type: excel
    path: ./data/records_{{param.date}}.xlsx
    sheets:
      - name: Sheet1
    header_row: 1
    force_string: true

  right:
    type: gaussdb
    connection: prod_oltp_t     # 引用 connections.yaml
    query: |
      SELECT id, name, amount, updated_at
      FROM app.records
      WHERE dt = '{{param.date}}'

match:
  keys:
    - left: 编号
      right: id

compare:
  defaults:
    mode: exact
    null_equivalents: ["", "null", "NULL", "NaN", "nan"]
  fields:
    - left: 名称
      right: name
      mode: string
      ignore_whitespace: true
    - left: 金额
      right: amount
      mode: numeric
      decimal_places: 2

output:
  dir: ./reports/{{param.date}}
  formats: [html, json, console]

runtime:
  engine: auto
  memory_threshold_rows: 500000
  log_level: INFO

# --- connections.yaml 示例（放在 ~/.datacompare/connections.yaml） ---
# prod_oltp_t:
#   type: gaussdb
#   variant: t                                          # 关键：区分 A / T
#   jdbc_url: "jdbc:zenith:@//10.0.0.20:1611/oltp_svc"  # 从 Data Studio 连接配置复制
#   jdbc_jar_path: /opt/gaussdb/gsjdbc4.jar             # 从华为支持网站下载
#   jdbc_driver_class: com.huawei.gauss.jdbc.ZenithDriver
#   user: analytics_ro
#   password: ${GAUSS_T_PWD}
#   jdbc_properties:                                     # 可选
#     loginTimeout: "30"
```

- [ ] **Step 4: Run test to verify passing**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py -v`
Expected: All 5 tests pass (4 original + 1 new).

Note: since `init` uses `importlib.resources.files("datacompare.templates")`, the template is discovered directly from the source tree in editable install mode. No `pip install -e` re-run needed.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/templates/excel_vs_gaussdb_t.yaml tests/unit/test_cli_init.py
git commit -m "feat(cli): add excel-vs-gaussdb-t init template"
```

---

## Milestone 8 · Documentation

### Task 8: Update README, CLAUDE.md, user-guide with GaussDB T section

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Add T variant section to `README.md`**

In `README.md`, locate the section "### connections.yaml 结构" (under "如何使用"). After the existing "GaussDB" example block, insert a new subsection:

```markdown
#### GaussDB T (OLTP) — 通过 JDBC 连接

GaussDB T 走的不是 PostgreSQL 协议，需要 JDBC 驱动。使用前请：

1. 安装可选依赖（含 JayDeBeApi + JPype1）：
   ```bash
   pip install 'datacompare[gaussdb-t]'
   ```
2. 确保机器上有 **JRE 8+**（`java -version` 能输出版本即可，无需 `java` 命令在 PATH，只要 JPype 能找到 JVM 库）
3. 从**华为支持网站**下载 `gsjdbc4.jar`（License 限制我们不能重新分发）

`connections.yaml` 中的 T 变体配置：
```yaml
prod_oltp_t:
  type: gaussdb
  variant: t                                       # 关键：区分 A / T
  jdbc_url: "jdbc:zenith:@//10.0.0.20:1611/svc"    # 从 Data Studio 连接配置复制
  jdbc_jar_path: /opt/gaussdb/gsjdbc4.jar
  jdbc_driver_class: com.huawei.gauss.jdbc.ZenithDriver
  user: analytics_ro
  password: ${GAUSS_T_PWD}
  jdbc_properties:                                 # 可选，透传给 JDBC driver
    loginTimeout: "30"
    fetchSize: "1000"
```

**注意事项**：
- 首次比对 T 时会有 1-2 秒 JVM 冷启动开销（后续查询无此开销）
- 常驻额外内存约 100-200MB（JVM baseline）
- **只用 GaussDB A 的用户完全不受影响** —— JVM 只在实际访问 T 时才启动
```

Also update the "### 数据源类型速查" section: locate the `**GaussDB**（`type: gaussdb`）` block and append after it:

```markdown
**GaussDB T**（`type: gaussdb, variant: t`）
```yaml
sources:
  right:
    type: gaussdb
    connection: prod_oltp_t
    query: SELECT ... FROM ... WHERE ...    # 与 A 变体相同的 SELECT
```
连接配置差异见前节。SQL 语法遵循 GaussDB T 方言（近 Oracle 风格）。
```

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, locate the "### 关键约束" section. Add these two bullets at the end:

```markdown
- **GaussDB 有两个变体 A/T**（v0.2 起）：A 用 psycopg2（PostgreSQL 协议），T 用 JDBC（JayDeBeApi + gsjdbc4.jar）。共用 `type: gaussdb`，用 `variant: a\|t` 字段区分。默认 `a`，向后兼容。
- **`GaussDBConnection` 是联合类型**（`GaussDBAConnection | GaussDBTConnection`），不能作为构造器调用。分派用 `isinstance` 检查具体子类。
```

In the "### 已知偏离" section, remove or update item 1 (about DiskEngine) if needed and add:

```markdown
5. **GaussDB T 集成测试通过 PG JDBC 代理验证**（`test_gaussdb_jdbc_via_postgres.py`）：目的是验证 JayDeBeApi 封装本身，不验证 GaussDB T 特定行为。真机 T 测试通过设置环境变量 `GAUSSDB_T_TEST_URL / _JAR / _CLASS / _USER / _PWD` 激活。
```

- [ ] **Step 3: Update `docs/user-guide.md`**

Locate the "## Sources" section. Update the GaussDB entry:

Replace:
```markdown
- **GaussDB**: PostgreSQL-protocol compatible; user provides full SELECT query
```

With:
```markdown
- **GaussDB A** (DWS / openGauss / GaussDB 100 PG-compat mode): PostgreSQL-protocol compatible via psycopg2; user provides full SELECT query. Default when `variant` is omitted.
- **GaussDB T** (OLTP, `variant: t`): JDBC via JayDeBeApi + gsjdbc4.jar. Requires `pip install 'datacompare[gaussdb-t]'` and JRE 8+. See README for connection example.
```

- [ ] **Step 4: Verify no code changes broke docs rendering**

The docs are Markdown — no test. But run full suite once more as sanity check:
```bash
.venv/Scripts/pytest tests/ -q
```
Expected: All tests still pass, same count as end of Task 7.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/user-guide.md
git commit -m "docs: GaussDB T variant usage, installation, and driver setup"
```

---

## Final Checklist

- [ ] Full test suite: `.venv/Scripts/pytest --cov=src/datacompare --cov-report=term-missing`
- [ ] Coverage on config models and driver dispatch: **100%**
- [ ] Coverage on JdbcDriver (excluding actual JDBC calls): **≥ 90%**
- [ ] Ruff clean: `.venv/Scripts/ruff check src/ tests/`
- [ ] Mypy clean: `.venv/Scripts/mypy src/datacompare/`
- [ ] `datacompare init excel-vs-gaussdb-t` outputs template correctly
- [ ] Verify no regression: `datacompare init excel-vs-gaussdb`, `api-vs-gaussdb`, `excel-vs-api` all still work
- [ ] If pushing: `git push origin main`

---

## Spec Coverage Map

| Spec § | Task |
|---|---|
| §2.1 User-facing YAML for A/T | T1 (Pydantic models) |
| §2.2 Field difference table | T1 (models enforce with `extra=forbid`) |
| §2.3 JDBC execution model (embedded JVM) | T4 (`_ensure_jvm` + JVM singleton) |
| §3.1 Layered architecture | T3 (extract `GaussDBDriver`) |
| §3.2 File impact table | T1, T3, T4, T5, T7, T8 |
| §4 Pydantic discriminated union | T1 |
| §5.1 Driver abstract | T3 |
| §5.2 PostgresDriver refactor | T3 |
| §5.3 JdbcDriver (JVM, URL builder, WHERE 1=0, setFetchSize) | T4 |
| §5.4 GaussDBSource thin wrapper | T3 |
| §6 `[gaussdb-t]` optional dependency | T2 |
| §7.1 Unit tests (discriminator, dispatch, JVM idempotent, URL builder, install hints) | T1, T3, T4 |
| §7.2.1 Integration test via PG JDBC | T6 |
| §7.2.2 Real T tests via env vars | Deferred to user-side (documented in T8 CLAUDE.md update) |
| §8 Migration path (4 independent commits) | T1, T3, T4, T8 respectively (T2/T5/T6/T7 are supplementary) |
| §9 Risk mitigations | Embedded in respective tasks (T4 for JVM/JAR, T5 for masking, T4 for WHERE 1=0 fallback) |
| §10.1 MVP inclusions | All 8 tasks |
| §10.2 YAGNI exclusions | Not built (Kerberos, connection pool, multi-JAR, auto-download) |
