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


def test_pipeline_left_literal_string_mode_broadcasts():
    """Constant string flows through string-mode transforms."""
    df = pd.DataFrame({"id": ["1", "2", "3"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone", mode="string")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result["zone"].tolist() == ["Azone", "Azone", "Azone"]


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
