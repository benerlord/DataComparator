# DataComparator 设计文档

- **日期**：2026-07-13
- **作者**：项目组
- **状态**：设计定稿，待实现
- **相关文件**：无（新项目）

---

## 1. 背景与目标

### 1.1 问题

日常业务中经常需要核对 **Excel 表格** 或 **API 响应** 与 **数据库（GaussDB）** 中的数据是否一致。目前只能人工比对或写一次性脚本，重复劳动多、可维护性差、易出错。

### 1.2 目标

构建一个**通用的数据比对 CLI 工具**——通过 YAML 配置任务，可比对以下三种数据源之间**任意两两**的一致性：

- Excel 文件（`.xlsx` / `.xls`）
- GaussDB 数据库
- HTTP API 响应

### 1.3 非目标（明确不做）

- Web UI / 桌面 GUI
- 除 GaussDB 外的其他数据库（架构预留，但 v1 不落地）
- NoSQL 数据源
- 任务调度、历史管理、通知——由用户用外部工具（cron / Airflow）编排
- 多任务并发执行
- 无主键的集合比对

---

## 2. 需求规格

### 2.1 数据源与配对

| 数据源类型 | v1 支持 | 说明 |
|---|---|---|
| Excel | ✅ | 多 sheet 可选、表头行可配、强制字符串读取 |
| GaussDB | ✅ | 兼容 PostgreSQL 协议，psycopg2 连接 |
| HTTP API | ✅ | 三种认证 + 三种分页 + JSONPath 提取 |
| 其他 RDBMS | ❌ | 架构预留（Driver 抽象），后续版本添加 |

**配对方式**：任意两两配对（`Excel⟷GaussDB`、`API⟷GaussDB`、`Excel⟷API`、`Excel⟷Excel`、`API⟷API`）。

### 2.2 行匹配

- 支持**单键**和**复合键**
- 支持**两侧列名不同**（通过配置里的键映射）
- **键值不做归一化**（键一致才视为同一行）
- **单侧主键重复 = 配置错误**，任务失败并列出重复键

### 2.3 字段比对

- 参与比对的字段**由用户显式列出**（含两侧列名映射）
- 支持 `exclude` 显式排除
- 三种模式：`exact` / `numeric` / `string`
- 全局默认规则 + 字段级覆盖

**数值处理**：

- 保留 N 位小数（默认 2）—— 使用**四舍五入（`ROUND_HALF_UP`）**，不用 Python 内置银行家舍入
- 两侧各自 round 后精确比较
- 支持从字符串解析数值 + 单位（如 `"30 TB"`），换算到统一单位后比较
- 内置四类单位：`storage`（B/KB/MB/GB/TB/PB）、`time`（ms/s/min/h/d）、`length`、`mass`

**字符串处理**：

- `ignore_whitespace`：`strip()` + 内部连续空白折叠
- `ignore_case`：`casefold()`
- `null_equivalents`：默认 `["", "null", "NULL", "NaN", "nan"]`，两侧归一化后同为 `None` 视为相等

### 2.4 数据规模

**混合规模**：小/中规模（< 50 万行/侧）走内存引擎；超过阈值自动降级到磁盘引擎（DuckDB）。

### 2.5 交付形态

CLI 命令行工具，YAML 配置驱动，无 GUI。

### 2.6 报告输出

一次任务可同时产出多种格式（用户在配置里勾选）：

| 格式 | 用途 |
|---|---|
| HTML | 面向人肉查看，含图表、可折叠明细 |
| Excel | 面向业务转发/复核，多 sheet + 条件格式高亮 |
| CSV | 面向再加工，分文件（`diff_details.csv` / `left_only.csv` / `right_only.csv` / `summary.csv`） |
| JSON | 面向集成告警，结构化输出 |
| Console | 面向终端，用 rich 渲染彩色摘要 |

---

## 3. 架构总览

### 3.1 分层架构

```
┌────────────────────────────────────────────────────┐
│  CLI 层 (Typer)                                     │
├────────────────────────────────────────────────────┤
│  配置层 (Pydantic 校验 YAML / 参数替换)               │
├────────────────────────────────────────────────────┤
│  DataSource 抽象层                                  │
│  ├── ExcelSource                                    │
│  ├── GaussDBSource                                  │
│  └── APISource                                      │
├────────────────────────────────────────────────────┤
│  归一化层（纯函数）                                   │
│  列名映射 → 字符串预处理 → 类型转换 → 单位换算 → 精度  │
├────────────────────────────────────────────────────┤
│  比对引擎（可插拔）                                   │
│  ├── InMemoryEngine (pandas)                        │
│  ├── DiskEngine (DuckDB)                            │
│  └── EngineRouter（自动路由）                        │
├────────────────────────────────────────────────────┤
│  报告层 (Reporter 抽象)                              │
│  ├── HTMLReporter                                   │
│  ├── ExcelReporter                                  │
│  ├── CSVReporter                                    │
│  ├── JSONReporter                                   │
│  └── ConsoleReporter                                │
└────────────────────────────────────────────────────┘
```

