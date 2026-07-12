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
