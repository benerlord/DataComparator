"""Typer CLI entry point."""
from __future__ import annotations
from pathlib import Path
import typer
from datacompare import __version__
from datacompare.config.loader import load_task, load_connections
from datacompare.config.errors import ConfigError
from datacompare.runner import execute

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
    params_dict = {}
    for kv in param:
        if "=" not in kv:
            typer.echo(f"invalid --param: {kv}", err=True)
            raise typer.Exit(1)
        k, v = kv.split("=", 1)
        params_dict[k] = v
    try:
        task = load_task(Path(task_file).expanduser(), params_dict)
        conn_path = Path(connections).expanduser()
        conns = load_connections(conn_path) if conn_path.exists() else {}
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)
    if dry_run:
        typer.echo("✓ configuration is valid (dry-run)")
        raise typer.Exit(0)
    try:
        result = execute(task, conns, output_dir_override=output_dir,
                         formats_override=fmt or None, engine_override=engine)
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True); raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"❌ error: {e}", err=True); raise typer.Exit(2)
    if fail_on_diff and (result.diff_rows > 0 or result.left_only > 0 or result.right_only > 0):
        raise typer.Exit(10)
    raise typer.Exit(0)


@app.command()
def validate(
    task_file: str = typer.Argument(...),
    connections: str = typer.Option("~/.datacompare/connections.yaml", "--connections", "-c"),
) -> None:
    """Validate a task config (no execution)."""
    from datacompare.validator import validate_task
    try:
        task = load_task(Path(task_file).expanduser())
        conn_path = Path(connections).expanduser()
        conns = load_connections(conn_path) if conn_path.exists() else {}
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True); raise typer.Exit(1)

    issues = validate_task(task, conns)
    if issues:
        typer.echo("❌ validation failed:")
        for issue in issues:
            typer.echo(f"  · {issue}")
        raise typer.Exit(1)
    typer.echo("✓ configuration is valid")


@app.command()
def init(
    template: str = typer.Argument(..., help="excel-vs-gaussdb | api-vs-gaussdb | excel-vs-api"),
) -> None:
    """Emit a config template to stdout."""
    from importlib import resources
    filename = template.replace("-", "_") + ".yaml"
    try:
        content = resources.files("datacompare.templates").joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        typer.echo(f"unknown template: {template}", err=True)
        raise typer.Exit(1)
    typer.echo(content)


if __name__ == "__main__":
    app()
