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


def test_validate_ok(tmp_path):
    left = tmp_path / "l.xlsx"
    right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [{"left": "amount", "right": "amount"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, ["validate", str(task), "--connections", str(conn)])
    assert result.exit_code == 0, result.stdout
    assert "valid" in result.stdout.lower() or "ok" in result.stdout.lower()


def test_validate_missing_column(tmp_path):
    left = tmp_path / "l.xlsx"; right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["order_id", "amount"], ["A1", "100"]])
    _make_xlsx(right, [["order_id", "amount"], ["A1", "100"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [{"left": "missing_col", "right": "amount"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, ["validate", str(task), "--connections", str(conn)])
    assert result.exit_code == 1
    assert "missing_col" in result.stdout or "missing_col" in (result.stderr or "")
