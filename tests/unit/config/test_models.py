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
