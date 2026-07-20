# 批次聚合报告实现计划

> **For agentic workers:** REQUIRED SUB-SKILL：用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务执行本计划。步骤用 checkbox（`- [ ]`）语法追踪。

**目标：** `execute_batch` 结束后在 `{output.dir}` 生成 `batch_summary.json` 和 `batch_summary.html` 两份聚合产物，同时包含成功任务的统计和失败任务的错误摘要，方便 CI 复查与人工浏览。

**架构：** 新建 `reporters/batch_summary.py` 模块含三个函数：`_build_summary_dict`（把 `BatchResult` + metadata → dict）、`write_batch_summary_json`、`write_batch_summary_html`。HTML 走 Jinja2 模板 `batch_summary.jinja2`，跟已有 `html_report.jinja2` 同目录同风格。`execute_batch` 记录 `started_at`/`ended_at`、接受新参数 `fail_on_diff`，结束前调用这两个 writer；写失败只 log warning 不改 `BatchResult`。

**技术栈：** Python 3.11+、`datetime`（tz-aware ISO 8601）、`json`、Jinja2（已有依赖）、pytest。

**Spec：** `docs/superpowers/specs/2026-07-20-batch-summary-report-design.md`

---

## 文件结构映射

| 文件 | 改动 | 责任 |
|------|------|------|
| `src/datacompare/reporters/batch_summary.py` | **新建** | `_build_summary_dict` + JSON writer + HTML writer |
| `src/datacompare/reporters/templates/batch_summary.jinja2` | **新建** | HTML 模板（内联 CSS、无 JS） |
| `src/datacompare/runner.py` | 修改 `execute_batch` | 接受 `fail_on_diff` 参数、记录时间戳、调用两个 writer |
| `src/datacompare/cli.py` | 微调 `execute_batch` 调用 | 传 `fail_on_diff=fail_on_diff` |
| `tests/unit/reporters/test_batch_summary.py` | **新建** | JSON schema、HTML 渲染、错误截断、离线可用 |
| `tests/integration/test_batch_e2e.py` | 追加 scenario L | 端到端验证两份文件生成 |
| `README.md` / `docs/user-guide.md` / `CLAUDE.md` | 追加 | 文档说明 |

---

## Task 1: `_build_summary_dict` + JSON writer

**Files:**
- Create: `src/datacompare/reporters/batch_summary.py`
- Test: create `tests/unit/reporters/test_batch_summary.py`

- [ ] **Step 1: 写失败测试（JSON schema 与字段规则）**

