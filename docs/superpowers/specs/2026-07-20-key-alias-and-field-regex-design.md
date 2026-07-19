# Key Alias 与 Field Regex 设计规范

**日期：** 2026-07-20
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划

## 问题背景

当前 `KeyMapping` 支持 `right_regex` 从右侧列值里提取 join 用的子串（v0.3），但比对字段 `FieldRule` 不支持任何 regex 变换。真实场景：

- 右侧 GaussDB 表的 `name` 列值形如 `"Alice@@r1"`
- 左侧 Excel 有独立的 `id` 列和 `name` 列
- match key 用 `{left: id, right: name, right_regex: '.*@@(.*)'}` 提取 `"r1"` 部分作 join
- 用户希望 compare field 是 `left.name` vs `right.name` **经 regex `(.*)@@.*` 提取前缀后的值**

当前 config 无法表达。此外还有一个隐性冲突：`k.right = "name"` 和 `f.right = "name"` 同名，`apply_column_mapping` 归一化后左右两侧各出现两个都叫 `name` 的列，`merge(on="name")` 报 `column label 'name' is not unique`。

## 方案概览

三处联动改动：

1. **`KeyMapping.alias`**：可选，给 join key 起一个 canonical 名字，避免与 field canonical 撞名
2. **`FieldRule.left_regex` / `right_regex`**：镜像 `KeyMapping` 的 regex 语义，作用于 field 值
3. **`apply_column_mapping` 重构**：允许同一源列被复制成多个 canonical 列（右侧 `name` 同时充当 `join_id` 和 `name`），regex 应用改到 rename+复制**之后**

## YAML 表面

```yaml
match:
  keys:
    - left: id
      right: name
      right_regex: '.*@@(.*)'    # 提取右侧 name 的后缀作 join 值
      alias: join_id             # 新：canonical 列名，避免与 field 撞名

compare:
  fields:
    - left: name
      right: name
      right_regex: '(.*)@@.*'    # 新：field 值走 regex 提取前缀
                                 # canonical = f.right = "name"
```

归一化完成后，左右两侧 DataFrame 结构均为 `[join_id, name]`。engine 在 `join_id` 上 merge，在 `name` 上 compare。报告里字段名为 `name`（不是 `join_id`）。

## 数据模型

### `KeyMapping`（`src/datacompare/config/models.py`）

```python
class KeyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    right: str
    left_regex: str | None = None
    right_regex: str | None = None
    alias: str | None = None                  # 新增
    # 现有 regex validator 不变
```

`alias` 无独立校验（任何非空字符串都可以；下游校验重复 canonical 时会一起管）。默认 `None` → canonical 走 `k.right`，与老行为等价。

### `FieldRule`（同文件）

在现有字段基础上新增：

```python
class FieldRule(BaseModel):
    # ... 现有字段（left/right/literals/mode/decimal_places/... 保持）
    left_regex: str | None = None             # 新增
    right_regex: str | None = None            # 新增
    # 复用 KeyMapping 现在用的同一个 regex validator（提取到模块级 helper 共享）
```

`FieldRule` 不加 `alias`（YAGNI，两个 field 想共用 `f.right` 是配置错误）。

### 共享 regex 校验器

抽出 `KeyMapping._validate_regex` 的实现为模块级函数 `_validate_optional_regex(v)`（`models.py` 内部）。两处 `field_validator` 均调用它：编译成功 + 捕获组数 ≤ 1。

## Canonical 名字规则

`src/datacompare/normalize/columns.py`：

```python
def key_canonical_name(k: KeyMapping) -> str:
    """新增：key 的 canonical 列名。有 alias 用 alias，否则用 k.right。"""
    return k.alias if k.alias is not None else k.right


def field_canonical_name(f: FieldRule) -> str:
    """保持不变：优先 f.right，其次 f.left，最后 '_literal' 兜底。"""
    if f.right is not None: return f.right
    if f.left is not None: return f.left
    return "_literal"
```

**加载期新校验**（`config/loader.py`，在完成 Pydantic 校验后追加）：收集所有 `[key_canonical_name(k) for k in match.keys] + [field_canonical_name(f) for f in compare.fields]`，若出现重复 → `ConfigError`，提示"canonical 列名 X 重复，给对应的 key 加 `alias`"。fail-fast，不拖到 pandas 层。

## `apply_column_mapping` 重构

把"整体 rename"改写成"逐列复制"，允许一个源列多次出现，产生多个 canonical 列：

```python
def apply_column_mapping(df, keys, fields, side):
    tasks: list[tuple[str, str]] = []       # (source_col, canonical_name)
    literal_fields: list[tuple[str, str | None]] = []
    for k in keys:
        tasks.append((getattr(k, side), key_canonical_name(k)))
    for f in fields:
        src = getattr(f, side)
        canonical = field_canonical_name(f)
        if src is not None:
            tasks.append((src, canonical))
        else:
            literal_fields.append((canonical, getattr(f, f"{side}_literal")))

    missing = [src for src, _ in tasks if src not in df.columns]
    if missing:
        raise ConfigError(
            f"columns not found in {side} source: {missing}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )

    result = pd.DataFrame(index=df.index)
    for src, canonical in tasks:
        result[canonical] = df[src].values   # 允许同源多次复制
    for canonical, lit in literal_fields:
        result[canonical] = lit
    return result
```

