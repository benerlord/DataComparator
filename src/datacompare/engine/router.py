"""Route to InMemoryEngine or DiskEngine based on estimated row counts."""
from __future__ import annotations
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from .base import CompareEngine
from .memory import InMemoryEngine
from .disk import DiskEngine


def select_engine(
    left: DataSource, right: DataSource, task: TaskConfig,
) -> CompareEngine:
    if task.runtime.engine == "memory":
        return InMemoryEngine()
    if task.runtime.engine == "disk":
        return DiskEngine()

    threshold = task.runtime.memory_threshold_rows
    lrows = left.estimated_rows()
    rrows = right.estimated_rows()
    max_rows = max(
        lrows if lrows is not None else threshold + 1,
        rrows if rrows is not None else threshold + 1,
    )
    return InMemoryEngine() if max_rows <= threshold else DiskEngine()
