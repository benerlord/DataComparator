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
