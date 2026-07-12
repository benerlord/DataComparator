import httpx
import respx
import pytest
from datacompare.sources.pagination import (
    PagePaginator, OffsetPaginator, CursorPaginator,
)
from datacompare.config.models import PaginationConfig


def _client():
    return httpx.Client(base_url="http://api.test")


@respx.mock
def test_page_paginator_stops_when_short():
    respx.get("http://api.test/orders", params={"pageNum": "1", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 1}, {"id": 2}], "total": 3}})
    )
    respx.get("http://api.test/orders", params={"pageNum": "2", "pageSize": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 3}], "total": 3}})
    )
    cfg = PaginationConfig(
        type="page", page_param="pageNum", size_param="pageSize", size=2,
        total_path="$.data.total",
    )
    p = PagePaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2


@respx.mock
def test_offset_paginator():
    respx.get("http://api.test/orders", params={"offset": "0", "limit": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 1}, {"id": 2}], "total": 4}})
    )
    respx.get("http://api.test/orders", params={"offset": "2", "limit": "2"}).mock(
        return_value=httpx.Response(200, json={"data": {"list": [{"id": 3}, {"id": 4}], "total": 4}})
    )
    cfg = PaginationConfig(
        type="offset", offset_param="offset", size_param="limit", size=2,
        total_path="$.data.total",
    )
    p = OffsetPaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2


@respx.mock
def test_cursor_paginator():
    respx.get("http://api.test/orders", params={"cursor": ""}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}], "next": "c1"})
    )
    respx.get("http://api.test/orders", params={"cursor": "c1"}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": 2}], "next": None})
    )
    cfg = PaginationConfig(
        type="cursor", cursor_param="cursor", size=2, next_cursor_path="$.next",
    )
    p = CursorPaginator(_client(), "GET", "/orders", {}, None, {}, cfg)
    pages = list(p)
    assert len(pages) == 2
