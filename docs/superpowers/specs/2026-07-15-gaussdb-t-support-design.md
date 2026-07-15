# GaussDB T 支持设计文档

- **日期**：2026-07-15
- **状态**：设计定稿，待实现
- **前置文档**：`2026-07-13-data-comparator-design.md`（原始设计，只涵盖 GaussDB A / DWS）
- **改动范围**：数据源层（`sources/gaussdb.py` 及新增 `sources/gaussdb_jdbc.py`）、配置模型、依赖组织、测试

---

## 1. 背景与目标

### 1.1 问题

DataComparator v0.1 只支持 GaussDB 的 **PostgreSQL 兼容变体**（GaussDB A / DWS / openGauss / GaussDB 100 PG 模式），通过 `psycopg2` 直连。但华为 GaussDB 家族还有另一大变体 **GaussDB T（Transactional / OLTP）**，走不同的有线协议 —— `psycopg2` **无法连接**。

用户实际环境里存在 GaussDB T 实例（Data Studio 工具能连上，说明 JDBC 驱动路径可行）。当前工具无法覆盖这类数据源。

### 1.2 目标

在**不破坏现有 GaussDB A 用户配置和行为**的前提下，为 `type: gaussdb` 数据源新增 GaussDB T 支持：

- 用户在 YAML 里加一行 `variant: t` 并配置 JDBC 信息，即可比对 GaussDB T 数据
- 现有 A 用户配置**零改动**继续工作
- 只用 A 变体的用户**不被强制装** Java / JayDeBeApi

### 1.3 非目标

- 不覆盖华为专有认证（Kerberos / SM3 / SM4）—— 首版只 user/password
- 不支持自动下载 `gsjdbc4.jar`（License 不允许分发；且增加故障面）
- 不做智能"driver class 名"猜测 —— 用户显式配置
- 不引入连接池（CLI 单进程一次性用完）

---

## 2. 需求规格

### 2.1 用户视角

**GaussDB A**（现有配置，零改动）：
```yaml
prod_dws_a:
  type: gaussdb
  # variant: a   ← 可省略，默认
  host: 10.0.0.10
  port: 5432
  database: dws
  user: analytics_ro
  password: ${GAUSS_A_PWD}
  ssl: require
```

**GaussDB T**（新增）：
```yaml
prod_oltp_t:
  type: gaussdb
  variant: t
  jdbc_url: "jdbc:zenith:@//10.0.0.20:1611/oltp_service"
  jdbc_jar_path: /opt/gaussdb/gsjdbc4.jar
  jdbc_driver_class: com.huawei.gauss.jdbc.ZenithDriver
  user: analytics_ro
  password: ${GAUSS_T_PWD}
  jdbc_properties:            # 可选，透传给 JDBC driver
    loginTimeout: "30"
    fetchSize: "1000"
```

### 2.2 字段差异对照

| 字段 | Variant A | Variant T |
|---|---|---|
| `variant` | `a`（默认，可省略） | `t`（必需） |
| `host / port / database` | ✅ 必需 | ❌ 已在 jdbc_url 里 |
| `ssl` | ✅ 可选 | ❌ 已在 jdbc_url 里 |
| `jdbc_url` | ❌ | ✅ 必需 |
| `jdbc_jar_path` | ❌ | ✅ 必需 |
| `jdbc_driver_class` | ❌ | ✅ 必需 |
| `jdbc_properties` | ❌ | ⚙️ 可选 |
| `user / password` | ✅ 必需 | ✅ 必需 |

### 2.3 执行模型（澄清 JDBC 的实现机制）

JDBC 走 **JayDeBeApi + JPype**：在 Python 进程里**嵌入一个 JVM**（in-process），SQL 通过 "Python 调 Java 方法" 的方式执行。**不会** fork `java -jar` 子进程。

- JVM 进程级单例、懒启动（第一次 T 连接时才启动，只用 A 的进程永不启动 JVM）
- 首次启动开销 ~500ms-2s，后续查询接近零开销
- 常驻额外内存 ~100-200MB
- 需要机器上有 JRE 8+ 可被 JPype 找到

---

## 3. 架构

### 3.1 层次

```
GaussDBSource (统一 DataSource 契约：columns / estimated_rows / read / close)
    ↓ 内部持有
GaussDBDriver (抽象基类：connect / cursor / fetch_chunks)
    ├── PostgresDriver     ← 现有 psycopg2 逻辑（variant=a）
    └── JdbcDriver         ← 新增，jaydebeapi + gsjdbc4.jar（variant=t）
```

