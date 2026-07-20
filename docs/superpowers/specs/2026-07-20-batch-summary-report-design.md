# 批次聚合报告设计规范

**日期：** 2026-07-20
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划

## 问题背景

批次模式（v0.4+）下，若某个 sub-task 运行时失败（例如 `sources.left.sheets`
指向不存在的 sheet 页），当前行为：

- 该 sub-task 抛异常 → `SubTaskResult(status="failed", error=e)`
- `on_error=continue`（默认）继续跑剩下的 sub-task
- **该失败 sub-task 的输出目录里什么都没生成**（`execute()` 未走到写 report）
- `{output.dir}/batch.log` 只有 JSON 事件流（人读不友好）
- 控制台打印每个 sub-task 一行 + 底部 Summary，但是 ephemeral（重定向就没了）

**痛点：** 批次跑完后没有一份**持久化的聚合结果**可回溯。CI / 后续复查需要
一份文件同时包含每个 sub-task 的状态、成功任务的比对统计、失败任务的错误摘要
和整批总数。

## 方案概览

`execute_batch` 结束后，在 `{output.dir}` 下额外生成两份聚合产物：

- `batch_summary.json` —— 机读友好，CI 直接 parse
- `batch_summary.html` —— 人读友好，静态单文件，链接到各 sub-task 的详细报告

失败 sub-task 的目录仍然为空（不改此现状——如果用户要看错误详情，看聚合 HTML
或 batch.log；stub per-task report 属于另一个改动，本 spec 不涵盖）。

## `batch_summary.json` schema

```json
{
  "batch_name": "cmdb_multi_sync",
  "started_at": "2026-07-20T14:23:00+08:00",
  "ended_at": "2026-07-20T14:23:12+08:00",
  "total_duration_ms": 12345,
  "task_count": 3,
  "success_count": 1,
  "failed_count": 1,
  "skipped_count": 1,
  "exit_code": 2,
  "tasks": [
    {
      "name": "physical_host",
      "status": "success",
      "duration_ms": 4200,
      "report_dir": "physical_host",
      "stats": {
        "left_total": 100,
        "right_total": 100,
        "matched": 100,
        "identical": 98,
        "diff": 2,
        "left_only": 0,
        "right_only": 0
      }
    },
    {
      "name": "cloud_vm",
      "status": "failed",
      "duration_ms": 150,
      "report_dir": "cloud_vm",
      "error": {
        "type": "ConfigError",
        "message": "columns not found in left source: ['sheets']",
        "path": "sources.left"
      }
    },
    {
      "name": "storage",
      "status": "skipped",
      "duration_ms": 0,
      "report_dir": "storage"
    }
  ]
}
```

**字段规则：**

- **顶层**：`batch_name`、`started_at`/`ended_at`（ISO 8601 带时区）、
  `total_duration_ms`、`task_count`、`success_count`/`failed_count`/`skipped_count`、
  `exit_code`（`BatchResult.compute_exit_code(fail_on_diff)` 的返回值——由
  `execute_batch` 或 CLI 层算好传入，因为 `fail_on_diff` 是 CLI 参数）
- **`tasks`**：数组，按执行顺序
- **每个 task 通用**：`name`、`status`（`"success"`/`"failed"`/`"skipped"`）、
  `duration_ms`、`report_dir`（相对 `{output.dir}` 的路径，例如 `"physical_host"`；
  skipped 任务仍写这个字段但目录不存在也 OK）
- **status=success**：额外 `stats` 对象，字段直接来自 `CompareResult`
- **status=failed**：额外 `error` 对象——`type`（`type(e).__name__`）、`message`
  （`str(e)` 截断到 500 字符防止爆炸）、可选 `path`（仅当异常是 `ConfigError`
  且带 `path` 属性时输出）
- **status=skipped**：只有通用字段（含 `report_dir`，虽然目录不存在），
  无 `stats`/`error`

**明确不包含：**
- 完整 stack trace（想看去 batch.log 或运行时日志查）
- 每行 diff 明细（在各 sub-task 的 `report.json` 里）
- 完整 config dump（`batch.yaml` 本身就是源）

## `batch_summary.html` 设计

**布局（纯静态、无 JS、内联 CSS）：**

```
┌─────────────────────────────────────────────────┐
│  Batch: cmdb_multi_sync                         │
│  Started 2026-07-20 14:23:00 · 12.3s · exit 2   │
│  1 ✓ succeeded · 1 ✗ failed · 1 - skipped       │
├─────────────────────────────────────────────────┤
│  # │ Task           │ Status │ Result           │
│  1 │ physical_host  │ ✓      │ 100 matched,     │
│    │                │        │ 2 diffs → report │
│  2 │ cloud_vm       │ ✗      │ ConfigError:     │
│    │                │        │ columns not      │
│    │                │        │ found ['sheets'] │
│  3 │ storage        │ -      │ (skipped)        │
└─────────────────────────────────────────────────┘
```

**要点：**
- 顶部 header：batch name、开始时间、总时长、exit code、三种状态计数
- 表格 rows：编号、任务名、状态标记（✓/✗/-）、Result 列
- **Result 列内容**：
  - success：`{matched} matched, {diff} diffs` + `→ report`（`<a href="{report_dir}/report.html">`）
  - failed：错误 type 前缀 + message（内联展示，`<pre>` 保留换行）
  - skipped：`(skipped)` 灰色
- 状态用颜色：绿（success）、红（failed）、灰（skipped）
- 相对路径链接——双击 `batch_summary.html` 直接跳转到 sub-task 报告
- 单文件、离线可用（内联 CSS，不引用外部资源）

