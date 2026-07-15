"""GaussDB data source with pluggable driver (Postgres protocol / JDBC)."""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from typing import Iterator, Any
import psycopg2
import pandas as pd
from .base import DataSource
from .registry import register_source
from datacompare.config.models import (
    GaussDBSourceConfig, GaussDBAConnection, GaussDBTConnection,
)
from datacompare.config.errors import ConfigError

_SELECT_RE = re.compile(r"^\s*(--[^\n]*\n\s*)*SELECT\b", re.IGNORECASE)


class GaussDBDriver(ABC):
    """Abstraction over concrete database driver (psycopg2 or JDBC).

    Returns raw Python value tuples; GaussDBSource handles string coercion.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection (idempotent)."""

    @abstractmethod
    def close(self) -> None:
        """Release connection resources."""

    @abstractmethod
    def columns_for(self, query: str) -> list[str]:
        """Return column names for `query` without fetching data rows."""

    @abstractmethod
    def count_for(self, query: str) -> int:
        """Return SELECT COUNT(*) FROM (query) t."""

    @abstractmethod
    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple[Any, ...]]]:
        """Stream query results as chunks of raw row tuples."""


class PostgresDriver(GaussDBDriver):
    """psycopg2-based driver for GaussDB A / DWS / openGauss / GaussDB 100 PG-compat."""

    def __init__(self, creds: GaussDBAConnection):
        self.creds = creds
        self._conn = None

    def connect(self) -> None:
        if self._conn is None:
            self._conn = psycopg2.connect(
                host=self.creds.host, port=self.creds.port,
                dbname=self.creds.database, user=self.creds.user,
                password=self.creds.password, sslmode=self.creds.ssl,
            )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def columns_for(self, query: str) -> list[str]:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({query}) t LIMIT 0")
            return [d.name for d in cur.description]

    def count_for(self, query: str) -> int:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM ({query}) t")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple]]:
        self.connect()
        with self._conn.cursor(name="datacompare_stream") as cur:
            cur.itersize = chunk_size
            cur.execute(query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                yield rows


@register_source("gaussdb")
class GaussDBSource(DataSource):
    def __init__(self, config: GaussDBSourceConfig, connection, name: str = ""):
        self.config = config
        self.creds = connection
        self.name = name or f"gaussdb:{self._display_target()}"
        self._driver: GaussDBDriver = self._make_driver(connection)
        self._validate_read_only()

    @staticmethod
    def _make_driver(creds) -> GaussDBDriver:
        if isinstance(creds, GaussDBAConnection):
            return PostgresDriver(creds)
        if isinstance(creds, GaussDBTConnection):
            # Lazy import: only pull in JdbcDriver when actually needed,
            # so users who don't use variant=t are never forced to install jaydebeapi.
            from .gaussdb_jdbc import JdbcDriver
            return JdbcDriver(creds)
        raise ConfigError(f"unknown GaussDB variant: {type(creds).__name__}")

    def _display_target(self) -> str:
        if isinstance(self.creds, GaussDBAConnection):
            return f"{self.creds.host}/{self.creds.database}"
        return self.creds.jdbc_url

    def _validate_read_only(self) -> None:
        if not _SELECT_RE.match(self.config.query):
            raise ConfigError(
                "only SELECT queries are permitted",
                path="sources.query",
                suggestion="wrap or rewrite as SELECT statement",
            )

    def columns(self) -> list[str]:
        return self._driver.columns_for(self.config.query)

    def estimated_rows(self) -> int | None:
        return self._driver.count_for(self.config.query)

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        cols = self.columns()
        for rows in self._driver.fetch_chunks(self.config.query, chunk_size):
            df = pd.DataFrame(rows, columns=cols)
            df = df.map(lambda v: None if v is None else str(v))
            df = df.astype(object)
            yield df

    def close(self) -> None:
        self._driver.close()
