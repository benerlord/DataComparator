# JDBC JAR 路径加载期 resolve 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GaussDBTConnection.jdbc_jar_path` 在 pydantic 加载期就 resolve 成绝对路径（含 `~` 展开）+ 存在性校验，避免 batch 模式下 CWD 变化导致第二个 sub-task 抛 `FileNotFoundException`。

**Architecture:** `@field_validator("jdbc_jar_path", mode="after")` 用 `Path(v).expanduser().resolve()` 转绝对路径，缺文件抛 `ValueError`（pydantic 包装成 `ValidationError`）。runtime `_ensure_jvm` 里的 `is_file()` 检查保留作 safety net。

**Tech Stack:** Python 3.11+ / pydantic v2 / pathlib

**规范来源:** `docs/superpowers/specs/2026-07-27-jdbc-jar-path-resolve-design.md`

---

## 文件结构

| 文件 | 变化类型 | 责任 |
|---|---|---|
| `src/datacompare/config/models.py` | 修改 | `GaussDBTConnection` 加 `@field_validator("jdbc_jar_path")` |
| `tests/unit/config/test_credentials.py` | 追加 | 4 个新单元测试（相对/绝对/~/不存在） |
| `tests/unit/config/test_gaussdb_discriminator.py` | 修改 | `test_isinstance_check_works_on_union_type` 里假路径 `"p"` 迁移到真文件 |
| `tests/unit/sources/test_gaussdb_driver_dispatch.py` | 修改 | `test_t_variant_creates_jdbc_driver` 里假路径 `"p"` 迁移到真文件 |
| `tests/unit/sources/test_gaussdb_jdbc_unit.py` | 修改 | `_creds` helper 从 `/nonexistent.jar` 迁移到 tmp_path 真文件 |
| `README.md` | 修改 | GaussDB T 连接示例后加"路径提示" |

**已确认不受影响**：
- `tests/integration/sources/test_gaussdb_jdbc_via_postgres.py` 已经用真实的 `pg_jdbc_jar` 路径
- `tests/unit/test_cli_init.py` 涉及模板文件，不实例化 `GaussDBTConnection`

---

## Task 依赖顺序

1. Task 1：Validator 实现 + 4 个新测试
2. Task 2：迁移 3 个旧测试（使用假 `jdbc_jar_path` 的）
3. Task 3：文档

Task 1 会让 Task 2 的旧测试挂——所以 Task 1 完成后需要立刻做 Task 2 才能全绿。可以并入同一 commit，但为了清晰保持分开。

---

### Task 1: `GaussDBTConnection` 加 field validator + 4 个新测试

**Files:**
- Modify: `src/datacompare/config/models.py`（`GaussDBTConnection` 类）
- Test: `tests/unit/config/test_credentials.py`（append 4 tests）

- [ ] **Step 1: 写 4 个失败测试**

追加到 `tests/unit/config/test_credentials.py`。文件顶部先补 import（检查是否已有；若无则追加）：

```python
from pathlib import Path
from pydantic import ValidationError
from datacompare.config.models import GaussDBTConnection
```

然后追加：

```python
def test_gaussdb_t_relative_jdbc_jar_path_resolved_to_absolute(tmp_path, monkeypatch):
    """相对 jdbc_jar_path 在 load 时被 resolve 成绝对路径。"""
    jar = tmp_path / "driver.jar"
    jar.write_bytes(b"fake")
    monkeypatch.chdir(tmp_path)
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://host:port/db",
        jdbc_jar_path="driver.jar",   # 相对路径
        jdbc_driver_class="com.x.Y",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path).is_absolute()
    assert Path(conn.jdbc_jar_path) == jar.resolve()


def test_gaussdb_t_home_expansion_in_jdbc_jar_path(tmp_path, monkeypatch):
    """~ 展开为 $HOME。"""
    home = tmp_path / "home"
    home.mkdir()
    jar_dir = home / ".datacompare"
    jar_dir.mkdir()
    jar = jar_dir / "driver.jar"
    jar.write_bytes(b"fake")
    monkeypatch.setenv("HOME", str(home))         # POSIX
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://x:1/y",
        jdbc_jar_path="~/.datacompare/driver.jar",
        jdbc_driver_class="c.X",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path) == jar.resolve()


def test_gaussdb_t_missing_jdbc_jar_path_raises_at_load():
    """JAR 不存在 → 加载期就报错，不用等到运行时。"""
    with pytest.raises(ValidationError, match="jdbc_jar_path 不存在"):
        GaussDBTConnection(
            variant="t",
            jdbc_url="jdbc:zenith://x:1/y",
            jdbc_jar_path="/nonexistent/absolute/path/x.jar",
            jdbc_driver_class="c.X",
            user="u", password="p",
        )


def test_gaussdb_t_absolute_jdbc_jar_path_untouched(tmp_path):
    """绝对路径不受影响（除了可能的 symlink resolve）。"""
    jar = tmp_path / "driver.jar"
    jar.write_bytes(b"fake")
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://x:1/y",
        jdbc_jar_path=str(jar),
        jdbc_driver_class="c.X",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path) == jar.resolve()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py::test_gaussdb_t_relative_jdbc_jar_path_resolved_to_absolute -v`