**语义变化说明：**

- 老实现："构造 rename_map → filter 到 src_cols → 一次性 rename"。同源列只能变成一个目标名。
- 新实现："对每个 (src, canonical) 对做一次 `result[canonical] = df[src].values`"。同源列可产生多个 canonical 列。
- 加载期已挡住 canonical 撞名，所以这里不需要再检查。
- `.values` 而不是 `df[src]` 直接赋值：切断视图关系，避免下游改动波及 `df`（保守）。

## Regex 应用顺序调整

`src/datacompare/normalize/pipeline.py::normalize_side`：

**当前顺序：**
```python
df = apply_key_regex(df, keys, side)          # 直接改原列
renamed = apply_column_mapping(df, ..., side)
```

**新顺序：**
```python
renamed = apply_column_mapping(df, ..., side) # 先复制+改名
apply_regex_on_canonical(renamed, {                    # 再对 canonical 列跑 key regex（严格）
    key_canonical_name(k): getattr(k, f"{side}_regex")
    for k in keys if getattr(k, f"{side}_regex") is not None
}, mode="strict")
apply_regex_on_canonical(renamed, {                    # 再对 canonical 列跑 field regex（软失败）
    field_canonical_name(f): getattr(f, f"{side}_regex")
    for f in compare.fields if getattr(f, f"{side}_regex") is not None
}, mode="soft")
# ... 后续 _process_value 循环不变
```

**为什么必须后置：** 右侧同一个源列 `name` 可能同时被 key（regex `.*@@(.*)`）和 field（regex `(.*)@@.*`）引用。如果在 rename+复制之前应用 regex，先跑的 regex 会污染源列，后跑的 regex 只能看到已被提取的子串。后置到 canonical 列上跑，两个 canonical 列各自跑自己的 regex，互不干扰。

## `apply_regex_on_canonical` 新公共函数

`src/datacompare/normalize/keys.py`：把现有 `_apply_pattern_to_column` 的核心提取成公共函数，两种失败模式共用。

```python
def apply_regex_on_canonical(
    df: pd.DataFrame,
    regex_map: dict[str, str],       # canonical_col -> pattern_string
    mode: Literal["strict", "soft"],
) -> None:
    """就地把 regex 应用到 df 的 canonical 列。

    - strict：任一行不匹配 → 抛 KeyRegexMismatchError（key 用）
    - soft：不匹配 → CoerceError(kind='regex_error', original=v)（field 用）
    - None 值透传不参与匹配
    - 有捕获组用 group(1)，否则用 group(0)
    """
    for col, pattern_str in regex_map.items():
        pattern = re.compile(pattern_str)
        df[col] = df[col].map(lambda v, p=pattern, m=mode, c=col:
            _apply_single(v, p, m, c))


def _apply_single(v, pattern, mode, col):
    if v is None:
        return None
    s = str(v)
    m = pattern.fullmatch(s)
    if m is None:
        if mode == "strict":
            raise KeyRegexMismatchError(...)
        return RegexError(original=s, pattern=pattern.pattern)
    return m.group(1) if pattern.groups == 1 else m.group(0)
```

**新增独立 sentinel**，与 `UnitError` / `CoerceError` 平级：

```python
# src/datacompare/normalize/regex.py（新文件）或塞进 normalize/keys.py
@dataclass(frozen=True)
class RegexError:
    original: str
    pattern: str
```

对应 `engine/result.py::DiffType` 新增枚举：`REGEX_ERROR = "regex_error"`。engine `_classify` 和 error 收集逻辑（`memory.py` / `disk.py`）加分支识别 `RegexError`，与现有 `CoerceError` → `type_error`、`UnitError` → `unit_error` 完全对称。理由：`CoerceError(original, target)` 结构本身没有 `kind` 字段，塞进去要么改结构要么滥用 `target` 字段存 "regex"，两条都不干净；平级新增最一致。

现有 `apply_key_regex` 逻辑并入这个新函数；调用点由 `normalize_side` 从"pre-rename 阶段"移到"post-rename 阶段"。

## 引擎侧

`src/datacompare/engine/memory.py`（第 56 行左右）和 `src/datacompare/engine/disk.py`（第 52 行左右）：

```python
# 老
key_cols = [k.right for k in task.match.keys]
# 新
from datacompare.normalize.columns import key_canonical_name
key_cols = [key_canonical_name(k) for k in task.match.keys]
```

与上一版 `field_canonical_name` 落地方式对称，engine 层不再硬编码 `k.right`。

## 不改动的部分

- `KeyMapping.left`/`.right` 类型不变（仍是必填 `str`）
- `FieldRule` 其余现有字段全部保留
- Report 里字段名仍用 canonical（`f.right`），跟老行为一致
- 批次模式合并规则、`on_error` 语义均不受影响
- 数据源层（`ExcelSource` / `GaussDBSource` / `APISource`）零改动
- Reporter 零改动

