import httpx
import respx
import pandas as pd
from datacompare.sources.api import APISource
from datacompare.config.models import (
    APISourceConfig, PaginationConfig, APIConnection, NoAuth,
)


def _cfg():
    return APISourceConfig(
        connection="svc",
        url="/orders",
        pagination=PaginationConfig(
            type="page", page_param="pageNum", size_param="pageSize", size=2,
            total_path="$.data.total",
        ),
        data_path="$.data.list[*]",
    )


def _conn():
    return APIConnection(base_url="http://api.test", auth=NoAuth())


@respx.mock
def test_columns_from_first_page_sample():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": "A1", "amount": "100"}], "total": 1}})
    )
    src = APISource(_cfg(), _conn())
    assert set(src.columns()) == {"id", "amount"}


@respx.mock
def test_read_extracts_and_strings():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"id": "A1", "amount": 100.5}, {"id": "A2", "amount": 200},
        ], "total": 2}})
    )
    src = APISource(_cfg(), _conn())
    df = pd.concat(src.read())
    assert len(df) == 2
    assert df.iloc[0]["id"] == "A1"
    assert df.iloc[0]["amount"] == "100.5"


@respx.mock
def test_estimated_rows_uses_total_path():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "1"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": "x"}], "total": 42}})
    )
    src = APISource(_cfg(), _conn())
    assert src.estimated_rows() == 42


@respx.mock
def test_retry_on_500():
    route = respx.get("http://api.test/orders").mock(side_effect=[
        httpx.Response(500), httpx.Response(500),
        httpx.Response(200, json={"data": {"list": [{"id": "x"}], "total": 1}}),
    ])
    src = APISource(_cfg(), _conn())
    _ = src.columns()
    assert route.call_count == 3
