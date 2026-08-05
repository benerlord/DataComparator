import pytest
from pathlib import Path
from pydantic import ValidationError
from datacompare.config.credentials import mask_password, resolve_keyring
from datacompare.config.models import GaussDBTConnection


def test_mask_password_dsn():
    assert mask_password("postgresql://u:secret@h:5432/db") == "postgresql://u:***@h:5432/db"


def test_mask_password_keyword():
    assert mask_password("host=x password=secret user=u") == "host=x password=*** user=u"


def test_mask_password_no_password():
    assert mask_password("host=x user=u") == "host=x user=u"


def test_resolve_keyring_scheme(mocker):
    mocker.patch("keyring.get_password", return_value="my_secret")
    assert resolve_keyring("keyring://myservice/myuser") == "my_secret"


def test_resolve_keyring_passthrough():
    assert resolve_keyring("plain_value") == "plain_value"


def test_mask_password_jdbc_userinfo():
    """JDBC URL with user:password@host form"""
    inp = "jdbc:zenith:@//user:secret@10.0.0.20:1611/svc"
    out = mask_password(inp)
    assert "secret" not in out
    assert "***" in out


def test_mask_password_jdbc_query_string():
    """JDBC URL with password=xxx as query parameter"""
    inp = "jdbc:zenith://host:1611/svc?user=u&password=secret&loginTimeout=30"
    out = mask_password(inp)
    assert "secret" not in out
    assert "password=***" in out


def test_mask_password_jdbc_pwd_query_variant():
    """Some JDBC drivers use pwd= instead of password="""
    inp = "jdbc:gaussdb://host/db?user=u&pwd=secret"
    out = mask_password(inp)
    assert "secret" not in out
    assert "pwd=***" in out


def test_mask_password_no_effect_on_plain_url():
    """URLs without embedded credentials pass through unchanged"""
    inp = "jdbc:postgresql://host:5432/db"
    assert mask_password(inp) == inp


# ---------------------------------------------------------------------------
# GaussDBTConnection.jdbc_jar_path validator (v0.10)
# ---------------------------------------------------------------------------

def test_gaussdb_t_relative_jdbc_jar_path_resolved_to_absolute(tmp_path, monkeypatch):
    """相对 jdbc_jar_path 在 load 时被 resolve 成绝对路径。"""
    jar = tmp_path / "driver.jar"
    jar.write_bytes(b"fake")
    monkeypatch.chdir(tmp_path)
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://host:port/db",
        jdbc_jar_path="driver.jar",   # 相对路径
        jdbc_driver_class="com.x.Y",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path).is_absolute()
    assert Path(conn.jdbc_jar_path) == jar.resolve()


def test_gaussdb_t_home_expansion_in_jdbc_jar_path(tmp_path, monkeypatch):
    """~ 展开为 $HOME。"""
    home = tmp_path / "home"
    home.mkdir()
    jar_dir = home / ".datacompare"
    jar_dir.mkdir()
    jar = jar_dir / "driver.jar"
    jar.write_bytes(b"fake")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://x:1/y",
        jdbc_jar_path="~/.datacompare/driver.jar",
        jdbc_driver_class="c.X",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path) == jar.resolve()


def test_gaussdb_t_missing_jdbc_jar_path_raises_at_load():
    """JAR 不存在 → 加载期就报错，不用等到运行时。"""
    with pytest.raises(ValidationError, match="jdbc_jar_path 不存在"):
        GaussDBTConnection(
            variant="t",
            jdbc_url="jdbc:zenith://x:1/y",
            jdbc_jar_path="/nonexistent/absolute/path/x.jar",
            jdbc_driver_class="c.X",
            user="u", password="p",
        )


def test_gaussdb_t_absolute_jdbc_jar_path_untouched(tmp_path):
    """绝对路径不受影响（除了可能的 symlink resolve）。"""
    jar = tmp_path / "driver.jar"
    jar.write_bytes(b"fake")
    conn = GaussDBTConnection(
        variant="t",
        jdbc_url="jdbc:zenith://x:1/y",
        jdbc_jar_path=str(jar),
        jdbc_driver_class="c.X",
        user="u", password="p",
    )
    assert Path(conn.jdbc_jar_path) == jar.resolve()
