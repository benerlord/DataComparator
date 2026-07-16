"""End-to-end tests for automatic log file creation in output.dir."""
from pathlib import Path
import re
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from datacompare.cli import app


runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def _write_task(task_path: Path, left_path: Path, right_path: Path, out_dir: Path):
    task_path.write_text(yaml.safe_dump({
        "name": "auto_log_test",
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
        "output": {"dir": str(out_dir), "formats": ["json"]},
    }))


_LOG_NAME_RE = re.compile(r"^run-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.log$")


def _find_auto_log(out_dir: Path) -> Path | None:
    matches = [p for p in out_dir.iterdir() if _LOG_NAME_RE.match(p.name)]
    return matches[0] if matches else None


def test_success_creates_auto_log_file_in_output_dir(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_no", "amount"], ["ORD-2026-000001", "100.00"]])
    _make_xlsx(right, [["order_id", "amount"], ["1", "100.00"]])
    out = tmp_path / "out"
    task = tmp_path / "task.yaml"
    _write_task(task, left, right, out)

    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 0, result.output
    log = _find_auto_log(out)
    assert log is not None, f"auto log not found in {list(out.iterdir())}"


def test_failure_still_creates_auto_log_file_with_mismatch_event(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["CANCEL-999", "100.00"],
    ])
    _make_xlsx(right, [["order_id", "amount"], ["1", "100.00"]])
    out = tmp_path / "out"
    task = tmp_path / "task.yaml"
    _write_task(task, left, right, out)

    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 2, result.output
    assert out.exists(), "output dir should exist so log file survives failure"
    log = _find_auto_log(out)
    assert log is not None
    contents = log.read_text(encoding="utf-8")
    assert "key_regex_mismatch" in contents
    assert "CANCEL-999" in contents


def test_explicit_log_file_overrides_auto(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_no", "amount"], ["ORD-2026-000001", "100.00"]])
    _make_xlsx(right, [["order_id", "amount"], ["1", "100.00"]])
    out = tmp_path / "out"
    task = tmp_path / "task.yaml"
    _write_task(task, left, right, out)
    custom_log = tmp_path / "custom_dir" / "my.log"

    result = runner.invoke(app, [
        "run", str(task),
        "--connections", str(tmp_path / "none.yaml"),
        "--log-file", str(custom_log),
    ])
    assert result.exit_code == 0, result.output
    assert custom_log.exists()
    # Auto log should NOT be created when --log-file is passed
    assert _find_auto_log(out) is None


def test_dry_run_creates_no_auto_log(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_no", "amount"], ["ORD-2026-000001", "100.00"]])
    _make_xlsx(right, [["order_id", "amount"], ["1", "100.00"]])
    out = tmp_path / "out"
    task = tmp_path / "task.yaml"
    _write_task(task, left, right, out)

    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert not out.exists() or _find_auto_log(out) is None


def test_output_dir_cli_override_places_log_there(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_no", "amount"], ["ORD-2026-000001", "100.00"]])
    _make_xlsx(right, [["order_id", "amount"], ["1", "100.00"]])
    yaml_out = tmp_path / "yaml_out"
    cli_out = tmp_path / "cli_out"
    task = tmp_path / "task.yaml"
    _write_task(task, left, right, yaml_out)

    result = runner.invoke(app, [
        "run", str(task),
        "--connections", str(tmp_path / "none.yaml"),
        "--output-dir", str(cli_out),
    ])
    assert result.exit_code == 0, result.output
    assert _find_auto_log(cli_out) is not None
    assert not yaml_out.exists() or _find_auto_log(yaml_out) is None
