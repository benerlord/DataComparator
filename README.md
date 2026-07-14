# DataComparator

一个通用的**数据一致性比对 CLI 工具**：通过 YAML 配置驱动，可以比对 **Excel 文件、GaussDB 数据库、HTTP API 响应** 之间任意两两的数据是否一致，一次运行生成 HTML / Excel / CSV / JSON / 终端多种格式的差异报告。

## 目录

- [项目介绍](#项目介绍)
- [安装](#安装)
- [快速开始](#快速开始)
- [如何使用](#如何使用)
- [常见操作](#常见操作)
- [日志与报错排查](#日志与报错排查)
- [命令一览](#命令一览)
- [更多文档](#更多文档)

---

## 项目介绍

### 解决什么问题

业务里经常需要"核对两份数据是否一致"：
- 业务同事发来的 Excel 是不是和数据库里的记录一致？
- 上游接口返回的数据和数仓落库的数据是不是对得上？
- 迁移前后的表数据是不是完全对得上？

以往通常靠人工肉眼比对、临时写脚本，重复劳动多且容易出错。DataComparator 把这类核对场景标准化：**一份 YAML 描述比对任务，一条命令跑完，一份结构化报告输出**。

### 核心能力

| 能力 | 说明 |
|---|---|
| 三种数据源 | Excel（`.xlsx` / `.xls`）、GaussDB、HTTP API（三种认证 × 三种分页 + JSONPath 提取） |
| 任意两两配对 | Excel ⟷ DB / Excel ⟷ API / API ⟷ DB / Excel ⟷ Excel 都可以 |
| 复合主键 + 两侧异名映射 | 左侧列叫"订单号"、右侧叫 `order_id`，配置里做映射 |
| 字段级比对规则 | 精确 / 数值容差 / 字符串归一，全局默认 + 字段级覆盖 |
| 数值处理 | 保留 N 位小数四舍五入（`ROUND_HALF_UP`）、从字符串解析单位（如 `"30 TB"` → GB） |
| 数据规模自适应 | 小/中量走内存 pandas，超过阈值自动切换 DuckDB 磁盘引擎 |
| 五种报告 | HTML（图表+分页表）、Excel（多 sheet + 高亮）、CSV（分文件）、JSON（结构化）、终端（rich 彩色） |
| CI/CD 友好 | 明确的退出码语义（`--fail-on-diff` 差异非零退出）、`--dry-run` 干跑校验、JSONL 结构化日志 |

### 架构分层

```
CLI (Typer)
   ↓
Config (Pydantic + YAML)
   ↓
DataSource 抽象 → Excel / GaussDB / API
   ↓
Normalize（纯函数）: 列名映射 → 字符串预处理 → 单位换算 → 类型转换 → 数值精度
   ↓
Engine（可插拔）: InMemoryEngine / DiskEngine + 自动路由
   ↓
Reporter（可插拔）: HTML / Excel / CSV / JSON / Console
```

---

## 安装

### 环境要求

- **Python 3.11+**（必需——代码使用 `X | Y` 联合类型和 `match/case`）
- Windows / macOS / Linux 均可
- 可选：Docker Desktop（仅在跑 GaussDB 集成测试时需要）

### 安装步骤

Windows / git-bash：
```bash
# 用 Python 3.11 建虚拟环境
py -3.11 -m venv .venv

# 激活并安装
.venv/Scripts/pip install -e ".[dev]"

# 验证
.venv/Scripts/python -m datacompare.cli version
# 输出: datacompare 0.1.0
```

macOS / Linux：
```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m datacompare.cli version
```

---

## 快速开始

### 5 分钟跑通第一个比对

**步骤 1**：生成一个任务模板
```bash
datacompare init excel-vs-gaussdb > task.yaml
```

**步骤 2**：**手动创建**连接凭据文件（这个文件**不随项目分发**，需要自己新建，**不要提交到 Git**）

先建好父目录：
```bash
# Linux / macOS / git-bash
mkdir -p ~/.datacompare

# Windows CMD
mkdir "%USERPROFILE%\.datacompare"

# Windows PowerShell
New-Item -ItemType Directory -Force -Path "$HOME\.datacompare"
```

然后创建 `~/.datacompare/connections.yaml`，写入你的连接信息：
```yaml
prod_dws:
  type: gaussdb
  host: 10.0.0.10
  port: 5432
  database: dws
  user: analytics_ro
  password: ${GAUSS_PROD_PWD}   # 从环境变量读，避免明文
  ssl: require
```

> 提示：路径完全自定义，也可以放在别处（如 `./secrets/conn.yaml`），运行时用 `--connections /your/path.yaml` 指定即可。默认路径只是约定俗成的位置。

**步骤 3**：把密码放到环境变量
```bash
export GAUSS_PROD_PWD='your_password'      # Linux/macOS
# 或
set GAUSS_PROD_PWD=your_password           # Windows CMD
$env:GAUSS_PROD_PWD='your_password'        # Windows PowerShell
```

**步骤 4**：编辑 `task.yaml`，把 `sources`、`match`、`compare` 部分改成你的实际字段（模板里带完整注释）

**步骤 5**：先做一次干跑校验，确认配置和连接都 OK
```bash
datacompare validate task.yaml --connections ~/.datacompare/connections.yaml
```

**步骤 6**：执行比对
```bash
datacompare run task.yaml \
  --connections ~/.datacompare/connections.yaml \
  --param month=2026-07
```

**步骤 7**：查看报告（默认输出到 `./reports/{{param.month}}/`）
- `report.html` — 浏览器打开，可视化差异表
- `report.xlsx` — 发给业务同事复核
- `report.json` — 集成到告警系统
- `csv/` — 分文件的差异明细，便于再加工

---

## 如何使用

### 配置文件的组织方式

**两类 YAML，职责分离**：

| 文件 | 内容 | 是否入库 |
|---|---|---|
| `task.yaml` | 任务描述（数据源、字段映射、比对规则、输出配置） | ✅ 可入 Git |
| `~/.datacompare/connections.yaml` | 数据库/API 的连接信息（含密码、token） | ❌ 不入 Git |

### task.yaml 结构

```yaml
name: 每日销售数据核对
description: 核对业务侧 Excel 与 DWS 层订单表

# 1. 数据源：left / right 各选一种
sources:
  left:
    type: excel
    path: ./data/sales_{{param.month}}.xlsx
    sheets:                    # 可选多个 sheet
      - name: 华北区
      - name: 华南区
    header_row: 1              # 表头所在行（默认 1）
    force_string: true         # Excel 单元格统一按字符串读

  right:
    type: gaussdb
    connection: prod_dws       # 引用 connections.yaml 里的条目
    query: |
      SELECT order_id, sku_code, region, amount, storage, order_time
      FROM dws.sales
      WHERE month = '{{param.month}}'

# 2. 行匹配：单键或复合键，两侧列名可映射
match:
  keys:
    - left: 订单号
      right: order_id
    - left: SKU编码
      right: sku_code

# 3. 字段比对规则：全局默认 + 字段级覆盖
compare:
  defaults:
    mode: exact
    null_equivalents: ["", "null", "NULL", "NaN", "nan"]

  fields:
    - left: 金额
      right: amount
      mode: numeric
      decimal_places: 2         # 双方各 round(2) 后精确比

    - left: 存储容量
      right: storage
      mode: numeric
      parse_unit: true          # 从字符串解析 "30 TB"
      unit_category: storage    # 内置类别: storage / time / length / mass
      normalize_to: GB          # 换算到 GB 再比

    - left: 区域
      right: region
      mode: string
      ignore_whitespace: true
      ignore_case: true

  exclude: [updated_at, etl_load_time]   # 显式排除这些列

# 4. 输出：可勾选多种
output:
  dir: ./reports/{{param.month}}
  formats: [html, excel, csv, json, console]

# 5. 运行参数
runtime:
  engine: auto                  # auto / memory / disk
  memory_threshold_rows: 500000 # 超过此阈值自动切磁盘引擎
  log_level: INFO
```

### 参数替换（三种占位符）

| 占位符 | 来源 | 例子 |
|---|---|---|
| `${ENV_VAR}` | 系统环境变量 | `password: ${GAUSS_PROD_PWD}` |
| `{{param.xxx}}` | CLI `--param xxx=yyy` | `month: "{{param.month}}"` |
| `{{today}}` / `{{now}}` | 内置函数 | `date: "{{today}}"` |

### 数据源类型速查

**Excel**（`type: excel`）
```yaml
sources:
  left:
    type: excel
    path: ./data.xlsx
    sheets: [{name: Sheet1}]     # 或 [{index: 0}]
    header_row: 1
    force_string: true
```

**GaussDB**（`type: gaussdb`）
```yaml
sources:
  right:
    type: gaussdb
    connection: prod_dws         # 引用 connections.yaml
    query: SELECT ... FROM ... WHERE ...
```

**HTTP API**（`type: api`）
```yaml
sources:
  left:
    type: api
    connection: order_service
    method: GET
    url: /v1/orders
    params:
      status: paid
    pagination:
      type: page                 # 或 offset / cursor
      page_param: pageNum
      size_param: pageSize
      size: 200
      total_path: $.data.total
    data_path: $.data.list[*]    # JSONPath 提取表格数据
    timeout: 30
    retry:
      max_attempts: 3
      backoff: 1.5
```

### connections.yaml 结构

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

# API - 无认证
public_svc:
  type: api
  base_url: https://api.example.com

# API - Bearer Token
order_service:
  type: api
  base_url: https://api.internal.company.com
  auth:
    kind: bearer
    token: ${ORDER_API_TOKEN}

# API - Cookie（先登录再取 cookie）
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

---

## 常见操作

### 1. 生成任务模板

```bash
# 三种模板可选
datacompare init excel-vs-gaussdb > task.yaml
datacompare init api-vs-gaussdb   > task.yaml
datacompare init excel-vs-api     > task.yaml
```

### 2. 干跑校验（不执行，只检查配置和连接）

```bash
datacompare validate task.yaml --connections ~/.datacompare/connections.yaml
```

会做三件事：
1. Pydantic 校验 YAML 语法与字段类型
2. 尝试连接每个数据源
3. 探测两侧列名，校验 `match.keys` 和 `compare.fields` 引用的列都存在

**输出示例**：
```
✓ configuration is valid
```
或
```
❌ validation failed:
  · left: match key column 'order_no' not found. Available: ['order_id', 'sku_code', ...]
```

### 3. 执行比对

```bash
datacompare run task.yaml \
  --connections ~/.datacompare/connections.yaml \
  --param month=2026-07 \
  --param region=north
```

### 4. 只输出某种格式（覆盖 YAML 里的 `output.formats`）

```bash
datacompare run task.yaml --format json --format console
```

### 5. 只做校验不执行（`--dry-run`）

```bash
datacompare run task.yaml --dry-run
```

### 6. CI/CD 集成：发现差异就失败

```bash
datacompare run task.yaml --fail-on-diff
echo $?    # 0 = 无差异；10 = 有差异
```

### 7. 强制使用指定引擎

```bash
# 大数据量强制走磁盘引擎（DuckDB）
datacompare run task.yaml --engine disk

# 明确用内存引擎（默认 auto 会根据行数自动选）
datacompare run task.yaml --engine memory
```

### 8. 覆盖输出目录

```bash
datacompare run task.yaml --output-dir /tmp/report-$(date +%Y%m%d)
```

### 9. 定时任务集成（Linux cron 示例）

```
# 每天 03:00 跑前一天的比对，有差异发邮件
0 3 * * * cd /opt/datacompare && \
  ./venv/bin/datacompare run task.yaml \
  --param date=$(date -d yesterday +\%Y-\%m-\%d) \
  --fail-on-diff \
  --log-file /var/log/datacompare/$(date +\%Y\%m\%d).log \
  --log-level INFO \
  || mail -s "DataCompare 差异告警" ops@example.com < /tmp/last-report.json
```

### 退出码语义（脚本可判断）

| 退出码 | 含义 |
|---|---|
| `0` | 成功（无差异，或未指定 `--fail-on-diff`） |
| `1` | 配置错误（YAML 校验、字段引用等） |
| `2` | 数据源连接/读取失败（网络断、SQL 报错、Excel 打不开等） |
| `3` | 内部错误（未预期异常） |
| `10` | 任务成功但发现差异，且指定了 `--fail-on-diff` |

---

## 日志与报错排查

### 日志的三种去向

DataComparator 用 **structlog** 输出结构化日志（JSON Lines 格式），可以同时输出到终端和文件。

```bash
# 1. 默认：只输出到终端（人类可读级别）
datacompare run task.yaml

# 2. 更详细的终端输出
datacompare run task.yaml --log-level DEBUG

# 3. 同时写入文件（JSON Lines，便于机器解析）
datacompare run task.yaml --log-file ./logs/run-$(date +%Y%m%d-%H%M%S).log

# 4. 静默模式（只在报错时输出）—— 适合 cron
datacompare run task.yaml --log-level ERROR
```

日志级别：`DEBUG` / `INFO`（默认）/ `WARN` / `ERROR`。

### 日志文件的格式

每行是一条独立的 JSON 记录，例如：
```json
{"event": "engine_selected", "engine": "InMemoryEngine", "left_rows": 12345, "right_rows": 12300, "threshold": 500000, "level": "info", "timestamp": "2026-07-13T15:20:31.123456Z"}
{"event": "compare_started", "task": "每日销售数据核对", "level": "info", "timestamp": "..."}
{"event": "compare_finished", "matched": 12280, "identical": 12250, "diff": 30, "duration_seconds": 4.2, "level": "info", "timestamp": "..."}
```

### 用 `jq` 快速筛查日志

```bash
# 查看所有 error 级别记录
cat logs/run-20260713-152031.log | jq 'select(.level == "error")'

# 查看每次运行的耗时
cat logs/*.log | jq 'select(.event == "compare_finished") | {task, duration_seconds}'

# 找出发现差异最多的运行
cat logs/*.log | jq -s 'map(select(.event == "compare_finished")) | sort_by(.diff) | reverse | .[:5]'
```

### 报错场景与排查思路

#### 情形 1：配置校验失败（退出码 1）

**症状**：
```
❌ 配置错误 · match.keys[0].right
    右侧数据源 (gaussdb: prod_dws) 中不存在列 'order_id'。
    右侧可用列: order_no, order_time, sku_code, amount, region, updated_at
    提示: 您是否想用 'order_no'？
```

**排查**：
1. 错误信息里的 `path` 直接告诉你出错在 YAML 的哪一层
2. `Available` 列出真实的列名，找一个像的填进去
3. 修改后重新 `validate`：
   ```bash
   datacompare validate task.yaml
   ```

#### 情形 2：数据源连接失败（退出码 2）

**症状**：
```
❌ error: could not connect to server: Connection refused
```

**排查**：
1. **GaussDB**：
   - 检查 host / port / ssl 是否正确
   - 用 `psql -h host -p 5432 -U user -d db` 单独测试连通性
   - 检查防火墙 / 白名单
2. **API**：
   - 用 `curl -v $URL` 测试接口能否直接访问
   - 检查 token 是否过期（Bearer）或登录 cookie 是否成功（Cookie 认证）
   - 日志里搜 `login_failed` / `4xx` / `5xx`
3. **Excel**：
   - 检查文件路径是否存在，是否有读权限
   - `.xls`（老格式）需要 `xlrd`，`.xlsx` 用 `openpyxl`
   - 检查文件是否被其他程序占用（Excel 正在打开时可能锁死）

#### 情形 3：主键重复导致任务中止

**症状**：
```
❌ error: duplicate keys in left side: [{'order_id': 'A001'}, {'order_id': 'A007'}, ...]
```

**排查**：
- 这是**配置错误**而非数据问题：如果一侧同一主键出现多行，比对无法进行
- 检查主键定义是否完整（是不是应该用**复合键** `[order_id, sku_code]` 而不是单键 `order_id`）
- 或者数据源查询/过滤条件是否需要加限定

#### 情形 4：字段解析错误（不阻塞任务，但报告里会体现）

**症状**：报告的 `errors` 部分出现：
```json
{
  "row_key": {"order_id": "A099"},
  "field": "amount",
  "kind": "type_error",
  "original": "N/A"
}
```

**说明**：某一行的 `amount` 值是 `"N/A"`，无法转换为数字。该行会作为 `type_error` 差异出现在明细里，其他行正常处理。

**排查**：
- 如果这是脏数据，源头修复
- 如果 `"N/A"` 应该被视为 null，把它加到 `null_equivalents`：
  ```yaml
  compare:
    defaults:
      null_equivalents: ["", "null", "NULL", "N/A", "NaN"]
  ```

#### 情形 5：单位解析错误

**症状**：报告里出现：
```json
{"kind": "unit_error", "original": "abc GB", "field": "storage"}
```

**说明**：字段值不匹配"数字+单位"格式，或者单位不在预置类别里。

**内置单位类别**：
| 类别 | 支持单位（大小写不敏感） |
|---|---|
| `storage` | B / KB / MB / GB / TB / PB（1024 进制） |
| `time` | ms / s / min / h / d |
| `length` | mm / cm / m / km |
| `mass` | mg / g / kg / t |

**排查**：
- 检查 `unit_category` 是否用对了
- 检查值格式：`"30 TB"` / `"30TB"` / `"30.5 tb"` 都支持；`"30 T"` 不支持（T 不是有效单位）

#### 情形 6：内存/性能问题

**症状**：任务卡住，内存持续增长，或最终 OOM。

**排查**：
1. 查日志找 `engine_selected` 事件，看用的哪个引擎
2. 如果是 `InMemoryEngine` 但数据量大，强制切磁盘引擎：
   ```bash
   datacompare run task.yaml --engine disk
   ```
3. 调低阈值使 auto 更早切换：
   ```yaml
   runtime:
     memory_threshold_rows: 100000    # 默认 500000
   ```
4. GaussDB 侧：确保 SQL 里加了合理的 `WHERE` 缩小数据量
5. API 侧：分页 `size` 别设太大（推荐 200-500）

#### 情形 7：pytest 里 Docker 相关测试全 skip

**症状**：
```
SKIPPED [1] tests/integration/sources/test_gaussdb.py:10: Docker daemon not available
```

**说明**：GaussDB 集成测试用 testcontainers 启动 PostgreSQL 容器，需要 Docker Desktop 运行。**不影响生产使用**，只在开发时用真实容器测试才需要。

**处理**：
- 只在你需要验证 GaussDB 相关改动时启动 Docker
- 平时开发保留 skip 是正常的

### 打开 debug 级别看内部细节

```bash
datacompare run task.yaml --log-level DEBUG --log-file ./debug.log
```

DEBUG 级别会额外记录：
- 每个数据源的连接细节（密码已脱敏）
- 每次 API 请求 URL 和响应状态
- 归一化管线每一步的输入/输出示例
- pandas merge 的中间统计

### 密码泄漏检查

**放心**：日志中的连接串会自动脱敏：
```
postgresql://user:***@host:5432/db
password=***
```

如果你在自己的日志/告警脚本里手工输出连接信息，请自行使用 `datacompare.config.credentials.mask_password()` 做脱敏。

---

## 命令一览

```
datacompare [OPTIONS] COMMAND [ARGS]

Commands:
  run       执行比对任务
  validate  校验配置文件（不执行）
  init      生成配置模板
  version   显示版本
```

### `datacompare run`

```
datacompare run TASK_FILE [OPTIONS]

Options:
  --connections PATH            凭据文件路径 [默认: ~/.datacompare/connections.yaml]
  --param KEY=VALUE, -p         任务参数（可多次）
  --output-dir PATH             覆盖输出目录
  --format TEXT, -f             覆盖输出格式（可多次）
  --engine [auto|memory|disk]   覆盖引擎选择
  --log-level [DEBUG|INFO|WARN|ERROR]
  --log-file PATH               日志额外输出到文件（JSON Lines）
  --dry-run                     完整校验但不执行
  --fail-on-diff                发现差异时退出码非 0（CI 集成用）
```

### `datacompare validate`

```
datacompare validate TASK_FILE [OPTIONS]

Options:
  --connections PATH   凭据文件路径 [默认: ~/.datacompare/connections.yaml]
```

### `datacompare init`

```
datacompare init TEMPLATE

支持的模板:
  excel-vs-gaussdb
  api-vs-gaussdb
  excel-vs-api
```

### `datacompare version`

```
datacompare version
```

---

## 更多文档

- **用户指南**：`docs/user-guide.md` — 更详细的配置说明
- **设计文档**：`docs/superpowers/specs/2026-07-13-data-comparator-design.md` — 架构决策和判等语义规则
- **实现计划**：`docs/superpowers/plans/2026-07-13-data-comparator.md` — 31 个 TDD 任务的完整实现记录
- **示例配置**：`examples/` — 三种典型场景的可运行 YAML

---

## 许可与反馈

Bug、需求、改进建议欢迎提 issue：https://github.com/benerlord/DataComparator/issues
