"""HTTP API data source with JSONPath extraction and tenacity retry."""
from __future__ import annotations
from typing import Iterator
import httpx
import pandas as pd
from jsonpath_ng import parse as jp_parse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import DataSource
from .registry import register_source
from .api_auth import build_client
from .pagination import PagePaginator, OffsetPaginator, CursorPaginator
from datacompare.config.models import APISourceConfig, APIConnection
from datacompare.config.errors import ConfigError


@register_source("api")
class APISource(DataSource):
    def __init__(self, config: APISourceConfig, connection: APIConnection, name: str = ""):
        self.config = config
        self.conn = connection
        self.name = name or f"api:{connection.base_url}{config.url}"
        self._client: httpx.Client | None = None
        self._data_extractor = jp_parse(config.data_path)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_client(self.conn)
            self._client.timeout = self.config.timeout
        return self._client

    def _wrapped_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = self._get_client()
        r = client.request(method, url, **kwargs)
        r.raise_for_status()
        return r

    def _fetch_sample_page(self, size: int = 1) -> dict:
        cfg = self.config.pagination
        params = {cfg.page_param or "page": "1", cfg.size_param or "size": str(size)}
        merged = {**self.config.params, **params}

        @retry(
            stop=stop_after_attempt(self.config.retry.max_attempts),
            wait=wait_exponential(multiplier=self.config.retry.backoff),
            retry=retry_if_exception_type(
                (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)
            ),
        )
        def _do():
            return self._wrapped_request(
                self.config.method, self.config.url,
                params=merged, json=self.config.body, headers=self.config.headers,
            )
        r = _do()
        return r.json()

    def _extract(self, payload: dict) -> list[dict]:
        return [m.value for m in self._data_extractor.find(payload)]

    def columns(self) -> list[str]:
        payload = self._fetch_sample_page(size=1)
        records = self._extract(payload)
        if not records:
            raise ConfigError("API first page returned no records; cannot infer columns")
        return list(records[0].keys())

    def estimated_rows(self) -> int | None:
        cfg = self.config.pagination
        if not cfg.total_path:
            return None
        payload = self._fetch_sample_page(size=1)
        matches = jp_parse(cfg.total_path).find(payload)
        if not matches:
            return None
        return int(matches[0].value)

    def _paginator(self):
        cfg = self.config.pagination
        client = self._get_client()
        args = (
            client, self.config.method, self.config.url, self.config.params,
            self.config.body, self.config.headers, cfg,
        )
        if cfg.type == "page":
            return PagePaginator(*args)
        if cfg.type == "offset":
            return OffsetPaginator(*args)
        if cfg.type == "cursor":
            return CursorPaginator(*args)
        raise ConfigError(f"unknown pagination type: {cfg.type}")

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        buffer: list[dict] = []
        for page in self._paginator():
            records = self._extract(page)
            if not records:
                break
            buffer.extend(records)
            if len(buffer) >= chunk_size:
                yield self._to_string_df(buffer)
                buffer = []
        if buffer:
            yield self._to_string_df(buffer)

    @staticmethod
    def _to_string_df(records: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(records)
        df = df.map(lambda v: None if v is None else str(v))
        return df.astype(object)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
