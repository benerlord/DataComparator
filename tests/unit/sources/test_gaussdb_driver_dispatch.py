import pytest
from datacompare.config.models import (
    GaussDBSourceConfig, GaussDBAConnection, GaussDBTConnection,
)
from datacompare.sources.gaussdb import GaussDBSource, GaussDBDriver, PostgresDriver


def test_a_variant_creates_postgres_driver():
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    conn = GaussDBAConnection(host="h", database="d", user="u", password="p")
    src = GaussDBSource(cfg, conn)
    assert isinstance(src._driver, PostgresDriver)


def test_t_variant_creates_jdbc_driver(tmp_path):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    cfg = GaussDBSourceConfig(connection="c", query="SELECT 1")
    conn = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path=str(jar),
        jdbc_driver_class="c", user="u", password="p",
    )
    src = GaussDBSource(cfg, conn)
    # Lazy import: check class name to avoid importing JdbcDriver here
    assert type(src._driver).__name__ == "JdbcDriver"


def test_gaussdb_driver_is_abstract():
    with pytest.raises(TypeError):
        GaussDBDriver()  # abstract, cannot instantiate


def test_select_only_validation_still_enforced():
    cfg = GaussDBSourceConfig(connection="c", query="INSERT INTO t VALUES (1)")
    conn = GaussDBAConnection(host="h", database="d", user="u", password="p")
    from datacompare.config.errors import ConfigError
    with pytest.raises(ConfigError, match="SELECT"):
        GaussDBSource(cfg, conn)