## 向后兼容

- 所有老 config：`alias` 默认 `None` → `key_canonical_name` 回退到 `k.right`；`FieldRule.regex` 默认 `None` → 不跑 regex。行为 100% 等价。
- `apply_column_mapping` 从"整体 rename"改为"逐列复制"：对下游透明，因为下游本来就是拿到列名/值使用，不依赖 pandas 视图关系。所有现有 fixture 测试应仍绿。
- Regex 后置：老 config 里 `KeyMapping.right_regex` 的语义完全不变（`re.fullmatch`、group 提取、None 透传、strict 失败），仅执行时机由 "pre-rename" 移到 "post-rename"。老测试仍应绿（同样的 regex，同样的输入串，同样的输出）。

## 校验规则

Pydantic 层：
- `FieldRule.left_regex` / `right_regex` 走与 `KeyMapping` 相同的 validator（编译成功 + 0/1 捕获组）

`config/loader.py` 层（Pydantic 校验之后）：
- **canonical 重复检查**：`{ key_canonical_name(k) for k in match.keys } ∪ { field_canonical_name(f) for f in compare.fields }` 出现重名 → `ConfigError`

## 失败语义

| 情境 | 行为 |
|------|------|
| key regex 编译失败 | 加载期报错（Pydantic） |
| field regex 编译失败 | 加载期报错（Pydantic） |
| canonical 名字撞车 | 加载期报错（loader） |
| 运行时 key regex 某行不匹配 | 抛 `KeyRegexMismatchError`，CLI exit 2（与现有一致） |
| 运行时 field regex 某行不匹配 | 该值变 `RegexError(original, pattern)` sentinel，engine 归 `DiffType.REGEX_ERROR`；不影响其他行 |
| 源列不存在（key 或 field 引用） | 加载期报错（apply_column_mapping 里 `missing` 检查提前到验证阶段仍成立） |

## 测试计划

**`tests/unit/config/test_models.py`：**
- `KeyMapping(alias="x")` OK
- `FieldRule(left="a", right="b", left_regex="valid")` OK
- `FieldRule(..., left_regex="(too)(many)(groups)")` → ValidationError
- 两个 field 用同一个 `f.right` → 加载期 canonical 撞车（loader 检查）
- key 和 field 撞名不加 alias → 加载期报错

**`tests/unit/normalize/test_columns.py`：**
- 同源复制：右侧 `name` 同时给 key（canonical `join_id`）和 field（canonical `name`）用 → 结果两列都在
- key alias 场景：`{right: name, alias: join_id}` → canonical 是 `join_id` 不是 `name`

**`tests/unit/normalize/test_regex.py`（新）：**
- `apply_regex_on_canonical` strict 模式：命中 → 提取；不命中 → 抛 `KeyRegexMismatchError`
- soft 模式：命中 → 提取；不命中 → 返回 `RegexError(original=<原值>, pattern=<模式串>)`
- None 值透传（strict 和 soft 都）
- 有捕获组用 `group(1)`，无捕获组用 `group(0)`

**`tests/unit/normalize/test_pipeline.py`：**
- 完整跑通"key alias + field regex + 同源复制"：右侧 `name = "prefix@@r1"` → normalize 后 `join_id = "r1"`、`name = "prefix"`
- field regex mismatch → 值变 sentinel，其他行正常

**`tests/unit/engine/test_same_column_name_collision.py`（补充）：**
- 端到端：左侧有 `name` 列 + key alias + field regex → engine 正确 join、正确 diff，报告字段名是 `name`

**`tests/integration/test_batch_e2e.py`（新场景 K）：**
- Excel + Excel（模拟 GaussDB）batch 子任务：右侧 `name` 双用，跑通 CLI → JSON 报告

## 文档

- `README.md`：`KeyMapping` 现有的 `right_regex` 小节后加"canonical alias（v0.6+）"和"字段级 regex"两个短小节
- `docs/user-guide.md`：`### Key regex normalization (v0.3+)` 后加姊妹小节"Key alias for canonical name conflicts (v0.6+)"和"Field regex normalization (v0.6+)"
- `CLAUDE.md` 关键约束追加：
  - `KeyMapping` 支持 `alias`（v0.6 起）：canonical 列名规则改由 `normalize/columns.py::key_canonical_name` 集中管理
  - `FieldRule` 支持 `left_regex/right_regex`（v0.6 起）：失败是**软**失败（sentinel），与 key regex 的**严**格失败不同
  - regex 应用顺序：**post-rename**（作用于 canonical 列），不是 pre-rename——源列可能被多次引用

## 工作量估算

- 模型（含共享 validator）：约 15 行
- `columns.py`（重构 + `key_canonical_name`）：约 30 行
- `keys.py`（提取公共函数、`apply_regex_on_canonical`）：约 40 行
- `pipeline.py`（调用点重排）：约 10 行
- 两个 engine：各约 2 行
- loader canonical 重复检查：约 15 行
- 测试：约 150 行（6 个测试文件的增量）
- 文档：约 40 行

单 PR，5-6 个 commit（按 TDD 节奏切）。无新依赖。
