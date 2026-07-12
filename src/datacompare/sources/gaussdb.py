"""GaussDB source via psycopg2 (compatible with PostgreSQL wire protocol)."""
from __future__ import annotations
import re
from typing import Iterator
import psycopg2
import pandas as pd
from .base import DataSource
from .registry import register_source
from datacompare.config.models import GaussDBSourceConfig, GaussDBConnection
from datacompare.config.errors import ConfigError

_SELECT_RE = re.compile(r"^\s*(--[^\n]*\n\s*)*SELECT\b", re.IGNORECASE)


@register_source("gaussdb")
class GaussDBSource(DataSource):
    def __init__(self, config: GaussDBSourceConfig, connection: GaussDBConnection, name: str = ""):
        self.config = config
        self.creds = connection
        self.name = name or f"gaussdb:{connection.host}/{connection.database}"
        self._conn = None
        self._validate_read_only()

    def _validate_read_only(self) -> None:
        if not _SELECT_RE.match(self.config.query):
            raise ConfigError(
                "only SELECT queries are permitted",
                path="sources.query",
                suggestion="wrap or rewrite as SELECT statement",
            )

    def _connect(self):
        if self._conn is None:
            self._conn = psycopg2.connect(
                host=self.creds.host,
                port=self.creds.port,
                dbname=self.creds.database,
                user=self.creds.user,
                password=self.creds.password,
                sslmode=self.creds.ssl,
            )
        return self._conn

    def columns(self) -> list[str]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({self.config.query}) t LIMIT 0")
            return [d.name for d in cur.description]

    def estimated_rows(self) -> int | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM ({self.config.query}) t")
            row = cur.fetchone()
            return int(row[0]) if row else None

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        cols = self.columns()
        conn = self._connect()
        with conn.cursor(name="datacompare_stream") as cur:
            cur.itersize = chunk_size
            cur.execute(self.config.query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                df = pd.DataFrame(rows, columns=cols)
                # Convert all values to string; None → pd.NA-preserving None
                df = df.map(lambda v: None if v is None else str(v))
                # Force object dtype (pandas 3.x defaults to str dtype otherwise)
                df = df.astype(object)
                yield df

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
