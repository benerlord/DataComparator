import json
import pandas as pd
from pathlib import Path
from datacompare.reporters.json import JSONReporter
from datacompare.engine.result import CompareResult

def _sample_result():
    return CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=10, right_total=10,
        matched_rows=8, identical_rows=7, diff_rows=1,
        left_only=2, right_only=2,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "1", "right_value": "2",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y"}]),
        engine_used="memory", duration_seconds=0.5, errors=[],
    )


def test_json_renders_file(tmp_path):
    reporter = JSONReporter({"truncate_details_over": 10_000}, tmp_path)
    p = reporter.render(_sample_result())
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["task"] == "t"
    assert data["summary"]["diff"] == 1
    assert len(data["diff_details"]) == 1
    assert data["truncated"] is False


def test_json_truncates_when_too_large(tmp_path):
    result = _sample_result()
    result.diff_details = pd.DataFrame([{"order_id": f"A{i}"} for i in range(50)])
    reporter = JSONReporter({"truncate_details_over": 10}, tmp_path)
    p = reporter.render(result)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["truncated"] is True
    assert len(data["diff_details"]) == 10
