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
