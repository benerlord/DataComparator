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
    def __init__(self, df, name="stub"):
        self._df = df
        self.name = name
    def columns(self): return list(self._df.columns)
    def estimated_rows(self): return len(self._df)
    def read(self, chunk_size=100_000):
        yield self._df


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
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["100.50", "200.00"], "region": ["N", "S"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.matched_rows == 2
    assert result.identical_rows == 2
    assert result.diff_rows == 0
    assert result.left_only == 0
    assert result.right_only == 0


def test_field_mismatch():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100.50"], "region": ["N"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["101.00"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    assert result.identical_rows == 0
    assert len(result.diff_details) == 1
    assert result.diff_details.iloc[0]["field"] == "amount"


def test_left_only_and_right_only():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A2"], "amount": ["1", "2"], "region": ["N", "S"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A2", "A3"], "amount": ["2", "3"], "region": ["S", "W"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.left_only == 1
    assert result.right_only == 1
    assert result.matched_rows == 1


def test_null_mismatch():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": [None],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["100"], "region": ["N"],
    }))
    result = InMemoryEngine().compare(left, right, _task())
    assert result.diff_rows == 1
    diff = result.diff_details.iloc[0]
    assert diff["diff_type"] == DiffType.NULL_MISMATCH.value


def test_duplicate_keys_rejected():
    left = _StubSource(pd.DataFrame({
        "order_id": ["A1", "A1"], "amount": ["1", "2"], "region": ["N", "N"],
    }))
    right = _StubSource(pd.DataFrame({
        "order_id": ["A1"], "amount": ["1"], "region": ["N"],
    }))
    with pytest.raises(Exception, match="duplicate"):
        InMemoryEngine().compare(left, right, _task())
