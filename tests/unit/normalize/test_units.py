import pytest
from datacompare.normalize.units import parse_and_convert, UnitError

def test_storage_tb_to_gb():
    assert parse_and_convert("30 TB", "storage", "GB") == pytest.approx(30720.0)

def test_storage_gb_to_tb_reverse():
    assert parse_and_convert("30720 GB", "storage", "TB") == pytest.approx(30.0)

def test_case_insensitive():
    assert parse_and_convert("30 tb", "storage", "GB") == pytest.approx(30720.0)
    assert parse_and_convert("30 Tb", "storage", "gb") == pytest.approx(30720.0)

def test_time_min_to_s():
    assert parse_and_convert("2 min", "time", "s") == pytest.approx(120.0)

def test_time_h_to_ms():
    assert parse_and_convert("1 h", "time", "ms") == pytest.approx(3_600_000.0)

def test_no_space_between_number_and_unit():
    assert parse_and_convert("30TB", "storage", "GB") == pytest.approx(30720.0)

def test_negative_and_float():
    assert parse_and_convert("-1.5 GB", "storage", "MB") == pytest.approx(-1536.0)

def test_scientific_notation():
    assert parse_and_convert("1.5e3 MB", "storage", "GB") == pytest.approx(1500.0 / 1024.0)

def test_no_unit_pattern_returns_error():
    result = parse_and_convert("not a number", "storage", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "no_unit_pattern"

def test_unknown_unit_returns_error():
    result = parse_and_convert("30 XX", "storage", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "unknown_unit"

def test_unknown_category_returns_error():
    result = parse_and_convert("30 TB", "bogus", "GB")
    assert isinstance(result, UnitError)
    assert result.reason == "unknown_category"