Create `tests/unit/reporters/test_batch_summary.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from datacompare.config.errors import ConfigError
from datacompare.engine.result import BatchResult, CompareResult, SubTaskResult
from datacompare.reporters.batch_summary import (
    _build_summary_dict,
    write_batch_summary_json,
)


def _cr(matched=100, identical=98, diff=2, left_only=0, right_only=0,
        left_total=100, right_total=100) -> CompareResult:
    """Minimal CompareResult factory for tests."""
    return CompareResult(
        task_name="t", left_name="left", right_name="right",
        left_total=left_total, right_total=right_total,
        matched_rows=matched, identical_rows=identical, diff_rows=diff,
        left_only=left_only, right_only=right_only,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=1.5,
    )


TZ = timezone(timedelta(hours=8))
STARTED = datetime(2026, 7, 20, 14, 23, 0, tzinfo=TZ)
ENDED = datetime(2026, 7, 20, 14, 23, 12, tzinfo=TZ)


def _batch_result(task_results):
    return BatchResult(
        batch_name="cmdb_multi_sync",
        task_results=task_results,
        total_duration_ms=12345,
    )


class TestBuildSummaryDict:
    def test_success_task_has_stats(self):
        r = SubTaskResult(task_name="physical_host", status="success",
                          comparison_result=_cr(), error=None, duration_ms=4200)
        d = _build_summary_dict(
            _batch_result([r]), exit_code=0,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"physical_host": "physical_host"},
        )
        assert d["batch_name"] == "cmdb_multi_sync"
        assert d["started_at"] == "2026-07-20T14:23:00+08:00"
        assert d["ended_at"] == "2026-07-20T14:23:12+08:00"
        assert d["total_duration_ms"] == 12345
        assert d["task_count"] == 1
        assert d["success_count"] == 1
        assert d["failed_count"] == 0
        assert d["skipped_count"] == 0
        assert d["exit_code"] == 0
        t = d["tasks"][0]
        assert t["name"] == "physical_host"
        assert t["status"] == "success"
        assert t["duration_ms"] == 4200
        assert t["report_dir"] == "physical_host"
        assert t["stats"] == {
            "left_total": 100, "right_total": 100,
            "matched": 100, "identical": 98, "diff": 2,
            "left_only": 0, "right_only": 0,
        }
        assert "error" not in t

    def test_failed_task_config_error_includes_path(self):
        err = ConfigError("columns not found in left source: ['sheets']",
                          path="sources.left")
        r = SubTaskResult(task_name="cloud_vm", status="failed",
                          comparison_result=None, error=err, duration_ms=150)
        d = _build_summary_dict(
            _batch_result([r]), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"cloud_vm": "cloud_vm"},
        )
        t = d["tasks"][0]
        assert t["status"] == "failed"
        assert t["error"]["type"] == "ConfigError"
        assert "columns not found" in t["error"]["message"]
        assert t["error"]["path"] == "sources.left"
        assert "stats" not in t

    def test_failed_task_generic_exception_omits_path(self):
        err = RuntimeError("something broke")
        r = SubTaskResult(task_name="api", status="failed",
                          comparison_result=None, error=err, duration_ms=99)
        d = _build_summary_dict(
            _batch_result([r]), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"api": "api"},
        )
        t = d["tasks"][0]
        assert t["error"]["type"] == "RuntimeError"
        assert t["error"]["message"] == "something broke"
        assert "path" not in t["error"]

    def test_skipped_task_no_stats_no_error(self):
        r = SubTaskResult(task_name="storage", status="skipped",
                          comparison_result=None, error=None, duration_ms=0)
        d = _build_summary_dict(
            _batch_result([r]), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"storage": "storage"},
        )
        t = d["tasks"][0]
        assert t["status"] == "skipped"
        assert t["duration_ms"] == 0
        assert t["report_dir"] == "storage"
        assert "stats" not in t
        assert "error" not in t

    def test_long_error_message_truncated_to_500_chars(self):
        long_msg = "x" * 1000
        err = RuntimeError(long_msg)
        r = SubTaskResult(task_name="t", status="failed",
                          comparison_result=None, error=err, duration_ms=1)
        d = _build_summary_dict(
            _batch_result([r]), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"t": "t"},
        )
        assert len(d["tasks"][0]["error"]["message"]) == 500

    def test_mixed_task_counts(self):
        rs = [
            SubTaskResult(task_name="a", status="success",
                          comparison_result=_cr(), error=None, duration_ms=1),
            SubTaskResult(task_name="b", status="failed",
                          comparison_result=None, error=RuntimeError("x"),
                          duration_ms=2),
            SubTaskResult(task_name="c", status="skipped",
                          comparison_result=None, error=None, duration_ms=0),
        ]
        d = _build_summary_dict(
            _batch_result(rs), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"a": "a", "b": "b", "c": "c"},
        )
        assert d["task_count"] == 3
        assert d["success_count"] == 1
        assert d["failed_count"] == 1
        assert d["skipped_count"] == 1
        assert [t["name"] for t in d["tasks"]] == ["a", "b", "c"]


class TestWriteBatchSummaryJson:
    def test_writes_valid_json_to_out_dir(self, tmp_path):
        r = SubTaskResult(task_name="t", status="success",
                          comparison_result=_cr(), error=None, duration_ms=1)
        path = write_batch_summary_json(
            _batch_result([r]), exit_code=0,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"t": "t"},
            out_dir=tmp_path,
        )
        assert path == tmp_path / "batch_summary.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["batch_name"] == "cmdb_multi_sync"
        assert data["tasks"][0]["name"] == "t"

    def test_json_uses_utf8_no_bom(self, tmp_path):
        r = SubTaskResult(task_name="任务_中文", status="success",
                          comparison_result=_cr(), error=None, duration_ms=1)
        path = write_batch_summary_json(
            _batch_result([r]), exit_code=0,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"任务_中文": "任务_中文"},
            out_dir=tmp_path,
        )
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "should be UTF-8 without BOM"
        assert "任务_中文".encode("utf-8") in raw
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/reporters/test_batch_summary.py -v
```

预期：全部失败（`ModuleNotFoundError: No module named 'datacompare.reporters.batch_summary'`）。

- [ ] **Step 3: 实现 batch_summary.py（dict builder + JSON writer）**

Create `src/datacompare/reporters/batch_summary.py`:

