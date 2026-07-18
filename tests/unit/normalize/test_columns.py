import pandas as pd
from datacompare.config.models import (
    KeyMapping, FieldRule, CompareDefaults, MatchConfig, CompareConfig,
)
from datacompare.normalize.columns import (
    apply_column_mapping, effective_rule, EffectiveRule,
)

def test_apply_column_mapping_left_side():
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100"], "extra": ["x"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["order_id", "amount"]
    assert result.iloc[0]["order_id"] == "A1"

def test_apply_column_mapping_right_side_no_rename_needed():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount")]
    result = apply_column_mapping(df, keys, fields, side="right")
    assert list(result.columns) == ["order_id", "amount"]

def test_effective_rule_inherits_defaults():
    defaults = CompareDefaults(mode="numeric", ignore_whitespace=True)
    rule = FieldRule(left="a", right="a")  # all None
    eff = effective_rule(rule, defaults)
    assert eff.mode == "numeric"
    assert eff.ignore_whitespace is True

def test_effective_rule_field_overrides_defaults():
    defaults = CompareDefaults(mode="exact", ignore_whitespace=False)
    rule = FieldRule(left="a", right="a", mode="numeric", ignore_whitespace=True)
    eff = effective_rule(rule, defaults)
    assert eff.mode == "numeric"
    assert eff.ignore_whitespace is True

def test_effective_rule_null_equivalents_override():
    defaults = CompareDefaults(null_equivalents=["", "null"])
    rule = FieldRule(left="a", right="a", null_equivalents=["-", "N/A"])
    eff = effective_rule(rule, defaults)
    assert eff.null_equivalents == ["-", "N/A"]


def test_apply_column_mapping_left_col_named_like_right_key_no_collision():
    """Regression: left has an unmapped column whose name equals a right-side
    canonical target (e.g. left.id maps to right.name, but left also has a
    stray 'name' column). The unmapped column must be dropped before rename,
    otherwise two 'name' columns collide and the downstream merge fails.
    """
    df = pd.DataFrame({
        "id": ["1", "2"],
        "name": ["should-drop-a", "should-drop-b"],
        "amount": ["10", "20"],
    })
    keys = [KeyMapping(left="id", right="name")]
    fields = [FieldRule(left="amount", right="amount")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["name", "amount"]
    assert result["name"].tolist() == ["1", "2"]  # came from 'id', not stray 'name'
