from datacompare.engine.router import select_engine
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.disk import DiskEngine
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.sources.base import DataSource
import pandas as pd


class _Sized(DataSource):
    def __init__(self, n: int | None):
        self._n = n; self.name = "s"
    def columns(self): return []
    def estimated_rows(self): return self._n
    def read(self, chunk_size=100_000):
        yield pd.DataFrame()


def _task(engine: str = "auto", threshold: int = 500_000):
    return TaskConfig(
        name="t",
        sources={"left": ExcelSourceConfig(path="a"), "right": ExcelSourceConfig(path="b")},
        match=MatchConfig(keys=[KeyMapping(left="k", right="k")]),
        compare=CompareConfig(defaults=CompareDefaults(),
                              fields=[FieldRule(left="v", right="v")]),
        output=OutputConfig(dir="./o", formats=["json"]),
        runtime=RuntimeConfig(engine=engine, memory_threshold_rows=threshold),
    )


def test_explicit_memory():
    e = select_engine(_Sized(10_000_000), _Sized(10_000_000), _task(engine="memory"))
    assert isinstance(e, InMemoryEngine)


def test_explicit_disk():
    e = select_engine(_Sized(100), _Sized(100), _task(engine="disk"))
    assert isinstance(e, DiskEngine)


def test_auto_small_uses_memory():
    e = select_engine(_Sized(1000), _Sized(1000), _task(engine="auto", threshold=500_000))
    assert isinstance(e, InMemoryEngine)


def test_auto_large_uses_disk():
    e = select_engine(_Sized(600_000), _Sized(1000), _task(engine="auto", threshold=500_000))
    assert isinstance(e, DiskEngine)


def test_auto_unknown_size_uses_disk():
    e = select_engine(_Sized(None), _Sized(1000), _task(engine="auto"))
    assert isinstance(e, DiskEngine)
