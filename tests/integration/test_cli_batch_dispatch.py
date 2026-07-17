from pathlib import Path
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app


runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    wb.save(path)


def _batch_two_success_yaml(tmp_path: Path) -> Path:
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: cli_batch
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
""", encoding="utf-8")
    return task


def test_cli_run_dispatches_to_batch_mode_exit_0(tmp_path):
    task = _batch_two_success_yaml(tmp_path)
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 0, result.output
    assert "cli_batch" in result.output or "Batch" in result.output
    assert "sub1" in result.output and "sub2" in result.output
    assert "succeeded" in result.output.lower() or "success" in result.output.lower()
    assert (tmp_path / "out" / "batch.log").exists()
    assert (tmp_path / "out" / "sub1" / "report.json").exists()
    assert (tmp_path / "out" / "sub2" / "report.json").exists()


def test_cli_batch_failure_returns_exit_2(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: mixed
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: ok
  - name: bad
    sources: {{left: {{path: {tmp_path}/missing.xlsx}}}}
""", encoding="utf-8")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 2, result.output


def test_cli_dry_run_batch_valid_exit_0(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = _batch_two_success_yaml(tmp_path)
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output.lower()
    assert "sub1" in result.output and "sub2" in result.output


def test_cli_dry_run_batch_invalid_lists_all_sub_task_errors(tmp_path):
    """Two sub-tasks with missing right.query — both should be listed."""
    task = tmp_path / "bad.yaml"
    task.write_text(f"""
name: bad_batch
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: gaussdb, connection: c}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub_a
  - name: sub_b
""", encoding="utf-8")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"), "--dry-run",
    ])
    assert result.exit_code == 1
    assert "sub_a" in result.output and "sub_b" in result.output
