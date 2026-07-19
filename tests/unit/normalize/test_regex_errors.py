from datacompare.normalize.regex_errors import RegexError


def test_regex_error_is_frozen_dataclass():
    e = RegexError(original="Alice", pattern=r"(.*)@@.*")
    assert e.original == "Alice"
    assert e.pattern == r"(.*)@@.*"
    import pytest
    with pytest.raises(Exception):
        e.original = "changed"  # type: ignore


def test_regex_error_equality():
    a = RegexError(original="x", pattern="p")
    b = RegexError(original="x", pattern="p")
    c = RegexError(original="x", pattern="q")
    assert a == b
    assert a != c