### 3.2 设计原则

1. **纯函数优先**：归一化层全部为可独立测试的纯函数
2. **接口隔离**：`DataSource` / `CompareEngine` / `Reporter` 三个抽象基类是三个扩展点
3. **配置即代码**：Pydantic 模型是 YAML 的单一真相源
4. **失败快**：配置在执行前完整校验，一次列出所有错误

---

## 4. 技术栈

| 角色 | 选型 | 理由 |
|---|---|---|
| Python | **3.11+** | `TypeAlias`, `Self`, 更快的 CPython |
| CLI 框架 | **Typer** | 基于 type hints，自动生成帮助 |
| 配置校验 | **Pydantic v2** | 强类型模型，字段级验证 |
| YAML 解析 | **ruamel.yaml** | 保留注释和顺序 |
| 表格（内存） | **pandas 2.x + pyarrow 后端** | 生态成熟；pyarrow 后端省内存 |
| 表格（磁盘） | **DuckDB** | 嵌入式，自动溢出磁盘 |
| GaussDB 驱动 | **psycopg2-binary** | GaussDB 兼容 PostgreSQL 协议 |
| Excel 读取 | **openpyxl**（xlsx）+ **xlrd**（xls） | openpyxl 支持强制字符串读 |
| Excel 报告写入 | **XlsxWriter** | 条件格式和图表表达力强 |
| HTTP | **httpx** | 现代、连接池、超时代理 |
| JSONPath | **jsonpath-ng** | 完整 JSONPath 语法 |
| HTML 模板 | **Jinja2** | 与 pandas 无缝配合 |
| 日志 | **structlog** | 结构化日志 |
| 敏感信息 | **os.environ + keyring**（可选） | YAML 里 `${ENV_VAR}` 引用 |
| 终端渲染 | **rich** | 彩色输出、进度条 |
| HTTP 重试 | **tenacity** | 仅对 5xx / 网络错误重试 |
| 测试 | **pytest + pytest-mock + respx + testcontainers + syrupy** | 分层测试 |
| 打包 | **uv + pyproject.toml** | 现代 Python 项目管理 |
| 代码质量 | **ruff + mypy** | lint + format + 类型检查 |

---

## 5. 项目结构

```
DataComparator/
├── pyproject.toml
├── uv.lock
├── README.md
├── src/
│   └── datacompare/
│       ├── __init__.py
│       ├── cli.py                    # Typer 入口: run/validate/init/version
│       │
│       ├── config/                   # 配置层
│       │   ├── models.py             # Pydantic 模型
│       │   ├── loader.py             # YAML → 模型 + 参数替换
│       │   └── credentials.py        # 环境变量 / keyring 解析
│       │
│       ├── sources/                  # DataSource 抽象与实现
│       │   ├── base.py               # DataSource 抽象基类
│       │   ├── excel.py
│       │   ├── gaussdb.py
│       │   ├── api.py
│       │   └── registry.py           # 类型 → 实现的注册表
│       │
│       ├── normalize/                # 归一化层（纯函数）
│       │   ├── columns.py            # 列名映射
│       │   ├── types.py              # 类型强制
│       │   ├── decimals.py           # 四舍五入
│       │   ├── units.py              # 单位换算 + 字符串解析
│       │   └── strings.py            # 空白/大小写/null 归一
│       │
│       ├── engine/                   # 比对引擎
│       │   ├── base.py
│       │   ├── memory.py             # InMemoryEngine
│       │   ├── disk.py               # DiskEngine
│       │   ├── router.py             # 引擎路由
│       │   └── result.py             # CompareResult 数据模型
│       │
│       ├── reporters/                # 报告层
│       │   ├── base.py
│       │   ├── html.py
│       │   ├── excel.py
│       │   ├── csv.py
│       │   ├── json.py
│       │   ├── console.py
│       │   └── templates/            # HTML/Excel 模板
│       │
│       └── utils/
│           ├── logging.py            # structlog 配置
│           └── progress.py           # rich 进度条
│
├── tests/                            # 与 src/ 对称
│   ├── unit/
│   ├── integration/
│   └── fixtures/                     # Excel/JSON/SQL 测试样本
│
├── examples/                         # 示例配置
│   ├── excel_vs_gaussdb.yaml
│   ├── api_vs_gaussdb.yaml
│   └── excel_vs_api.yaml
│
└── docs/
    ├── superpowers/specs/            # 设计文档
    └── user-guide.md
```