```python
"""Batch-level aggregate summary reports (JSON + HTML).

Written by execute_batch after all sub-tasks complete. Provides a persistent,
consolidated view of the whole batch: per-task status, successful task stats,
failed task error info, and overall counts + exit code.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datacompare.config.errors import ConfigError
from datacompare.engine.result import BatchResult, SubTaskResult

_ERROR_MESSAGE_MAX_CHARS = 500


def _task_dict(sub: SubTaskResult, report_dir: str) -> dict[str, Any]:
    """Convert one SubTaskResult into its JSON entry."""
    entry: dict[str, Any] = {
        "name": sub.task_name,
        "status": sub.status,
        "duration_ms": sub.duration_ms,
        "report_dir": report_dir,
    }
    if sub.status == "success" and sub.comparison_result is not None:
        cr = sub.comparison_result
        entry["stats"] = {
            "left_total": cr.left_total,
            "right_total": cr.right_total,
            "matched": cr.matched_rows,
            "identical": cr.identical_rows,
            "diff": cr.diff_rows,
            "left_only": cr.left_only,
            "right_only": cr.right_only,
        }
    elif sub.status == "failed" and sub.error is not None:
        err_dict: dict[str, Any] = {
            "type": type(sub.error).__name__,
            "message": str(sub.error)[:_ERROR_MESSAGE_MAX_CHARS],
        }
        if isinstance(sub.error, ConfigError) and sub.error.path is not None:
            err_dict["path"] = sub.error.path
        entry["error"] = err_dict
    return entry


def _build_summary_dict(
    batch_result: BatchResult,
    exit_code: int,
    started_at: datetime,
    ended_at: datetime,
    report_dirs: dict[str, str],
) -> dict[str, Any]:
    """Build the JSON-serializable summary dict shared by JSON and HTML writers.

    report_dirs maps task_name -> relative path under out_dir (typically just
    task_name, but may differ if the sub-task set an explicit output.dir).
    """
    return {
        "batch_name": batch_result.batch_name,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "total_duration_ms": batch_result.total_duration_ms,
        "task_count": len(batch_result.task_results),
        "success_count": batch_result.success_count,
        "failed_count": batch_result.failed_count,
        "skipped_count": batch_result.skipped_count,
        "exit_code": exit_code,
        "tasks": [
            _task_dict(sub, report_dirs.get(sub.task_name, sub.task_name))
            for sub in batch_result.task_results
        ],
    }


def write_batch_summary_json(
    batch_result: BatchResult,
    exit_code: int,
    started_at: datetime,
    ended_at: datetime,
    report_dirs: dict[str, str],
    out_dir: Path,
) -> Path:
    """Write batch_summary.json to out_dir. Returns the file path."""
    data = _build_summary_dict(
        batch_result, exit_code, started_at, ended_at, report_dirs,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "batch_summary.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
```

Also create the empty `tests/unit/reporters/__init__.py` if it doesn't exist:

```bash
ls tests/unit/reporters/__init__.py 2>/dev/null || touch tests/unit/reporters/__init__.py
```

- [ ] **Step 4: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/reporters/test_batch_summary.py -v
```

预期：所有 7 个测试 pass。

- [ ] **Step 5: 全套 unit 回归**

```bash
.venv/Scripts/pytest tests/unit/ -q
```

预期：全绿。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/reporters/batch_summary.py tests/unit/reporters/test_batch_summary.py
# add __init__.py if newly created
git add tests/unit/reporters/__init__.py 2>/dev/null || true
git commit -m "feat(reporters): batch_summary dict builder + JSON writer"
```

---

## Task 2: HTML 模板 + `write_batch_summary_html`

**Files:**
- Create: `src/datacompare/reporters/templates/batch_summary.jinja2`
- Modify: `src/datacompare/reporters/batch_summary.py` (append `write_batch_summary_html`)
- Test: append to `tests/unit/reporters/test_batch_summary.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/unit/reporters/test_batch_summary.py`:

