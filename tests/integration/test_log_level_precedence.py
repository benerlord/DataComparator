"""Verify CLI --log-level > task.runtime.log_level > default INFO precedence."""
import logging
from pathlib import Path
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


def _write_task(task_path: Path, out_dir: Path, runtime_log_level: str | None = None):
    left = task_path.parent / "left.xlsx"
    right = task_path.parent / "right.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "1.00"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "1.00"]])
    doc = {
        "name": "log_level_test",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount", "mode": "numeric", "decimal_places": 2},
        ]},
        "output": {"dir": str(out_dir), "formats": ["json"]},
    }
    if runtime_log_level is not None:
        doc["runtime"] = {"log_level": runtime_log_level}
    task_path.write_text(yaml.safe_dump(doc))


def _run_and_get_effective_level(tmp_path, runtime_log_level, cli_log_level=None):
    task = tmp_path / "task.yaml"
    out = tmp_path / "out"
    _write_task(task, out, runtime_log_level=runtime_log_level)
    args = ["run", str(task), "--connections", str(tmp_path / "none.yaml")]
    if cli_log_level is not None:
        args += ["--log-level", cli_log_level]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    # After configure_logging runs, root logger level reflects what was chosen.
    return logging.getLogger().level


def test_cli_log_level_wins_over_task_runtime(tmp_path):
    level = _run_and_get_effective_level(tmp_path, runtime_log_level="ERROR",
                                          cli_log_level="DEBUG")
    assert level == logging.DEBUG


def test_task_runtime_log_level_used_when_no_cli_flag(tmp_path):
    level = _run_and_get_effective_level(tmp_path, runtime_log_level="ERROR",
                                          cli_log_level=None)
    assert level == logging.ERROR


def test_default_info_when_neither_set(tmp_path):
    # No runtime block at all; Pydantic default is INFO.
    level = _run_and_get_effective_level(tmp_path, runtime_log_level=None,
                                          cli_log_level=None)
    assert level == logging.INFO


def test_cli_debug_beats_task_debug_same_level(tmp_path):
    """Sanity: no interference when both agree."""
    level = _run_and_get_effective_level(tmp_path, runtime_log_level="DEBUG",
                                          cli_log_level="DEBUG")
    assert level == logging.DEBUG
