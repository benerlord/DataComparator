"""Integration test: exercise JdbcDriver via PostgreSQL JDBC driver.

Purpose: validate that JayDeBeApi + JVM lifecycle + fetch_chunks work correctly,
without needing an actual GaussDB T instance. The PostgreSQL JDBC driver is
Apache-2.0 licensed and downloaded on-demand.

Skipped when: Docker unavailable, jaydebeapi unavailable, or JVM unavailable.
"""
from __future__ import annotations
import os
import urllib.request
from pathlib import Path
import pytest

# Skip guards
docker = pytest.importorskip("docker")
try:
    _c = docker.from_env()
    _c.ping()
except Exception:
    pytest.skip("Docker daemon not available", allow_module_level=True)

try:
    import jaydebeapi  # noqa: F401
    import jpype  # noqa: F401
except ImportError:
    pytest.skip("jaydebeapi / jpype not installed", allow_module_level=True)

from testcontainers.postgres import PostgresContainer
from datacompare.sources.gaussdb_jdbc import JdbcDriver
from datacompare.config.models import GaussDBTConnection


PG_JDBC_JAR_URL = "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
PG_JDBC_JAR_NAME = "postgresql-42.7.4.jar"
JAR_CACHE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "jars"


@pytest.fixture(scope="module")
def pg_jdbc_jar():
    """Download PostgreSQL JDBC jar into tests/fixtures/jars/ (cached)."""
    JAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = JAR_CACHE_DIR / PG_JDBC_JAR_NAME
    if not target.exists():
        try:
            urllib.request.urlretrieve(PG_JDBC_JAR_URL, str(target))
        except Exception as e:
            pytest.skip(f"Cannot download PG JDBC jar: {e}")
    return target


@pytest.fixture(scope="module")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        import psycopg2
        conn = psycopg2.connect(
            host=pg.get_container_host_ip(),
            port=pg.get_exposed_port(5432),
            user=pg.username, password=pg.password, dbname=pg.dbname,
        )
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE sales (
                    order_id TEXT, region TEXT, amount NUMERIC
                );
                INSERT INTO sales VALUES
                    ('A001', 'North', 100.50),
                    ('A002', 'South', 200.00),
                    ('A003', 'West', 300.75);
            """)
        conn.commit()
        conn.close()
        yield pg


@pytest.fixture
def creds(pg_container, pg_jdbc_jar):
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return GaussDBTConnection(
        variant="t",
        jdbc_url=f"jdbc:postgresql://{host}:{port}/{pg_container.dbname}",
        jdbc_jar_path=str(pg_jdbc_jar),
        jdbc_driver_class="org.postgresql.Driver",
        user=pg_container.username,
        password=pg_container.password,
    )


def test_columns_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        cols = driver.columns_for("SELECT order_id, region, amount FROM sales")
        assert cols == ["order_id", "region", "amount"]
    finally:
        driver.close()


def test_count_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        assert driver.count_for("SELECT * FROM sales") == 3
    finally:
        driver.close()


def test_fetch_chunks_via_jdbc(creds):
    driver = JdbcDriver(creds)
    try:
        chunks = list(driver.fetch_chunks("SELECT * FROM sales ORDER BY order_id", chunk_size=2))
        # Chunks should sum to 3 rows total
        rows = [r for c in chunks for r in c]
        assert len(rows) == 3
        assert rows[0][0] == "A001"
    finally:
        driver.close()


def test_jdbc_properties_appended(creds):
    """URL with jdbc_properties should still connect (postgres driver accepts loginTimeout)."""
    creds_with_props = creds.model_copy(update={"jdbc_properties": {"loginTimeout": "10"}})
    driver = JdbcDriver(creds_with_props)
    try:
        driver.connect()  # Should succeed
        assert driver._conn is not None
    finally:
        driver.close()
