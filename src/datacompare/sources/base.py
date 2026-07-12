"""Abstract DataSource contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator
import pandas as pd


class DataSource(ABC):
    """
    All rows returned by read() are strings (or None for nulls).
    Type coercion, decimals, and unit parsing happen in the normalize layer.
    """
    name: str = ""

    @abstractmethod
    def columns(self) -> list[str]:
        """Return the column header list. Used to validate config references."""

    @abstractmethod
    def estimated_rows(self) -> int | None:
        """Return a row-count estimate; None if unknown. Used by engine router."""

    @abstractmethod
    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        """Yield DataFrame chunks of string-typed values."""

    def close(self) -> None:
        """Release file handles / connections. Default no-op."""
        return None