```python
class TestWriteBatchSummaryHtml:
    def test_writes_valid_html_to_out_dir(self, tmp_path):
        from datacompare.reporters.batch_summary import write_batch_summary_html
        rs = [
            SubTaskResult(task_name="physical_host", status="success",
                          comparison_result=_cr(matched=100, diff=2),
                          error=None, duration_ms=4200),
            SubTaskResult(task_name="cloud_vm", status="failed",
                          comparison_result=None,
                          error=ConfigError("columns not found in left source: ['sheets']",
                                            path="sources.left"),
                          duration_ms=150),
            SubTaskResult(task_name="storage", status="skipped",
                          comparison_result=None, error=None, duration_ms=0),
        ]
        path = write_batch_summary_html(
            _batch_result(rs), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"physical_host": "physical_host",
                         "cloud_vm": "cloud_vm", "storage": "storage"},
            out_dir=tmp_path,
        )
        assert path == tmp_path / "batch_summary.html"
        assert path.exists()
        html = path.read_text(encoding="utf-8")
        # batch metadata visible
        assert "cmdb_multi_sync" in html
        assert "exit 2" in html or "exit_code: 2" in html or "exit&nbsp;2" in html
        # each task name visible
        assert "physical_host" in html
        assert "cloud_vm" in html
        assert "storage" in html
        # status markers
        assert "✓" in html
        assert "✗" in html
        # success task stats visible
        assert "100" in html   # matched or left_total
        # failed task error type + message visible
        assert "ConfigError" in html
        assert "columns not found" in html
        # link to sub-task report (relative)
        assert 'href="physical_host/report.html"' in html

    def test_html_is_offline_single_file(self, tmp_path):
        """No external resource references — must render offline."""
        from datacompare.reporters.batch_summary import write_batch_summary_html
        r = SubTaskResult(task_name="t", status="success",
                          comparison_result=_cr(), error=None, duration_ms=1)
        path = write_batch_summary_html(
            _batch_result([r]), exit_code=0,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"t": "t"},
            out_dir=tmp_path,
        )
        html = path.read_text(encoding="utf-8")
        # No CDN / external URLs (allow DOCTYPE w3.org)
        for token in ["src=\"http", "href=\"http", "cdn.", "googleapis"]:
            assert token not in html, f"external ref found: {token}"

    def test_html_escapes_error_message(self, tmp_path):
        """Error messages containing HTML must be escaped, not rendered."""
        from datacompare.reporters.batch_summary import write_batch_summary_html
        r = SubTaskResult(task_name="t", status="failed",
                          comparison_result=None,
                          error=RuntimeError("<script>alert('xss')</script>"),
                          duration_ms=1)
        path = write_batch_summary_html(
            _batch_result([r]), exit_code=2,
            started_at=STARTED, ended_at=ENDED,
            report_dirs={"t": "t"},
            out_dir=tmp_path,
        )
        html = path.read_text(encoding="utf-8")
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html or "&#34;xss&#34;" in html or "&#x27;xss&#x27;" in html
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/reporters/test_batch_summary.py::TestWriteBatchSummaryHtml -v
```

预期：3 个测试全部失败（`ImportError: cannot import name 'write_batch_summary_html'`）。

- [ ] **Step 3: 创建 Jinja2 模板**

Create `src/datacompare/reporters/templates/batch_summary.jinja2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Batch Summary: {{ summary.batch_name }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 960px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { margin-bottom: 0.2em; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 1em; }
  .counts { margin: 1em 0; font-size: 1.05em; }
  .counts .ok { color: #2a7a2a; margin-right: 1em; }
  .counts .fail { color: #b02222; margin-right: 1em; }
  .counts .skip { color: #888; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.5em; }
  th, td { border: 1px solid #ddd; padding: 0.5em 0.75em; text-align: left;
           vertical-align: top; }
  th { background: #f5f5f5; }
  td.num { text-align: right; width: 3em; }
  td.status { width: 3em; font-size: 1.3em; text-align: center; }
  .row-success td.status { color: #2a7a2a; }
  .row-failed td.status { color: #b02222; }
  .row-skipped td.status, .row-skipped { color: #888; }
  .err-type { font-weight: bold; }
  pre { white-space: pre-wrap; margin: 0.2em 0 0; font-size: 0.9em; }
  a { color: #2a5fdb; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>Batch: {{ summary.batch_name }}</h1>
<p class="meta">
  Started {{ summary.started_at }} ·
  {{ "%.1f"|format(summary.total_duration_ms / 1000) }}s ·
  exit&nbsp;{{ summary.exit_code }}
</p>
<p class="counts">
  <span class="ok">{{ summary.success_count }} ✓ succeeded</span>
  <span class="fail">{{ summary.failed_count }} ✗ failed</span>
  <span class="skip">{{ summary.skipped_count }} - skipped</span>
</p>
<table>
  <thead>
    <tr><th>#</th><th>Task</th><th>Status</th><th>Result</th><th>Duration</th></tr>
  </thead>
  <tbody>
  {% for t in summary.tasks %}
    <tr class="row-{{ t.status }}">
      <td class="num">{{ loop.index }}</td>
      <td>{{ t.name }}</td>
      <td class="status">
        {% if t.status == "success" %}✓
        {% elif t.status == "failed" %}✗
        {% else %}-{% endif %}
      </td>
      <td>
        {% if t.status == "success" %}
          {{ t.stats.matched }} matched, {{ t.stats.diff }} diffs,
          {{ t.stats.left_only }} left-only, {{ t.stats.right_only }} right-only
          &nbsp;<a href="{{ t.report_dir }}/report.html">→ report</a>
        {% elif t.status == "failed" %}
          <span class="err-type">{{ t.error.type }}</span>{% if t.error.path %}
          <span class="meta">at {{ t.error.path }}</span>{% endif %}
          <pre>{{ t.error.message }}</pre>
        {% else %}
          (skipped)
        {% endif %}
      </td>
      <td class="num">{{ "%.1f"|format(t.duration_ms / 1000) }}s</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</body>
</html>
```

- [ ] **Step 4: 实现 write_batch_summary_html**