Expected: FAIL — 当前 model 没有 validator，`jdbc_jar_path` 保持原样 `"driver.jar"`（相对），`Path("driver.jar").is_absolute()` 是 False，断言挂

## Step 3: 修改 `src/datacompare/config/models.py`

在 `GaussDBTConnection` 类（约第 238-248 行）的定义**结尾**（`jdbc_properties` 字段后）追加 validator。先确认顶部 imports 有 `Path` 和 `field_validator`：

- 检查 `from pathlib import Path` 是否已存在（若无，加到 imports 区）
- 检查 pydantic import 是否含 `field_validator`（很可能已有；若无，追加）

在 `GaussDBTConnection` 末尾追加：

```python
    @field_validator("jdbc_jar_path", mode="after")
    @classmethod
    def _resolve_and_check_jar(cls, v: str) -> str:
        """v0.10+: 加载期把相对路径 resolve 成绝对路径 + ~ 展开 + 存在性校验。

        避免 batch 模式下 CWD 在 sub-task 之间变化导致 JVM 找不到 JAR。
        相对路径按运行 datacompare 命令时的 CWD 解析。
        """
        resolved = Path(v).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(
                f"jdbc_jar_path 不存在: {resolved} (原值: {v}, 已按 CWD 解析)"
            )
        return str(resolved)
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `.venv/Scripts/pytest tests/unit/config/test_credentials.py -v -k "gaussdb_t"`
Expected: 4 个新测试全 PASS。

- [ ] **Step 5: 全量回归（预期部分旧测试挂）**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: **PARTIAL FAIL** — Task 1 会让 3 个旧测试挂（`test_gaussdb_driver_dispatch.py::test_t_variant_creates_jdbc_driver`、`test_gaussdb_discriminator.py::test_isinstance_check_works_on_union_type`、`test_gaussdb_jdbc_unit.py` 的 `_creds` helper 被调用的所有测试）。**Task 2 会修**。

**不要 commit** 到这里再前进——先跑 Task 2 让全套变绿，然后一起或分开 commit。

- [ ] **Step 6: 暂存这一步的修改（不 commit）**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_credentials.py
```
（Task 2 完成后一起 commit，或分开 commit 都可以——见 Task 2 结尾）

---

### Task 2: 迁移 3 个使用假 `jdbc_jar_path` 的旧测试

**Files:**
- Modify: `tests/unit/config/test_gaussdb_discriminator.py`
- Modify: `tests/unit/sources/test_gaussdb_driver_dispatch.py`
- Modify: `tests/unit/sources/test_gaussdb_jdbc_unit.py`

背景：三个旧测试用 `jdbc_jar_path="p"` 或 `"/nonexistent.jar"` 只是为了满足 model 字段非空要求，不真的走 JVM。Task 1 的 validator 现在会拒绝这些假路径。迁移到 `tmp_path` 里造真文件。

## Step 1: 修改 `tests/unit/config/test_gaussdb_discriminator.py`

找到 `test_isinstance_check_works_on_union_type`（约第 88-96 行）：

```python
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

改为接受 `tmp_path` fixture 并造真 JAR：

```python
def test_isinstance_check_works_on_union_type(tmp_path):
    """Python 3.10+ isinstance(x, X | Y) support — required by runner.py:27"""
    a = GaussDBAConnection(host="h", database="d", user="u", password="p")
    assert isinstance(a, GaussDBConnection)
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    t = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path=str(jar),
        jdbc_driver_class="c", user="u", password="p",
    )
    assert isinstance(t, GaussDBConnection)
