"""Pagination iterators for APISource."""
from __future__ import annotations
from typing import Iterator, Any
import httpx
from jsonpath_ng import parse as jp_parse
from datacompare.config.models import PaginationConfig


def _extract_first(payload: Any, jsonpath: str | None) -> Any:
    if not jsonpath:
        return None
    matches = jp_parse(jsonpath).find(payload)
    return matches[0].value if matches else None


class _BasePaginator:
    def __init__(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        params: dict[str, str],
        body: dict | None,
        headers: dict[str, str],
        pagination: PaginationConfig,
    ):
        self.client = client
        self.method = method
        self.url = url
        self.base_params = params
        self.body = body
        self.headers = headers
        self.cfg = pagination

    def _request(self, params: dict[str, str]) -> dict:
        merged = {**self.base_params, **params}
        r = self.client.request(
            self.method, self.url, params=merged, json=self.body, headers=self.headers,
        )
        r.raise_for_status()
        return r.json()


class PagePaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        page = 1
        cfg = self.cfg
        while True:
            params = {cfg.page_param: str(page), cfg.size_param: str(cfg.size)}
            payload = self._request(params)
            yield payload
            total = _extract_first(payload, cfg.total_path)
            if total is not None and page * cfg.size >= int(total):
                break
            if cfg.total_path is None:
                page += 1
                if page > 10_000:
                    break
                continue
            page += 1


class OffsetPaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        offset = 0
        cfg = self.cfg
        while True:
            params = {cfg.offset_param: str(offset), cfg.size_param: str(cfg.size)}
            payload = self._request(params)
            yield payload
            total = _extract_first(payload, cfg.total_path)
            if total is not None and offset + cfg.size >= int(total):
                break
            offset += cfg.size
            if offset > 10_000_000:
                break


class CursorPaginator(_BasePaginator):
    def __iter__(self) -> Iterator[dict]:
        cursor = ""
        cfg = self.cfg
        while True:
            params = {cfg.cursor_param: cursor}
            payload = self._request(params)
            yield payload
            next_val = _extract_first(payload, cfg.next_cursor_path)
            if not next_val:
                break
            cursor = str(next_val)
