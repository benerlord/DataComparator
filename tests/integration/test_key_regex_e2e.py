"""End-to-end + engine parity tests for key regex transform.

Uses Excel-vs-Excel (no external services) so tests are self-contained.
"""
import json
from pathlib import Path

import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from datacompare.cli import app
from datacompare.config.models import (
    CompareConfig,
    CompareDefaults,
    ExcelSourceConfig,
    FieldRule,
    KeyMapping,
    MatchConfig,
    OutputConfig,
    RuntimeConfig,
    TaskConfig,
)
from datacompare.engine.disk import DiskEngine
from datacompare.engine.memory import InMemoryEngine
from datacompare.sources.excel import ExcelSource


runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def _task_yaml(left_path: Path, right_path: Path, out_dir: Path) -> dict:
    return {
        "name": "key_regex_e2e",
        "sources": {
            "left": {"type": "excel", "path": str(left_path)},
            "right": {"type": "excel", "path": str(right_path)},
        },
        "match": {"keys": [
            {"left": "order_no", "right": "order_id",
             "left_regex": r"ORD-\d{4}-0*(\d+)"},
        ]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount",
             "mode": "numeric", "decimal_places": 2},
        ]},
        "output": {"dir": str(out_dir),
                   "formats": ["json"]},
    }


def _build_task(left_path: Path, right_path: Path, engine: str) -> TaskConfig:
    return TaskConfig(
        name="parity",
        sources={
            "left": ExcelSourceConfig(path=str(left_path)),
            "right": ExcelSourceConfig(path=str(right_path)),
        },
        match=MatchConfig(keys=[KeyMapping(
            left="order_no", right="order_id",
            left_regex=r"ORD-\d{4}-0*(\d+)",
        )]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(left="amount", right="amount",
                              mode="numeric", decimal_places=2)],
        ),
        output=OutputConfig(dir="./out", formats=["json"]),
        runtime=RuntimeConfig(engine=engine, memory_threshold_rows=500_000),
    )


def test_engine_parity_with_left_regex(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["ORD-2026-000002", "200.00"],
        ["ORD-2026-000003", "300.00"],
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
        ["2", "200.50"],   # value diff
        ["4", "400.00"],   # right-only
    ])

    mem_task = _build_task(left_path, right_path, engine="memory")
    disk_task = _build_task(left_path, right_path, engine="disk")

    mem_left = ExcelSource(ExcelSourceConfig(path=str(left_path)), name="left")
    mem_right = ExcelSource(ExcelSourceConfig(path=str(right_path)), name="right")
    disk_left = ExcelSource(ExcelSourceConfig(path=str(left_path)), name="left")
    disk_right = ExcelSource(ExcelSourceConfig(path=str(right_path)), name="right")

    try:
        mem_result = InMemoryEngine().compare(mem_left, mem_right, mem_task)
    finally:
        mem_left.close()
        mem_right.close()
    try:
        disk_result = DiskEngine().compare(disk_left, disk_right, disk_task)
    finally:
        disk_left.close()
        disk_right.close()

    assert mem_result.matched_rows == disk_result.matched_rows
    assert mem_result.diff_rows == disk_result.diff_rows
    assert mem_result.identical_rows == disk_result.identical_rows
    assert mem_result.left_total == disk_result.left_total
    assert mem_result.right_total == disk_result.right_total
    assert mem_result.left_only == disk_result.left_only
    assert mem_result.right_only == disk_result.right_only
    # errors list should agree (both empty in this happy-path scenario)
    assert len(mem_result.errors) == len(disk_result.errors)

    # Sanity: expected outcome should be 2 matched (keys 1, 2), one diff (key 2),
    # one left-only (key 3), one right-only (key 4).
    assert mem_result.matched_rows == 2
    assert mem_result.diff_rows == 1
    assert mem_result.left_only == 1
    assert mem_result.right_only == 1


def test_cli_run_succeeds_with_key_regex(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["ORD-2026-000002", "200.00"],
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
        ["2", "200.00"],
    ])

    task_path = tmp_path / "task.yaml"
    out_dir = tmp_path / "out"
    task_path.write_text(yaml.safe_dump(_task_yaml(left_path, right_path, out_dir)))

    result = runner.invoke(app, [
        "run", str(task_path),
        "--connections", str(tmp_path / "nonexistent.yaml"),
    ])
    assert result.exit_code == 0, result.output

    json_files = list(out_dir.glob("*.json"))
    assert len(json_files) == 1
    report = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert report["summary"]["matched"] == 2
    assert report["summary"]["diff"] == 0
    assert report["summary"]["left_only"] == 0
    assert report["summary"]["right_only"] == 0


def test_cli_run_exits_2_and_logs_on_regex_mismatch(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["CANCEL-999", "100.00"],   # regex mismatch
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
    ])

    task_path = tmp_path / "task.yaml"
    out_dir = tmp_path / "out"
    task_path.write_text(yaml.safe_dump(_task_yaml(left_path, right_path, out_dir)))

    result = runner.invoke(app, [
        "run", str(task_path),
        "--connections", str(tmp_path / "nonexistent.yaml"),
    ])
    assert result.exit_code == 2, result.output
    combined = (result.output or "") + (result.stderr or "")
    assert "CANCEL-999" in combined or "key regex mismatch" in combined
    # No report files should be produced when the run aborts.
    assert not out_dir.exists() or not list(out_dir.glob("*.json"))
