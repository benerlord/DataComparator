import json
from pathlib import Path
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def _make_xlsx(path: Path, rows: list[list]):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_run_excel_vs_excel_json(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100.50"], ["A2", "200"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100.51"], ["A2", "200"]])

    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "name": "excel_vs_excel",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount", "mode": "numeric", "decimal_places": 2}
        ]},
        "output": {"dir": str(tmp_path / "out"), "formats": ["json"]},
    }))

    connections = tmp_path / "connections.yaml"
    connections.write_text("")

    result = runner.invoke(app, [
        "run", str(task), "--connections", str(connections),
    ])
    assert result.exit_code == 0, result.stdout

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["diff"] == 1


def test_run_fail_on_diff(tmp_path):
    left = tmp_path / "l.xlsx"
    right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["id", "v"], ["A", "1"]])
    _make_xlsx(right, [["id", "v"], ["A", "2"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "id", "right": "id"}]},
        "compare": {"fields": [{"left": "v", "right": "v", "mode": "string"}]},
        "output": {"dir": str(tmp_path / "out"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(conn), "--fail-on-diff",
    ])
    assert result.exit_code == 10
