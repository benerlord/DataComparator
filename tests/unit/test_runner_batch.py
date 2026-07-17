from pathlib import Path
import pytest
from openpyxl import Workbook
from datacompare.config.loader import load_task_or_batch
from datacompare.runner import execute_batch
from datacompare.engine.result import BatchResult


def _make_xlsx(path: Path, rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)


def _write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def _batch_two_success(tmp_path: Path) -> Path:
    _make_xlsx(tmp_path / "left.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"], ["A2", "2.00"],
    ])
    _make_xlsx(tmp_path / "right.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"], ["A2", "2.00"],
    ])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: [{{left: amount, right: amount, mode: numeric, decimal_places: 2}}]
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
""")
    return task


def test_execute_batch_all_success(tmp_path):
    task_path = _batch_two_success(tmp_path)
    batch = load_task_or_batch(task_path, {})
    result = execute_batch(batch, connections={})
    assert isinstance(result, BatchResult)
    assert result.success_count == 2
    assert result.failed_count == 0
    assert (tmp_path / "out" / "sub1" / "report.json").exists()
    assert (tmp_path / "out" / "sub2" / "report.json").exists()


def test_execute_batch_continues_on_sub_task_failure(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"],
    ])
    _make_xlsx(tmp_path / "right.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"],
    ])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
on_error: continue
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: [{{left: amount, right: amount, mode: numeric, decimal_places: 2}}]
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
    sources:
      left: {{path: {tmp_path}/missing.xlsx}}
""")
    batch = load_task_or_batch(task, {})
    result = execute_batch(batch, connections={})
    assert result.success_count == 1
    assert result.failed_count == 1
    assert result.task_results[0].status == "success"
    assert result.task_results[1].status == "failed"
    assert result.task_results[1].error is not None


def test_execute_batch_sub_task_explicit_output_dir_overrides_autopath(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    custom_dir = tmp_path / "custom_place"
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
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
  - name: sub_custom
    output:
      dir: {custom_dir}
""")
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    assert (custom_dir / "report.json").exists()
    # auto-path NOT used
    assert not (tmp_path / "out" / "sub_custom").exists() or \
        not (tmp_path / "out" / "sub_custom" / "report.json").exists()
