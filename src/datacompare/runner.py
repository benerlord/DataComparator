"""Orchestration: build sources, run engine, dispatch reporters."""
from __future__ import annotations
from pathlib import Path
from datacompare.config.models import (
    TaskConfig, AnyConnection, ExcelSourceConfig, GaussDBSourceConfig,
    APISourceConfig, GaussDBConnection, APIConnection,
)
from datacompare.config.errors import ConfigError
from datacompare.sources.base import DataSource
from datacompare.sources.excel import ExcelSource
from datacompare.sources.gaussdb import GaussDBSource
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.result import CompareResult
from datacompare.reporters.json import JSONReporter
from datacompare.reporters.console import ConsoleReporter


def _build_source(cfg, connections: dict[str, AnyConnection], side_name: str) -> DataSource:
    if isinstance(cfg, ExcelSourceConfig):
        return ExcelSource(cfg, name=f"{side_name}:{cfg.path}")
    if isinstance(cfg, GaussDBSourceConfig):
        conn = connections.get(cfg.connection)
        if not isinstance(conn, GaussDBConnection):
            raise ConfigError(f"connection '{cfg.connection}' not found or wrong type")
        return GaussDBSource(cfg, conn, name=f"{side_name}:{cfg.connection}")
    if isinstance(cfg, APISourceConfig):
        from datacompare.sources.api import APISource
        conn = connections.get(cfg.connection)
        if not isinstance(conn, APIConnection):
            raise ConfigError(f"connection '{cfg.connection}' not found or wrong type")
        return APISource(cfg, conn, name=f"{side_name}:{cfg.connection}")
    raise ConfigError(f"unsupported source: {type(cfg).__name__}")


REPORTER_MAP: dict[str, type] = {
    "json": JSONReporter,
    "console": ConsoleReporter,
}


def dispatch_reporters(result: CompareResult, task: TaskConfig, output_dir: Path) -> list[Path]:
    outputs: list[Path] = []
    for fmt in task.output.formats:
        cls = REPORTER_MAP.get(fmt)
        if cls is None:
            continue  # HTML/Excel/CSV wired up in later tasks
        opts = {
            "truncate_details_over": task.output.truncate_details_over,
            **(task.output.html.model_dump() if fmt == "html" else {}),
            **(task.output.excel.model_dump() if fmt == "excel" else {}),
        }
        reporter = cls(opts, output_dir)
        path = reporter.render(result)
        if path is not None:
            outputs.append(path)
    return outputs


def execute(
    task: TaskConfig,
    connections: dict[str, AnyConnection],
    output_dir_override: str | None = None,
    formats_override: list[str] | None = None,
    engine_override: str | None = None,
) -> CompareResult:
    if formats_override:
        task.output.formats = list(formats_override)  # type: ignore[assignment]
    if engine_override:
        task.runtime.engine = engine_override  # type: ignore[assignment]

    left = _build_source(task.sources["left"], connections, side_name="left")
    right = _build_source(task.sources["right"], connections, side_name="right")

    try:
        # Milestone 4 wires only InMemoryEngine; router comes in Task 26.
        engine = InMemoryEngine()
        result = engine.compare(left, right, task)
    finally:
        left.close()
        right.close()

    output_dir = Path(output_dir_override or task.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch_reporters(result, task, output_dir)
    return result
