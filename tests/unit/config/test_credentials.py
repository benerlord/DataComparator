import pytest
from datacompare.config.credentials import mask_password, resolve_keyring


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
