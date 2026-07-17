"""End-to-end batch tests: heterogeneous right sides, mixed pass/fail, cross-sheet."""
import json
from pathlib import Path
import httpx
import respx
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app


runner = CliRunner()


def _make_xlsx(path: Path, sheets: dict[str, list[list]]):
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


@respx.mock
def test_batch_scenario_g_heterogeneous_success(tmp_path):
    """Scenario G: 3 sub-tasks — Excel→Excel(sheet), Excel→Excel(other file), Excel→API."""
    _make_xlsx(tmp_path / "manage.xlsx", {
        "PHYSICAL": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
        "VM": [["id", "name"], ["v1", "vm-1"], ["v2", "vm-2"]],
        "API_DATA": [["id", "value"], ["a1", "10"], ["a2", "20"]],
    })
    _make_xlsx(tmp_path / "snapshot.xlsx", {
        "PHYSICAL": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
    })
    _make_xlsx(tmp_path / "vm_ref.xlsx", {
        "VM": [["id", "name"], ["v1", "vm-1"], ["v2", "vm-2"]],
    })
    respx.get("http://api.test/v1/data", params={"page": "1", "size": "100"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"id": "a1", "value": "10"}, {"id": "a2", "value": "20"},
        ]}})
    )
    respx.get("http://api.test/v1/data", params={"page": "2", "size": "100"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": []}})
    )
    conns = tmp_path / "conns.yaml"
    conns.write_text("""
api_svc:
  type: api
  base_url: http://api.test
""", encoding="utf-8")
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: hetero
sources:
  left: {{type: excel, path: {tmp_path}/manage.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: cross_sheet
    sources:
      left: {{sheets: [{{name: PHYSICAL}}]}}
      right: {{type: excel, path: {tmp_path}/snapshot.xlsx, sheets: [{{name: PHYSICAL}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
  - name: vs_another_excel
    sources:
      left: {{sheets: [{{name: VM}}]}}
      right: {{type: excel, path: {tmp_path}/vm_ref.xlsx, sheets: [{{name: VM}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
  - name: vs_api
    sources:
      left: {{sheets: [{{name: API_DATA}}]}}
      right:
        type: api
        connection: api_svc
        url: /v1/data
        pagination: {{type: page, page_param: page, size_param: size, size: 100}}
        data_path: $.data.list[*]
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: value, right: value}}]}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(conns)])
    assert result.exit_code == 0, result.output
    for sub in ["cross_sheet", "vs_another_excel", "vs_api"]:
        assert (tmp_path / "reports" / sub / "report.json").exists()
    batch_log = tmp_path / "reports" / "batch.log"
    entries = [json.loads(l) for l in batch_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    task_ends = [e for e in entries if e["event"] == "task_end"]
    assert len(task_ends) == 3
    assert all(e["status"] == "success" for e in task_ends)


@respx.mock
def test_batch_scenario_h_mixed_failure_continue(tmp_path):
    """Scenario H: 3 sub-tasks — 1 success + 1 missing file + 1 API 500."""
    _make_xlsx(tmp_path / "manage.xlsx", {
        "OK_SHEET": [["id"], ["x1"]],
        "MISSING_RIGHT": [["id"], ["y1"]],
        "API_500": [["id"], ["z1"]],
    })
    _make_xlsx(tmp_path / "ok_right.xlsx", {
        "OK_SHEET": [["id"], ["x1"]],
    })
    respx.get("http://api.test/broken").mock(return_value=httpx.Response(500))
    conns = tmp_path / "conns.yaml"
    conns.write_text("api_svc: {type: api, base_url: http://api.test}\n", encoding="utf-8")
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: mixed
on_error: continue
sources:
  left: {{type: excel, path: {tmp_path}/manage.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: ok_task
    sources:
      left: {{sheets: [{{name: OK_SHEET}}]}}
      right: {{type: excel, path: {tmp_path}/ok_right.xlsx, sheets: [{{name: OK_SHEET}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: file_missing
    sources:
      left: {{sheets: [{{name: MISSING_RIGHT}}]}}
      right: {{type: excel, path: {tmp_path}/DOES_NOT_EXIST.xlsx}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: api_broken
    sources:
      left: {{sheets: [{{name: API_500}}]}}
      right:
        type: api
        connection: api_svc
        url: /broken
        pagination: {{type: page, page_param: page, size_param: size, size: 100}}
        data_path: $.data
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(conns)])
    assert result.exit_code == 2
    assert (tmp_path / "reports" / "ok_task" / "report.json").exists()
    batch_log = tmp_path / "reports" / "batch.log"
    entries = [json.loads(l) for l in batch_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    task_ends = {e["task_name"]: e for e in entries if e["event"] == "task_end"}
    assert task_ends["ok_task"]["status"] == "success"
    assert task_ends["file_missing"]["status"] == "failed"
    assert task_ends["api_broken"]["status"] == "failed"


def test_batch_scenario_i_same_excel_cross_sheet(tmp_path):
    """Scenario I: sub-task compares two sheets from the same Excel file."""
    _make_xlsx(tmp_path / "same.xlsx", {
        "LEFT_SHEET": [["id", "v"], ["a", "1"], ["b", "2"]],
        "RIGHT_SHEET": [["id", "v"], ["a", "1"], ["b", "2"]],
    })
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: same_file_cross_sheet
sources:
  left: {{type: excel, path: {tmp_path}/same.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: sheet_a_vs_sheet_b
    sources:
      left: {{sheets: [{{name: LEFT_SHEET}}]}}
      right: {{type: excel, path: {tmp_path}/same.xlsx, sheets: [{{name: RIGHT_SHEET}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: v, right: v}}]}}
""", encoding="utf-8")
    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "reports" / "sheet_a_vs_sheet_b" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["matched"] == 2
