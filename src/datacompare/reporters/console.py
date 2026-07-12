"""Terminal reporter using rich."""
from __future__ import annotations
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from datacompare.engine.result import CompareResult
from .base import Reporter


class ConsoleReporter(Reporter):
    def render(self, result: CompareResult) -> None:
        console = Console()
        console.print(Panel.fit(f"[bold]{result.task_name}[/bold] · 比对完成"))

        header = Table.grid(padding=(0, 1))
        header.add_row("左侧:", result.left_name, f"{result.left_total:,} 行")
        header.add_row("右侧:", result.right_name, f"{result.right_total:,} 行")
        header.add_row("引擎:", result.engine_used, f"耗时 {result.duration_seconds:.2f}s")
        console.print(header)

        stats = Table(title="匹配情况")
        stats.add_column("指标"); stats.add_column("数量", justify="right")
        stats.add_row("匹配率", f"{result.match_rate() * 100:.2f}%")
        stats.add_row("完全一致", f"{result.identical_rows:,}")
        stats.add_row("字段差异", f"{result.diff_rows:,}")
        stats.add_row("左侧独有", f"{result.left_only:,}")
        stats.add_row("右侧独有", f"{result.right_only:,}")
        console.print(stats)

        if result.errors:
            console.print(f"[yellow]⚠  {len(result.errors)} 个字段解析错误[/yellow]")
        return None
