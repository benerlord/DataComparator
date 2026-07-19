import pytest
from pydantic import ValidationError
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, GaussDBSourceConfig, APISourceConfig,
    FieldRule, CompareDefaults, MatchConfig, KeyMapping, CompareConfig,
    OutputConfig, RuntimeConfig, SheetSelector, PaginationConfig,
)

def test_excel_source_defaults():
    src = ExcelSourceConfig(path="foo.xlsx")
    assert src.type == "excel"
    assert src.header_row == 1
    assert src.force_string is True
    assert src.sheets == [SheetSelector(index=0)]

def test_field_rule_override_semantics_optional_none():
    rule = FieldRule(left="a", right="b")
    assert rule.mode is None
    assert rule.ignore_whitespace is None
    assert rule.decimal_places is None

def test_task_config_requires_left_and_right():
    with pytest.raises(ValidationError):
        TaskConfig(
            name="x",
            sources={"left": ExcelSourceConfig(path="a.xlsx")},
            match=MatchConfig(keys=[KeyMapping(left="k", right="k")]),
            compare=CompareConfig(defaults=CompareDefaults(), fields=[]),
            output=OutputConfig(dir="./out", formats=["json"]),
        )

def test_pagination_type_literal():
    p = PaginationConfig(type="page", page_param="pageNum", size_param="pageSize", size=100)
    assert p.type == "page"
    with pytest.raises(ValidationError):
        PaginationConfig(type="bogus", size=100)

def test_gaussdb_source_requires_query():
    src = GaussDBSourceConfig(connection="prod", query="SELECT 1")
    assert src.type == "gaussdb"
    assert src.connection == "prod"

def test_api_source_requires_url():
    src = APISourceConfig(
        connection="svc", url="/v1/orders",
        pagination=PaginationConfig(type="page", size=100),
        data_path="$.data.list[*]",
    )
    assert src.method == "GET"
    assert src.timeout == 30


def test_key_mapping_defaults_regex_to_none():
    k = KeyMapping(left="a", right="b")
    assert k.left_regex is None
    assert k.right_regex is None


def test_key_mapping_accepts_valid_regex():
    k = KeyMapping(left="a", right="b", left_regex=r"ORD-\d+")
    assert k.left_regex == r"ORD-\d+"


def test_key_mapping_accepts_one_capture_group():
    k = KeyMapping(left="a", right="b", left_regex=r"ORD-0*(\d+)")
    assert k.left_regex == r"ORD-0*(\d+)"


def test_key_mapping_rejects_invalid_regex_syntax():
    with pytest.raises(ValidationError) as exc:
        KeyMapping(left="a", right="b", left_regex=r"ORD-[")
    assert "invalid regex" in str(exc.value)


def test_key_mapping_rejects_two_capture_groups():
    with pytest.raises(ValidationError) as exc:
        KeyMapping(left="a", right="b", right_regex=r"(\d+)-(\w+)")
    msg = str(exc.value)
    assert "capture groups" in msg
    assert "(?:...)" in msg


def test_key_mapping_allows_noncapturing_groups():
    k = KeyMapping(left="a", right="b", left_regex=r"(?:ORD|CUS)-(\d+)")
    assert k.left_regex == r"(?:ORD|CUS)-(\d+)"


def test_key_mapping_explicit_null_regex():
    k = KeyMapping(left="a", right="b", left_regex=None, right_regex=None)
    assert k.left_regex is None and k.right_regex is None


class TestFieldRuleLiterals:
    def test_column_only_both_sides_ok(self):
        f = FieldRule(left="a", right="b")
        assert f.left == "a" and f.right == "b"
        assert f.left_literal is None and f.right_literal is None

    def test_left_literal_with_right_column_ok(self):
        f = FieldRule(left_literal="Azone", right="type")
        assert f.left is None
        assert f.left_literal == "Azone"
        assert f.right == "type"

    def test_left_literal_null_ok(self):
        # explicit null literal — asserts right column is None for matched rows
        f = FieldRule(left_literal=None, right="deleted_at")
        assert f.left is None
        assert f.left_literal is None
        assert "left_literal" in f.model_fields_set  # marker: explicitly set

    def test_right_literal_with_left_column_ok(self):
        f = FieldRule(left="name", right_literal="prod")
        assert f.right is None
        assert f.right_literal == "prod"

    def test_missing_left_specifier_raises(self):
        with pytest.raises(ValidationError, match="'left' or 'left_literal'"):
            FieldRule(right="b")

    def test_missing_right_specifier_raises(self):
        with pytest.raises(ValidationError, match="'right' or 'right_literal'"):
            FieldRule(left="a")

    def test_both_left_and_left_literal_raises(self):
        with pytest.raises(ValidationError, match="cannot specify both 'left'"):
            FieldRule(left="a", left_literal="X", right="b")

    def test_both_right_and_right_literal_raises(self):
        with pytest.raises(ValidationError, match="cannot specify both 'right'"):
            FieldRule(left="a", right="b", right_literal="Y")