- `GaussDBSource` 只关心业务逻辑：SELECT 白名单、列名探测、行数估算、分块读取、字符串化
- `Driver` 只关心底层连接：怎么建连、怎么发 SQL、怎么拿结果
- **变体切换点**：`GaussDBSource.__init__` 根据 `connection.variant` 实例化对应 Driver

### 3.2 影响文件

| 文件 | 改动 |
|---|---|
| `config/models.py` | 拆 `GaussDBConnection` 为 `GaussDBAConnection` / `GaussDBTConnection`；`GaussDBConnection` 名字保留但**重新定义为联合类型** `GaussDBAConnection \| GaussDBTConnection`（Python 3.10+ 支持 `isinstance` 检查联合），discriminator 只在 `AnyConnection` 顶层用 `Annotated` 应用 |
| `tests/integration/sources/test_gaussdb.py` | **必需迁移一处**：`GaussDBConnection(host=..., ...)` 构造器 → `GaussDBAConnection(host=..., ...)`（联合类型不能作为构造器调用） |
| `sources/gaussdb.py` | 引入 `GaussDBDriver` 抽象；把 psycopg2 代码搬进 `PostgresDriver`；`GaussDBSource` 薄化到 ~30 行 |
| `sources/gaussdb_jdbc.py`（新） | `JdbcDriver` 实现 + JVM 生命周期管理 |
| `runner.py` | `_build_source` 里 isinstance 检查自动匹配新联合类型；**代码无需改** |
| `pyproject.toml` | 新增 optional dependency `[gaussdb-t]` 装 `JayDeBeApi` + `JPype1` |
| `tests/unit/config/test_gaussdb_discriminator.py`（新） | Pydantic discriminator 用例 |
| `tests/unit/sources/test_gaussdb_driver_dispatch.py`（新） | Driver 分派单元测试 |
| `tests/unit/sources/test_gaussdb_jdbc_unit.py`（新） | JdbcDriver 单元测试（mock jpype/jaydebeapi） |
| `tests/integration/sources/test_gaussdb_jdbc_via_postgres.py`（新） | 用 PG JDBC 驱动验证 JayDeBeApi 封装（不需要真实 GaussDB T） |
| `tests/integration/sources/test_gaussdb.py`（现有） | 不改，保持 A 侧集成测试 |

---

## 4. 配置模型（Pydantic）

```python
# src/datacompare/config/models.py

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class GaussDBAConnection(BaseModel):
    """PostgreSQL 协议兼容变体（DWS / openGauss / GaussDB 100 PG 模式）"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["gaussdb"] = "gaussdb"
    variant: Literal["a"] = "a"
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    ssl: Literal["disable", "require", "verify-ca"] = "require"


class GaussDBTConnection(BaseModel):
    """GaussDB T (OLTP) — via JDBC + JayDeBeApi"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["gaussdb"] = "gaussdb"
    variant: Literal["t"]
    jdbc_url: str = Field(min_length=1)
    jdbc_jar_path: str = Field(min_length=1)
    jdbc_driver_class: str = Field(min_length=1)
    user: str
    password: str
    jdbc_properties: dict[str, str] = Field(default_factory=dict)


# 联合类型：可用于 isinstance 检查（Python 3.10+），可用于类型注解
GaussDBConnection = GaussDBAConnection | GaussDBTConnection

# 顶层 AnyConnection 加上 discriminator，用于 Pydantic 校验分派
AnyConnection = Annotated[
    GaussDBAConnection | GaussDBTConnection | APIConnection,
    Field(discriminator="variant"),   # 需要 APIConnection 也有 variant/type 字段作为区分
]
# 实际上 APIConnection 用 type 字段而非 variant；见下方替代实现
```

**替代实现（更稳妥）**：`AnyConnection` 使用 `TypeAdapter` 而非 discriminator，兼容 API 侧的既有 type-based 分派逻辑：

```python
GaussDBConnection = Annotated[
    GaussDBAConnection | GaussDBTConnection,
    Field(discriminator="variant"),
]

AnyConnection = GaussDBConnection | APIConnection   # 顶层不加 discriminator
# 加载时 loader.py 用 TypeAdapter(AnyConnection).validate_python(...) 处理
```