---

## 6. 配置文件模型

### 6.1 组织形式

- **任务配置**（可入库）：`./comparisons/xxx.yaml`
- **连接凭据配置**（含敏感字段，不入库）：`~/.datacompare/connections.yaml`
- **环境变量**：任何值都可用 `${ENV_VAR}` 引用

### 6.2 任务配置示例（Excel ⟷ GaussDB）

```yaml
name: 每日销售数据核对
description: 核对业务侧 Excel 与 DWS 层订单表的一致性

# ---------- 数据源 ----------
sources:
  left:
    type: excel
    path: ./data/sales_{{param.month}}.xlsx
    sheets:
      - name: 华北区
      - name: 华南区
      - index: 3
    header_row: 2
    force_string: true

  right:
    type: gaussdb
    connection: prod_dws
    query: |
      SELECT order_id, sku_code, region, amount, storage, order_time
      FROM dws.sales
      WHERE month = '{{param.month}}'

# ---------- 行匹配 ----------
match:
  keys:
    - left: 订单号
      right: order_id
    - left: SKU编码
      right: sku_code

# ---------- 字段级比对规则 ----------
compare:
  defaults:
    mode: exact
    ignore_whitespace: false
    ignore_case: false
    null_equivalents: ["", "null", "NULL", "NaN"]

  fields:
    - left: 金额
      right: amount
      mode: numeric
      decimal_places: 2

    - left: 存储容量
      right: storage
      mode: numeric
      parse_unit: true
      unit_category: storage
      normalize_to: GB

    - left: 区域
      right: region
      mode: string
      ignore_whitespace: true
      ignore_case: true

    - left: 下单时间
      right: order_time
      mode: exact
      as_type: datetime
      datetime_format: "%Y-%m-%d %H:%M:%S"

  exclude: [updated_at, etl_load_time]

# ---------- 输出 ----------
output:
  dir: ./reports/{{param.month}}
  formats:
    - html
    - excel
    - csv
    - json
    - console
  html:
    include_charts: true
  excel:
    highlight_diff_cells: true

# ---------- 执行参数 ----------
runtime:
  engine: auto
  memory_threshold_rows: 500000
  log_level: INFO
```

### 6.3 API 数据源配置

```yaml
sources:
  left:
    type: api
    connection: order_service
    method: GET
    url: /v1/orders
    params:
      month: "{{param.month}}"
      status: paid
    pagination:
      type: page
      page_param: pageNum
      size_param: pageSize
      size: 200
      total_path: $.data.total
    data_path: $.data.list[*]
    timeout: 30
    retry:
      max_attempts: 3
      backoff: 1.5
```

### 6.4 连接凭据配置

```yaml
# GaussDB
prod_dws:
  type: gaussdb
  host: 10.0.0.10
  port: 5432
  database: dws
  user: analytics_ro
  password: ${GAUSS_PROD_PWD}
  ssl: require

# API（Bearer）
order_service:
  type: api
  base_url: https://api.internal.company.com
  auth:
    kind: bearer
    token: ${ORDER_API_TOKEN}

# API（Cookie）
crm_api:
  type: api
  base_url: https://crm.internal.company.com
  auth:
    kind: cookie
    login_url: /auth/login
    login_method: POST
    login_body:
      username: ${CRM_USER}
      password: ${CRM_PWD}
    cookie_names: [SESSIONID, XSRF-TOKEN]
```

### 6.5 参数替换机制

三类占位符，按顺序解析：

| 占位符 | 来源 | 示例 |
|---|---|---|
| `${ENV_VAR}` | 系统环境变量 | `password: ${GAUSS_PROD_PWD}` |
| `{{param.xxx}}` | CLI `--param xxx=yyy` | `month: "{{param.month}}"` |
| `{{today}}` / `{{now}}` | 内置函数 | `date: "{{today}}"` |

### 6.6 Pydantic 模型骨架