**模板位置：** `src/datacompare/reporters/templates/batch_summary.jinja2`
（跟已有的 `html_report.jinja2` 同目录、同后缀风格）

**若 HTML reporter 未注册在 sub-task 的 `output.formats` 里：** `→ report` 链接
仍然生成，但指向的文件不存在——用户点击会 404。可接受：这是 config 问题
（既然想让批次里能跳转，就把 sub-task 的 formats 加 html）。**不做**自动补充
或校验。

## 实现分工

### 新模块 `src/datacompare/reporters/batch_summary.py`

包含两个函数：

```python
def write_batch_summary_json(
    batch_result: BatchResult,
    exit_code: int,
    started_at: datetime,
    ended_at: datetime,
    out_dir: Path,
) -> Path:
    """Write batch_summary.json to out_dir. Returns the file path."""

def write_batch_summary_html(
    batch_result: BatchResult,
    exit_code: int,
    started_at: datetime,
    ended_at: datetime,
    out_dir: Path,
) -> Path:
    """Render batch_summary.html via Jinja2. Returns the file path."""
```

这两个函数共享一个内部辅助 `_build_summary_dict(...)` 生成 dict 结构，JSON
直接 dump、HTML 传给 Jinja2 模板。

### `execute_batch` 增强（`src/datacompare/runner.py`）

- 记录 `started_at` / `ended_at`（`datetime` 对象，带本地时区）
- 在 return `BatchResult` 之前，调用 `write_batch_summary_json` 和
  `write_batch_summary_html`
- `exit_code` 由谁计算？**由 `execute_batch` 接受一个 `fail_on_diff: bool`
  参数，内部调用 `batch_result.compute_exit_code(fail_on_diff)` 后传给写函数。**
  CLI 层继续用它的 `--fail-on-diff` flag 传给 `execute_batch`
- **失败模式**：写聚合报告本身不该抛异常（如果磁盘满等——记 log warning，
  不改 `BatchResult`）

**签名变化：**

```python
# 旧
def execute_batch(batch: BatchConfig, connections: dict[str, AnyConnection]) -> BatchResult

# 新
def execute_batch(
    batch: BatchConfig,
    connections: dict[str, AnyConnection],
    fail_on_diff: bool = False,
) -> BatchResult
```

向后兼容：`fail_on_diff` 有默认值，老 CLI 调用不用改也能编译（虽然会默认
不当 fail_on_diff 处理，但对不需要 exit code 10 语义的调用等价）。

### CLI（`src/datacompare/cli.py`）

传参：`execute_batch(cfg, conns, fail_on_diff=fail_on_diff)`。控制台输出的
summary footer **不动**（已经够用，且 batch_summary.html/json 已经持久化了同
信息）。

## 测试

**新单元测试** `tests/unit/reporters/test_batch_summary.py`：
- 混合 success/failed/skipped → JSON schema 完整、字段类型正确
- Failed 任务是 `ConfigError` → error.path 字段出现
- Failed 任务是其他异常 → 只有 error.type + error.message
- 长 error message → 截断到 500 字符
- HTML 渲染成功、链接正确指向相对路径
- HTML 单文件、无外部资源引用（grep 一下 `http://`/`https://` 应该无匹配，
  除非 W3C DOCTYPE）

**集成测试** `tests/integration/test_batch_e2e.py` 加一个 scenario L：
- 3-sub-task batch：1 成功 + 1 sheets 不存在导致 failed + 1 config 错误 fail_fast
  下会 skipped（但这里跑 on_error=continue，所以 skipped 场景需要另造：用 fail_fast
  模式让第二个失败后第三个 skipped）
- 断言 `batch_summary.json` 存在、结构正确、`success_count`/`failed_count`
  /`skipped_count` 匹配、`exit_code` 正确
- 断言 `batch_summary.html` 存在，文本里包含 3 个 sub-task 的名字和状态标记

**回归**：既有 `test_batch_scenario_g` / `h` / `i` / `j` / `k` 应仍绿——它们
不检查 batch_summary.* 的存在，但新写的这两份文件出现在 `{output.dir}` 下也
不会影响它们的断言。

## 文档

- `README.md`：在"批次模式"小节末尾追加一段"聚合报告"说明——两份文件的路径、
  用途、如何在 CI 里 parse JSON
- `docs/user-guide.md`：批次模式章节的"每个 sub-task 写到 ..."后加一句
  "另外 `{output.dir}/batch_summary.{json,html}` 汇总所有 sub-task 状态"
- `CLAUDE.md`：在批次模式的约束条目后加一条"批次聚合报告由 `reporters/
  batch_summary.py` 生成，`execute_batch` 结束后写入 `{output.dir}`"

## 向后兼容

- 老 `execute_batch(cfg, conns)` 调用兼容（`fail_on_diff` 默认 False；exit_code
  可能与 CLI 计算的不一致，但 CLI 会传 True/False 覆盖）
- 老 `batch.log` 事件流一字不动
- 各 sub-task 自己的 report 不受影响
- 新增两份文件对没有磁盘配额敏感的用户完全透明

## 工作量估算

- `reporters/batch_summary.py`（含 dict builder、JSON writer、HTML writer）：约 80 行
- `reporters/templates/batch_summary.html.j2`：约 60 行 HTML + 内联 CSS
- `runner.py` 集成：约 15 行
- `cli.py` 微调（传 `fail_on_diff`）：约 3 行
- 测试：约 100 行
- 文档：约 30 行

单 PR，5-6 个 commit。无新依赖（Jinja2、json、datetime 都是已有栈）。
