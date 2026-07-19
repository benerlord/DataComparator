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


import structlog


def test_apply_key_regex_partial_match_raises_because_fullmatch():
    df = pd.DataFrame({"code": ["abc123def"]})
    keys = [KeyMapping(left="code", right="code", left_regex=r"\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    err = exc.value
    assert err.side == "left"
    assert err.column == "code"
    assert err.value == "abc123def"
    assert err.pattern == r"\d+"
    assert err.row_index == 0


def test_apply_key_regex_complete_mismatch_raises():
    df = pd.DataFrame({"order_no": ["ORD-001", "ORD-002", "CANCEL-999"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    err = exc.value
    assert err.row_index == 2  # third row, 0-based
    assert err.value == "CANCEL-999"


def test_apply_key_regex_first_mismatch_wins_fail_fast():
    df = pd.DataFrame({"order_no": ["BAD1", "BAD2"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    assert exc.value.row_index == 0  # first mismatch, not second
    assert exc.value.value == "BAD1"


def test_apply_key_regex_emits_structured_log_on_mismatch():
    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[cap])
    try:
        df = pd.DataFrame({"order_no": ["CANCEL-1"]})
        keys = [KeyMapping(
            left="order_no", right="order_id", left_regex=r"ORD-\d+",
        )]
        with pytest.raises(KeyRegexMismatchError):
            apply_key_regex(df, keys, side="left")
        assert len(cap.entries) >= 1
        entry = next(e for e in cap.entries if e["event"] == "key_regex_mismatch")
        assert entry["side"] == "left"
        assert entry["column"] == "order_no"
        assert entry["value"] == "CANCEL-1"
        assert entry["pattern"] == r"ORD-\d+"
        assert entry["row_index"] == 0
        assert entry["log_level"] == "error"
    finally:
        # restore default configuration to avoid leaking test config
        structlog.reset_defaults()


class TestApplyRegexOnCanonical:
    def test_strict_mode_extracts_group_one(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", "Bob@@2"]})
        apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")
        assert df["c"].tolist() == ["1", "2"]

    def test_strict_mode_raises_on_mismatch(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", "no_at_at"]})
        with pytest.raises(KeyRegexMismatchError):
            apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")

    def test_soft_mode_extracts_group_one(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", "Bob@@2"]})
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        assert df["c"].tolist() == ["Alice", "Bob"]

    def test_soft_mode_returns_sentinel_on_mismatch(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        from datacompare.normalize.regex_errors import RegexError
        df = pd.DataFrame({"c": ["Alice@@1", "no_at_at", "Carol@@3"]})
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        vals = df["c"].tolist()
        assert vals[0] == "Alice"
        assert isinstance(vals[1], RegexError)
        assert vals[1].original == "no_at_at"
        assert vals[1].pattern == r"(.*)@@.*"
        assert vals[2] == "Carol"

    def test_none_values_passthrough_strict(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", None]}, dtype=object)
        apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")
        assert df["c"].tolist() == ["1", None]

    def test_none_values_passthrough_soft(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", None]}, dtype=object)
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        assert df["c"].tolist() == ["Alice", None]

    def test_zero_groups_uses_group_zero(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["abc", "xyz"]})
        apply_regex_on_canonical(df, {"c": r"[a-z]+"}, mode="strict")
        assert df["c"].tolist() == ["abc", "xyz"]

    def test_multi_column_regex_map(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({
            "a": ["X@@1", "Y@@2"],
            "b": ["P@@Q", "R@@S"],
        })
        apply_regex_on_canonical(df, {
            "a": r".*@@(.*)",
            "b": r"(.*)@@.*",
        }, mode="strict")
        assert df["a"].tolist() == ["1", "2"]
        assert df["b"].tolist() == ["P", "R"]

    def test_empty_regex_map_noop(self):
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["a", "b"]})
        apply_regex_on_canonical(df, {}, mode="strict")
        assert df["c"].tolist() == ["a", "b"]