```

同一文件另一处（约第 80-85 行的 `data = {..."jdbc_jar_path": "p"...}`）—— 那里是**测另一个失败路径**（`ValidationError, match="extra"`，因为 data 里含额外 `host` 字段）。validator 会不会先于 extra-forbid 触发？

**关键**：pydantic v2 里 `extra="forbid"` 是 model_config 层面的检查，通常先于 field_validator 执行；字段值 `"p"` 走 field_validator 时会挂，但 extra 字段可能先触发。为了保险，把 `"jdbc_jar_path": "p"` 也改成真文件，避免哪个 error 先出现的不确定性。

找到那个测试（`test_..._raises_extra` 之类，约第 74-85 行）：

```python
def test_type_adapter_rejects_extras_on_t_variant():
    """T variant 不允许 A variant 的字段（如 host）。"""
    data = {
        "type": "gaussdb", "variant": "t", "host": "h",
        "jdbc_url": "j", "jdbc_jar_path": "p", "jdbc_driver_class": "c",
        "user": "u", "password": "p",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)
```

改为接受 `tmp_path`：

```python
def test_type_adapter_rejects_extras_on_t_variant(tmp_path):
    """T variant 不允许 A variant 的字段（如 host）。"""
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    data = {
        "type": "gaussdb", "variant": "t", "host": "h",
        "jdbc_url": "j", "jdbc_jar_path": str(jar), "jdbc_driver_class": "c",
        "user": "u", "password": "p",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)
```

**注意**：先 Read 这个文件确认测试函数的实际名字（我猜的可能不完全对），再改。

## Step 2: 修改 `tests/unit/sources/test_gaussdb_driver_dispatch.py`

找到 `test_t_variant_creates_jdbc_driver`（约第 15-23 行）：

```python
def test_t_variant_creates_jdbc_driver():
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    conn = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path="p",
        jdbc_driver_class="c", user="u", password="p",
    )
    src = GaussDBSource(cfg, conn)
    assert type(src._driver).__name__ == "JdbcDriver"
```

改为：

```python
def test_t_variant_creates_jdbc_driver(tmp_path):
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    conn = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path=str(jar),
        jdbc_driver_class="c", user="u", password="p",
    )
    src = GaussDBSource(cfg, conn)
    assert type(src._driver).__name__ == "JdbcDriver"
```

## Step 3: 修改 `tests/unit/sources/test_gaussdb_jdbc_unit.py::_creds`

找到 `_creds` helper（约第 8-17 行）：

```python
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
```

改为把 `jdbc_jar_path` 变成参数，caller 提供真路径。全部 `_creds` 调用点都要改，或者给 `_creds` 一个默认真路径。**推荐做法**：让 `_creds` 接收 `jar_path` 参数：

```python
def _creds(jar_path: str, **overrides):
    base = dict(
        variant="t",
        jdbc_url="jdbc:zenith:@//h:1611/svc",
        jdbc_jar_path=jar_path,
        jdbc_driver_class="com.huawei.gauss.jdbc.ZenithDriver",
        user="u", password="p",
    )
    base.update(overrides)
    return GaussDBTConnection(**base)
