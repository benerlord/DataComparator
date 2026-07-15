import pytest
import pandas as pd

# Skip whole module if Docker unavailable
docker = pytest.importorskip("docker")
try:
    _c = docker.from_env()
    _c.ping()
except Exception:
    pytest.skip("Docker daemon not available", allow_module_level=True)

from testcontainers.postgres import PostgresContainer
from datacompare.sources.gaussdb import GaussDBSource
from datacompare.config.models import GaussDBSourceConfig, GaussDBAConnection


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
def creds(pg_container):
    return GaussDBAConnection(
        type="gaussdb",
        host=pg_container.get_container_host_ip(),
        port=int(pg_container.get_exposed_port(5432)),
        database=pg_container.dbname,
        user=pg_container.username,
        password=pg_container.password,
        ssl="disable",
    )


def test_columns(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT order_id, region, amount FROM sales")
    src = GaussDBSource(cfg, creds)
    assert src.columns() == ["order_id", "region", "amount"]
    src.close()


def test_estimated_rows(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT * FROM sales")
    src = GaussDBSource(cfg, creds)
    assert src.estimated_rows() == 3
    src.close()


def test_read_returns_strings(creds):
    cfg = GaussDBSourceConfig(connection="test", query="SELECT * FROM sales ORDER BY order_id")
    src = GaussDBSource(cfg, creds)
    df = pd.concat(src.read())
    assert len(df) == 3
    assert df.iloc[0]["order_id"] == "A001"
    assert df.iloc[0]["amount"] == "100.50"
    assert all(df.dtypes == "object")
    src.close()


def test_non_select_query_rejected(creds):
    cfg = GaussDBSourceConfig(
        connection="test",
        query="INSERT INTO sales VALUES ('X', 'Y', 0)",
    )
    src = GaussDBSource(cfg, creds)
    with pytest.raises(Exception, match="SELECT"):
        src.columns()
    src.close()
