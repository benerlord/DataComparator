from datetime import datetime
import pytest
from datacompare.normalize.types import coerce_type, CoerceError

def test_none_passthrough():
    assert coerce_type(None, "int") is None

def test_no_target_type_passthrough():
    assert coerce_type("hello", None) == "hello"

def test_to_int():
    assert coerce_type("42", "int") == 42

def test_to_float():
    assert coerce_type("3.14", "float") == 3.14

def test_to_string():
    assert coerce_type("42", "string") == "42"

def test_to_datetime_with_format():
    result = coerce_type("2026-07-13 15:20:00", "datetime", datetime_format="%Y-%m-%d %H:%M:%S")
    assert result == datetime(2026, 7, 13, 15, 20, 0)

def test_to_datetime_iso_no_format():
    result = coerce_type("2026-07-13T15:20:00", "datetime")
    assert result == datetime(2026, 7, 13, 15, 20, 0)

def test_int_conversion_failure_returns_sentinel():
    result = coerce_type("not_a_number", "int")
    assert isinstance(result, CoerceError)
    assert result.target == "int"
    assert result.original == "not_a_number"

def test_datetime_format_mismatch_returns_sentinel():
    result = coerce_type("bad", "datetime", datetime_format="%Y-%m-%d")
    assert isinstance(result, CoerceError)