后者与现有 `load_connections()` 的 `TypeAdapter(AnyConnection).validate_python()` 模式一致，**采纳此实现**。

**校验行为**：
- 用户漏写 `variant` → 默认 `a`，走 `GaussDBAConnection` 校验
- `variant: t` 但缺 `jdbc_url` → 报错：`jdbc_url: field required`
- A 变体误写 `jdbc_url` → `extra fields not permitted`（`extra="forbid"` 起作用）
- 错误消息里明确指出是哪个 discriminator 分支不匹配

---

## 5. Driver 抽象与实现

### 5.1 抽象基类

```python
# src/datacompare/sources/gaussdb.py

from abc import ABC, abstractmethod
from typing import Iterator, Any


class GaussDBDriver(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def columns_for(self, query: str) -> list[str]:
        """探测 query 的列名（不返回数据行）"""

    @abstractmethod
    def count_for(self, query: str) -> int:
        """SELECT COUNT(*) FROM (query) t"""

    @abstractmethod
    def fetch_chunks(self, query: str, chunk_size: int) -> Iterator[list[tuple[Any, ...]]]:
        """流式执行 query，按 chunk_size 分块产出原始行元组"""
```

Driver 返回**原始 Python 值元组**（`int` / `Decimal` / `datetime` 等）；字符串化 + `astype(object)` 由 `GaussDBSource.read()` 统一做（保持现有契约）。

### 5.2 `PostgresDriver`

原 `GaussDBSource` 里的 psycopg2 代码几乎照搬（`connect / columns / count / fetchmany with named cursor`），逻辑不变。

### 5.3 `JdbcDriver`

放在独立文件 `sources/gaussdb_jdbc.py`，**默认不导入** —— 只在 `variant=t` 且实际实例化 JdbcDriver 时才 import jaydebeapi/jpype。

**JVM 生命周期**：

```python
_JVM_STARTED = False   # 模块级，进程内共享

def _ensure_jvm(jar_path: str) -> None:
    """幂等地启动 JVM 并把 JAR 加入 classpath"""
    global _JVM_STARTED
    try:
        import jaydebeapi, jpype
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
        try:
            jpype.addClassPath(jar_path)   # 多 T 连接场景追加 classpath
        except AttributeError:
            pass   # 旧 JPype 版本 fallback
```

**核心接口**：

```python
class JdbcDriver(GaussDBDriver):
    def __init__(self, creds: GaussDBTConnection):
        self.creds = creds
        self._conn = None

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

    def _build_url_with_properties(self) -> str:
        base = self.creds.jdbc_url
        if not self.creds.jdbc_properties:
            return base
        pairs = "&".join(f"{k}={v}" for k, v in self.creds.jdbc_properties.items())
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{pairs}"

    def columns_for(self, query: str) -> list[str]:
        self.connect()
        cur = self._conn.cursor()
        try:
            cur.execute(f"SELECT * FROM ({query}) t WHERE 1=0")
            return [d[0] for d in cur.description]
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
            try:
                cur._rs.setFetchSize(chunk_size)   # hint 给 driver，best-effort
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

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
```

**关键决定**：
- **`WHERE 1=0` 替代 `LIMIT 0`** —— GaussDB T 可能是 Oracle 风格 SQL，`LIMIT` 不通用；PostgresDriver 里保留 `LIMIT 0`（PG 原生）
- **`setFetchSize` 是 hint** —— best-effort，`try/except` 忽略失败
- **`jdbc_properties` 追加到 URL query string** —— 大多数 JDBC driver 接受这种方式

### 5.4 `GaussDBSource` 薄化

```python
@register_source("gaussdb")
class GaussDBSource(DataSource):
    def __init__(self, config, connection, name: str = ""):
        self.config = config
        self.creds = connection
        self.name = name or f"gaussdb:{self._display_target()}"
        self._driver: GaussDBDriver = self._make_driver(connection)
        self._validate_read_only()

    @staticmethod
    def _make_driver(creds) -> GaussDBDriver:
        if isinstance(creds, GaussDBAConnection):
            return PostgresDriver(creds)
        if isinstance(creds, GaussDBTConnection):
            from .gaussdb_jdbc import JdbcDriver   # 惰性 import
            return JdbcDriver(creds)
        raise ConfigError(f"unknown GaussDB variant: {type(creds).__name__}")

    def columns(self) -> list[str]:
        return self._driver.columns_for(self.config.query)

    def estimated_rows(self) -> int | None:
        return self._driver.count_for(self.config.query)

    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        cols = self.columns()
        for rows in self._driver.fetch_chunks(self.config.query, chunk_size):
            df = pd.DataFrame(rows, columns=cols)
            df = df.map(lambda v: None if v is None else str(v))
            df = df.astype(object)
            yield df

    def close(self) -> None:
        self._driver.close()
```

