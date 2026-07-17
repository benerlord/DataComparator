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


def test_init_excel_vs_gaussdb_t():
    result = runner.invoke(app, ["init", "excel-vs-gaussdb-t"])
    assert result.exit_code == 0
    assert "variant: t" in result.stdout
    assert "jdbc_url" in result.stdout
    assert "jdbc_jar_path" in result.stdout
    assert "jdbc_driver_class" in result.stdout


def test_init_unknown_template():
    result = runner.invoke(app, ["init", "bogus"])
    assert result.exit_code != 0


def test_init_output_flag_writes_utf8_no_bom(tmp_path):
    """The -o flag bypasses shell redirection so PowerShell can't produce UTF-16."""
    out = tmp_path / "task.yaml"
    result = runner.invoke(app, ["init", "excel-vs-gaussdb", "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    raw = out.read_bytes()
    # No BOM
    assert not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM present"
    assert not raw.startswith(b"\xff\xfe"), "UTF-16 LE BOM present"
    assert not raw.startswith(b"\xfe\xff"), "UTF-16 BE BOM present"
    # Valid UTF-8, contains the Chinese template text
    text = raw.decode("utf-8")
    assert "每日销售数据核对" in text
    # LF line endings (not CRLF)
    assert b"\r\n" not in raw


def test_init_output_flag_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "dir" / "task.yaml"
    result = runner.invoke(app, ["init", "excel-vs-api", "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()


def test_init_output_flag_shows_confirmation(tmp_path):
    out = tmp_path / "task.yaml"
    result = runner.invoke(app, ["init", "excel-vs-gaussdb", "-o", str(out)])
    assert "✓" in result.stdout or "wrote" in result.stdout
    assert str(out) in result.stdout or out.name in result.stdout


def test_init_output_written_file_is_yaml_parseable_by_ruamel(tmp_path):
    """End-to-end guard: the written file must load cleanly with the project's YAML lib."""
    from ruamel.yaml import YAML
    out = tmp_path / "task.yaml"
    result = runner.invoke(app, ["init", "excel-vs-gaussdb", "-o", str(out)])
    assert result.exit_code == 0
    data = YAML(typ="safe").load(out.read_text(encoding="utf-8"))
    assert data["name"] == "每日销售数据核对"