```

**先 Read 整个 `test_gaussdb_jdbc_unit.py` 文件**看有多少地方调 `_creds()`，每处都要加 `jar_path` 参数（通常都用 `tmp_path / "fake.jar"` 先 `write_bytes(b"")` 再传路径）。如果调用点不多（≤3 处），直接改；如果多，用一个 pytest fixture 造 jar 更清爽：

```python
@pytest.fixture
def fake_jar(tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    return str(jar)


def _creds(jar_path: str, **overrides):
    ...


def test_something(fake_jar):
    conn = _creds(jar_path=fake_jar)
    ...
```

**特别注意** `test_missing_jar_raises_config_error`（第 20-24 行）—— 这个测试专门验证 `_ensure_jvm` 在 JAR 不存在时抛 `ConfigError`。它直接把 `str(tmp_path / "missing.jar")`（不 write）传给 `_ensure_jvm(missing)`，不走 model 构造，**不受影响**。保持原样。

## Step 4: 运行迁移后的测试

Run: `.venv/Scripts/pytest tests/unit/config/test_gaussdb_discriminator.py tests/unit/sources/test_gaussdb_driver_dispatch.py tests/unit/sources/test_gaussdb_jdbc_unit.py -v`
Expected: 全 PASS。

## Step 5: 全量回归

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（预期 357 passed，2 skipped——原 353 + 4 新测试）。

## Step 6: Commit

```bash
git add src/datacompare/config/models.py \
        tests/unit/config/test_credentials.py \
        tests/unit/config/test_gaussdb_discriminator.py \
        tests/unit/sources/test_gaussdb_driver_dispatch.py \
        tests/unit/sources/test_gaussdb_jdbc_unit.py
git commit -m "$(cat <<'EOF'
fix(config): jdbc_jar_path 加载期 resolve 成绝对路径 + 存在性校验 (v0.10)

修复 batch 模式下相对 jdbc_jar_path 在第二个 sub-task 起因 CWD 变化抛
Java FileNotFoundException 的问题：GaussDBTConnection 加
@field_validator("jdbc_jar_path") 在加载期 Path().expanduser().resolve()
转成绝对路径 + is_file() 校验，缺文件立即 ValidationError。runtime
_ensure_jvm 的 is_file() 检查作 safety net 保留。~ 展开自动生效。

三个使用假 jdbc_jar_path='p' / '/nonexistent.jar' 的旧测试迁移到 tmp_path
造真 JAR。test_missing_jar_raises_config_error 直接调 _ensure_jvm 不走
model 构造，无影响。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

（如果偏好分开 commit：Task 1 单独 commit，Task 2 迁移单独 commit 也可以。这里因为 Task 1 单独 commit 会让 pytest 挂，选择合并 commit 保证任何单个 SHA 都是绿的。）

---

### Task 3: 文档提示

**Files:**
- Modify: `README.md`（GaussDB T 连接示例节）

- [ ] **Step 1: Grep 找 GaussDB T 相关文档位置**

Run: `grep -n "variant: t" README.md` 或 `grep -n "jdbc_jar_path" README.md`

预期找到形如：
```yaml
prod_dws:
  type: gaussdb
  variant: t
  jdbc_url: ...
  jdbc_jar_path: /path/to/gsjdbc4.jar
  ...
```

- [ ] **Step 2: 在示例 YAML 之后追加"路径提示"段落**

在 GaussDB T 连接示例的 YAML 代码块**之后**追加：

```markdown

**路径提示**（v0.10+）：`jdbc_jar_path` 支持相对路径（按运行 `datacompare`
命令时的 CWD 解析）、`~` 展开、绝对路径三种写法。加载期即转成绝对路径存入
内存，batch 模式跨 sub-task 不会受 CWD 变化影响。为最大可移植性推荐用
绝对路径或 `~/.datacompare/xxx.jar`：

```yaml
jdbc_jar_path: /opt/gauss/gsjdbc4.jar         # 绝对路径（推荐）
jdbc_jar_path: ~/.datacompare/gsjdbc4.jar     # $HOME 展开（推荐）
jdbc_jar_path: ./drivers/gsjdbc4.jar          # 相对 CWD（谨慎，batch 里易踩坑）
```
```

- [ ] **Step 3: 验证文档格式**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（文档变更不影响测试）。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: v0.10 jdbc_jar_path 路径提示 — README

GaussDB T 连接示例后加"路径提示"段落：说明 v0.10 起 jdbc_jar_path 支持
相对/~ 展开/绝对三种写法，加载期即转绝对路径避免 batch 模式 CWD 变化问题。
推荐绝对路径或 ~/.datacompare/xxx.jar 写法。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## 完成后总校验

- [ ] 全量测试：`.venv/Scripts/pytest tests/ -q` → 全绿（预期 357 passed / 2 skipped）
- [ ] Lint：`.venv/Scripts/ruff check src/ tests/` → 无新增 error
- [ ] 类型：`.venv/Scripts/mypy src/datacompare/` → 无新增 error
- [ ] 手动烟测：`connections.yaml` 里 `jdbc_jar_path` 写相对路径（如 `.datacompare/xxx.jar`），跑 `datacompare validate connections/task.yaml`。以前会通过（validate 不 touch JAR），现在会立即报"jdbc_jar_path 不存在: <绝对路径> (原值: .datacompare/xxx.jar, 已按 CWD 解析)"，用户能一眼看到问题
