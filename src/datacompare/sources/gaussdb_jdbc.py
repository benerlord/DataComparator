"""GaussDB T driver via JDBC + JayDeBeApi (embedded JVM).

JVM is a process-level singleton, lazily started on first T connection.
Users who only use variant=a never trigger JVM startup.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator, Any
from datacompare.config.models import GaussDBTConnection
from datacompare.config.errors import ConfigError
from .gaussdb import GaussDBDriver


# Module-level flag: JVM lifecycle spans the entire Python process.
_JVM_STARTED = False


def _ensure_jvm(jar_path: str) -> None:
    """Start JVM (if not already) and register the JDBC JAR on classpath.

    Idempotent: safe to call multiple times.
    """
    global _JVM_STARTED
    try:
        import jaydebeapi  # noqa: F401
        import jpype
    except ImportError as e:
        raise ConfigError(
            "GaussDB T (variant=t) 需要 JayDeBeApi + JPype，"
            "请安装：pip install 'datacompare[gaussdb-t]'"
        ) from e

    if not Path(jar_path).is_file():
        raise ConfigError(
            f"JDBC JAR 不存在：{jar_path}",
            path="connections.jdbc_jar_path",
            suggestion="从华为支持网站下载 gsjdbc4.jar 后填写正确路径",
        )

    if not jpype.isJVMStarted():
        jpype.startJVM(
            jpype.getDefaultJVMPath(),
            f"-Djava.class.path={jar_path}",
            convertStrings=True,
        )
        _JVM_STARTED = True
    else:
        # JVM already running: try to add this JAR to classpath (multi-T-connection case)
        try:
            jpype.addClassPath(jar_path)
        except AttributeError:
            # JPype < 1.0 doesn't have addClassPath; JAR must have been in initial classpath.
            pass


class JdbcDriver(GaussDBDriver):
    def __init__(self, creds: GaussDBTConnection):
        self.creds = creds
        self._conn = None

    def _build_url_with_properties(self) -> str:
        base = self.creds.jdbc_url
        if not self.creds.jdbc_properties:
            return base
        pairs = "&".join(f"{k}={v}" for k, v in self.creds.jdbc_properties.items())
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{pairs}"

    def connect(self) -> None:
        if self._conn is not None:
            return
        import jaydebeapi
        _ensure_jvm(self.creds.jdbc_jar_path)
        url = self._build_url_with_properties()
        self._conn = jaydebeapi.connect(
            self.creds.jdbc_driver_class,
            url,
            [self.creds.user, self.creds.password],
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _probe_columns(self, cur, query: str) -> list[str]:
        """Try WHERE 1=0 first (Oracle-style dialects); fall back to LIMIT 0."""
        try:
            cur.execute(f"SELECT * FROM ({query}) t WHERE 1=0")
        except Exception:
            cur.execute(f"SELECT * FROM ({query}) t LIMIT 0")
        return [d[0] for d in cur.description]

    def columns_for(self, query: str) -> list[str]:
        self.connect()
        cur = self._conn.cursor()
        try:
            return self._probe_columns(cur, query)
        finally:
            cur.close()

    def count_for(self, query: str) -> int:
        self.connect()
        cur = self._conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM ({query}) t")
            return int(cur.fetchone()[0])
        finally:
            cur.close()

    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple]]:
        self.connect()
        cur = self._conn.cursor()
        try:
            # Hint to JDBC driver about network fetch batch size (best-effort).
            try:
                cur._rs.setFetchSize(chunk_size)  # jaydebeapi cursor exposes ResultSet as _rs
            except Exception:
                pass
            cur.execute(query)
            while True:
                rows = cur.fetchmany(chunk_size)
                if not rows:
                    break
                yield rows
        finally:
            cur.close()