```python
class SourceConfig(BaseModel):
    type: Literal["excel", "gaussdb", "api"]

class ExcelSourceConfig(SourceConfig):
    type: Literal["excel"] = "excel"
    path: str
    sheets: list[SheetSelector] = [SheetSelector(index=0)]
    header_row: int = 1
    force_string: bool = True

class FieldRule(BaseModel):
    """
    字段级规则。所有可覆盖属性用 `None` 表示"未指定，继承全局 defaults"；
    非 None 值表示"显式覆盖全局默认"。加载阶段会做 defaults 与 field 的合并。
    """
    left: str
    right: str
    mode: Literal["exact", "numeric", "string"] | None = None
    decimal_places: int | None = None
    parse_unit: bool | None = None
    unit_category: str | None = None
    normalize_to: str | None = None
    ignore_whitespace: bool | None = None
    ignore_case: bool | None = None
    null_equivalents: list[str] | None = None
    as_type: Literal["datetime", "int", "float", "string"] | None = None
    datetime_format: str | None = None

class CompareDefaults(BaseModel):
    """全局默认规则；作用于所有字段，可被 FieldRule 覆盖。"""
    mode: Literal["exact", "numeric", "string"] = "exact"
    ignore_whitespace: bool = False
    ignore_case: bool = False
    null_equivalents: list[str] = ["", "null", "NULL", "NaN", "nan"]

class TaskConfig(BaseModel):
    name: str
    description: str = ""
    sources: dict[Literal["left", "right"], SourceConfig]
    match: MatchConfig
    compare: CompareConfig
    output: OutputConfig
    runtime: RuntimeConfig = RuntimeConfig()
```

### 6.7 凭据安全设计

- **禁止**在 task 配置里写明文密码/token；写了报错并引导用户挪到凭据文件
- **凭据文件权限检查**：文件权限过宽（Windows 可读、Unix world-readable）时告警
- **日志脱敏**：所有连接串在日志中自动打码（`password=***`）

---

## 7. DataSource 抽象与实现

### 7.1 抽象基类

```python
class DataSource(ABC):
    """所有数据源的统一契约。"""

    name: str  # 用于日志/报告标识（'left' / 'right'）

    @abstractmethod
    def columns(self) -> list[str]:
        """返回列名列表；用于配置校验（键/字段是否存在）。"""

    @abstractmethod
    def estimated_rows(self) -> int | None:
        """估算行数；None 表示不确定。用于引擎路由决策。"""

    @abstractmethod
    def read(self, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        """流式返回 DataFrame 分块。所有列默认为字符串类型；
        类型转换发生在归一化层。"""

    def close(self) -> None:
        """释放连接/文件句柄。默认空实现。"""
```

**为什么统一返回字符串**：Excel 侧要求 force_string；对齐三种数据源避免自动类型推断歧义；类型转换由用户配置驱动，可预测、可测试。

### 7.2 ExcelSource

- `openpyxl` `read_only=True` 模式，避免大文件全部加载
- 多 sheet：逐 sheet 读取后 concat，加隐藏列 `__sheet__` 用于报告定位（不参与比对）
- 表头行可配（默认 1）
- 多 sheet 表头不一致直接报错并列出差异

### 7.3 GaussDBSource

- `psycopg2` 连接（GaussDB 兼容 PostgreSQL 协议）
- SQL 由用户完整编写
- 服务器端游标（named cursor）+ `fetchmany` 分块拉取
- 列名探测：`SELECT * FROM (user_query) t LIMIT 0`
- 行数估算：`SELECT COUNT(*) FROM (user_query) t`
- SSL 默认 `require`
- **只支持 SELECT**：游标层白名单拒绝写操作

### 7.4 APISource

- `httpx.Client` 复用连接
- 认证：`none` / `bearer` / `cookie`（cookie 模式先登录取 cookie）
- 分页：三种独立迭代器（`PagePaginator` / `OffsetPaginator` / `CursorPaginator`）
- 数据提取：`jsonpath-ng` 完整 JSONPath 语法
- 参数化：URL、参数支持 `{{param}}` / `{{today}}`
- 重试：`tenacity` 仅对 5xx 和网络错误重试，不对 4xx 重试
- 列名探测：拉一小页样本，取首条记录的 keys

### 7.5 注册表（扩展点）

```python
SOURCE_REGISTRY: dict[str, type[DataSource]] = {}

def register_source(type_name: str):
    def _decorator(cls):
        SOURCE_REGISTRY[type_name] = cls
        return cls
    return _decorator

@register_source("excel")
class ExcelSource(DataSource): ...

@register_source("gaussdb")
class GaussDBSource(DataSource): ...

@register_source("api")
class APISource(DataSource): ...
```

未来加 MySQL：只需实现 `MySQLSource` 并注册，核心代码不改。

---

## 8. 归一化层

### 8.1 管线顺序

每个字段按以下**固定顺序**处理：

```
原始字符串
    ↓
① 列名映射    → 两侧列名统一（默认取 right 侧名）
    ↓
② 字段选择    → 只保留 keys ∪ compare.fields，其余丢弃
    ↓
③ 字符串预处理 → 去空白 / 大小写 / null 等价
    ↓
④ 类型转换    → str → int/float/datetime
    ↓
⑤ 单位换算    → 解析 "30 TB" → 数值 30720
    ↓
⑥ 数值精度    → round_half_up(N)
    ↓
可比较的规范化 DataFrame
```