Append to `src/datacompare/reporters/batch_summary.py`:

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def write_batch_summary_html(
    batch_result: BatchResult,
    exit_code: int,
    started_at: datetime,
    ended_at: datetime,
    report_dirs: dict[str, str],
    out_dir: Path,
) -> Path:
    """Render batch_summary.html via Jinja2. Returns the file path."""
    summary = _build_summary_dict(
        batch_result, exit_code, started_at, ended_at, report_dirs,
    )
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "jinja2"]),
    )
    template = env.get_template("batch_summary.jinja2")
    html = template.render(summary=summary)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "batch_summary.html"
    path.write_text(html, encoding="utf-8")
    return path
```

Move the `from jinja2 import ...` line to the top of the file with the other imports (or leave it inline — Ruff will flag; group it). Recommended: put with other imports.

- [ ] **Step 5: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/reporters/test_batch_summary.py -v
```

预期：全部 10 个测试（7 from Task 1 + 3 new）pass。

- [ ] **Step 6: 全套 unit 回归**

```bash
.venv/Scripts/pytest tests/unit/ -q
```

预期：全绿。

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/reporters/batch_summary.py \
        src/datacompare/reporters/templates/batch_summary.jinja2 \
        tests/unit/reporters/test_batch_summary.py
git commit -m "feat(reporters): batch_summary HTML writer with Jinja2 template"
```

---

## Task 3: `execute_batch` 集成时间戳与聚合写入

**Files:**
- Modify: `src/datacompare/runner.py::execute_batch` (lines 153-227)

- [ ] **Step 1: 写失败测试**

Append to `tests/unit/test_runner_batch.py`（若无此文件，创建之）:

```python
import json
from pathlib import Path

from openpyxl import Workbook

from datacompare.config.models import BatchConfig
from datacompare.config.loader import load_task_or_batch
from datacompare.runner import execute_batch


def _make_xlsx(path: Path, sheets: dict):
    wb = Workbook()
    default_ws = wb.active
    default_ws.title = "_placeholder"
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for r in rows:
            ws.append(r)
    if "_placeholder" in wb.sheetnames:
        del wb["_placeholder"]
    wb.save(path)


def test_execute_batch_writes_batch_summary_json_and_html(tmp_path):
    """execute_batch produces batch_summary.{json,html} in the aggregate out_dir."""
    _make_xlsx(tmp_path / "l.xlsx", {"S": [["id"], ["x"]]})
    _make_xlsx(tmp_path / "r.xlsx", {"S": [["id"], ["x"]]})
    yaml_path = tmp_path / "batch.yaml"
    yaml_path.write_text(f"""
name: agg_test
sources:
  left: {{type: excel, path: {tmp_path}/l.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: t1
    sources:
      left: {{sheets: [{{name: S}}]}}
      right: {{type: excel, path: {tmp_path}/r.xlsx, sheets: [{{name: S}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
""", encoding="utf-8")
    cfg = load_task_or_batch(yaml_path)
    assert isinstance(cfg, BatchConfig)
    execute_batch(cfg, {}, fail_on_diff=False)
    summary_json = tmp_path / "reports" / "batch_summary.json"
    summary_html = tmp_path / "reports" / "batch_summary.html"
    assert summary_json.exists()
    assert summary_html.exists()
    data = json.loads(summary_json.read_text(encoding="utf-8"))
    assert data["batch_name"] == "agg_test"
    assert data["task_count"] == 1
    assert data["success_count"] == 1
    assert data["exit_code"] == 0
    assert data["tasks"][0]["name"] == "t1"
    assert data["tasks"][0]["report_dir"] == "t1"


