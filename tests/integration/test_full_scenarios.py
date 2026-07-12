import json
from pathlib import Path
import httpx
import respx
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


@respx.mock
def test_excel_vs_api_all_formats(tmp_path):
    excel_path = tmp_path / "expected.xlsx"
    _make_xlsx(excel_path, [
        ["order_id", "amount"],
        ["A1", "100.50"],
        ["A2", "200.00"],
        ["A3", "300.00"],
    ])

    respx.get("http://api.test/orders", params={"offset": "0", "limit": "10"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"order_id": "A1", "amount": "100.50"},
            {"order_id": "A2", "amount": "199.99"},   # diff
        ]}})
    )
    respx.get("http://api.test/orders", params={"offset": "10", "limit": "10"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": []}})
    )

    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "name": "excel_vs_api_scenario",
        "sources": {
            "left": {"type": "excel", "path": str(excel_path)},
            "right": {
                "type": "api", "connection": "svc", "url": "/orders",
                "pagination": {
                    "type": "offset", "offset_param": "offset",
                    "size_param": "limit", "size": 10,
                },
                "data_path": "$.data.list[*]",
            },
        },
        "match": {"keys": [{"left": "order_id", "right": "order_id"}]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount", "mode": "numeric", "decimal_places": 2}
        ]},
        "output": {"dir": str(tmp_path / "out"),
                   "formats": ["html", "excel", "csv", "json", "console"]},
    }))
    conn = tmp_path / "conn.yaml"
    conn.write_text(yaml.safe_dump({
        "svc": {"type": "api", "base_url": "http://api.test"}
    }))

    result = runner.invoke(app, ["run", str(task), "--connections", str(conn)])
    assert result.exit_code == 0, f"stdout={result.stdout}\nexit={result.exit_code}"

    out = tmp_path / "out"
    assert (out / "report.html").exists()
    assert (out / "report.xlsx").exists()
    assert (out / "report.json").exists()
    assert (out / "csv" / "diff_details.csv").exists()

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["diff"] == 1
    assert report["summary"]["left_only"] == 1  # A3
    assert report["summary"]["right_only"] == 0


def test_dry_run_exits_zero_without_running(tmp_path):
    left = tmp_path / "l.xlsx"; right = tmp_path / "r.xlsx"
    _make_xlsx(left, [["k", "v"], ["A", "1"]])
    _make_xlsx(right, [["k", "v"], ["A", "1"]])
    task = tmp_path / "t.yaml"
    task.write_text(yaml.safe_dump({
        "name": "t",
        "sources": {
            "left": {"type": "excel", "path": str(left)},
            "right": {"type": "excel", "path": str(right)},
        },
        "match": {"keys": [{"left": "k", "right": "k"}]},
        "compare": {"fields": [{"left": "v", "right": "v"}]},
        "output": {"dir": str(tmp_path / "o"), "formats": ["json"]},
    }))
    conn = tmp_path / "c.yaml"; conn.write_text("")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(conn), "--dry-run",
    ])
    assert result.exit_code == 0
    assert not (tmp_path / "o").exists()