### 8.2 字符串预处理

```python
def normalize_string(
    s: str,
    ignore_whitespace: bool = False,
    ignore_case: bool = False,
    null_equivalents: list[str] = [],
) -> str | None:
    if s in null_equivalents or s is None:
        return None
    if ignore_whitespace:
        s = re.sub(r"\s+", " ", s.strip())
    if ignore_case:
        s = s.casefold()
    return s
```

### 8.3 类型转换（失败不阻塞）

```python
def coerce_type(
    s: str | None,
    as_type: Literal["datetime", "int", "float", "string"] | None,
    datetime_format: str | None = None,
) -> Any:
    if s is None:
        return None
    if as_type is None:
        return s
    try:
        match as_type:
            case "int":      return int(s)
            case "float":    return float(s)
            case "datetime": return datetime.strptime(s, datetime_format) if datetime_format \
                                    else dateutil.parser.parse(s)
            case "string":   return s
    except (ValueError, TypeError):
        return _CoerceError(original=s, target=as_type)
```

**关键决定**：类型转换失败不抛异常，返回哨兵值。引擎将其记为 `type_error` 差异；不因一行坏数据整个任务失败。

### 8.4 单位换算（内置四类）

```python
UNIT_TABLES = {
    "storage": {   # 基准 = B
        "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3,
        "TB": 1024**4, "PB": 1024**5,
    },
    "time": {      # 基准 = ms
        "ms": 1, "s": 1_000, "min": 60_000,
        "h": 3_600_000, "d": 86_400_000,
    },
    "length": {"mm": 1, "cm": 10, "m": 1_000, "km": 1_000_000},
    "mass":   {"mg": 1, "g": 1_000, "kg": 1_000_000, "t": 1_000_000_000},
}

_UNIT_PATTERN = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z]+)\s*$"
)

def parse_and_convert(s: str, category: str, target_unit: str) -> float | _UnitError:
    m = _UNIT_PATTERN.match(s)
    if not m:
        return _UnitError(original=s, reason="no_unit_pattern")
    value, unit = float(m.group(1)), m.group(2)
    table = UNIT_TABLES.get(category)
    if table is None:
        return _UnitError(original=s, reason="unknown_category")
    # 大小写不敏感查找：把表键与传入单位都规范化到小写
    lookup = {k.lower(): v for k, v in table.items()}
    if unit.lower() not in lookup or target_unit.lower() not in lookup:
        return _UnitError(original=s, reason="unknown_unit")
    return value * lookup[unit.lower()] / lookup[target_unit.lower()]
```

单位匹配默认大小写不敏感（`"tb" == "TB"`）；解析失败返回哨兵值（`_UnitError`）。

### 8.5 数值精度（四舍五入）

```python
def round_half_up(x: float, places: int) -> float:
    q = Decimal(10) ** -places
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))
```

**关键决定**：用 `Decimal.quantize(ROUND_HALF_UP)`。Python 内置 `round()` 是银行家舍入，业务比对会出问题（`round(0.5)==0`）。

---

## 9. 比对引擎

### 9.1 抽象基类

```python
class CompareEngine(ABC):
    @abstractmethod
    def compare(
        self,
        left: DataSource,
        right: DataSource,
        task: TaskConfig,
    ) -> CompareResult: ...
```

### 9.2 CompareResult 数据模型

```python
@dataclass
class CompareResult:
    task_name: str
    left_name: str
    right_name: str

    # 概要统计
    left_total: int
    right_total: int
    matched_rows: int
    identical_rows: int
    diff_rows: int
    left_only: int
    right_only: int

    # 明细
    diff_details: pd.DataFrame        # 列：keys... | field | left_value | right_value | diff_type
    left_only_rows: pd.DataFrame
    right_only_rows: pd.DataFrame

    # 元信息
    engine_used: str                  # "memory" | "disk"
    duration_seconds: float
    errors: list[FieldError]
```

`diff_type` 枚举：`value_mismatch` / `type_error` / `unit_error` / `null_mismatch`。

### 9.3 InMemoryEngine（pandas）

**算法**：

1. 全量加载（chunk 拼接）为两个 DataFrame
2. 分别归一化（管线 §8.1）
3. 主键 `outer join`，`indicator=True` 标识匹配来源
4. 分类：`both` / `left_only` / `right_only`
5. 逐字段**向量化判等**（数值型 `l != r`；字符串型 `l != r`；哨兵值和 None 特殊处理）
6. 装配 `CompareResult`

