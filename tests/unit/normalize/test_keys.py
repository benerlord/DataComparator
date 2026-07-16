import pandas as pd
import pytest
from datacompare.config.models import KeyMapping
from datacompare.normalize.keys import KeyRegexMismatchError, apply_key_regex


def test_key_regex_mismatch_error_carries_all_fields():
    err = KeyRegexMismatchError(
        side="left",
        column="order_no",
        value="CANCEL-999",
        pattern=r"ORD-\d+",
        row_index=3,
    )
    assert err.side == "left"
    assert err.column == "order_no"
    assert err.value == "CANCEL-999"
    assert err.pattern == r"ORD-\d+"
    assert err.row_index == 3
    assert isinstance(err, ValueError)


def test_key_regex_mismatch_error_message_includes_all_fields():
    err = KeyRegexMismatchError(
        side="right", column="id", value="abc", pattern=r"\d+", row_index=0,
    )
    msg = str(err)
    assert "right" in msg
    assert "'id'" in msg
    assert "'abc'" in msg
    assert r"'\\d+'" in msg or r"\d+" in msg
    assert "row_index=0" in msg


def test_apply_key_regex_no_regex_returns_df_unchanged():
    df = pd.DataFrame({"order_id": ["A1", "A2"], "amount": ["100", "200"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_id"]) == ["A1", "A2"]
    assert list(result["amount"]) == ["100", "200"]


def test_apply_key_regex_returns_copy_not_original():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    result = apply_key_regex(df, keys, side="left")
    assert result is not df


def test_apply_key_regex_empty_dataframe():
    df = pd.DataFrame({"order_id": [], "amount": []}).astype(object)
    keys = [KeyMapping(left="order_id", right="order_id", left_regex=r"\d+")]
    result = apply_key_regex(df, keys, side="left")
    assert len(result) == 0


def test_apply_key_regex_capture_group_one_extracts_group_1():
    df = pd.DataFrame({"order_no": ["ORD-000123", "ORD-000456"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_no"]) == ["123", "456"]


def test_apply_key_regex_no_capture_group_uses_full_match():
    df = pd.DataFrame({"code": ["ABC123", "XYZ789"]})
    keys = [KeyMapping(left="code", right="code", left_regex=r"[A-Z]+\d+")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["code"]) == ["ABC123", "XYZ789"]


def test_apply_key_regex_none_value_passes_through():
    df = pd.DataFrame({"order_no": ["ORD-001", None]}).astype(object)
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="left")
    vals = result["order_no"].tolist()
    assert vals[0] == "1"
    assert vals[1] is None


def test_apply_key_regex_right_side_uses_right_regex():
    df = pd.DataFrame({"order_id": ["ORD-000123"]})
    keys = [KeyMapping(left="order_no", right="order_id", right_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="right")
    assert list(result["order_id"]) == ["123"]


def test_apply_key_regex_side_specific_only_transforms_configured_side():
    df_left = pd.DataFrame({"order_no": ["ORD-000123"]})
    df_right = pd.DataFrame({"order_id": ["123"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    left_out = apply_key_regex(df_left, keys, side="left")
    right_out = apply_key_regex(df_right, keys, side="right")
    assert list(left_out["order_no"]) == ["123"]
    assert list(right_out["order_id"]) == ["123"]  # right had no regex — unchanged


def test_apply_key_regex_composite_keys_independent_regexes():
    df = pd.DataFrame({
        "order_no": ["ORD-000123", "ORD-000456"],
        "region_code": ["REG_BJ", "REG_SH"],
    })
    keys = [
        KeyMapping(left="order_no", right="oid", left_regex=r"ORD-0*(\d+)"),
        KeyMapping(left="region_code", right="reg", left_regex=r"REG_([A-Z]+)"),
    ]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_no"]) == ["123", "456"]
    assert list(result["region_code"]) == ["BJ", "SH"]
