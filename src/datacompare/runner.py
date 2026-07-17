"""Orchestration: build sources, run engine, dispatch reporters."""
from __future__ import annotations
import time
from pathlib import Path
from datacompare.config.models import (
    TaskConfig, AnyConnection, ExcelSourceConfig, GaussDBSourceConfig,
    APISourceConfig, GaussDBConnection, APIConnection, BatchConfig,
)
from datacompare.config.errors import ConfigError
from datacompare.config.loader import merge_sub_task
from datacompare.sources.base import DataSource
from datacompare.sources.excel import ExcelSource
from datacompare.sources.gaussdb import GaussDBSource
from datacompare.engine.memory import InMemoryEngine  # noqa: F401 – kept for backwards compat
from datacompare.engine.router import select_engine
from datacompare.engine.result import CompareResult, BatchResult, SubTaskResult
from datacompare.reporters.json import JSONReporter
from datacompare.reporters.console import ConsoleReporter
from datacompare.reporters.html import HTMLReporter
from datacompare.reporters.excel import ExcelReporter
from datacompare.reporters.csv import CSVReporter


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
    "html": HTMLReporter,
    "excel": ExcelReporter,
    "csv": CSVReporter,
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
        engine = select_engine(left, right, task)
        result = engine.compare(left, right, task)
    finally:
        left.close()
        right.close()

    output_dir = Path(output_dir_override or task.output.dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dispatch_reporters(result, task, output_dir)
    return result


def _build_defaults_dict(batch: BatchConfig) -> dict:
    """Extract non-None defaults blocks for merge."""
    return {
        k: v for k, v in {
            "sources": batch.sources,
            "match": batch.match,
            "compare": batch.compare,
            "output": batch.output,
            "runtime": batch.runtime,
        }.items() if v is not None
    }


def _resolve_sub_task_output_dir(
    sub_raw: dict, merged: dict, default_dir: str, sub_name: str
) -> str:
    """Explicit sub-task output.dir wins; else auto-append sub_name to default_dir."""
    if isinstance(sub_raw.get("output"), dict) and "dir" in sub_raw["output"]:
        return sub_raw["output"]["dir"]
    return str(Path(default_dir) / sub_name)


def execute_batch(batch: BatchConfig, connections: dict[str, AnyConnection]) -> BatchResult:
    """Run each sub-task sequentially. on_error=continue (default) — always run all;
    fail_fast handling arrives in T6."""
    defaults = _build_defaults_dict(batch)
    default_out_dir = (batch.output or {}).get("dir", "./reports")
    results: list[SubTaskResult] = []
    batch_start = time.monotonic()

    for sub in batch.tasks:
        sub_raw = {"name": sub.name, **(sub.model_extra or {})}
        merged = merge_sub_task(defaults, sub_raw)
        sub_out_dir = _resolve_sub_task_output_dir(sub_raw, merged, default_out_dir, sub.name)
        merged.setdefault("output", {})
        merged["output"]["dir"] = sub_out_dir

        sub_task_start = time.monotonic()
        try:
            task = TaskConfig.model_validate(merged)
            cr = execute(task, connections)
            results.append(SubTaskResult(
                task_name=sub.name, status="success",
                comparison_result=cr, error=None,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))
        except Exception as e:
            results.append(SubTaskResult(
                task_name=sub.name, status="failed",
                comparison_result=None, error=e,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))

    return BatchResult(
        batch_name=batch.name,
        task_results=results,
        total_duration_ms=int((time.monotonic() - batch_start) * 1000),
    )