**优化**：向量化判等（避免 `.apply` 逐行），归一化用 `.pipe()` 链式。

### 9.4 DiskEngine（DuckDB）

**流程**：

1. 流式加载 + 归一化 → 建 DuckDB 表（`left_t`、`right_t`）
2. SQL `FULL OUTER JOIN` 计算 `joined` 表，含 `match_type` 列
3. UNPIVOT 各字段差异到 `diff_details` 表
4. 组装 `CompareResult`

**为什么归一化仍在 Python 层**：单位解析、类型强制、`Decimal` 精度用 SQL 表达复杂且方言相关；Python 层做归一化，DuckDB 只负责规模庞大的 JOIN。

### 9.5 引擎路由

```python
def select_engine(left, right, task) -> CompareEngine:
    if task.runtime.engine == "memory":
        return InMemoryEngine(task)
    if task.runtime.engine == "disk":
        return DiskEngine(task)

    # auto
    threshold = task.runtime.memory_threshold_rows
    lrows = left.estimated_rows()
    rrows = right.estimated_rows()
    max_rows = max(
        lrows if lrows is not None else threshold + 1,
        rrows if rrows is not None else threshold + 1,
    )
    return InMemoryEngine(task) if max_rows <= threshold else DiskEngine(task)
```

**关键决定**：行数无法估算时（API 无 total）默认走磁盘引擎——宁可保守也不能内存爆掉。

### 9.6 判等语义（写死规则）

| 场景 | 判定 |
|---|---|
| `None == None` | 相等 |
| `None ≠ "x"` | 不相等（`null_mismatch`） |
| 数值型 + `decimal_places=N` | `round_half_up(l, N) == round_half_up(r, N)` |
| 字符串带单位 + `parse_unit` | 解析换算后按数值比较，再按 `decimal_places` 或精确比 |
| 类型转换失败 | 记为 `type_error`，两侧值都保留原始字符串 |
| 单位解析失败 | 记为 `unit_error` |
| 单侧主键重复 | 任务失败，列出重复键 |

---

## 10. 报告层

### 10.1 Reporter 抽象

```python
class Reporter(ABC):
    def __init__(self, config: ReporterConfig, output_dir: Path):
        self.config = config
        self.output_dir = output_dir

    @abstractmethod
    def render(self, result: CompareResult) -> Path | None:
        """产出报告；返回文件路径（终端类型返回 None）。"""
```

### 10.2 HTMLReporter

单文件 HTML（内联所有 CSS/JS，可离线打开）。

**结构**：
1. 顶部摘要卡片：任务名、执行时间、两侧数据源、总耗时、引擎
2. 关键指标区：匹配率 / 差异行数 / 左侧独有 / 右侧独有 / 字段错误数
3. 图表（可开关）：匹配状态饼图 + 各字段差异计数柱状图
4. 字段差异明细表（DataTables 前端分页，差异类型颜色区分）
5. 左侧独有 / 右侧独有：折叠区，各显示前 500 行
6. 配置回显：任务 YAML 只读展示

### 10.3 ExcelReporter

多 sheet `.xlsx`（XlsxWriter）：

| Sheet 名 | 内容 |
|---|---|
| `摘要` | 指标 + 内嵌图表 |
| `字段差异` | 主键 / 字段 / 左值 / 右值 / 差异类型；条件格式高亮 |
| `左侧独有` | 完整行 |
| `右侧独有` | 完整行 |
| `配置` | 任务 YAML 文本 |

### 10.4 CSVReporter

一个目录多个 CSV：
- `diff_details.csv`
- `left_only.csv`
- `right_only.csv`
- `summary.csv`

不合并，因为三类数据列结构不同。

### 10.5 JSONReporter

单文件 JSON，结构对齐 `CompareResult`。

大数据保护：`diff_details` / `left_only` / `right_only` 超过阈值（默认 10000 条）时截断，顶层加 `"truncated": true`。

### 10.6 ConsoleReporter

用 rich 渲染彩色摘要，不写文件。

---

## 11. CLI 接口

### 11.1 子命令

```
datacompare [OPTIONS] COMMAND [ARGS]

Commands:
  run       执行比对任务
  validate  校验配置文件（不执行）
  init      生成配置模板
  version   显示版本
```

### 11.2 `run` 命令

```
datacompare run TASK_FILE [OPTIONS]

Options:
  --connections PATH            凭据文件路径 [default: ~/.datacompare/connections.yaml]
  --param KEY=VALUE             任务参数（可多次）
  --output-dir PATH             覆盖输出目录
  --format TEXT                 覆盖输出格式（可多次）
  --engine [auto|memory|disk]   覆盖引擎选择
  --log-level [DEBUG|INFO|WARN|ERROR]
  --log-file PATH               日志额外输出到文件（JSON Lines）
  --dry-run                     完整校验但不执行
  --fail-on-diff                发现差异时退出码非 0（CI 集成用）
```

