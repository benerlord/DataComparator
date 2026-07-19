# DataComparator

CLI 工具，用 YAML 配置驱动，比对 **Excel / GaussDB / HTTP API** 之间任意两两的数据一致性。

## 常用命令（Windows/git-bash）

```bash
# 安装 / 重装
.venv/Scripts/pip install -e ".[dev]"

# 单元 + 集成测试（Docker 未跑时 GaussDB 集成测试自动 skip）
.venv/Scripts/pytest tests/ -q

# 覆盖率
.venv/Scripts/pytest tests/ --cov=src/datacompare --cov-report=term-missing

# Lint / 类型
.venv/Scripts/ruff check src/ tests/
.venv/Scripts/mypy src/datacompare/

# 运行 CLI
.venv/Scripts/python -m datacompare.cli version
.venv/Scripts/python -m datacompare.cli init excel-vs-gaussdb -o task.yaml  # -o 写 UTF-8；PowerShell 里 > 会变 UTF-16 无法解析
.venv/Scripts/python -m datacompare.cli validate task.yaml --connections ~/.datacompare/connections.yaml
.venv/Scripts/python -m datacompare.cli run task.yaml --param month=2026-07
```

## 环境要点

- **Python 3.11+ 必需**（代码使用 `X | Y` 联合类型和 `match/case`）。系统 `python` 可能指向 3.9，用 `py -3.11 -m venv .venv` 建虚拟环境。
- **git-bash shell**：Bash 命令用正斜杠路径，venv 用 `.venv/Scripts/` 而不是 `.venv/bin/`。
- **GaussDB 集成测试** 走 testcontainers，需要 Docker Desktop 运行。未运行时测试自动 skip，不算失败。

## 架构分层（六层，每层可独立测试）

```
CLI (Typer)  →  Config (Pydantic + YAML)  →  DataSource 抽象
                                              → Excel / GaussDB / API
                                                     ↓
                                            Normalize (纯函数)
                                            columns → strings → types → units → decimals
                                                     ↓
                                            Engine (可插拔)
                                            InMemoryEngine / DiskEngine + Router
                                                     ↓
                                            Reporter (可插拔)
                                            HTML / Excel / CSV / JSON / Console
```

## 目录约定

- `src/datacompare/` 主包，`tests/` 与之镜像对称
- `sources/` `engine/` `reporters/` 三个扩展点，通过 registry / ABC 契约
- `normalize/` 全是**纯函数**，无外部 IO，最容易测
- `templates/` 内嵌 YAML 模板（`init` 命令通过 `importlib.resources` 读取）
- `reporters/templates/` Jinja2 HTML 模板
- 权威文档：`docs/superpowers/specs/2026-07-13-data-comparator-design.md`（设计规范）和 `docs/superpowers/plans/2026-07-13-data-comparator.md`（实现计划）

## 关键约束（改代码前务必了解）

