# Key Regex Transform Design

**日期**：2026-07-16
**版本**：v0.3（在 v0.2 GaussDB T 之后）
**状态**：设计已确认，待实现

## 背景

现有 `match.keys` 的 `left` / `right` 只做**列名映射**，join 时用 pandas `.merge()` 对原始字符串做严格相等比较（见 `src/datacompare/normalize/pipeline.py:60-67` 和 `src/datacompare/engine/memory.py:69`）。

当左右两侧的 key 字面值不同、但可以通过**确定性正则规则**转换成同一形式时（如左侧 `"ORD-2026-000123"` 对右侧 `"123"`），当前实现无法匹配 —— 全部会落入 `left_only` / `right_only`。

本设计新增可选的 **key 归一化步骤**，允许在 join 之前对任一侧的 key 列跑一次正则提取。

## 需求范围

**In scope（本次实现）**：
- 每对 key 支持独立的 `left_regex` / `right_regex`（均可选）
- 正则语义：Python `re.fullmatch`，0 或 1 个捕获组
- 严格模式：任一行的正则不匹配 → 立即抛专用异常，任务失败（退出码见 §错误语义）
- 结构化错误日志（structlog），字段：`side`、`column`、`row_index`、`value`、`pattern`

**Out of scope（后续版本或按需再加）**：
- 其他转换算子（strip_prefix、pad_zero、date_format、to_upper 等）
- 值映射表（`{"北京": "BJ"}` 这种字典转换）
- 模糊/相似度匹配
- 多列组合成一个 key
- 一列拆分成多个 key
- 日志中的 key 值脱敏

## 架构

新增 **"key 归一化"** 步骤，插在归一化管线的**最前面**：

```
DataSource.read() → DataFrame（keys + fields，均为 str|None）
     ↓
[新] apply_key_regex(df, keys, side)   ← 本次要加
     ↓
apply_column_mapping (columns.py)      ← 现有：左右列名统一到 right
     ↓
per-field normalize (strings/units/types/decimals)
     ↓
engine.merge (strict equal on key cols)
```

**位置选择理由**：
- 在 `apply_column_mapping` 之前跑 —— 此时列名还是原始的，`left_regex` 操作左侧原列、`right_regex` 操作右侧原列，配置符号与列名一一对应，读者不用心算 rename
- 与 fields 归一化解耦 —— fields 有自己的 CompareDefaults 管线，keys 走独立路径
- **重复键检测**（`memory.py:66`、`disk.py:64`）在 regex 之后跑是正确语义 —— 规则可能把不同原始值折叠成同一 key（如 `"ORD-2026-000123"` 和 `"ORD-2027-000123"` 都提取出 `"123"`），此时"重复 = 配置错误"必须触发

**归属层**：新文件 `src/datacompare/normalize/keys.py`，纯函数，无外部 IO，风格与 `normalize/columns.py` `normalize/strings.py` 一致。

## 配置形状

### YAML 示例

```yaml
match:
  keys:
    - left: order_no
      right: order_id
      left_regex: 'ORD-\d{4}-0*(\d+)'   # 可选；未指定 = 原样透传
      right_regex: null                  # 可选；等价于省略

    - left: region
      right: region                       # 无正则，最简形式，向后兼容
```

### Pydantic 模型（`src/datacompare/config/models.py`）

```python
import re
from pydantic import BaseModel, ConfigDict, field_validator

class KeyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    right: str
    left_regex: str | None = None
    right_regex: str | None = None

    @field_validator("left_regex", "right_regex")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            pattern = re.compile(v)
        except re.error as e:
            raise ValueError(f"invalid regex {v!r}: {e}")
        if pattern.groups > 1:
            raise ValueError(
                f"regex {v!r} has {pattern.groups} capture groups; "
                "must have 0 or 1. Use non-capturing (?:...) for grouping without capture."
            )
        return v
```

### 关键约定

- **完全向后兼容**：现有 task.yaml 一行不改（两个新字段默认 `None`）
- **加载时校验**：非法正则 / ≥2 个捕获组 在 `datacompare validate` 阶段就报错，`run` 前必然失败干净
- **不做编译缓存**：Python `re` 模块自带 LRU cache（默认 512），YAGNI
- **模板更新**：`templates/*.yaml` 三个模板加一行注释示例，指向文档；不预置具体规则以免既有用户混淆

## 正则语义

### 匹配范围：`re.fullmatch`

整串必须完全匹配才算成功。理由：
- 与"严格模式失败"策略一致 —— 用户写的规则应完整覆盖 key 的样子
- 不匹配就报错，杜绝"部分匹配意外通过"
- 想放松：用户自己在 pattern 里加 `.*`

### 捕获组数量与归一化后的 key