### 11.3 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功（无差异，或未指定 `--fail-on-diff`） |
| `1` | 配置校验失败 |
| `2` | 数据源连接/读取失败 |
| `3` | 内部错误 |
| `10` | 成功但发现差异且指定了 `--fail-on-diff` |

### 11.4 `validate` 命令

1. Pydantic 校验任务和凭据配置
2. 尝试连接每个数据源（不读数据）：Excel 打开验证、GaussDB `SELECT 1`、API HEAD/OPTIONS 探测
3. 探测两侧列名，校验 `match.keys` 和 `compare.fields` 引用的列都存在
4. 输出配置解析结果与检查清单

### 11.5 `init` 命令

生成带注释的完整 YAML 模板：

```bash
datacompare init excel-vs-gaussdb > task.yaml
datacompare init api-vs-gaussdb   > task.yaml
```

### 11.6 日志与进度

- **日志**：structlog 结构化，默认终端；`--log-file` 输出到 JSON Lines 便于机器解析
- **进度条**：rich Progress，三阶段（加载左侧 / 加载右侧 / 比对中）
- **静默模式**：`--log-level ERROR` 适合定时任务

### 11.7 错误信息友好化

`ConfigError` 统一封装，携带 `path`（错在配置的哪个字段）和 `suggestion`（可能的候选）：

```
❌ 配置错误 · match.keys[0].right
    右侧数据源 (gaussdb: prod_dws) 中不存在列 'order_id'。
    右侧可用列: order_no, order_time, sku_code, amount, region, updated_at
    提示: 您是否想用 'order_no'？
```

---

## 12. 测试策略

### 12.1 分层测试

| 层 | 类型 | 工具 |
|---|---|---|
| 归一化 | 单元（重点） | pytest 参数化 |
| 数据源 | 单元 + 集成 | pytest-mock, respx, testcontainers |
| 引擎 | 集成 | pytest |
| 报告 | 快照 | pytest + syrupy |
| CLI | 端到端 | typer.testing.CliRunner |

### 12.2 关键测试用例

1. 单位换算对称性：`30 TB → GB = 30720`，反向相等
2. 四舍五入：`round_half_up(2.5, 0) == 3`（不是 2）
3. null 等价矩阵：11 组两侧 null 表示互相判等
4. 主键在两侧列名不同：join 后统计正确
5. 单侧主键重复：任务失败，错误信息列出重复键
6. API 三种分页：mock 响应验证 page / offset / cursor 都能完整拉完
7. API cookie 认证：login → 拿 cookie → 后续请求自动带 cookie
8. JSONPath 提取：`$.data.list[*]` 从嵌套结构正确提取
9. 引擎路由：超阈值走 Disk；无法估算走 Disk；强制指定优先
10. **两个引擎结果等价**：同一份 fixture，`InMemory` 与 `Disk` 的 `CompareResult`（除 `engine_used`、`duration_seconds` 外）字段完全一致
11. Excel 多 sheet 表头不一致：任务失败，标出哪个 sheet 哪一列不对
12. 类型转换失败不阻塞：`"N/A"` 只在 `errors` 中出现
13. 参数替换：`{{param.month}}` / `${ENV}` / `{{today}}` 三类正确解析
14. CLI `validate` 干跑：连接失败时精准报告哪个数据源连不上
15. 退出码语义：无差异 → 0；有差异 + `--fail-on-diff` → 10；配置错 → 1

### 12.3 测试 fixture

- `sales_left.xlsx` 300 行，含各种边界值
- `sales_right.json` 对应的 DB 导出快照
- `api_responses/` 各种分页/认证响应快照
- GaussDB 集成测试：testcontainers 起 openGauss 或 PostgreSQL 兼容镜像

**测试可完全离线运行**。

### 12.4 质量指标

- 单元测试覆盖率 ≥ 90%（归一化、配置层）
- 集成测试覆盖率 ≥ 75%（数据源、引擎、报告）
- 关键路径 100%（CLI 主命令、退出码、错误提示）
- CI：ruff → mypy → pytest（含 coverage）

---

## 13. MVP 范围（v0.1）

### 13.1 包含

