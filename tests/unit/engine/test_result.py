import pytest
import pandas as pd
from datacompare.engine.result import CompareResult, FieldError, DiffType

def test_compare_result_defaults():
    r = CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=0, right_total=0,
        matched_rows=0, identical_rows=0, diff_rows=0,
        left_only=0, right_only=0,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.0, errors=[],
    )
    assert r.match_rate() == 0.0

def test_match_rate_computed():
    r = CompareResult(
        task_name="t", left_name="l", right_name="r",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=1.0, errors=[],
    )
    # 90 identical out of (100+100-95) unique
    assert r.match_rate() == pytest.approx(90 / (100 + 100 - 95))

def test_diff_type_enum():
    assert DiffType.VALUE_MISMATCH.value == "value_mismatch"
    assert DiffType.TYPE_ERROR.value == "type_error"
    assert DiffType.UNIT_ERROR.value == "unit_error"
    assert DiffType.NULL_MISMATCH.value == "null_mismatch"

def test_field_error_fields():
    e = FieldError(row_key={"id": "A1"}, field="amount", kind="type_error", original="N/A")
    assert e.kind == "type_error"