| 捕获组数量 | 归一化后用什么 | 例子 |
|---|---|---|
| 0 个 | `m.group(0)`（整个匹配） | `'\d+'` on `"123"` → `"123"` |
| 1 个 | `m.group(1)`（第一个组） | `'ORD-0*(\d+)'` on `"ORD-000123"` → `"123"` |
| ≥2 个 | **Pydantic 校验阶段直接报错** | 不允许，避免"拼接顺序"的隐式约定 |

想拼多组？用非捕获组 `(?:...)` 或写成一个大捕获组把想要的整段圈起来。

### Flags

不支持独立的 flags 配置项。用户可在 pattern 里用 inline flag 语法：
- `(?i)ord-\d+` —— case-insensitive
- `(?s)...` —— dot 匹配换行
- `(?x)...` —— verbose 模式

## 错误语义

### 异常类型

新增 `src/datacompare/normalize/keys.py`：

```python
class KeyRegexMismatchError(ValueError):
    """Raised when a key value fails to fullmatch the configured regex.

    Fail-fast: first mismatch aborts the task with exit code 2 (see §CLI 退出码).
    """
    def __init__(
        self,
        side: str,          # "left" | "right"
        column: str,        # 原始列名（left 用 k.left，right 用 k.right）
        value: str,         # 不匹配的原始值
        pattern: str,       # 正则字符串
        row_index: int,     # DataFrame 内 0-based 位置（见下方说明）
    ):
        self.side = side
        self.column = column
        self.value = value
        self.pattern = pattern
        self.row_index = row_index
        super().__init__(
            f"key regex mismatch on {side} side, column={column!r}, "
            f"row_index={row_index}, value={value!r}, pattern={pattern!r}"
        )
```

**`row_index` 语义**：DataSource.read() 返回的 DataFrame 内 0-based 位置。不等于 Excel 行号（表头已剥离，多 sheet 已 concat）。用户排查时需按 sheet 配置反算。此语义与既有"重复键"报错保持一致（后者直接给 `row_key` dict，不给行号；本设计更进一步）。

### Fail-fast，不 collect-all

发现第一个不匹配就抛，不遍历完再报。理由：
- 一个正则规则错，通常整批都错，收集百万行错误无意义
- 与现有"重复键 = ValueError"（`memory.py:67`、`disk.py:65`）的错误策略一致 —— 都是配置错误，早死早超生
- 用户拿到第一条样本 `value` 和 `pattern`，就能定位问题

### null 值处理

某行的 key 列本身为 `None`（如 Excel 空单元格）：**不跑 regex，原样透传 None**。

理由：
- 与 fields 层的 null 处理一致（null_equivalents 也是"识别 null 后透传"）
- key 为空是数据质量问题，会自然显示在 left_only / right_only 报告里
- 用户想严格：由业务端保证 key 非空即可

### 结构化日志

抛异常前先写一条 structlog `error` 事件：

```python
logger.error(
    "key_regex_mismatch",
    side=side,
    column=column,
    row_index=row_index,
    value=value,          # 完整原始值，不脱敏
    pattern=pattern,
)
# 注：如果 runner 后续用 structlog.contextvars.bind_contextvars(task=task.name)
# 绑定了任务名，`merge_contextvars`（已在 logging.py:30 配置）会自动带上 task 字段。
# 本设计不新增该绑定，视作独立的可选增强。
```

### CLI 退出码

复用现有 **exit 2 = 数据源连接/读取失败** 语义。理由：`KeyRegexMismatchError` 继承 `ValueError`，被 `cli.py:61` 的 `except Exception` 捕获 → `typer.Exit(2)`（与既有 `engine/memory.py:67` 抛的"重复键"`ValueError` 走同一路径 —— 都属于"数据与配置约束不符"的运行期错误）。不新增退出码。

若希望走 exit 1（配置错误）路径，需要 `KeyRegexMismatchError` 继承 `ConfigError` 并注册在 `cli.py:59` 的 `except ConfigError`。**本设计不这么做**，理由：`ConfigError` 语义是"配置本身不合法"（YAML 解析失败、Pydantic 校验失败），而此处配置合法、只是数据不合规则，语义应等同于"重复键"。

### 报告器影响

任务失败 → 无比对结果 → 不产出 HTML/Excel/CSV/JSON 报告。CLI 只输出错误消息 + structlog 事件。

## 契约签名

`src/datacompare/normalize/keys.py`：

```python
def apply_key_regex(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Apply regex fullmatch to key columns; return new DataFrame with transformed keys.

    - side="left" uses k.left as column and k.left_regex as pattern
    - side="right" uses k.right as column and k.right_regex as pattern
    - Keys without a regex are passed through unchanged
    - None values are passed through unchanged (not matched)
    - First mismatch raises KeyRegexMismatchError

    Returns a copy of df with the same columns; only key columns' values may change.
    """
```

调用点：`normalize_side` (in `pipeline.py`) 首行调用 `apply_key_regex(df, keys, side)`，把结果传给 `apply_column_mapping`。

