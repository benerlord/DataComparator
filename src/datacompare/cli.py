"""Typer CLI entry point."""
from __future__ import annotations
import typer
from datacompare import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo(f"datacompare {__version__}")


@app.command()
def run(
    task_file: str = typer.Argument(..., help="Path to task YAML config"),
    connections: str = typer.Option(
        "~/.datacompare/connections.yaml", "--connections", "-c",
        help="Path to connections YAML",
    ),
    param: list[str] = typer.Option([], "--param", "-p", help="KEY=VALUE"),
    output_dir: str | None = typer.Option(None, "--output-dir"),
    fmt: list[str] = typer.Option([], "--format", "-f"),
    engine: str | None = typer.Option(None, "--engine"),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_file: str | None = typer.Option(None, "--log-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fail_on_diff: bool = typer.Option(False, "--fail-on-diff"),
) -> None:
    """Execute a comparison task."""
    typer.echo("run: not implemented yet")
    raise typer.Exit(3)


@app.command()
def validate(
    task_file: str = typer.Argument(...),
    connections: str = typer.Option("~/.datacompare/connections.yaml", "--connections", "-c"),
) -> None:
    """Validate a task config (no execution)."""
    typer.echo("validate: not implemented yet")
    raise typer.Exit(3)


@app.command()
def init(
    template: str = typer.Argument(..., help="Template name"),
) -> None:
    """Emit a config template to stdout."""
    typer.echo("init: not implemented yet")
    raise typer.Exit(3)


if __name__ == "__main__":
    app()