---

## 6. 依赖组织

```toml
# pyproject.toml
[project]
dependencies = [
    # ... 现有依赖不变
    "psycopg2-binary>=2.9",
]

[project.optional-dependencies]
gaussdb-t = [
    "JayDeBeApi>=1.2.3",
    "JPype1>=1.5",
]

dev = [
    # ... 现有 dev 依赖
    "datacompare[gaussdb-t]",   # 开发环境自动装全
]
```

**用户按需选择**：
- 只用 A：`pip install datacompare`（不需要 Java）
- 用 T：`pip install 'datacompare[gaussdb-t]'` + 机器上装 JRE 8+
- 都用：同上

---

## 7. 测试策略

### 7.1 单元测试

| 文件 | 覆盖 |
|---|---|
| `tests/unit/config/test_gaussdb_discriminator.py` | Pydantic 辨识联合：默认 variant / 缺字段报错 / extra 拒绝 / 参数替换 |
| `tests/unit/sources/test_gaussdb_driver_dispatch.py` | `_make_driver` 按 connection 类型分派 |
| `tests/unit/sources/test_gaussdb_jdbc_unit.py` | `_ensure_jvm` 幂等 / JAR 不存在报错 / URL 构建 / jaydebeapi 未装时提示安装 |

**关键用例**：
- `_ensure_jvm` 调用多次只 `startJVM` 一次
- 缺 JAR 报 `JDBC JAR 不存在` + 建议
- 缺 jaydebeapi 报 `pip install 'datacompare[gaussdb-t]'`
- URL properties 追加：`?loginTimeout=30&fetchSize=1000`（避免重复 `?`）
- Pydantic：`variant: t` 缺 `jdbc_url` 报字段必需；A 变体误写 `jdbc_url` 报 extra 拒绝

### 7.2 集成测试

**PostgresDriver 侧**（GaussDB A）：现有 `test_gaussdb.py` 保持不变 —— testcontainers PostgreSQL，Docker 未装时 skip。

**JdbcDriver 侧**：两层策略

**7.2.1 可离线跑的"JDBC 封装正确性"测试** ⭐ 推荐必做

- 使用 **PostgreSQL JDBC 驱动**（`postgresql-42.x.jar`，Apache 2.0）
- 连的是 testcontainers 起的 PostgreSQL
- 目的：验证 JayDeBeApi + JVM 生命周期 + `fetch_chunks` 封装正确性（不是 GaussDB T 特定行为）
- Skip 条件：Docker 未装 / jaydebeapi 未装 / JVM 不可用
- 文件：`tests/integration/sources/test_gaussdb_jdbc_via_postgres.py`

**7.2.2 可选的"真实 GaussDB T"手动集成测试**

- 用户环境有 GaussDB T 时可运行
- 环境变量激活：`GAUSSDB_T_TEST_URL / _JAR / _CLASS / _USER / _PWD`
- 环境变量未设置时整个模块 skip
- CI 默认 skip
- 文件：`tests/integration/sources/test_gaussdb_t_real.py`

### 7.3 覆盖率目标

- Pydantic 模型 + 分派逻辑：**100%**
- JdbcDriver（不含实际 JDBC 调用）：**≥ 90%**
- JayDeBeApi 封装（通过 PG JDBC 集成测试）：路径 parity

---

## 8. 迁移路径（零破坏升级）

四个独立提交，每步可独立测试与 revert：

1. **配置模型改造**：`GaussDBAConnection` + `GaussDBTConnection` + discriminated union；`GaussDBConnection` 名字保留但改为联合类型 `GaussDBAConnection | GaussDBTConnection`（`runner.py:27` 的 `isinstance(conn, GaussDBConnection)` 在 Python 3.10+ 下继续工作）；`tests/integration/sources/test_gaussdb.py:43` 的构造器调用改为 `GaussDBAConnection(...)`
2. **Driver 抽象引入**：`GaussDBDriver` 基类 + `PostgresDriver`；`GaussDBSource._make_driver` 分派
3. **JdbcDriver 落地**：`sources/gaussdb_jdbc.py` + `[gaussdb-t]` optional dep + 单元测试 + PG JDBC 集成测试
4. **文档更新**：README / CLAUDE / user-guide / init 模板

