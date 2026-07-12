import pandas as pd
from datacompare.reporters.csv import CSVReporter
from datacompare.engine.result import CompareResult


def _sample():
    return CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=1, right_total=1,
        matched_rows=1, identical_rows=0, diff_rows=1,
        left_only=1, right_only=1,
        diff_details=pd.DataFrame([{"order_id": "A1", "field": "amount",
                                    "left_value": "1", "right_value": "2",
                                    "diff_type": "value_mismatch"}]),
        left_only_rows=pd.DataFrame([{"order_id": "X"}]),
        right_only_rows=pd.DataFrame([{"order_id": "Y"}]),
        engine_used="memory", duration_seconds=0.1, errors=[],
    )


def test_csv_writes_all_files(tmp_path):
    CSVReporter({}, tmp_path).render(_sample())
    assert (tmp_path / "csv" / "diff_details.csv").exists()
    assert (tmp_path / "csv" / "left_only.csv").exists()
    assert (tmp_path / "csv" / "right_only.csv").exists()
    assert (tmp_path / "csv" / "summary.csv").exists()


def test_csv_summary_content(tmp_path):
    CSVReporter({}, tmp_path).render(_sample())
    summary = (tmp_path / "csv" / "summary.csv").read_text(encoding="utf-8-sig")
    assert "matched_rows" in summary
    assert "1" in summary
