import pandas as pd
from datacompare.reporters.html import HTMLReporter
from datacompare.engine.result import CompareResult


def _sample():
    return CompareResult(
        task_name="Sales", left_name="left.xlsx", right_name="prod.db",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "100.5", "right_value": "100.6",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X1"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y1"}]),
        engine_used="memory", duration_seconds=1.2, errors=[],
    )


def test_html_writes_file(tmp_path):
    p = HTMLReporter({"include_charts": True}, tmp_path).render(_sample())
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "Sales" in content
    assert "value_mismatch" in content
    assert "<!DOCTYPE html>" in content


def test_html_without_charts(tmp_path):
    p = HTMLReporter({"include_charts": False}, tmp_path).render(_sample())
    content = p.read_text(encoding="utf-8")
    # Chart script should not be included
    assert "chart-data" not in content
