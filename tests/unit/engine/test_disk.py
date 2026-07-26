import pytest
import pandas as pd
from datacompare.engine.disk import DiskEngine
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.result import DiffType
from datacompare.config.errors import ConfigError
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


def test_disk_engine_field_missing_parity_with_memory():
    """同样的 fixture，disk 和 memory 引擎对缺列的处理应一致。"""
    left_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                             "vmemorys": ["16", "32"]})

    def _make_task():
        return TaskConfig(
            name="t",
            sources={"left": ExcelSourceConfig(path="d"), "right": ExcelSourceConfig(path="d")},
            match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
            compare=CompareConfig(defaults=CompareDefaults(), fields=[
                FieldRule(left="name", right="name"),
                FieldRule(left="vmemorys", right="vmemorys"),
            ]),
            output=OutputConfig(dir="./out", formats=["json"]),
        )

    mem_result = InMemoryEngine().compare(
        _StubSource(left_df, "L"), _StubSource(right_df, "R"), _make_task(),
    )
    disk_result = DiskEngine().compare(
        _StubSource(left_df, "L"), _StubSource(right_df, "R"), _make_task(),
    )

    assert mem_result.diff_rows == disk_result.diff_rows
    mem_fm = mem_result.diff_details[
        mem_result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    disk_fm = disk_result.diff_details[
        disk_result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    assert len(mem_fm) == len(disk_fm) == 1
    assert mem_fm.iloc[0]["field"] == disk_fm.iloc[0]["field"] == "vmemorys"
    assert mem_fm.iloc[0]["left_value"] == disk_fm.iloc[0]["left_value"] == "字段不存在"


def test_disk_engine_both_sides_field_missing_raises():
    left_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": ExcelSourceConfig(path="d"), "right": ExcelSourceConfig(path="d")},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="both_missing", right="both_missing"),
        ]),
        output=OutputConfig(dir="./out", formats=["json"]),
    )
    with pytest.raises(ConfigError) as excinfo:
        DiskEngine().compare(_StubSource(left_df), _StubSource(right_df), task)
    assert "both_missing" in str(excinfo.value)


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
