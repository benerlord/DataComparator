import pandas as pd
import pytest
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.result import DiffType
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource


class _StubSource(DataSource):
    def __init__(self, name, df):
        self._name = name
        self._df = df

    @property
    def name(self):
        return self._name

    def columns(self):
        return list(self._df.columns)

    def estimated_rows(self):
        return len(self._df)

    def read(self, chunk_size=100_000):
        yield self._df.astype(object)


def _task():
    return TaskConfig(
        name="t",
        sources={
            "left": ExcelSourceConfig(path="dummy"),
            "right": ExcelSourceConfig(path="dummy"),
        },
        match=MatchConfig(keys=[KeyMapping(left="order_id", right="order_id")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[
                FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2),
                FieldRule(left="region", right="region", mode="string"),
            ],
        ),
        output=OutputConfig(dir="./out", formats=["console"]),
        runtime=RuntimeConfig(),
    )


def test_all_match():
    left = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    right = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.matched_rows == 2
    assert result.identical_rows == 2
    assert result.diff_rows == 0
    assert result.left_only == 0
    assert result.right_only == 0


def test_field_mismatch():
    left = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1"], "amount": ["100.50"], "region": ["N"],
    }))
    right = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1"], "amount": ["101.00"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    assert result.identical_rows == 0
    assert len(result.diff_details) == 1
    assert result.diff_details.iloc[0]["field"] == "amount"


def test_left_only_and_right_only():
    left = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["1", "2"], "region": ["N", "S"],
    }))
    right = _StubSource("stub", pd.DataFrame({
        "order_id": ["A2", "A3"], "amount": ["2", "3"], "region": ["S", "W"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.left_only == 1
    assert result.right_only == 1
    assert result.matched_rows == 1


def test_null_mismatch():
    left = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": [None],
    }))
    right = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    diff = result.diff_details.iloc[0]
    assert diff["diff_type"] == DiffType.NULL_MISMATCH.value


def test_duplicate_keys_rejected():
    left = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1", "A1"], "amount": ["1", "2"], "region": ["N", "N"],
    }))
    right = _StubSource("stub", pd.DataFrame({
        "order_id": ["A1"], "amount": ["1"], "region": ["N"],
    }))
    with pytest.raises(Exception, match="duplicate"):
        InMemoryEngine().compare(left, right, _task())


def test_field_missing_on_left_produces_summary_diff():
    """左侧缺 vmemorys 字段 → 该字段跳过 per-row，追加一条汇总。"""
    left_df = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "b", "c"]})
    right_df = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "b", "c"],
                             "vmemorys": ["16", "32", "64"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="vmemorys", right="vmemorys"),   # 左缺
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)

    assert result.matched_rows == 3
    assert result.identical_rows == 3   # name 都相同
    assert result.diff_rows == 1        # 只 +1（汇总一条）
    field_missing_records = result.diff_details[
        result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    assert len(field_missing_records) == 1
    r = field_missing_records.iloc[0]
    assert r["field"] == "vmemorys"
    assert r["left_value"] == "字段不存在"
    assert r["right_value"] == "(右侧 3 行有值)"
    assert r["id"] == ""


def test_field_missing_on_right_produces_summary_diff():
    left_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                            "hostname": ["h1", "h2"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="hostname", right="hostname"),
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)

    r = result.diff_details[result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value].iloc[0]
    assert r["field"] == "hostname"
    assert r["left_value"] == "(左侧 2 行有值)"
    assert r["right_value"] == "字段不存在"


def test_field_missing_on_both_sides_raises_config_error():
    from datacompare.config.errors import ConfigError

    left_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="both_missing", right="both_missing"),
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    with pytest.raises(ConfigError) as excinfo:
        InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    assert "both_missing" in str(excinfo.value)


def test_field_missing_multiple_fields_ordering_matches_declaration():
    # 字段声明顺序: id_field, missL, missR, name
    left_df = pd.DataFrame({"id": ["1"], "id_field": ["v1"], "missR": ["r1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "id_field": ["v1"], "missL": ["l1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="id_field", right="id_field"),
            FieldRule(left="missL", right="missL"),   # 左缺
            FieldRule(left="missR", right="missR"),   # 右缺
            FieldRule(left="name", right="name"),
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    fm = result.diff_details[result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value]
    assert fm["field"].tolist() == ["missL", "missR"]  # 按声明顺序


def test_field_missing_left_only_rows_padded_with_placeholder():
    # 左独有 id=99；左缺 hostname 字段
    left_df = pd.DataFrame({"id": ["1", "99"], "name": ["a", "z"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                             "hostname": ["h1", "h2"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="hostname", right="hostname"),   # 左缺
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    # left_only_rows 中缺失的 hostname 列应补 "字段不存在"
    assert "hostname" in result.left_only_rows.columns
    assert (result.left_only_rows["hostname"] == "字段不存在").all()


def test_field_missing_right_only_rows_padded_with_placeholder():
    """Symmetric to _left_only_rows_padded: 右独有 + 右缺 field → 右侧
    独有行的缺列填 "字段不存在"。"""
    # 右独有 id=99；右缺 hostname 字段
    left_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                            "hostname": ["h1", "h2"]})
    right_df = pd.DataFrame({"id": ["1", "99"], "name": ["a", "z"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"},
                 "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="hostname", right="hostname"),   # 右缺
        ]),
        output=OutputConfig(dir="./out", formats=["console"]),
    )
    result = InMemoryEngine().compare(
        _StubSource("L", left_df), _StubSource("R", right_df), task,
    )
    assert "hostname" in result.right_only_rows.columns
    assert (result.right_only_rows["hostname"] == "字段不存在").all()
