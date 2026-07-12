import pytest
import pandas as pd
from datacompare.sources.base import DataSource
from datacompare.sources.registry import (
    register_source, get_source_class, SOURCE_REGISTRY,
)

def test_register_and_lookup():
    @register_source("dummy_test")
    class DummySource(DataSource):
        name = "dummy"
        def columns(self): return []
        def estimated_rows(self): return 0
        def read(self, chunk_size=100_000):
            yield pd.DataFrame()

    assert get_source_class("dummy_test") is DummySource
    SOURCE_REGISTRY.pop("dummy_test")  # cleanup

def test_lookup_unknown_type_raises():
    with pytest.raises(KeyError, match="unknown_source_type"):
        get_source_class("unknown_source_type")

def test_data_source_is_abstract():
    with pytest.raises(TypeError):
        DataSource()  # cannot instantiate abstract
