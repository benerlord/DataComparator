import pytest
from datacompare.normalize.keys import KeyRegexMismatchError


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
