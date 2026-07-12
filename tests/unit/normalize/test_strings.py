import pytest
from datacompare.normalize.strings import normalize_string

DEFAULT_NULLS = ["", "null", "NULL", "NaN", "nan"]

@pytest.mark.parametrize("value", DEFAULT_NULLS)
def test_null_equivalents_become_none(value):
    assert normalize_string(value, null_equivalents=DEFAULT_NULLS) is None

def test_none_stays_none():
    assert normalize_string(None, null_equivalents=DEFAULT_NULLS) is None

def test_ignore_whitespace_strips_and_folds():
    result = normalize_string("  hello   world  ", ignore_whitespace=True)
    assert result == "hello world"

def test_ignore_case_uses_casefold():
    assert normalize_string("Straße", ignore_case=True) == "strasse"

def test_combined_flags():
    result = normalize_string("  HELLO  World  ", ignore_whitespace=True, ignore_case=True)
    assert result == "hello world"

def test_no_flags_returns_unchanged():
    assert normalize_string("  Foo  ") == "  Foo  "

def test_null_check_precedes_normalization():
    # 'NULL' is in null equivalents; case-fold should not apply first
    assert normalize_string("NULL", ignore_case=True, null_equivalents=["NULL"]) is None
