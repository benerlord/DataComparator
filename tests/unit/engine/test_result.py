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


def test_diff_type_regex_error_enum():
    assert DiffType.REGEX_ERROR.value == "regex_error"

def test_field_error_fields():
    e = FieldError(row_key={"id": "A1"}, field="amount", kind="type_error", original="N/A")
    assert e.kind == "type_error"


from datacompare.engine.result import BatchResult, SubTaskResult, CompareResult
import pandas as pd


def _dummy_compare(name: str = "t") -> CompareResult:
    return CompareResult(
        task_name=name, left_name="l", right_name="r",
        left_total=1, right_total=1, matched_rows=1, identical_rows=1,
        diff_rows=0, left_only=0, right_only=0,
        diff_details=pd.DataFrame(), left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.1,
    )


def test_sub_task_result_success():
    st = SubTaskResult(
        task_name="s1", status="success",
        comparison_result=_dummy_compare("s1"),
        error=None, duration_ms=1234,
    )
    assert st.status == "success"
    assert st.is_success


def test_sub_task_result_failed_carries_error():
    err = ValueError("boom")
    st = SubTaskResult(task_name="s2", status="failed",
                       comparison_result=None, error=err, duration_ms=50)
    assert st.status == "failed"
    assert not st.is_success
    assert st.error is err


def test_sub_task_result_skipped():
    st = SubTaskResult(task_name="s3", status="skipped",
                       comparison_result=None, error=None, duration_ms=0)
    assert st.status == "skipped"


def test_batch_result_aggregates_counts():
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "success", _dummy_compare(), None, 100),
            SubTaskResult("s2", "failed", None, ValueError("x"), 50),
            SubTaskResult("s3", "skipped", None, None, 0),
        ],
        total_duration_ms=150,
    )
    assert br.success_count == 1
    assert br.failed_count == 1
    assert br.skipped_count == 1


def test_batch_result_exit_code_all_success_no_diff():
    br = BatchResult(
        batch_name="b",
        task_results=[SubTaskResult("s1", "success", _dummy_compare(), None, 100)],
        total_duration_ms=100,
    )
    assert br.compute_exit_code(fail_on_diff=False) == 0


def test_batch_result_exit_code_all_success_with_diff_fail_on_diff():
    cr = _dummy_compare()
    cr.diff_rows = 1
    br = BatchResult(
        batch_name="b",
        task_results=[SubTaskResult("s1", "success", cr, None, 100)],
        total_duration_ms=100,
    )
    assert br.compute_exit_code(fail_on_diff=True) == 10


def test_batch_result_exit_code_config_error_wins_over_runtime():
    """priority: 2 > 10 > 1 > 0 - runtime (2) beats config (1)."""
    from datacompare.config.errors import ConfigError
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "failed", None, ConfigError("bad"), 50),
            SubTaskResult("s2", "failed", None, ValueError("runtime"), 100),
        ],
        total_duration_ms=150,
    )
    assert br.compute_exit_code(fail_on_diff=False) == 2


def test_batch_result_exit_code_config_error_only():
    from datacompare.config.errors import ConfigError
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "failed", None, ConfigError("bad"), 50),
            SubTaskResult("s2", "success", _dummy_compare(), None, 100),
        ],
        total_duration_ms=150,
    )
    assert br.compute_exit_code(fail_on_diff=False) == 1