- **所有 DataSource 返回值都是 `str | None`**：Excel/DB/API 都统一。类型转换发生在 normalize 层，由配置驱动。改数据源实现时必须保持这一契约（用 `.astype(object)` 强制 pandas 3.x 保留 object dtype）。
- **数值四舍五入用 `ROUND_HALF_UP`（`normalize/decimals.py`），不是 Python 内置 `round()`**：后者是银行家舍入（`round(0.5)==0`），业务比对会出问题。
- **归一化管线顺序固定**：列名映射 → 字符串预处理 → 单位换算 → 类型转换 → 精度。见 `normalize/pipeline.py`。改顺序会静默改变判等语义。
- **类型/单位转换失败不抛异常**，返回 sentinel 值（`CoerceError` / `UnitError`）。引擎将它们标为 `type_error` / `unit_error` 差异。不要在归一化层加 `try/raise`。
- **GaussDB 只允许 SELECT**：`gaussdb.py` 里的正则白名单在初始化时校验。这是安全边界，别绕过。
- **FieldRule 覆盖语义**：可覆盖属性用 `None` 表示"继承 `CompareDefaults`"，非 `None` 表示"显式覆盖"。别把默认值设成 `False` —— 那样区分不出"未指定"和"显式关闭"。
- **主键在单侧重复 = 配置错误**，任务失败并列出重复键（不是静默 join）。
- **GaussDB 有两个变体 A/T**（v0.2 起）：A 用 psycopg2（PostgreSQL 协议），T 用 JDBC（JayDeBeApi + gsjdbc4.jar）。共用 `type: gaussdb`，用 `variant: a|t` 字段区分。默认 `a`，向后兼容。
- **`GaussDBConnection` 是联合类型**（`GaussDBAConnection | GaussDBTConnection`），不能作为构造器调用。分派用 `isinstance` 检查具体子类。
- **KeyMapping 支持 `left_regex` / `right_regex`**（v0.3 起）：可选，跑 `re.fullmatch`，允许 0 或 1 个捕获组（≥2 组加载时报错）。有捕获组用 `group(1)`，否则用 `group(0)`。**严格失败**：任一行不匹配 → 抛 `KeyRegexMismatchError`（`ValueError` 子类）→ CLI exit 2。null 值透传不参与匹配。归属层：`normalize/keys.py`。运行位置：`normalize_side` 首行，在 `apply_column_mapping` 之前。
- **批次模式 `tasks:`**（v0.4 起）：task.yaml 顶层出现 `tasks:` 键 → `load_task_or_batch` 返回 `BatchConfig`；`execute_batch` 顺序跑每个 sub-task。每个 sub-task 深度合并 defaults：dict 递归、list 替换、嵌套 dict 的 `type` 变化时 replace。`on_error: continue`（默认）或 `fail_fast`。CLI 退出码优先级 `2 > 10 > 1 > 0`。批次总日志 `batch.log` 只记元事件，sub-task 详细日志仍在各自目录。**加载阶段**（YAML 解析、defaults 合并冲突、sub-task 唯一性、每个 sub-task 完整 Pydantic 校验）**永远 fail-fast**，不受 `on_error` 影响。
- **`FieldRule` 支持 `left_literal` / `right_literal`**（v0.5 起）：每侧必须恰好
  指定 `<side>` 或 `<side>_literal` 之一。验证器用 `model_fields_set` 判定"是否
  提供"，**不**用 `value is None`——`left_literal: null` 是合法的（表示"断言另
  一侧为 null"），跟"未提供 left_literal"运行时值相同但语义不同。改这条约束前
  想清楚会不会把 null 字面量误判为未设置。canonical 列名规则由
  `normalize/columns.py::field_canonical_name` 集中管理：优先 `f.right`，其次
  `f.left`（用于 right_literal 场景），最后 `"_literal"` 兜底；normalize 层和
  engine 层都通过该 helper 拿列名，别在别处硬编码 `f.right`。

## 开发流程约定

- **TDD**：新代码先写失败测试，再实现，最后 commit。plan 里每个任务都是这个节奏。
- **一个提交一件事**：commit 消息用 `feat(<layer>): ...` / `fix(...)` / `docs: ...` / `test: ...` 格式。参考 `git log --oneline` 里已有的风格。
- **归一化层的新功能**：必须 pytest 参数化覆盖边界值（null、空串、极值、负数）。
- **加数据源**：实现 `DataSource` 子类并 `@register_source("type_name")` 装饰。核心代码不改。
- **加报告器**：实现 `Reporter` 子类，在 `runner.py:REPORTER_MAP` 注册。

## 已知偏离（透明记录，参考 plan 末尾）

1. **`engine/disk.py`** v0.1 用 pandas outer-join，不是 spec §9.4 规定的 DuckDB SQL JOIN。语义与 `InMemoryEngine` 完全等价（有 parity test），但没有 DuckDB 磁盘溢出的规模优势。v1.0 优化项。
2. **API `read()` 的分页请求** 目前没走 `tenacity` 重试；只有 `columns()`/`estimated_rows()` 的采样请求有重试。
3. **单位大小写敏感度** 目前硬编码为不敏感，无 `unit_case_sensitive` 配置项（YAGNI）。
4. **`tests/fixtures/excel/*.xlsx`** 会被 pytest autouse fixture 每次重新生成，导致 `git status` 显示 1 字节差异。建议加入 `.gitignore`。
5. **GaussDB T 集成测试通过 PG JDBC 代理验证**（`test_gaussdb_jdbc_via_postgres.py`）：目的是验证 JayDeBeApi 封装本身，不验证 GaussDB T 特定行为。真机 T 测试可通过环境变量方式激活（未落地）。

## 退出码语义（CLI 用户会依赖）

| 码 | 含义 |
|---|---|
| 0 | 成功（无差异，或未指定 `--fail-on-diff`） |
| 1 | 配置错误 |
| 2 | 数据源连接/读取失败 |
| 3 | 内部错误 |
| 10 | 成功但发现差异且指定了 `--fail-on-diff` |

## 依赖策略

- **不加新依赖**除非无法用现有栈实现。当前栈：pandas 2.x + pyarrow / duckdb / openpyxl / psycopg2-binary / httpx / typer / pydantic v2 / ruamel.yaml / jsonpath-ng / Jinja2 / XlsxWriter / structlog / rich / tenacity。
- **PyYAML** 是 `respx`/`docker` 的传递依赖，测试里可以直接 `import yaml`。生产代码用 `ruamel.yaml`。
