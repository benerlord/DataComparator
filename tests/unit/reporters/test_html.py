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


def test_html_renders_field_missing_row_with_gray_class(tmp_path):
    """v0.8: diff_type=field_missing 的 diff 行的样式类存在 CSS 里，且
    "字段不存在" 字面量能在 HTML 中被找到（作为表格单元格值）。"""
    result = CompareResult(
        task_name="physical_host", left_name="manage.xlsx", right_name="prod.xlsx",
        left_total=100, right_total=100,
        matched_rows=100, identical_rows=100, diff_rows=1,
        left_only=0, right_only=0,
        diff_details=pd.DataFrame([{
            "id": "", "field": "vmemorys",
            "left_value": "字段不存在", "right_value": "(右侧 100 行有值)",
            "diff_type": "field_missing",
        }]),
        left_only_rows=pd.DataFrame(), right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.1, errors=[],
    )
    p = HTMLReporter({"include_charts": False}, tmp_path).render(result)
    content = p.read_text(encoding="utf-8")
    # 字面量出现在 diff_details 单元格里
    assert "字段不存在" in content
    # CSS 规则存在
    assert "tr.field_missing" in content
    # diff_type 字符串也出现（作为单元格值）
    assert "field_missing" in content