- 三种数据源（Excel / GaussDB / API），任意两两配对
- 复合主键 + 两侧列名映射
- 字段级比对规则（`exact` / `numeric` / `string`），全局默认 + 字段级覆盖
- 数值精度（N 位小数四舍五入，默认 2）
- 字符串带单位解析（内置 storage / time / length / mass）
- 双引擎自动路由（memory / disk）
- 五种报告器（HTML / Excel / CSV / JSON / Console）
- CLI 四个子命令（run / validate / init / version）
- 凭据独立文件 + 环境变量 + 参数替换
- 结构化日志 + rich 进度条
- Excel 多 sheet 选择 + 强制字符串读 + 表头行可配
- API 三种认证（none / bearer / cookie）+ 三种分页（page / offset / cursor）+ JSONPath

### 13.2 明确不做

- 其他数据库（MySQL / Postgres / Oracle 等）
- NoSQL 数据源
- OAuth2 / 自定义签名认证
- 用户自定义单位表
- 用户自定义比对函数（Python 钩子）
- 调度和历史管理
- 邮件 / IM 通知
- Web UI / 桌面 GUI
- 多任务并发执行
- 配置文件里内嵌 Python 代码或复杂模板逻辑
- 两侧同为无主键的集合比对

---

## 14. 迭代路线图

| 版本 | 时间 | 内容 |
|---|---|---|
| **v0.1 (MVP)** | 初次交付 | §13.1 范围 |
| **v0.2** | +2 周 | Driver 抽象层，加 MySQL / PostgreSQL；OAuth2 认证 |
| **v0.3** | +1 月 | 用户自定义单位表；字段级自定义 Python 表达式（受限沙箱） |
| **v0.4** | +2 月 | 无主键的集合比对模式 |
| **v1.0** | +3 月 | 性能优化；文档站点；插件机制（`entry_points`） |

**触发升级信号**：用户频繁手写包装脚本 → 补齐命令；多环境同配置需求 → 加环境 profile；大量 `--param` → 引入默认值和校验；报告文件过大 → 分片/按需加载。

---

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| GaussDB 特有 SQL 与 PostgreSQL 兼容层差异 | v1 只走 psycopg2 + 用户自写 SQL；不做 ORM；驱动层预留 Driver 抽象 |
| Excel "看似数字实为字符串"（`'0001'`） | `force_string` 默认开启；用户指定 `as_type` 才转 |
| API 单页超大导致内存爆炸 | 分页迭代器 buffer 累积到 `chunk_size` 后 flush |
| DuckDB 版本升级 SQL 行为变化 | 版本锁；每次升级跑"引擎等价性"测试套件 |
| 用户在生产环境误跑到写库 | 只允许 SELECT，游标层白名单拒绝改写 |
| 凭据泄露（提交 Git、日志明文） | 任务配置里明文密码字段直接报错；日志过滤器强制脱敏 |
| 归一化管线顺序错导致误判 | 顺序作为单元测试固化行为；重要顺序在代码注释和文档明确 |

---

## 16. 实现里程碑（供 plan 使用）

推荐顺序，每个里程碑可独立跑测试：

1. **骨架 + 配置层**：pyproject / 项目结构 / Pydantic 模型 / YAML 加载 / `validate` 命令
2. **归一化层（纯函数）**：`strings` / `types` / `decimals` / `units`；配套单元测试
3. **Excel + GaussDB 数据源**：先落地这两种
4. **InMemoryEngine + Console/JSON Reporter**：端到端最小闭环
5. **API 数据源**（含三种分页 + 三种认证）
6. **HTML / Excel / CSV Reporter**
7. **DiskEngine + 引擎路由**
8. **CLI 完整化**：`run` / `init` / `validate` 打磨、进度条、错误友好化
9. **端到端测试套件 + 文档 + 示例配置**

---

## 附录 A · 判等语义完整规则表

| 场景 | 判定 | 差异类型 |
|---|---|---|
| 两侧原始值都 ∈ `null_equivalents` | 相等 | — |
| 一侧 ∈ `null_equivalents`，另一侧非空 | 不相等 | `null_mismatch` |
| 两侧都是字符串，`mode=exact` 且未开归一化 | 字节比较 | `value_mismatch` |
| 两侧都是字符串，`mode=string` 开归一化 | 归一化后比较 | `value_mismatch` |
| 两侧都是数字，`mode=numeric` + `decimal_places=N` | `round_half_up(l,N) == round_half_up(r,N)` | `value_mismatch` |
| 两侧带单位字符串 + `parse_unit=true` | 解析换算到 `normalize_to`，按数值判等 | `value_mismatch` 或 `unit_error` |
| 任一侧类型转换失败 | 记为错误，值原样保留 | `type_error` |
| 任一侧单位解析失败 | 记为错误，值原样保留 | `unit_error` |
| 主键在单侧内部重复 | 任务失败，不进比对 | — |
