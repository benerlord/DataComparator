"""rich Progress helpers."""
from __future__ import annotations
from contextlib import contextmanager
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn


@contextmanager
def three_phase_progress():
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    ) as progress:
        yield progress
