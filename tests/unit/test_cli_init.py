from typer.testing import CliRunner
from datacompare.cli import app

runner = CliRunner()


def test_init_excel_vs_gaussdb():
    result = runner.invoke(app, ["init", "excel-vs-gaussdb"])
    assert result.exit_code == 0
    assert "excel" in result.stdout
    assert "gaussdb" in result.stdout


def test_init_api_vs_gaussdb():
    result = runner.invoke(app, ["init", "api-vs-gaussdb"])
    assert result.exit_code == 0
    assert "api" in result.stdout
    assert "pagination" in result.stdout


def test_init_excel_vs_api():
    result = runner.invoke(app, ["init", "excel-vs-api"])
    assert result.exit_code == 0
    assert "excel" in result.stdout
    assert "api" in result.stdout


def test_init_unknown_template():
    result = runner.invoke(app, ["init", "bogus"])
    assert result.exit_code != 0
