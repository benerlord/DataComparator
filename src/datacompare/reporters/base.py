"""Abstract Reporter contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from datacompare.engine.result import CompareResult


class Reporter(ABC):
    def __init__(self, config: dict, output_dir: Path | None):
        self.config = config
        self.output_dir = output_dir

    @abstractmethod
    def render(self, result: CompareResult) -> Path | None: ...
