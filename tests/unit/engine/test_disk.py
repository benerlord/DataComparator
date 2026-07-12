import pandas as pd
from datacompare.engine.disk import DiskEngine
from datacompare.engine.memory import InMemoryEngine
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource


class _StubSource(DataSource):
    def __init__(self, df, name="stub"):
        self._df = df; self.name = name
    def columns(self): return list(self._df.columns)
    def estimated_rows(self): return len(self._df)
    def read(self, chunk_size=100_000):
        for i in range(0, len(self._df), chunk_size):
            yield self._df.iloc[i:i + chunk_size]


def _task():
    return TaskConfig(
        name="t",
        sources={"left": ExcelSourceConfig(path="d"), "right": ExcelSourceConfig(path="d")},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="amount", right="amount", mode="numeric", decimal_places=2),
            FieldRule(left="region", right="region", mode="string"),
        ]),
        output=OutputConfig(dir="./out", formats=["json"]),
        runtime=RuntimeConfig(engine="disk"),
    )


def test_disk_engine_matches_in_memory():
    left = _StubSource(pd.DataFrame({
        "id": [f"A{i}" for i in range(20)],
        "amount": [f"{i}.50" for i in range(20)],
        "region": ["N"] * 10 + ["S"] * 10,
    }))
    right = _StubSource(pd.DataFrame({
        "id": [f"A{i}" for i in range(15)] + [f"B{i}" for i in range(5)],
        "amount": [f"{i}.50" if i != 5 else "99.00" for i in range(15)] + ["0"] * 5,
        "region": ["N"] * 10 + ["S"] * 5 + ["W"] * 5,
    }))
    task = _task()
    mem_result = InMemoryEngine().compare(left, right, task)
    disk_result = DiskEngine().compare(_StubSource(left._df), _StubSource(right._df), task)
    assert disk_result.matched_rows == mem_result.matched_rows
    assert disk_result.identical_rows == mem_result.identical_rows
    assert disk_result.diff_rows == mem_result.diff_rows
    assert disk_result.left_only == mem_result.left_only
    assert disk_result.right_only == mem_result.right_only
    assert disk_result.engine_used == "disk"