## 测试策略

### 单元测试 — `tests/normalize/test_keys.py`（新增）

Pytest 参数化覆盖：

| 场景 | 输入 | 预期 |
|---|---|---|
| 无正则 → 原样透传 | `left_regex=None` | 值不变 |
| 1 个捕获组 → 用 group(1) | `'ORD-0*(\d+)'` on `"ORD-000123"` | `"123"` |
| 无捕获组 + 整串匹配 → 用 group(0) | `'\d+'` on `"123"` | `"123"` |
| 部分匹配（fullmatch 拒绝） | `'\d+'` on `"abc123def"` | `KeyRegexMismatchError` |
| 完全不匹配 → 抛异常 | `'ORD-\d+'` on `"CANCEL-1"` | `KeyRegexMismatchError`，字段完整 |
| null 值透传 | `'\d+'` on `None` | 保持 `None`，不抛 |
| 复合键：两 key 各有 regex | 两个 KeyMapping 都配 | 分别独立处理 |
| 只 left_regex，右侧无 regex（最常见） | | 左侧转换，右侧原样 |
| 只 right_regex，左侧无 regex | | 右侧转换，左侧原样 |
| 空 DataFrame | 0 行 | 返回 0 行、不抛 |

### 配置模型测试 — `tests/config/test_models.py`（追加）

| 场景 | 预期 |
|---|---|
| 未设置 left_regex/right_regex | 加载成功，值为 None |
| 非法正则语法 | Pydantic `ValidationError` |
| ≥2 个捕获组 | Pydantic `ValidationError`，错误消息提示用 `(?:...)` |
| 明确 `null` | 加载成功，等价于省略 |

### 引擎 parity — `tests/engine/test_parity.py`（追加参数化）

新增 1 个 fixture：left 有 `left_regex`，右侧原样。断言 `InMemoryEngine` 和 `DiskEngine` 结果字段一致（matched_rows / diff_rows / left_only / right_only 数量与 row_key）。

### 端到端 — `tests/e2e/test_end_to_end.py`（追加 2 个场景）

**成功场景**：Excel 有 `order_no` 列（值形如 `"ORD-2026-000123"`），DB 有 `order_id` 列（值形如 `"123"`），配 `left_regex: 'ORD-\d{4}-0*(\d+)'`。跑 `datacompare run`：
- 退出码 0
- HTML/Excel/CSV/JSON 报告都产出
- 匹配行数正确

**失败场景**：同上，但 Excel 混入一行 `order_no="CANCEL-999"`。跑 `datacompare run`：
- 退出码 2（与"重复键" ValueError 同路径，见 §CLI 退出码）
- stderr / 结构化日志里包含 `key_regex_mismatch` 事件
- 事件字段含 `column="order_no"`、`value="CANCEL-999"`、`pattern="ORD-\\d{4}-0*(\\d+)"`
- 不产出任何报告文件

## 影响的现有文件

- `src/datacompare/config/models.py` — `KeyMapping` 新增 2 字段 + validator
- `src/datacompare/normalize/keys.py` — **新建**
- `src/datacompare/normalize/pipeline.py` — `normalize_side` 首行调 `apply_key_regex`
- `src/datacompare/runner.py` — 无需改（`KeyRegexMismatchError` 是 `ValueError` 子类，走 `cli.py:61` 既有 `except Exception` → exit 2）
- `src/datacompare/templates/excel_vs_gaussdb.yaml`、`excel_vs_gaussdb_t.yaml`、`api_vs_gaussdb.yaml`、`excel_vs_api.yaml` — 每份加一行注释示例
- `CLAUDE.md` — "关键约束" 加一条："KeyMapping 支持 left_regex/right_regex，走 fullmatch + 严格失败"
- `README.md` / `docs/user-guide.md` — 新增一小节示例

## 兼容性

**完全向后兼容**：所有现有 task.yaml 无需修改；`left_regex` / `right_regex` 缺省 = 现有行为。

**性能**：仅在配了 regex 的 key 上产生每行一次 `re.fullmatch` 开销；Python `re` 模块自带 LRU 缓存。大数据量场景（disk engine 分块）仍逐块跑，与 fields 归一化同数量级，不预期成为瓶颈。

## 未来扩展路径

按需引入的顺序建议（不承诺时间表）：

1. **更多算子**：strip_prefix / pad_zero / date_format —— 采用同样"每算子独立字段"策略，或改成 `key_transform: [{type: ..., ...}, ...]` 步骤列表
2. **值映射表**：`value_map: {"北京": "BJ"}` 与 regex 正交，可共存（先 regex 后 map）
3. **多列组合**：`left: [region, order_id]` + `right: composite_key`，需引入拼接语法
4. **日志脱敏**：`log_value_mask: true` 或全局配置，把 `value` 字段替换为 `<masked>`

以上均**不在**本次实现范围内。