**每步保证**：现有 psycopg2 集成测试 skip-when-no-Docker 行为不变；现有 `test_models.py` 全部通过。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| JDBC driver class 名与 URL 格式因 GaussDB T 版本不同 | `jdbc_driver_class` 和 `jdbc_url` 均必需 + 用户显式提供；不做智能猜测；错误消息明确指引从 Data Studio 复制 |
| JPype 与某些 Java 版本组合兼容问题 | 首次 `startJVM()` 失败时输出 JRE 版本、JPype 版本、jvm.dll 路径；文档建议 JRE 11 LTS |
| `gsjdbc4.jar` 华为专属无法分发 | 文档说明"必须从华为支持网站自行下载"；`_ensure_jvm` 对 JAR 不存在报友好错误 |
| JVM 常驻 ~150MB 内存 | 只有 variant=t 才启 JVM；文档说明 |
| `setFetchSize` 不是所有 driver 都尊重 | best-effort + `try/except` 忽略；文档提醒大数据加 `WHERE` 缩小结果集 |
| JayDeBeApi cursor 关闭异常路径可能泄漏 | `try/finally` 严格关闭；`GaussDBSource.close()` 在 `runner.execute()` 的 `finally` 里被调用 |
| `WHERE 1=0` 在 T 上万一不通用 | fallback：先 `WHERE 1=0` 失败再试 `LIMIT 0`，都失败报错 |
| JDBC URL 里明文密码可能进日志 | 扩展 `mask_password()` 匹配 `jdbc:...password=xxx` 和 `jdbc:...://user:xxx@`；单元测试覆盖 |

---

## 10. MVP 范围（v0.2）

### 10.1 包含

- ✅ Pydantic 辨识联合（`GaussDBAConnection` / `GaussDBTConnection`）
- ✅ `GaussDBDriver` 抽象 + `PostgresDriver`（重构）+ `JdbcDriver`（新增）
- ✅ JVM 进程级懒加载单例
- ✅ JAR 存在性检查 + jaydebeapi 未装的友好错误
- ✅ `jdbc_properties` 追加到 URL
- ✅ `WHERE 1=0` 替代 `LIMIT 0`（T 侧兼容） + 失败 fallback 到 `LIMIT 0`
- ✅ 日志脱敏扩展到 JDBC URL
- ✅ 单元测试 + "通过 PG JDBC 验证 JayDeBeApi"集成测试
- ✅ optional dependency `[gaussdb-t]`
- ✅ README / CLAUDE.md / user-guide 更新
- ✅ `datacompare init excel-vs-gaussdb-t` 新模板

### 10.2 不做（YAGNI）

- ❌ 内置 driver class 名候选表（智能猜测）
- ❌ 自动下载 gsjdbc4.jar（License + 故障面）
- ❌ 华为专有认证（Kerberos / SM3 / SM4）
- ❌ 连接池
- ❌ 多 JAR classpath（首版单 JAR，若反馈需要再扩展成 `jdbc_jar_paths: list[str]`）

### 10.3 后续演进（非本次）

- v0.3：`OpenGaussLibpqDriver`（覆盖 openGauss 独有行为）
- v0.4：JDBC 驱动池化（若 datacompare 未来变常驻服务）
- v0.5：华为专有认证支持

---

## 附录 A · 与原始设计（v0.1）的差异

原始设计（`2026-07-13-data-comparator-design.md`）§7.3 说 "GaussDBSource 使用 psycopg2 连接（GaussDB 兼容 PostgreSQL 协议）"。本设计将其**分为两个变体**并抽象出 `GaussDBDriver`：

- 原假设"GaussDB 都兼容 PG 协议"**只对 GaussDB A / DWS 成立**；GaussDB T 走 JDBC。
- 本次改造是原设计 §14 迭代路线里 "v0.2 — 补充数据库驱动抽象层" 的自然演进 —— 只不过第一个新增的不是 MySQL，而是同为 GaussDB 家族的 T 变体。
- `GaussDBConnection` 由具体类变为 discriminated union；旧名保留为 `GaussDBAConnection` 的别名，保证向后兼容。
