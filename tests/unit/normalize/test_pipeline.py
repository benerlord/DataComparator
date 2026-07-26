import pandas as pd
import pytest
from datacompare.config.models import (
    KeyMapping, FieldRule, CompareDefaults, CompareConfig, MatchConfig,
)
from datacompare.normalize.keys import KeyRegexMismatchError
from datacompare.normalize.pipeline import normalize_side

def _cfg(fields, defaults=None):
    return CompareConfig(defaults=defaults or CompareDefaults(), fields=fields)

def test_pipeline_renames_and_filters_columns():
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100.50"], "extra": ["x"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["order_id", "amount"]

def test_numeric_rounding():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100.556"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["amount"] == 100.56

def test_null_equivalent_becomes_none():
    df = pd.DataFrame({"order_id": ["A1"], "region": ["null"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(left="region", right="region", mode="string")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["region"] is None

def test_unit_parse():
    df = pd.DataFrame({"order_id": ["A1"], "storage": ["30 TB"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    fields = [FieldRule(
        left="storage", right="storage", mode="numeric",
        parse_unit=True, unit_category="storage", normalize_to="GB", decimal_places=0,
    )]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["storage"] == 30720

def test_string_case_and_whitespace():
    df = pd.DataFrame({"order_id": ["A1"], "region": ["  NORTH  "]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    defaults = CompareDefaults()
    fields = [FieldRule(
        left="region", right="region", mode="string",
        ignore_whitespace=True, ignore_case=True,
    )]
    result = normalize_side(df, keys, _cfg(fields, defaults), side="left")
    assert result.iloc[0]["region"] == "north"


def test_pipeline_applies_left_regex_before_join():
    df = pd.DataFrame({"order_no": ["ORD-000123"], "amount": ["100"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       left_regex=r"ORD-0*(\d+)")]
    fields = [FieldRule(left="amount", right="amount")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["order_id", "amount"]
    assert result.iloc[0]["order_id"] == "123"


def test_pipeline_applies_right_regex():
    df = pd.DataFrame({"order_id": ["ORD-000456"], "amount": ["200"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       right_regex=r"ORD-0*(\d+)")]
    fields = [FieldRule(left="amount", right="amount")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert result.iloc[0]["order_id"] == "456"


def test_pipeline_raises_key_regex_mismatch_error():
    df = pd.DataFrame({"order_no": ["CANCEL-999"], "amount": ["100"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       left_regex=r"ORD-\d+")]
    fields = [FieldRule(left="amount", right="amount")]
    with pytest.raises(KeyRegexMismatchError):
        normalize_side(df, keys, _cfg(fields), side="left")


def test_pipeline_backward_compatible_without_regex():
    """Existing configs without left_regex/right_regex must behave identically."""
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100.50"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["order_id"] == "A1"
    assert result.iloc[0]["amount"] == 100.50


def test_pipeline_left_literal_with_numeric_mode_coerces():
    """left_literal: '30' + mode: numeric + decimal_places: 2 → 30.0."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="30", right="memory",
                        mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["id", "memory"]
    assert result["memory"].tolist() == [30.0, 30.0]


def test_pipeline_left_literal_null_produces_none_column():
    """left_literal: null → column of None on all rows."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal=None, right="deleted_at")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result["deleted_at"].isna().all()


def test_pipeline_left_literal_string_mode_applies_transforms():
    """Constant string literal flows through string-mode transforms
    (ignore_case, ignore_whitespace)."""
    df = pd.DataFrame({"id": ["1", "2", "3"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(
        left_literal="  AZONE  ",
        right="zone",
        mode="string",
        ignore_whitespace=True,
        ignore_case=True,
    )]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    # ignore_whitespace strips, ignore_case casefolds
    assert result["zone"].tolist() == ["azone", "azone", "azone"]


def test_pipeline_right_literal_canonical_name_uses_left():
    """When right side is literal, canonical column name comes from f.left.
    Side='right' means we're normalizing right-side data which has no 'name'
    column; the literal 'prod' fills it under the canonical name 'name'."""
    df = pd.DataFrame({"id": ["1"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="name", right_literal="prod")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert "name" in result.columns
    assert result["name"].tolist() == ["prod"]


def test_pipeline_key_alias_and_field_regex_end_to_end_right_side():
    """Right side: source 'name' feeds both key (regex .*@@(.*), canonical join_id)
    and field (regex (.*)@@.*, canonical name)."""
    df = pd.DataFrame({"name": ["Alice@@1", "Bob@@2", "Carol@@3"]})
    keys = [KeyMapping(left="id", right="name",
                       right_regex=r".*@@(.*)", alias="join_id")]
    fields = [FieldRule(left="name", right="name",
                        right_regex=r"(.*)@@.*")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2", "3"]
    assert result["name"].tolist() == ["Alice", "Bob", "Carol"]


def test_pipeline_key_alias_left_side_no_regex():
    """Left side: no regex on either key or field; alias renames key canonical."""
    df = pd.DataFrame({"id": ["1", "2"], "name": ["Alice", "Bob"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2"]
    assert result["name"].tolist() == ["Alice", "Bob"]


def test_pipeline_field_regex_soft_failure_returns_sentinel():
    """Row that doesn't match field regex becomes RegexError, other rows fine."""
    from datacompare.normalize.regex_errors import RegexError
    df = pd.DataFrame({"id": ["1", "2", "3"], "code": ["A@@X", "no_at", "B@@Y"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="code", right="code", right_regex=r"(.*)@@.*")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    vals = result["code"].tolist()
    assert vals[0] == "A"
    assert isinstance(vals[1], RegexError)
    assert vals[1].original == "no_at"
    assert vals[2] == "B"


def test_pipeline_key_regex_still_strict_after_reorder():
    """After moving key regex post-rename, strict semantics preserved:
    mismatch aborts the entire task via KeyRegexMismatchError."""
    import pytest
    from datacompare.normalize.keys import KeyRegexMismatchError
    df = pd.DataFrame({"name": ["Alice@@1", "no_at_at"]})
    keys = [KeyMapping(left="id", right="name",
                       right_regex=r".*@@(.*)", alias="join_id")]
    fields = []
    with pytest.raises(KeyRegexMismatchError):
        normalize_side(df, keys, _cfg(fields), side="right")


def test_normalize_side_skips_missing_field_at_pipeline_level():
    """v0.8 pre-flight for Task 4: normalize_side must transparently skip
    fields whose source column is absent, without KeyError. Regex/coerce/
    decimal steps for the missing field must be no-ops."""
    df = pd.DataFrame({"id": ["1", "2"], "amt": ["10.556", "20.556"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="missing_col", right="missing_col",
                  mode="numeric", decimal_places=2),   # 缺列 + numeric 若未跳过会 KeyError
        FieldRule(left="amt", right="amount",
                  mode="numeric", decimal_places=2),
    ]
    # 不应抛异常。missing_col 从结果中消失，amount 正常参与 numeric 归一化。
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["id", "amount"]   # missing_col 缺席
    assert result.iloc[0]["amount"] == 10.56
    assert result.iloc[1]["amount"] == 20.56


def test_normalize_side_skips_missing_field_with_regex():
    """A field with a side_regex whose source column is missing must not
    even attempt regex application — no RegexError, no KeyError."""
    df = pd.DataFrame({"id": ["1"], "name": ["alice"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="missing_col", right="missing_col",
                  left_regex=r"foo(.*)"),   # 缺列 + regex 若未跳过会崩
        FieldRule(left="name", right="name"),
    ]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["id", "name"]
    assert result.iloc[0]["name"] == "alice"
