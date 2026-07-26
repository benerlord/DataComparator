import pytest
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
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["order_id", "amount"]
    assert result.iloc[0]["order_id"] == "A1"

def test_apply_column_mapping_right_side_no_rename_needed():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount")]
    result, _ = apply_column_mapping(df, keys, fields, side="right")
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
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["name", "amount"]
    assert result["name"].tolist() == ["1", "2"]  # came from 'id', not stray 'name'


def test_apply_column_mapping_left_literal_injects_constant_column():
    """Left has no 'zone' column but field is {left_literal: 'Azone', right: 'zone'}.
    Result must contain a 'zone' column filled with 'Azone' for every row."""
    df = pd.DataFrame({"id": ["1", "2", "3"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone")]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "zone"]
    assert result["zone"].tolist() == ["Azone", "Azone", "Azone"]


def test_apply_column_mapping_right_literal_injects_constant_column():
    """Symmetric: right side literal. Canonical name comes from f.left when
    only right side is literal."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="name", right_literal="prod")]
    result, _ = apply_column_mapping(df, keys, fields, side="right")
    assert "name" in result.columns
    assert result["name"].tolist() == ["prod", "prod"]


def test_apply_column_mapping_left_literal_null():
    """left_literal: null → column of None values."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal=None, right="deleted_at")]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "deleted_at"]
    assert result["deleted_at"].isna().all()


def test_apply_column_mapping_literal_on_empty_dataframe():
    """Empty DataFrame + literal → empty column, no crash."""
    df = pd.DataFrame({"id": pd.Series([], dtype=object)})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="X", right="zone")]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "zone"]
    assert len(result) == 0


def test_apply_column_mapping_mixed_column_and_literal_fields():
    """Some fields have literal, others have real columns."""
    df = pd.DataFrame({"id": ["1"], "amt": ["100"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="amt", right="amount"),
        FieldRule(left_literal="Azone", right="zone"),
    ]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert set(result.columns) == {"id", "amount", "zone"}
    assert result.iloc[0]["amount"] == "100"
    assert result.iloc[0]["zone"] == "Azone"


def test_apply_column_mapping_left_side_with_right_literal_field():
    """FieldRule(left='name', right_literal='prod') normalized with side='left':
    canonical name falls back to f.left when f.right is None.
    Regression guard against rename_map[src] = None (produces NaN-keyed column).
    """
    df = pd.DataFrame({"id": ["1", "2"], "name": ["alice", "bob"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="name", right_literal="prod")]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "name"]
    assert result["name"].tolist() == ["alice", "bob"]


def test_key_canonical_name_no_alias_returns_right():
    from datacompare.normalize.columns import key_canonical_name
    k = KeyMapping(left="id", right="name")
    assert key_canonical_name(k) == "name"


def test_key_canonical_name_with_alias_returns_alias():
    from datacompare.normalize.columns import key_canonical_name
    k = KeyMapping(left="id", right="name", alias="join_id")
    assert key_canonical_name(k) == "join_id"


def test_apply_column_mapping_key_alias_uses_alias_as_canonical():
    """Key with alias — canonical name comes from alias, not k.right."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = []
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["join_id"]
    assert result["join_id"].tolist() == ["1", "2"]


def test_apply_column_mapping_same_source_column_duplicated_for_key_and_field():
    """Right side: 'name' column used by BOTH key (canonical join_id via alias)
    AND field (canonical name). Both canonical columns must exist and contain
    the SAME source values (regex not applied here — that's a later step)."""
    df = pd.DataFrame({"name": ["Alice@@1", "Bob@@2"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result, _ = apply_column_mapping(df, keys, fields, side="right")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["Alice@@1", "Bob@@2"]
    assert result["name"].tolist() == ["Alice@@1", "Bob@@2"]


def test_apply_column_mapping_left_side_with_key_alias_and_stray_col():
    """Left has 'id' and 'name'; key {left: id, right: name, alias: join_id};
    field {left: name, right: name}. Both must survive with correct values."""
    df = pd.DataFrame({"id": ["1", "2"], "name": ["Alice", "Bob"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result, _ = apply_column_mapping(df, keys, fields, side="left")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2"]
    assert result["name"].tolist() == ["Alice", "Bob"]


def test_apply_column_mapping_field_missing_returns_marker():
    """v0.8: field 缺列不再 raise，而是从结果 df 剔除并加入 missing set。"""
    df = pd.DataFrame({"id": ["1", "2"], "vmemory": ["16", "32"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="vmemorys", right="vmemorys"),  # 打字错误，左侧无此列
        FieldRule(left="vmemory", right="vmemory"),    # 存在
    ]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset({"vmemorys"})
    assert list(result_df.columns) == ["id", "vmemory"]
    assert result_df["vmemory"].tolist() == ["16", "32"]


def test_apply_column_mapping_no_field_missing_returns_empty_frozenset():
    df = pd.DataFrame({"id": ["1"], "amt": ["10"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="amt", right="amount")]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset()
    assert list(result_df.columns) == ["id", "amount"]


def test_apply_column_mapping_multiple_field_missing_all_reported():
    """所有单侧缺列的 field canonical 都应出现在 missing 集里，一个不漏。"""
    df = pd.DataFrame({"id": ["1"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="a", right="a"),
        FieldRule(left="b", right="b"),
        FieldRule(left="c", right="c"),
    ]
    _df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset({"a", "b", "c"})


def test_apply_column_mapping_key_missing_still_raises():
    """v0.8: key 缺列仍然硬失败（不像 field 那样软化）。"""
    from datacompare.config.errors import ConfigError
    df = pd.DataFrame({"amount": ["10"]})   # 无 id 列
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="amount", right="amount")]
    with pytest.raises(ConfigError) as excinfo:
        apply_column_mapping(df, keys, fields, side="left")
    assert "id" in str(excinfo.value)


def test_apply_column_mapping_literal_field_untouched_by_missing_check():
    """Literal 字段在该侧没有 source 列 → 不算 missing。"""
    df = pd.DataFrame({"id": ["1"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone")]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset()
    assert "zone" in result_df.columns
