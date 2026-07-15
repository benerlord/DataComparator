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
