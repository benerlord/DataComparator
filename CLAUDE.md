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
- **批次聚合报告**（v0.7 起）：`execute_batch` 结束后调用
  `reporters/batch_summary.py::write_batch_summary_{json,html}`，在
  `{output.dir}` 生成 `batch_summary.json` 和 `batch_summary.html`。JSON 用于
  CI parse、HTML 用于人工浏览。**写这两份文件本身不能抛异常**——磁盘满等错误
  只 log warning，不改 `BatchResult`（约束在 `execute_batch` 的 writer 循环
  try/except 里）。`fail_on_diff` 作为参数从 CLI 一路传到 `execute_batch` 用于
  算 `exit_code`，别在 writer 里再算一次——单一权威源。
- **`FieldRule` 支持 `left_literal` / `right_literal`**（v0.5 起）：每侧必须恰好
  指定 `<side>` 或 `<side>_literal` 之一。验证器用 `model_fields_set` 判定"是否
  提供"，**不**用 `value is None`——`left_literal: null` 是合法的（表示"断言另
  一侧为 null"），跟"未提供 left_literal"运行时值相同但语义不同。改这条约束前
  想清楚会不会把 null 字面量误判为未设置。canonical 列名规则由
  `normalize/columns.py::field_canonical_name` 集中管理：优先 `f.right`，其次
  `f.left`（用于 right_literal 场景），最后 `"_literal"` 兜底；normalize 层和
  engine 层都通过该 helper 拿列名，别在别处硬编码 `f.right`。
- **`KeyMapping` 支持 `alias`**（v0.6 起）：给 join key 自定义 canonical
  列名，避免与 field canonical 撞车。canonical 命名规则由
  `normalize/columns.py::key_canonical_name`（`alias` 优先，回退 `k.right`）
  集中管理。engine 和 normalize 都通过这个 helper 拿 join key 列名，别
  硬编码 `k.right`。**加载期 canonical 重复检查**在 `config/loader.py`
  的 `_check_canonical_uniqueness`——任何 key/field canonical 撞车都在这里
  fail-fast，不到 pandas 层才炸。
- **`FieldRule` 支持 `left_regex` / `right_regex`**（v0.6 起）：语义与
  `KeyMapping` 的 regex 一致（`re.fullmatch`、0/1 捕获组、None 透传），
  **但失败模式相反**——key regex 不匹配 → 严格失败（`KeyRegexMismatchError`
  → CLI exit 2）；field regex 不匹配 → **软失败**（`RegexError` sentinel，
  engine 归 `DiffType.REGEX_ERROR`，其他行不影响）。原因：坏 key 让
  整个 join 无意义，坏 field 只是一行数据问题。
- **Regex 应用顺序**（v0.6 起）：`normalize_side` 先 `apply_column_mapping`
  复制+改名，**再**跑 key regex（strict）和 field regex（soft），都作用在
  canonical 列上。别改回 pre-rename——右侧同一个源列可能同时被 key
  和 field 引用（如右侧 `name` = "prefix@@id" 双用），只有先复制再分别
  跑 regex 才不互相污染。
- **`apply_column_mapping` 是"tasks 列表"模型**（v0.6 起）：每个 key/field
  贡献一个 `(source_col, canonical)` 对，同源列多次出现 = 复制成多个
  canonical 列（不是 rename）。canonical 撞名靠 loader fail-fast 挡住，
  运行时不用再查重。
- **`apply_column_mapping` 缺列语义**（v0.8 起）：**field 缺列不再 raise**，
  改为返回 `(df, missing_field_canonicals: frozenset[str])`。只有 **key
  缺列**才 raise `ConfigError`（无 key 无法 join）。"双侧同 field 缺"的硬
  失败判定在 engine 层——因为需要跨侧信息。signature 是 tuple，任何调用方
  （现只有 `pipeline.py` 和测试）都必须显式解包。
- **`NormalizedSide` 数据容器 + engine 缺列消费**（v0.8 起）：`normalize_side`
  返回 `NormalizedSide(df, missing_field_canonicals)` 而非裸 DataFrame。任
  何消费方要显式取 `.df`。engine 层用 `missing_field_canonicals`：① 双侧
  交集非空 → raise `ConfigError`；② 单侧存在 → 跳过 per-row 比对并追加一
  条 `field_missing` 汇总记录（`_build_field_missing_record` in
  `engine/_field_missing.py`）；③ `left_only_rows` / `right_only_rows` 补
  齐 "字段不存在" 常量列，reporter schema 齐整。汇总记录 key 列填空串，
  left_value / right_value 为中文字面量 "字段不存在"，不走 sentinel
  dataclass 路径。**diff_rows 语义变化**：`diff_rows = (matched_rows -
  identical_rows) + summary_missing_count`，可能超过 matched_rows（结构性
  缺失是额外 diff，不属于任何具体行）。`merged_col_name(canonical, side,
  left_missing, right_missing)` 处理 pandas outer-merge 后缀歧义——两侧都
  有的列有 `__left/__right` 后缀，单侧列保留 bare 名。memory/disk 两引擎
  都通过这个 shared helper 消歧。

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
