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

from jinja2 import Environment, FileSystemLoader, select_autoescape

from datacompare.config.errors import ConfigError
from datacompare.engine.result import BatchResult, SubTaskResult

_ERROR_MESSAGE_MAX_CHARS = 500
_TEMPLATE_DIR = Path(__file__).parent / "templates"


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
