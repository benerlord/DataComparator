# JDBC JAR 路径加载期 resolve 设计规范

**日期：** 2026-07-27
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划（bug fix 性质）
**目标版本：** v0.10

## 问题背景

用户报告：使用 `batch.yaml` 跑多 sub-task 比对时，**第一个 sub-task 成功，
从第二个开始报错**：

```
java.io.FileNotFoundException: D:\pythonProject\DataComparator-main\src\datacompare\sources.datacompare\com.huawei.gauss.jdbc.ZenithDriver-V300R001C00SPC100B210.jar
```

用户的 `connections.yaml` 里 `jdbc_jar_path` 写的是**相对路径**（`.datacompare/xxx.jar`
形式）。分析：

- 第一个 sub-task 时进程 CWD 恰好是项目根目录，相对路径能找到 JAR，JVM 启动成功
- 第二个 sub-task 时 CWD 已经变化（batch 执行、log 目录切换等），相对路径失效
- JVM 通过 `jpype.addClassPath(jar_path)` 尝试挂载 JAR 时，Java 层抛
  `FileNotFoundException`

**痛点**：
- 错误发生在**运行中途**，不是加载期，用户已经跑了一半才发现路径问题
- 错误信息是 Java stack trace，用户很难关联到"YAML 里 `jdbc_jar_path`
  写的是相对路径"这个根因
- CWD 依赖使得同一份 YAML 在不同工作目录下行为不一致，不可移植

## 方案概览

**根本修复**：在 `GaussDBTConnection` 的 pydantic validator 里，把
`jdbc_jar_path` 在**加载期**就 resolve 成绝对路径 + 检查文件存在性。

- 相对路径按用户运行 `datacompare` 命令时的 CWD 解析（跟 shell 命令行工具
  惯例一致）
- 自动展开 `~`（`Path.expanduser()`），支持 `~/.datacompare/xxx.jar` 写法
- 文件不存在 → 加载期就 `ValidationError`，不用等到第二个 sub-task 才炸
- 一旦转成绝对路径存进 model，下游任何 CWD 变化都不再影响 JVM

## 改动细节

### 改动 1：`GaussDBTConnection` 加 field validator

`src/datacompare/config/models.py`：

```python
from pathlib import Path
from pydantic import field_validator


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

### 改动 2：`_ensure_jvm` 保留现有 `is_file()` 检查

不删。作为 safety net：若有代码绕过 validator 直接构造
`GaussDBTConnection`（比如测试代码 monkeypatch model 字段），仍能明确报错。
运行到 `_ensure_jvm` 时，正常路径下 `jar_path` 已经是绝对且存在，
`is_file()` 立即通过。

### 改动 3：文档提示

`README.md` GaussDB T 章节示例连接配置末尾加一句：

> **路径提示**：`jdbc_jar_path` 支持相对路径（按运行 `datacompare` 命令时
> 的 CWD 解析）、`~` 展开、绝对路径三种写法。加载期即转成绝对路径存入
> 内存，batch 模式跨 sub-task 不会受 CWD 变化影响。为最大可移植性推荐用
> 绝对路径或 `~/.datacompare/xxx.jar`。

## 测试

新增到 `tests/unit/config/test_credentials.py`（或 `test_models.py`，跟已有
`GaussDBTConnection` 测试同处）：

### `test_gaussdb_t_relative_jdbc_jar_path_resolved_to_absolute`

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
```

### `test_gaussdb_t_home_expansion_in_jdbc_jar_path`

```python
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
```

### `test_gaussdb_t_missing_jdbc_jar_path_raises_at_load`

```python
def test_gaussdb_t_missing_jdbc_jar_path_raises_at_load():
    """JAR 不存在 → 加载期就报错，不用等到运行时。"""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="jdbc_jar_path 不存在"):
        GaussDBTConnection(
            variant="t",
            jdbc_url="jdbc:zenith://x:1/y",
            jdbc_jar_path="/nonexistent/absolute/path/x.jar",
            jdbc_driver_class="c.X",
            user="u", password="p",
        )
```

### `test_gaussdb_t_absolute_jdbc_jar_path_untouched`

```python
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

### 回归

- 现有 `tests/unit/config/test_credentials.py` 里已有的 `GaussDBTConnection`
  测试可能用了假路径 → 需要迁移到 `tmp_path` 里造真文件（少数几个测试）
- `tests/unit/sources/test_gaussdb_jdbc_unit.py` — 检查 mock 场景下是否
  绕过了 validator（若直接用 `GaussDBTConnection.model_construct` 或
  bypass 就 OK；若正常构造需要真 JAR）
- `tests/integration/sources/test_gaussdb_jdbc_via_postgres.py` — Docker
  测试，PG JDBC JAR 应该真实存在，无影响

### 验证命令

```bash
.venv/Scripts/pytest tests/ -q         # 全绿
.venv/Scripts/ruff check src/ tests/   # 无新增 warning
```

## 向后兼容

| 老 YAML 场景 | v0.10 行为 |
|---|---|
| 绝对路径 | 无影响（除 symlink 会被 `resolve()` 追到最终 target） |
| 相对路径 + JAR 存在 | 加载期转绝对路径，跑起来跟以前一样但不再有 CWD 依赖 |
| 相对路径 + JAR 不存在 | 加载期立即 `ValidationError`，比以前"跑到第二个 task 才 Java stack" 友好 |
| `~/xxx` 之前不展开的 | 现在自动展开，原本失败的场景变成功 |

无 API 破坏面。model 字段类型仍是 `str`，只是值变成绝对路径。

## 明确不做的事

- **不改基准为 `connections.yaml` 目录**：需要把 yaml 文件路径贯穿到
  Pydantic 验证器里（validation context 或自定义 loader），实现复杂度显著
  高于收益。用户想要"YAML 和 JAR 一起放"可以用 `~/.datacompare/xxx.jar`
- **不改基准为 `~/.datacompare/`**：跟 CLI `-c` 显式指定的 connections
  文件路径互相矛盾
- **不做 JVM 生命周期重构**：JVM 是 process-level singleton 这一层不动；
  本 spec 仅解决"JAR 路径解析"这一个具体问题
- **不引入路径解析辅助模块**：单个 validator 足够；不为一个 field 抽
  helper

## 工作量估算

| 模块 | 行数 |
|---|---|
| `config/models.py` validator | ~15 |
| 测试（4 个新单元测试）| ~50 |
| 迁移可能受影响的既有测试 | ~10 |
| 文档（README 一段）| ~5 |

单 PR，2-3 commits。**无新依赖**。