def test_execute_batch_summary_exit_code_reflects_fail_on_diff(tmp_path):
    """With diffs and fail_on_diff=True, summary exit_code should be 10."""
    _make_xlsx(tmp_path / "l.xlsx", {"S": [["id", "v"], ["x", "1"]]})
    _make_xlsx(tmp_path / "r.xlsx", {"S": [["id", "v"], ["x", "2"]]})
    yaml_path = tmp_path / "batch.yaml"
    yaml_path.write_text(f"""
name: diff_test
sources:
  left: {{type: excel, path: {tmp_path}/l.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: t1
    sources:
      left: {{sheets: [{{name: S}}]}}
      right: {{type: excel, path: {tmp_path}/r.xlsx, sheets: [{{name: S}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: v, right: v}}]}}
""", encoding="utf-8")
    cfg = load_task_or_batch(yaml_path)
    execute_batch(cfg, {}, fail_on_diff=True)
    data = json.loads(
        (tmp_path / "reports" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert data["exit_code"] == 10  # diff + fail_on_diff


def test_execute_batch_summary_records_failed_task(tmp_path):
    """A sub-task that raises should appear in summary with status=failed and error info."""
    _make_xlsx(tmp_path / "l.xlsx", {"S": [["id"], ["x"]]})
    _make_xlsx(tmp_path / "r.xlsx", {"S": [["id"], ["x"]]})
    yaml_path = tmp_path / "batch.yaml"
    yaml_path.write_text(f"""
name: fail_test
on_error: continue
sources:
  left: {{type: excel, path: {tmp_path}/l.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: t_ok
    sources:
      left: {{sheets: [{{name: S}}]}}
      right: {{type: excel, path: {tmp_path}/r.xlsx, sheets: [{{name: S}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: t_bad_sheet
    sources:
      left: {{sheets: [{{name: DOES_NOT_EXIST}}]}}
      right: {{type: excel, path: {tmp_path}/r.xlsx, sheets: [{{name: S}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
""", encoding="utf-8")
    cfg = load_task_or_batch(yaml_path)
    execute_batch(cfg, {}, fail_on_diff=False)
    data = json.loads(
        (tmp_path / "reports" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert data["success_count"] == 1
    assert data["failed_count"] == 1
    assert data["exit_code"] == 2  # runtime error present
    task_by_name = {t["name"]: t for t in data["tasks"]}
    assert task_by_name["t_ok"]["status"] == "success"
    assert task_by_name["t_bad_sheet"]["status"] == "failed"
    assert "error" in task_by_name["t_bad_sheet"]
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/test_runner_batch.py -v
```

预期：全部失败——`execute_batch` 尚未接受 `fail_on_diff` 参数（`TypeError`），也不写 summary 文件。

- [ ] **Step 3: 修改 execute_batch 签名 + 集成时间戳 + 调用 writers**

Edit `src/datacompare/runner.py`. Replace the entire `execute_batch` function (lines 153-227) with:

```python
def execute_batch(
    batch: BatchConfig,
    connections: dict[str, AnyConnection],
    fail_on_diff: bool = False,
) -> BatchResult:
    """Run each sub-task sequentially. on_error=continue (default) runs all;
    on_error=fail_fast marks remaining sub-tasks as skipped after first failure.

    Writes:
    - {output.dir}/batch.log — structured JSON event stream (task_start, task_end, etc.)
    - {output.dir}/batch_summary.json — aggregate result for CI/programmatic use
    - {output.dir}/batch_summary.html — human-readable index page

    fail_on_diff propagates from the CLI --fail-on-diff flag and only affects
    the exit_code recorded in the summary; the BatchResult object itself is
    identical either way.
    """
    from datetime import datetime, timezone
    from datacompare.reporters.batch_summary import (
        write_batch_summary_json,
        write_batch_summary_html,
    )

    defaults = _build_defaults_dict(batch)
    default_out_dir = (batch.output or {}).get("dir", "./reports")
    Path(default_out_dir).mkdir(parents=True, exist_ok=True)
    batch_log_path = Path(default_out_dir) / "batch.log"
    logger, handler = _init_batch_logger(batch_log_path)

    results: list[SubTaskResult] = []
    report_dirs: dict[str, str] = {}  # task_name -> path relative to default_out_dir
    started_at = datetime.now(timezone.utc).astimezone()
    batch_start = time.monotonic()
    logger.info("batch_start", batch_name=batch.name,
                task_count=len(batch.tasks), on_error=batch.on_error)

    try:
        aborted = False
        for i, sub in enumerate(batch.tasks, start=1):
            if aborted:
                results.append(SubTaskResult(
                    task_name=sub.name, status="skipped",
                    comparison_result=None, error=None, duration_ms=0,
                ))
                report_dirs[sub.name] = sub.name
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="skipped",
                            duration_ms=0)
                continue

            logger.info("task_start", task_name=sub.name, index=i, total=len(batch.tasks))

            sub_raw = {"name": sub.name, **(sub.model_extra or {})}
            merged = merge_sub_task(defaults, sub_raw)
            sub_out_dir = _resolve_sub_task_output_dir(sub_raw, merged, default_out_dir, sub.name)
            merged.setdefault("output", {})
            merged["output"]["dir"] = sub_out_dir

            # Record relative report_dir for summary
            try:
                rel = str(Path(sub_out_dir).relative_to(default_out_dir))
            except ValueError:
                rel = sub_out_dir  # sub-task set an unrelated absolute output.dir
            report_dirs[sub.name] = rel

            sub_task_start = time.monotonic()
            try:
                task = TaskConfig.model_validate(merged)
                cr = execute(task, connections)
                dur = int((time.monotonic() - sub_task_start) * 1000)
                results.append(SubTaskResult(
                    task_name=sub.name, status="success",
                    comparison_result=cr, error=None, duration_ms=dur,
                ))
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="success",
                            matched=cr.matched_rows, diff=cr.diff_rows,
                            left_only=cr.left_only, right_only=cr.right_only,
                            duration_ms=dur)
            except Exception as e:
                dur = int((time.monotonic() - sub_task_start) * 1000)
                results.append(SubTaskResult(
                    task_name=sub.name, status="failed",
                    comparison_result=None, error=e, duration_ms=dur,
                ))
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="failed",
                            error_type=type(e).__name__,
                            error_message=str(e), duration_ms=dur)
                if batch.on_error == "fail_fast":
                    aborted = True

        total_dur = int((time.monotonic() - batch_start) * 1000)
        ended_at = datetime.now(timezone.utc).astimezone()
        result = BatchResult(
            batch_name=batch.name, task_results=results, total_duration_ms=total_dur,
        )
        logger.info("batch_end", batch_name=batch.name,
                    success=result.success_count, failed=result.failed_count,
                    skipped=result.skipped_count, total_duration_ms=total_dur)

        # Write aggregate summary files. Failures here MUST NOT break the batch
        # — log warning and continue so we still return BatchResult.
        exit_code = result.compute_exit_code(fail_on_diff)
        for writer_name, writer in [
            ("batch_summary.json", write_batch_summary_json),
            ("batch_summary.html", write_batch_summary_html),
        ]:
            try:
                writer(
                    result, exit_code=exit_code,
                    started_at=started_at, ended_at=ended_at,
                    report_dirs=report_dirs,
                    out_dir=Path(default_out_dir),
                )
            except Exception as e:
                logger.warning("batch_summary_write_failed",
                               file=writer_name, error_type=type(e).__name__,
                               error_message=str(e))

        return result
    finally:
        logging.getLogger("datacompare.batch").removeHandler(handler)
        handler.close()
```

- [ ] **Step 4: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/test_runner_batch.py -v
```

预期：全部 3 个 pass。

- [ ] **Step 5: 全套 unit 回归**

```bash
.venv/Scripts/pytest tests/unit/ -q
```

预期：全绿。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/runner.py tests/unit/test_runner_batch.py
git commit -m "feat(runner): execute_batch writes batch_summary.{json,html} with fail_on_diff-aware exit_code"
```

---

## Task 4: CLI 传参

**Files:**
- Modify: `src/datacompare/cli.py:116` (execute_batch 调用)

- [ ] **Step 1: 修改调用点**

Edit `src/datacompare/cli.py`, line 116 — change from:

```python
        batch_result = execute_batch(cfg, conns)
```

to:

```python
        batch_result = execute_batch(cfg, conns, fail_on_diff=fail_on_diff)
```

- [ ] **Step 2: 全套回归验证 CLI 行为不变**

```bash
.venv/Scripts/pytest tests/ -q
```

预期：全绿。既有 batch e2e 集成测试（scenarios G/H/I/J/K）仍应通过——它们只检查
sub-task 的 report.json 存在与 batch.log 事件，不会因为新增两份聚合文件而失败。

- [ ] **Step 3: Commit**

```bash
git add src/datacompare/cli.py
git commit -m "feat(cli): pass fail_on_diff to execute_batch for accurate summary exit_code"
```

---

## Task 5: Batch e2e scenario L（覆盖失败任务 + 聚合报告）

**Files:**
- Modify: `tests/integration/test_batch_e2e.py`

- [ ] **Step 1: 追加测试**

Append to `tests/integration/test_batch_e2e.py`:

```python
def test_batch_scenario_l_summary_report_with_failure(tmp_path):
    """Scenario L: batch with 1 success + 1 failed (bad sheet) + 1 skipped
    (fail_fast) produces batch_summary.{json,html} with all statuses reflected.
    """
    _make_xlsx(tmp_path / "left.xlsx", {
        "GOOD": [["id"], ["1"], ["2"]],
        "BAD_INPUT": [["id"], ["3"]],  # left side sheet exists
    })
    _make_xlsx(tmp_path / "right.xlsx", {
        "GOOD": [["id"], ["1"], ["2"]],
        # NO sheet for the failing sub-task → right side read fails
    })
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: scenario_l
on_error: fail_fast
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: ok_task
    sources:
      left: {{sheets: [{{name: GOOD}}]}}
      right: {{type: excel, path: {tmp_path}/right.xlsx, sheets: [{{name: GOOD}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: bad_sheet_task
    sources:
      left: {{sheets: [{{name: BAD_INPUT}}]}}
      right: {{type: excel, path: {tmp_path}/right.xlsx, sheets: [{{name: DOES_NOT_EXIST}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: skipped_after_failure
    sources:
      left: {{sheets: [{{name: GOOD}}]}}
      right: {{type: excel, path: {tmp_path}/right.xlsx, sheets: [{{name: GOOD}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 2  # runtime error present

    # JSON summary
    summary_json = tmp_path / "reports" / "batch_summary.json"
    assert summary_json.exists()
    data = json.loads(summary_json.read_text(encoding="utf-8"))
    assert data["batch_name"] == "scenario_l"
    assert data["task_count"] == 3
    assert data["success_count"] == 1
    assert data["failed_count"] == 1
    assert data["skipped_count"] == 1
    assert data["exit_code"] == 2
    by_name = {t["name"]: t for t in data["tasks"]}
    assert by_name["ok_task"]["status"] == "success"
    assert "stats" in by_name["ok_task"]
    assert by_name["bad_sheet_task"]["status"] == "failed"
    assert "error" in by_name["bad_sheet_task"]
    assert by_name["skipped_after_failure"]["status"] == "skipped"

    # HTML summary
    summary_html = tmp_path / "reports" / "batch_summary.html"
    assert summary_html.exists()
    html_text = summary_html.read_text(encoding="utf-8")
    for name in ("ok_task", "bad_sheet_task", "skipped_after_failure"):
        assert name in html_text
    assert "✓" in html_text
    assert "✗" in html_text
    assert 'href="ok_task/report.html"' in html_text
```

- [ ] **Step 2: 跑测试**

```bash
.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_l_summary_report_with_failure -v
```

预期：PASS。

- [ ] **Step 3: 全套集成回归**

```bash
.venv/Scripts/pytest tests/integration/ -q
```

预期：全绿（Docker 相关 skip 可接受）。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_batch_e2e.py
git commit -m "test(integration): batch scenario L — summary report with mixed success/failed/skipped"
```

---

## Task 6: 文档

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: README.md**

Find the "批次模式" section (search `批次模式` or `batch-example`). Locate the paragraph
describing sub-task output directories (something like "每个 sub-task 写入
{output.dir}/{sub_task.name}/..."). Right after that paragraph add:

```markdown
批次跑完后，还会在 `{output.dir}` 下额外生成两份聚合产物：

- `batch_summary.json` —— 机读格式，CI 场景直接 parse。字段包含 `batch_name`、
  `started_at`/`ended_at`、`total_duration_ms`、`exit_code`、`success_count`
  /`failed_count`/`skipped_count`，以及每个 sub-task 的状态、比对统计
  （成功任务）或错误摘要（失败任务）。
- `batch_summary.html` —— 静态单文件索引页，链接到各 sub-task 的详细 report。
  双击就能在浏览器里浏览整批结果，失败任务的错误 message 直接内联展示。
```

- [ ] **Step 2: docs/user-guide.md**

Find the batch mode section (`### Batch mode` or 中文对应）with the rules bullet
list. Append two bullets to that list:

```markdown
- 批次结束后，`{defaults.output.dir}/batch_summary.json` 汇总所有 sub-task 的
  状态与统计（成功任务的 matched/diff/only 计数，失败任务的错误 type 与 message
  截断到 500 字符），并记录整批的 `exit_code`
- 同目录下 `batch_summary.html` 是人读友好的索引页，静态单文件，含到各 sub-task
  详细 report 的相对链接
```

- [ ] **Step 3: CLAUDE.md**

Find the `## 关键约束` section, locate the `批次模式 tasks:` bullet (should be
around line 71). Append a new bullet immediately after it:

```markdown
- **批次聚合报告**（v0.7 起）：`execute_batch` 结束后调用
  `reporters/batch_summary.py::write_batch_summary_{json,html}`，在
  `{output.dir}` 生成 `batch_summary.json` 和 `batch_summary.html`。JSON 用于
  CI parse、HTML 用于人工浏览。**写这两份文件本身不能抛异常**——磁盘满等错误
  只 log warning，不改 `BatchResult`（约束在 `execute_batch` 的 writer 循环
  try/except 里）。`fail_on_diff` 作为参数从 CLI 一路传到 `execute_batch` 用于
  算 `exit_code`，别在 writer 里再算一次——单一权威源。
```

- [ ] **Step 4: 验证**

```bash
grep -n "batch_summary" README.md docs/user-guide.md CLAUDE.md
```

预期：每个文件至少 1 处匹配。

```bash
.venv/Scripts/pytest tests/ -q
```

预期：全绿。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/user-guide.md CLAUDE.md
git commit -m "docs: batch aggregate summary report (batch_summary.{json,html})"
```

---

## 实现后 checklist

全部 6 个任务提交后：

- [ ] 全套跑一遍：`.venv/Scripts/pytest tests/ -q`
- [ ] Ruff 无回归：`.venv/Scripts/ruff check src/ tests/`
- [ ] mypy 无回归：`.venv/Scripts/mypy src/datacompare/`
- [ ] Push：`git push`

任一失败就地修，别推破的 suite。
