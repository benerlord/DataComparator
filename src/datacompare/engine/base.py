"""Abstract CompareEngine contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from .result import CompareResult


class CompareEngine(ABC):
    @abstractmethod
    def compare(
        self,
        left: DataSource,
        right: DataSource,
        task: TaskConfig,
    ) -> CompareResult: ...
