import sys
import pytest
from pathlib import Path
from datacompare.config.models import GaussDBTConnection
from datacompare.config.errors import ConfigError


def _creds(**overrides):
    base = dict(
        variant="t",
        jdbc_url="jdbc:zenith:@//h:1611/svc",
        jdbc_jar_path="/nonexistent.jar",
        jdbc_driver_class="com.huawei.gauss.jdbc.ZenithDriver",
        user="u", password="p",
    )
    base.update(overrides)
    return GaussDBTConnection(**base)


def test_missing_jar_raises_config_error(tmp_path):
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm
    missing = str(tmp_path / "missing.jar")
    with pytest.raises(ConfigError, match="JDBC JAR 不存在"):
        _ensure_jvm(missing)


def test_no_jaydebeapi_installed_gives_install_hint(mocker, tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")  # exists but empty (JAR content not validated in _ensure_jvm)
    mocker.patch.dict(sys.modules, {"jaydebeapi": None, "jpype": None})
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm
    with pytest.raises(ConfigError, match=r"pip install 'datacompare\[gaussdb-t\]'"):
        _ensure_jvm(str(jar))


def test_ensure_jvm_is_idempotent(mocker, tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    fake_jpype = mocker.MagicMock()
    # First call sees JVM not started; subsequent see it started
    fake_jpype.isJVMStarted.side_effect = [False, True, True]
    fake_jpype.getDefaultJVMPath.return_value = "/fake/libjvm.so"
    mocker.patch.dict(sys.modules, {"jaydebeapi": mocker.MagicMock(), "jpype": fake_jpype})

    # Force reimport so the freshly-mocked jpype is used
    if "datacompare.sources.gaussdb_jdbc" in sys.modules:
        del sys.modules["datacompare.sources.gaussdb_jdbc"]
    from datacompare.sources.gaussdb_jdbc import _ensure_jvm

    _ensure_jvm(str(jar))
    _ensure_jvm(str(jar))
    _ensure_jvm(str(jar))
    assert fake_jpype.startJVM.call_count == 1


def test_url_properties_appended_no_existing_qs():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds(jdbc_properties={"loginTimeout": "30", "fetchSize": "1000"})
    driver = JdbcDriver(creds)
    url = driver._build_url_with_properties()
    assert url.startswith("jdbc:zenith:@//h:1611/svc?")
    assert "loginTimeout=30" in url
    assert "fetchSize=1000" in url
    assert url.count("?") == 1


def test_url_properties_appended_when_qs_exists():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds(
        jdbc_url="jdbc:zenith:@//h:1611/svc?existing=x",
        jdbc_properties={"loginTimeout": "30"},
    )
    driver = JdbcDriver(creds)
    url = driver._build_url_with_properties()
    assert url == "jdbc:zenith:@//h:1611/svc?existing=x&loginTimeout=30"


def test_url_no_properties_unchanged():
    from datacompare.sources.gaussdb_jdbc import JdbcDriver
    creds = _creds()  # no jdbc_properties
    driver = JdbcDriver(creds)
    assert driver._build_url_with_properties() == "jdbc:zenith:@//h:1611/svc"
