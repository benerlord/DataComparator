# 字段缺列软失败 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 单侧 field 缺列从硬失败改成软失败：跳过该字段的 per-row 比对，在 diff_details 追加一条汇总记录（left_value/right_value = "字段不存在"），其它字段照常比对。key 缺列和双侧同 field 缺列仍硬失败。

**Architecture:** `apply_column_mapping` 签名变为 `-> tuple[pd.DataFrame, frozenset[str]]`；`normalize_side` 返回新数据类 `NormalizedSide(df, missing_field_canonicals)`；engine 消费两侧 `NormalizedSide`，双侧同字段缺 → raise，单侧缺 → 跳过 per-row 并追加一条汇总 diff。新增 `DiffType.FIELD_MISSING = "field_missing"`，HTML 用灰色背景（`tr.field_missing`）区分。

**Tech Stack:** Python 3.11+ / pandas 2.x / dataclasses / pytest / Jinja2

**规范来源:** `docs/superpowers/specs/2026-07-27-field-missing-soft-fail-design.md`

---

## 文件结构

| 文件 | 变化类型 | 责任 |
|---|---|---|
| `src/datacompare/normalize/columns.py` | 修改 | `apply_column_mapping` 拆分 key/field 缺列检测；key 缺列 raise、field 缺列进 missing 集 |
| `src/datacompare/normalize/pipeline.py` | 修改 | 新增 `NormalizedSide` 数据类；`normalize_side` 返回 `NormalizedSide`；跳过缺失字段的下游步骤 |
| `src/datacompare/engine/result.py` | 修改 | `DiffType` 枚举新增 `FIELD_MISSING = "field_missing"` |
| `src/datacompare/engine/_field_missing.py` | 新建 | `_build_field_missing_record()` helper（memory/disk 共用） |
| `src/datacompare/engine/memory.py` | 修改 | 消费 `NormalizedSide`；双侧缺检查；per-field 跳过+汇总；`left_only_rows`/`right_only_rows` 补齐"字段不存在" |
| `src/datacompare/engine/disk.py` | 修改 | 镜像 memory.py 改动 |
| `src/datacompare/reporters/templates/html_report.jinja2` | 修改 | `<style>` 加 `tr.field_missing { background: #ececec; }` |
| `tests/unit/normalize/test_columns.py` | 修改+追加 | 迁移现有测试到 tuple 返回值；追加缺列相关测试 |
| `tests/unit/normalize/test_pipeline.py` | 修改+追加 | 迁移现有测试到 `.df` 访问；追加缺列相关测试 |
| `tests/unit/engine/test_memory.py` | 追加 | 缺列 8 个测试 |
| `tests/unit/engine/test_disk.py` | 追加 | parity test |
| `tests/unit/reporters/test_html.py` | 追加 | CSS 类渲染断言 |
| `tests/integration/test_batch_e2e.py` | 追加 | Scenario M（3-sub-task：success/缺列 success/key 缺 failed） |
| `README.md` | 修改 | 批次模式小节末尾加"字段缺列软失败" |
| `docs/user-guide.md` | 修改 | 新增 `### 字段缺列软失败（v0.8+）` |
| `CLAUDE.md` | 修改 | 加两条约束条目 |

---

## Task 依赖顺序

1. Task 1：`DiffType.FIELD_MISSING` 枚举 + helper（独立，可最先）
2. Task 2：`apply_column_mapping` 签名变更 + 迁移旧测试 + 更新 `pipeline.py` 内的调用点
3. Task 3：`NormalizedSide` + `normalize_side` 签名变更 + 迁移旧测试 + 更新 engines 调用点
4. Task 4：Engine memory — 双侧缺检查 + 缺列 diff 汇总 + `left_only`/`right_only` 补齐
5. Task 5：Engine disk — 镜像 Task 4
6. Task 6：HTML CSS + reporter 测试
7. Task 7：Integration Scenario M
8. Task 8：文档（README + user-guide + CLAUDE.md）

每个 Task 完成后系统仍是绿的（所有旧测试通过）。

---

### Task 1: 新增 `DiffType.FIELD_MISSING` 枚举 + 汇总记录 helper

**Files:**
- Modify: `src/datacompare/engine/result.py`
- Create: `src/datacompare/engine/_field_missing.py`
- Test: `tests/unit/engine/test_result.py`
- Test: `tests/unit/engine/test_field_missing_helper.py`（新建）

- [ ] **Step 1: 写失败测试 — 枚举新值存在**

追加到 `tests/unit/engine/test_result.py`：

```python
def test_diff_type_field_missing_enum_value():
    from datacompare.engine.result import DiffType
    assert DiffType.FIELD_MISSING.value == "field_missing"
```

- [ ] **Step 2: 运行确认测试失败**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py::test_diff_type_field_missing_enum_value -v`
Expected: FAIL with `AttributeError: FIELD_MISSING`

- [ ] **Step 3: 修改 `src/datacompare/engine/result.py`**

在 `DiffType` 枚举内追加一行：

```python
class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    REGEX_ERROR = "regex_error"
    NULL_MISMATCH = "null_mismatch"
    FIELD_MISSING = "field_missing"
```

- [ ] **Step 4: 运行确认测试通过**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py -v`
Expected: PASS

- [ ] **Step 5: 写失败测试 — helper 构建左侧缺列汇总记录**

创建 `tests/unit/engine/test_field_missing_helper.py`：

```python
from datacompare.engine._field_missing import _build_field_missing_record


def test_build_record_left_missing():
    record = _build_field_missing_record(
        field_canonical="vmemorys",
        side_missing="left",
        key_cols=["id", "reId"],
        other_side_row_count=10000,
    )
    assert record == {
        "id": "",
        "reId": "",
        "field": "vmemorys",
        "left_value": "字段不存在",
        "right_value": "(右侧 10000 行有值)",
        "diff_type": "field_missing",
    }


def test_build_record_right_missing():
    record = _build_field_missing_record(
        field_canonical="hostname",
        side_missing="right",
        key_cols=["id"],
        other_side_row_count=500,
    )
    assert record == {
        "id": "",
        "field": "hostname",
        "left_value": "(左侧 500 行有值)",
        "right_value": "字段不存在",
        "diff_type": "field_missing",
    }


def test_build_record_no_key_cols():
    record = _build_field_missing_record(
        field_canonical="x",
        side_missing="left",
        key_cols=[],
        other_side_row_count=1,
    )
    assert record == {
        "field": "x",
        "left_value": "字段不存在",
        "right_value": "(右侧 1 行有值)",
        "diff_type": "field_missing",
    }
```

- [ ] **Step 6: 运行确认测试失败**

Run: `.venv/Scripts/pytest tests/unit/engine/test_field_missing_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'datacompare.engine._field_missing'`

- [ ] **Step 7: 创建 helper 模块**

写文件 `src/datacompare/engine/_field_missing.py`：

```python
"""Helper for constructing field-missing summary diff records.

Used by memory and disk engines when a compare field's column is absent on
exactly one side (single-side miss). Both-sides miss raises earlier;
key miss raises even earlier in apply_column_mapping.
"""
from __future__ import annotations
from typing import Literal
from .result import DiffType


def _build_field_missing_record(
    field_canonical: str,
    side_missing: Literal["left", "right"],
    key_cols: list[str],
    other_side_row_count: int,
) -> dict:
    """Build one summary diff row for a field that is missing on `side_missing`.

    Key columns are filled with empty strings — this record is structural, not
    row-specific. The present side's value describes total row count on that
    side (not matched row count), because "how many rows would have compared"
    is meaningless when a whole column is absent.
    """
    record: dict = {k: "" for k in key_cols}
    record["field"] = field_canonical
    if side_missing == "left":
        record["left_value"] = "字段不存在"
        record["right_value"] = f"(右侧 {other_side_row_count} 行有值)"
    else:
        record["left_value"] = f"(左侧 {other_side_row_count} 行有值)"
        record["right_value"] = "字段不存在"
    record["diff_type"] = DiffType.FIELD_MISSING.value
    return record
```

- [ ] **Step 8: 运行确认测试通过**

Run: `.venv/Scripts/pytest tests/unit/engine/test_field_missing_helper.py tests/unit/engine/test_result.py -v`
Expected: 全部 PASS

- [ ] **Step 9: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 所有旧测试仍绿（本 Task 未改任何调用方）

- [ ] **Step 10: Commit**

```bash
git add src/datacompare/engine/result.py src/datacompare/engine/_field_missing.py tests/unit/engine/test_result.py tests/unit/engine/test_field_missing_helper.py
git commit -m "$(cat <<'EOF'
feat(engine): add DiffType.FIELD_MISSING + _build_field_missing_record helper

Foundation for v0.8 field-missing soft-fail: enum value + shared record
builder (memory/disk engines will consume in later tasks).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `apply_column_mapping` 返回 `(df, missing_field_canonicals)`

**Files:**
- Modify: `src/datacompare/normalize/columns.py`
- Modify: `src/datacompare/normalize/pipeline.py`（调用点解包）
- Modify: `tests/unit/normalize/test_columns.py`（迁移全部旧断言到 `[0]` 或 `df, _`）

- [ ] **Step 1: 写失败测试 — 缺 field 时不 raise、返回 missing 集**

追加到 `tests/unit/normalize/test_columns.py`：

```python
def test_apply_column_mapping_field_missing_returns_marker():
    """v0.8: field 缺列不再 raise，而是从结果 df 剔除并加入 missing set。"""
    df = pd.DataFrame({"id": ["1", "2"], "vmemory": ["16", "32"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="vmemorys", right="vmemorys"),  # 打字错误，左侧无此列
        FieldRule(left="vmemory", right="vmemory"),    # 存在
    ]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset({"vmemorys"})
    assert list(result_df.columns) == ["id", "vmemory"]
    assert result_df["vmemory"].tolist() == ["16", "32"]


def test_apply_column_mapping_no_field_missing_returns_empty_frozenset():
    df = pd.DataFrame({"id": ["1"], "amt": ["10"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="amt", right="amount")]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset()
    assert list(result_df.columns) == ["id", "amount"]


def test_apply_column_mapping_multiple_field_missing_all_reported():
    df = pd.DataFrame({"id": ["1"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="a", right="a"),
        FieldRule(left="b", right="b"),
        FieldRule(left="c", right="c"),
    ]
    _df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset({"a", "b", "c"})


def test_apply_column_mapping_key_missing_still_raises():
    """v0.8: key 缺列仍然硬失败（不像 field 那样软化）。"""
    from datacompare.config.errors import ConfigError
    df = pd.DataFrame({"amount": ["10"]})   # 无 id 列
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="amount", right="amount")]
    with pytest.raises(ConfigError) as excinfo:
        apply_column_mapping(df, keys, fields, side="left")
    assert "id" in str(excinfo.value)


def test_apply_column_mapping_literal_field_untouched_by_missing_check():
    """Literal 字段在该侧没有 source 列 → 不算 missing。"""
    df = pd.DataFrame({"id": ["1"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone")]
    result_df, missing = apply_column_mapping(df, keys, fields, side="left")
    assert missing == frozenset()
    assert "zone" in result_df.columns
```

在文件顶部 imports 加：
```python
import pytest
```
（若已存在，跳过）

- [ ] **Step 2: 运行新测试确认失败**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py::test_apply_column_mapping_field_missing_returns_marker -v`
Expected: FAIL — 当前 apply_column_mapping 抛 `ConfigError` 或返回单值

- [ ] **Step 3: 修改 `src/datacompare/normalize/columns.py::apply_column_mapping`**

替换现有函数（第 73-123 行）为：

```python
def apply_column_mapping(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    fields: list[FieldRule],
    side: Literal["left", "right"],
) -> tuple[pd.DataFrame, frozenset[str]]:
    """Build a new DataFrame with canonical-named columns.

    Task-list model (v0.6+): each key/field produces a (source_col, canonical)
    pair. A source column may appear in multiple pairs — it gets copied under
    each canonical name.

    v0.8 缺列语义：
      - key 缺列 → 立即抛 ConfigError（key 是硬约束，没 key 无法 join）
      - field 缺列 → 从结果 df 剔除，其 canonical 加入 missing_field_canonicals
        返回集；下游 engine 决定汇总行为
      - literal 字段（该侧无 source 列）不进 missing 检测

    Returns:
        (df_with_canonical_columns, missing_field_canonicals)
    """
    key_tasks: list[tuple[str, str]] = []             # (source_col, canonical)
    field_tasks: list[tuple[str, str]] = []           # (source_col, canonical)
    literal_fields: list[tuple[str, str | None]] = [] # (canonical, literal_value)

    for k in keys:
        key_tasks.append((getattr(k, side), key_canonical_name(k)))
    for f in fields:
        src = getattr(f, side)
        canonical = field_canonical_name(f)
        if src is not None:
            field_tasks.append((src, canonical))
        else:
            literal_fields.append((canonical, getattr(f, f"{side}_literal")))

    # key 缺列 → 硬失败（不变）
    key_missing_sources = [src for src, _ in key_tasks if src not in df.columns]
    if key_missing_sources:
        from datacompare.config.errors import ConfigError
        raise ConfigError(
            f"columns not found in {side} source: {key_missing_sources}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )

    # field 缺列 → 从 field_tasks 剔除，收集 canonical
    missing_field_canonicals: set[str] = set()
    surviving_field_tasks: list[tuple[str, str]] = []
    for src, canonical in field_tasks:
        if src not in df.columns:
            missing_field_canonicals.add(canonical)
        else:
            surviving_field_tasks.append((src, canonical))

    # 拷贝：先 key，后存活的 field，再 literal
    result = pd.DataFrame(index=df.index)
    for src, canonical in key_tasks:
        result[canonical] = df[src].values
    for src, canonical in surviving_field_tasks:
        result[canonical] = df[src].values
    for canonical, literal_val in literal_fields:
        result[canonical] = literal_val

    return result, frozenset(missing_field_canonicals)
```

- [ ] **Step 4: 修改 `src/datacompare/normalize/pipeline.py::normalize_side` 内的调用**

在 pipeline.py 中找到（约第 69 行）：
```python
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
```

改为：
```python
    renamed, missing_field_canonicals = apply_column_mapping(df, keys, compare.fields, side=side)
```

（本 Task 暂不动 `normalize_side` 的返回类型，`missing_field_canonicals` 在 Task 3 才会外传。这里先赋值但先不使用，让 pipeline 编译通过。）

在函数末尾 return 之前，加一个安全断言防止下游步骤误访问缺失列（在 Step 5 的迁移测试里也需要）：

```python
    # v0.8: 后续 regex/coerce/decimal 步骤应通过 `if col in result.columns` 天然跳过缺列，
    # 但显式过滤 field 列名列表能防止未来重构误引入 KeyError。
    ...
```

**具体做法**：把最后一行 return 改为只 select 现有列：

原（约第 97 行）：
```python
    return result[key_cols + [field_canonical_name(f) for f in compare.fields]]
```

改为：
```python
    surviving_field_cols = [
        field_canonical_name(f)
        for f in compare.fields
        if field_canonical_name(f) not in missing_field_canonicals
    ]
    return result[key_cols + surviving_field_cols]
```

同理，在 pipeline.py 里 Step 4 迭代 fields 做 `_process_value` 的循环（约第 93-96 行），也加上跳过：

原：
```python
    for rule in compare.fields:
        eff = effective_rule(rule, compare.defaults)
        col = field_canonical_name(rule)
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
```

改为：
```python
    for rule in compare.fields:
        col = field_canonical_name(rule)
        if col in missing_field_canonicals:
            continue
        eff = effective_rule(rule, compare.defaults)
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
```

**注意** Step 2/3 的 regex map 循环使用 `field_canonical_name(f)` 作为 map 键。`apply_regex_on_canonical` 内部通过 `if col in df.columns` 判断，缺列会天然跳过，无需额外过滤。但为了显式：

原（约第 84-89 行）：
```python
    field_regex_map: dict[str, str] = {}
    for f in compare.fields:
        pattern = getattr(f, f"{side}_regex")
        if pattern is not None:
            field_regex_map[field_canonical_name(f)] = pattern
    apply_regex_on_canonical(renamed, field_regex_map, mode="soft")
```

改为：
```python
    field_regex_map: dict[str, str] = {}
    for f in compare.fields:
        canonical = field_canonical_name(f)
        if canonical in missing_field_canonicals:
            continue
        pattern = getattr(f, f"{side}_regex")
        if pattern is not None:
            field_regex_map[canonical] = pattern
    apply_regex_on_canonical(renamed, field_regex_map, mode="soft")
```

- [ ] **Step 5: 迁移 `tests/unit/normalize/test_columns.py` 现有旧测试到 tuple 返回**

用 `Edit` 或 `Grep` 找所有 `apply_column_mapping(` 调用点，把 `result = apply_column_mapping(...)` 改为 `result, _ = apply_column_mapping(...)`。

具体要改的旧测试（每个都要改）：
- `test_apply_column_mapping_left_side`
- `test_apply_column_mapping_right_side_no_rename_needed`
- `test_apply_column_mapping_left_col_named_like_right_key_no_collision`
- `test_apply_column_mapping_left_literal_injects_constant_column`
- `test_apply_column_mapping_right_literal_injects_constant_column`
- `test_apply_column_mapping_left_literal_null`
- `test_apply_column_mapping_literal_on_empty_dataframe`
- `test_apply_column_mapping_mixed_column_and_literal_fields`
- `test_apply_column_mapping_left_side_with_right_literal_field`
- `test_apply_column_mapping_key_alias_uses_alias_as_canonical`
- `test_apply_column_mapping_same_source_column_duplicated_for_key_and_field`
- `test_apply_column_mapping_left_side_with_key_alias_and_stray_col`

每处：`result = apply_column_mapping(...)` → `result, _ = apply_column_mapping(...)`（其余断言不变）。

- [ ] **Step 6: 运行所有相关测试**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -v`
Expected: 全部 PASS（旧测试迁移完 + 新缺列测试通过）

- [ ] **Step 7: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（`normalize_side` 内部已解包新签名；engines 通过 `normalize_side` 间接调用，暂无破坏）

- [ ] **Step 8: Commit**

```bash
git add src/datacompare/normalize/columns.py src/datacompare/normalize/pipeline.py tests/unit/normalize/test_columns.py
git commit -m "$(cat <<'EOF'
refactor(normalize): apply_column_mapping returns (df, missing_field_canonicals)

field 缺列不再抛 ConfigError，改为返回 missing canonical 集合；key 缺列仍
硬失败。pipeline.py 内部解包并跳过缺列的 regex/coerce/decimal 步骤。旧测试
迁移到 tuple 返回值。engine 层暂未消费 missing 信息（Task 3/4 处理）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `NormalizedSide` 数据类 + `normalize_side` 返回类型变更

**Files:**
- Modify: `src/datacompare/normalize/pipeline.py`（新增 NormalizedSide + 返回改造）
- Modify: `src/datacompare/engine/memory.py`（消费点 unpack `.df`）
- Modify: `src/datacompare/engine/disk.py`（消费点 unpack `.df`）
- Modify: `tests/unit/normalize/test_pipeline.py`（迁移到 `.df` 访问）

- [ ] **Step 1: 写失败测试 — normalize_side 返回 NormalizedSide**

追加到 `tests/unit/normalize/test_pipeline.py`：

```python
def test_normalize_side_returns_normalized_side_dataclass():
    from datacompare.normalize.pipeline import NormalizedSide
    df = pd.DataFrame({"id": ["1"], "amt": ["10"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="amt", right="amount")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert isinstance(result, NormalizedSide)
    assert isinstance(result.df, pd.DataFrame)
    assert result.missing_field_canonicals == frozenset()


def test_normalize_side_reports_missing_field_canonicals():
    df = pd.DataFrame({"id": ["1"], "vmemory": ["16"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="vmemorys", right="vmemorys"),   # 打字错误 → 缺列
        FieldRule(left="vmemory", right="vmemory"),     # 存在
    ]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.missing_field_canonicals == frozenset({"vmemorys"})
    assert list(result.df.columns) == ["id", "vmemory"]


def test_normalize_side_skips_normalization_for_missing_field():
    """缺列的 field 不参与 regex/coerce/decimal 步骤（否则会 KeyError）。"""
    df = pd.DataFrame({"id": ["1"], "amt": ["10.556"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="missing_col", right="missing_col",
                  mode="numeric", decimal_places=2),   # 缺列 + numeric 会 KeyError 如未跳过
        FieldRule(left="amt", right="amount",
                  mode="numeric", decimal_places=2),
    ]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    # 若未跳过缺列的 numeric 处理，此行会 KeyError；能走到断言即证明跳过成功
    assert result.missing_field_canonicals == frozenset({"missing_col"})
    assert result.df.iloc[0]["amount"] == 10.56
```

- [ ] **Step 2: 运行新测试确认失败**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py::test_normalize_side_returns_normalized_side_dataclass -v`
Expected: FAIL with `ImportError: cannot import name 'NormalizedSide'`

- [ ] **Step 3: 修改 `src/datacompare/normalize/pipeline.py`**

在文件顶部 imports 后增加 dataclass：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedSide:
    """`normalize_side` 的返回值。纯数据容器。

    - df: 归一化后的 DataFrame，含 key canonical 列 + 存在的 field canonical 列
    - missing_field_canonicals: 该侧因源列缺失被跳过的 field canonical 集合
    """
    df: "pd.DataFrame"
    missing_field_canonicals: frozenset[str]
```

修改 `normalize_side` 函数签名与返回：

```python
def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> NormalizedSide:
```

函数末尾原：
```python
    return result[key_cols + surviving_field_cols]
```

改为：
```python
    return NormalizedSide(
        df=result[key_cols + surviving_field_cols],
        missing_field_canonicals=missing_field_canonicals,
    )
```

- [ ] **Step 4: 更新 `src/datacompare/engine/memory.py` 消费点**

`InMemoryEngine.compare` 内（约第 61-62 行）：

原：
```python
        ldf = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        rdf = normalize_side(right_raw, task.match.keys, task.compare, side="right")
```

改为（本 Task 只 unpack，不使用 missing 集合，避免破坏）：
```python
        left_side = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        right_side = normalize_side(right_raw, task.match.keys, task.compare, side="right")
        ldf = left_side.df
        rdf = right_side.df
```

（Task 4 会替换整个 compare 方法，让它真正消费 missing。这里保持最小改动确保绿。）

- [ ] **Step 5: 更新 `src/datacompare/engine/disk.py` 消费点**

`_normalize_all` 静态方法内（约第 141-143 行）：

原：
```python
        chunks = []
        for chunk in src.read():
            chunks.append(normalize_side(chunk, task.match.keys, task.compare, side=side))
        if not chunks:
            return pd.DataFrame()
        return pd.concat(chunks, ignore_index=True)
```

改为：
```python
        dfs = []
        for chunk in src.read():
            side_result = normalize_side(chunk, task.match.keys, task.compare, side=side)
            dfs.append(side_result.df)
        if not dfs:
            return pd.DataFrame()
        return pd.concat(dfs, ignore_index=True)
```

**注意**：`_normalize_all` 会调用 `normalize_side` 多次（每 chunk 一次），missing 集在 chunk 之间应该一致（来自同一 task config），但 disk 引擎当前把 missing 信息丢弃了。Task 5 会重写 disk 的 compare，届时再重构。

- [ ] **Step 6: 迁移 `tests/unit/normalize/test_pipeline.py` 现有旧测试**

现有测试直接对 `normalize_side` 返回值做 `.columns` / `.iloc` / `list(...)` 等 DataFrame 访问，需改为 `.df.columns` / `.df.iloc[0]` 等。

要改的测试（每个都要）：
- `test_pipeline_renames_and_filters_columns` — `result.columns` → `result.df.columns`
- `test_numeric_rounding` — `result.iloc[0]` → `result.df.iloc[0]`
- `test_null_equivalent_becomes_none` — 同上
- `test_unit_parse` — 同上
- `test_string_case_and_whitespace` — 同上
- `test_pipeline_applies_left_regex_before_join` — `result.columns` 和 `result.iloc[0]` 都改
- `test_pipeline_applies_right_regex` — `result.iloc[0]` → `result.df.iloc[0]`

`test_pipeline_raises_key_regex_mismatch_error` — 不需改（只 raise 断言，不访问返回值）。

如 `test_pipeline.py` 还有其它 `result.` 或 `result[` 调用点，用 grep 通盘查一次：

```bash
.venv/Scripts/python -c "import re, pathlib; p = pathlib.Path('tests/unit/normalize/test_pipeline.py'); print([i for i, l in enumerate(p.read_text().splitlines(), 1) if 'result.' in l or 'result[' in l])"
```

对每一行手动确认是否需 `.df` 前缀。

- [ ] **Step 7: 运行 pipeline 测试**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -v`
Expected: 全部 PASS

- [ ] **Step 8: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（engines 已 unpack `.df`；miss 信息暂被丢弃但不影响现有功能）

- [ ] **Step 9: Commit**

```bash
git add src/datacompare/normalize/pipeline.py src/datacompare/engine/memory.py src/datacompare/engine/disk.py tests/unit/normalize/test_pipeline.py
git commit -m "$(cat <<'EOF'
refactor(normalize): normalize_side returns NormalizedSide(df, missing_field_canonicals)

新增 frozen dataclass NormalizedSide 承载 df 和缺列 canonical 集合。engines
暂只 unpack .df；缺列消费在 Task 4/5 完成。旧 pipeline 测试迁移到 .df 访问。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Engine memory — 双侧缺检查 + 汇总 diff + left_only/right_only 补齐

**Files:**
- Modify: `src/datacompare/engine/memory.py`
- Test: `tests/unit/engine/test_memory.py`

- [ ] **Step 1: 写失败测试 — 单字段左缺产生汇总记录**

追加到 `tests/unit/engine/test_memory.py`（如需要参考现有测试模式，先 Read 该文件前 50 行）：

```python
def test_field_missing_on_left_produces_summary_diff():
    """左侧缺 vmemorys 字段 → 该字段跳过 per-row，追加一条汇总。"""
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.engine.result import DiffType
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    left_df = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "b", "c"]})
    right_df = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "b", "c"],
                             "vmemorys": ["16", "32", "64"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="vmemorys", right="vmemorys"),   # 左缺
        ]),
        output=OutputConfig(dir="./out"),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)

    # matched_rows 不变
    assert result.matched_rows == 3
    assert result.identical_rows == 3   # name 都相同
    # diff_rows 只 +1（一条汇总）
    assert result.diff_rows == 1
    field_missing_records = result.diff_details[
        result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    assert len(field_missing_records) == 1
    r = field_missing_records.iloc[0]
    assert r["field"] == "vmemorys"
    assert r["left_value"] == "字段不存在"
    assert r["right_value"] == "(右侧 3 行有值)"
    assert r["id"] == ""


def test_field_missing_on_right_produces_summary_diff():
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.engine.result import DiffType
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    left_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                            "hostname": ["h1", "h2"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="hostname", right="hostname"),
        ]),
        output=OutputConfig(dir="./out"),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)

    r = result.diff_details[result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value].iloc[0]
    assert r["field"] == "hostname"
    assert r["left_value"] == "(左侧 2 行有值)"
    assert r["right_value"] == "字段不存在"


def test_field_missing_on_both_sides_raises_config_error():
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.config.errors import ConfigError
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    left_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="both_missing", right="both_missing"),
        ]),
        output=OutputConfig(dir="./out"),
    )
    with pytest.raises(ConfigError) as excinfo:
        InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    assert "both_missing" in str(excinfo.value)


def test_field_missing_multiple_fields_ordering_matches_declaration():
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.engine.result import DiffType
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    # 字段声明顺序: id_field, missL, missR, name
    left_df = pd.DataFrame({"id": ["1"], "id_field": ["v1"], "missR": ["r1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "id_field": ["v1"], "missL": ["l1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="id_field", right="id_field"),
            FieldRule(left="missL", right="missL"),   # 左缺
            FieldRule(left="missR", right="missR"),   # 右缺
            FieldRule(left="name", right="name"),
        ]),
        output=OutputConfig(dir="./out"),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    fm = result.diff_details[result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value]
    assert fm["field"].tolist() == ["missL", "missR"]  # 按声明顺序


def test_field_missing_left_only_rows_padded_with_placeholder():
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    # 左独有 id=99；左缺 hostname 字段
    left_df = pd.DataFrame({"id": ["1", "99"], "name": ["a", "z"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                             "hostname": ["h1", "h2"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"}, "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="hostname", right="hostname"),   # 左缺
        ]),
        output=OutputConfig(dir="./out"),
    )
    result = InMemoryEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
    # left_only_rows 中缺失的 hostname 列应补 "字段不存在"
    assert "hostname" in result.left_only_rows.columns
    assert (result.left_only_rows["hostname"] == "字段不存在").all()
```

- [ ] **Step 2: 运行新测试确认失败**

Run: `.venv/Scripts/pytest tests/unit/engine/test_memory.py::test_field_missing_on_left_produces_summary_diff -v`
Expected: FAIL — 当前 memory 引擎会因缺列在 apply_column_mapping 层 raise（Task 2 已改）或 diff_details 不含 field_missing 类型

- [ ] **Step 3: 重写 `src/datacompare/engine/memory.py::InMemoryEngine.compare`**

在文件顶部 imports 追加：
```python
from datacompare.config.errors import ConfigError
from datacompare.engine._field_missing import _build_field_missing_record
```

替换现有 `InMemoryEngine.compare` 方法为：

```python
class InMemoryEngine(CompareEngine):
    def compare(
        self, left: DataSource, right: DataSource, task: TaskConfig,
    ) -> CompareResult:
        started = time.perf_counter()
        left_raw = pd.concat(list(left.read()), ignore_index=True)
        right_raw = pd.concat(list(right.read()), ignore_index=True)

        left_total = len(left_raw)
        right_total = len(right_raw)

        key_cols = [key_canonical_name(k) for k in task.match.keys]
        field_cols = [field_canonical_name(f) for f in task.compare.fields]

        left_side = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        right_side = normalize_side(right_raw, task.match.keys, task.compare, side="right")
        ldf = left_side.df
        rdf = right_side.df

        # v0.8: 双侧同 field 缺 → 硬失败
        both_missing = left_side.missing_field_canonicals & right_side.missing_field_canonicals
        if both_missing:
            raise ConfigError(
                f"compare fields not found in either source: {sorted(both_missing)}",
                path="compare.fields",
                suggestion=(
                    f"available left={list(left_raw.columns)}, "
                    f"available right={list(right_raw.columns)}"
                ),
            )

        # duplicate key check
        for label, df in (("left", ldf), ("right", rdf)):
            dupes = df[df.duplicated(subset=key_cols, keep=False)]
            if not dupes.empty:
                keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                raise ValueError(f"duplicate keys in {label} side: {keys_display}")

        merged = ldf.merge(
            rdf, on=key_cols, how="outer", indicator=True,
            suffixes=("__left", "__right"),
        )

        both = merged[merged["_merge"] == "both"]
        left_only_mask = merged["_merge"] == "left_only"
        right_only_mask = merged["_merge"] == "right_only"

        diff_records: list[dict] = []
        errors: list[FieldError] = []
        identical_mask = pd.Series(True, index=both.index)

        for f in task.compare.fields:
            canonical = field_canonical_name(f)
            # v0.8: 单侧缺 → 追加一条汇总记录，跳过 per-row
            if canonical in left_side.missing_field_canonicals:
                diff_records.append(_build_field_missing_record(
                    field_canonical=canonical, side_missing="left",
                    key_cols=key_cols, other_side_row_count=right_total,
                ))
                continue
            if canonical in right_side.missing_field_canonicals:
                diff_records.append(_build_field_missing_record(
                    field_canonical=canonical, side_missing="right",
                    key_cols=key_cols, other_side_row_count=left_total,
                ))
                continue

            lcol = f"{canonical}__left"
            rcol = f"{canonical}__right"
            for idx, row in both.iterrows():
                lv, rv = row[lcol], row[rcol]
                if not _values_equal(lv, rv):
                    identical_mask.at[idx] = False
                    diff_records.append({
                        **{k: row[k] for k in key_cols},
                        "field": canonical,
                        "left_value": _display(lv),
                        "right_value": _display(rv),
                        "diff_type": _classify(lv, rv),
                    })
                if isinstance(lv, (CoerceError, UnitError, RegexError)):
                    if isinstance(lv, CoerceError):
                        kind = "type_error"
                    elif isinstance(lv, UnitError):
                        kind = "unit_error"
                    else:
                        kind = "regex_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=lv.original,
                    ))
                if isinstance(rv, (CoerceError, UnitError, RegexError)):
                    if isinstance(rv, CoerceError):
                        kind = "type_error"
                    elif isinstance(rv, UnitError):
                        kind = "unit_error"
                    else:
                        kind = "regex_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=rv.original,
                    ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        # v0.8: 汇总记录也计入 diff_rows；identical_rows 只受 per-row 影响
        # 所以 diff_rows 不再等于 matched_rows - identical_rows，而是显式计数
        summary_missing_count = sum(
            1 for f in task.compare.fields
            if field_canonical_name(f) in left_side.missing_field_canonicals
            or field_canonical_name(f) in right_side.missing_field_canonicals
        )
        diff_rows = (matched_rows - identical_rows) + summary_missing_count

        # v0.8: left_only_rows / right_only_rows 补齐缺列
        # 存活字段列走原路径 rename；缺失字段列填 "字段不存在" 常量
        surviving_left_field_cols = [
            c for c in field_cols if c not in left_side.missing_field_canonicals
        ]
        surviving_right_field_cols = [
            c for c in field_cols if c not in right_side.missing_field_canonicals
        ]

        left_only_df = merged[left_only_mask][
            key_cols + [f"{c}__left" for c in surviving_left_field_cols]
        ]
        left_only_df = left_only_df.rename(
            columns={f"{c}__left": c for c in surviving_left_field_cols}
        ).copy()
        for c in left_side.missing_field_canonicals:
            left_only_df[c] = "字段不存在"
        # 保证列顺序与 field_cols 一致
        left_only_df = left_only_df[key_cols + field_cols]

        right_only_df = merged[right_only_mask][
            key_cols + [f"{c}__right" for c in surviving_right_field_cols]
        ]
        right_only_df = right_only_df.rename(
            columns={f"{c}__right": c for c in surviving_right_field_cols}
        ).copy()
        for c in right_side.missing_field_canonicals:
            right_only_df[c] = "字段不存在"
        right_only_df = right_only_df[key_cols + field_cols]

        diff_df = pd.DataFrame(diff_records)

        return CompareResult(
            task_name=task.name,
            left_name=left.name,
            right_name=right.name,
            left_total=left_total,
            right_total=right_total,
            matched_rows=matched_rows,
            identical_rows=identical_rows,
            diff_rows=diff_rows,
            left_only=int(left_only_mask.sum()),
            right_only=int(right_only_mask.sum()),
            diff_details=diff_df,
            left_only_rows=left_only_df,
            right_only_rows=right_only_df,
            engine_used="memory",
            duration_seconds=time.perf_counter() - started,
            errors=errors,
        )
```

- [ ] **Step 4: 运行新测试**

Run: `.venv/Scripts/pytest tests/unit/engine/test_memory.py -v -k field_missing`
Expected: 5 个 field_missing 测试全 PASS

- [ ] **Step 5: 运行 memory 全部旧测试**

Run: `.venv/Scripts/pytest tests/unit/engine/test_memory.py -v`
Expected: 全绿（旧测试不涉及缺列，diff_rows 计算等价）

- [ ] **Step 6: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（disk 引擎仍走旧路径，未消费 missing；下一 Task 处理）

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/engine/memory.py tests/unit/engine/test_memory.py
git commit -m "$(cat <<'EOF'
feat(engine/memory): field-missing soft-fail — summary diff + left_only padding

单侧 field 缺列 → 跳过 per-row，追加一条汇总 diff（left_value/right_value =
"字段不存在"，key 列填空串）。双侧同 field 缺 → ConfigError。
left_only_rows/right_only_rows 中缺失字段列补 "字段不存在"，schema 齐整。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Engine disk — 镜像 memory 改动 + parity 测试

**Files:**
- Modify: `src/datacompare/engine/disk.py`
- Test: `tests/unit/engine/test_disk.py`

- [ ] **Step 1: 写失败测试 — disk 与 memory 的缺列语义等价**

追加到 `tests/unit/engine/test_disk.py`（先 Read 该文件了解现有测试模式）：

```python
def test_disk_engine_field_missing_parity_with_memory():
    """同样的 fixture，disk 和 memory 引擎对缺列的处理应一致。"""
    from datacompare.engine.memory import InMemoryEngine
    from datacompare.engine.disk import DiskEngine
    from datacompare.engine.result import DiffType
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    left_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"]})
    right_df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"],
                             "vmemorys": ["16", "32"]})

    def _make_task():
        return TaskConfig(
            name="t",
            sources={"left": {"type": "excel", "path": "x"},
                     "right": {"type": "excel", "path": "x"}},
            match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
            compare=CompareConfig(defaults=CompareDefaults(), fields=[
                FieldRule(left="name", right="name"),
                FieldRule(left="vmemorys", right="vmemorys"),
            ]),
            output=OutputConfig(dir="./out"),
        )

    mem_result = InMemoryEngine().compare(
        _StubSource("L", left_df), _StubSource("R", right_df), _make_task(),
    )
    disk_result = DiskEngine().compare(
        _StubSource("L", left_df), _StubSource("R", right_df), _make_task(),
    )

    assert mem_result.diff_rows == disk_result.diff_rows
    mem_fm = mem_result.diff_details[
        mem_result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    disk_fm = disk_result.diff_details[
        disk_result.diff_details["diff_type"] == DiffType.FIELD_MISSING.value
    ]
    assert len(mem_fm) == len(disk_fm) == 1
    assert mem_fm.iloc[0]["field"] == disk_fm.iloc[0]["field"] == "vmemorys"
    assert mem_fm.iloc[0]["left_value"] == disk_fm.iloc[0]["left_value"] == "字段不存在"


def test_disk_engine_both_sides_field_missing_raises():
    from datacompare.engine.disk import DiskEngine
    from datacompare.config.errors import ConfigError
    from datacompare.config.models import (
        TaskConfig, MatchConfig, CompareConfig, CompareDefaults,
        KeyMapping, FieldRule, OutputConfig,
    )
    from datacompare.sources.base import DataSource

    class _StubSource(DataSource):
        def __init__(self, name, df):
            self._name, self._df = name, df
        @property
        def name(self): return self._name
        def columns(self): return list(self._df.columns)
        def estimated_rows(self): return len(self._df)
        def read(self, chunk_size=None):
            yield self._df.astype(object)

    import pandas as pd
    left_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    right_df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    task = TaskConfig(
        name="t",
        sources={"left": {"type": "excel", "path": "x"},
                 "right": {"type": "excel", "path": "x"}},
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(defaults=CompareDefaults(), fields=[
            FieldRule(left="name", right="name"),
            FieldRule(left="both_missing", right="both_missing"),
        ]),
        output=OutputConfig(dir="./out"),
    )
    with pytest.raises(ConfigError):
        DiskEngine().compare(_StubSource("L", left_df), _StubSource("R", right_df), task)
```

- [ ] **Step 2: 运行新测试确认失败**

Run: `.venv/Scripts/pytest tests/unit/engine/test_disk.py::test_disk_engine_field_missing_parity_with_memory -v`
Expected: FAIL — disk 引擎当前会在 `_normalize_all` 后丢失 missing 信息，per-field 循环访问不存在的列会 KeyError

- [ ] **Step 3: 重写 `src/datacompare/engine/disk.py::DiskEngine.compare` 和 `_normalize_all`**

在文件顶部 imports 追加：
```python
from datacompare.config.errors import ConfigError
from datacompare.engine._field_missing import _build_field_missing_record
```

替换 `_normalize_all` 静态方法：
```python
    @staticmethod
    def _normalize_all(src: DataSource, task: TaskConfig, side: str):
        """Returns (concatenated_df, missing_field_canonicals). Missing 集合在
        chunk 之间应一致（来自同一 task config），取首个 chunk 的即可。"""
        from datacompare.normalize.pipeline import normalize_side, NormalizedSide
        dfs = []
        missing: frozenset[str] = frozenset()
        for chunk in src.read():
            side_result = normalize_side(chunk, task.match.keys, task.compare, side=side)
            dfs.append(side_result.df)
            missing = side_result.missing_field_canonicals   # 后覆盖前，等价
        if not dfs:
            return pd.DataFrame(), missing
        return pd.concat(dfs, ignore_index=True), missing
```

替换 `DiskEngine.compare`：
```python
    def compare(self, left: DataSource, right: DataSource, task: TaskConfig) -> CompareResult:
        started = time.perf_counter()
        con = duckdb.connect()   # reserved for future SQL JOIN optimization
        key_cols = [key_canonical_name(k) for k in task.match.keys]
        field_cols = [field_canonical_name(f) for f in task.compare.fields]

        left_df, left_missing = self._normalize_all(left, task, "left")
        right_df, right_missing = self._normalize_all(right, task, "right")

        left_total = len(left_df)
        right_total = len(right_df)

        # 双侧同 field 缺 → 硬失败
        both_missing = left_missing & right_missing
        if both_missing:
            con.close()
            raise ConfigError(
                f"compare fields not found in either source: {sorted(both_missing)}",
                path="compare.fields",
                suggestion=(
                    f"available left={list(left_df.columns)}, "
                    f"available right={list(right_df.columns)}"
                ),
            )

        for label, df in (("left", left_df), ("right", right_df)):
            dupes = df[df.duplicated(subset=key_cols, keep=False)]
            if not dupes.empty:
                keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                raise ValueError(f"duplicate keys in {label} side: {keys_display}")

        merged = left_df.merge(
            right_df, on=key_cols, how="outer", indicator=True,
            suffixes=("__left", "__right"),
        )
        both = merged[merged["_merge"] == "both"]
        left_only_mask = merged["_merge"] == "left_only"
        right_only_mask = merged["_merge"] == "right_only"

        diff_records: list[dict] = []
        errors: list[FieldError] = []
        identical_mask = pd.Series(True, index=both.index)

        for f in task.compare.fields:
            canonical = field_canonical_name(f)
            if canonical in left_missing:
                diff_records.append(_build_field_missing_record(
                    field_canonical=canonical, side_missing="left",
                    key_cols=key_cols, other_side_row_count=right_total,
                ))
                continue
            if canonical in right_missing:
                diff_records.append(_build_field_missing_record(
                    field_canonical=canonical, side_missing="right",
                    key_cols=key_cols, other_side_row_count=left_total,
                ))
                continue
            lcol = f"{canonical}__left"
            rcol = f"{canonical}__right"
            for idx, row in both.iterrows():
                lv, rv = row[lcol], row[rcol]
                if not _values_equal(lv, rv):
                    identical_mask.at[idx] = False
                    diff_records.append({
                        **{k: row[k] for k in key_cols},
                        "field": canonical,
                        "left_value": _display(lv),
                        "right_value": _display(rv),
                        "diff_type": _classify(lv, rv),
                    })
                for side_v in (lv, rv):
                    if isinstance(side_v, CoerceError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=canonical, kind="type_error", original=side_v.original,
                        ))
                    elif isinstance(side_v, UnitError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=canonical, kind="unit_error", original=side_v.original,
                        ))
                    elif isinstance(side_v, RegexError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=canonical, kind="regex_error", original=side_v.original,
                        ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        summary_missing_count = sum(
            1 for f in task.compare.fields
            if field_canonical_name(f) in left_missing
            or field_canonical_name(f) in right_missing
        )
        diff_rows = (matched_rows - identical_rows) + summary_missing_count

        surviving_left_field_cols = [c for c in field_cols if c not in left_missing]
        surviving_right_field_cols = [c for c in field_cols if c not in right_missing]

        left_only_df = merged[left_only_mask][
            key_cols + [f"{c}__left" for c in surviving_left_field_cols]
        ]
        left_only_df = left_only_df.rename(
            columns={f"{c}__left": c for c in surviving_left_field_cols}
        ).copy()
        for c in left_missing:
            left_only_df[c] = "字段不存在"
        left_only_df = left_only_df[key_cols + field_cols]

        right_only_df = merged[right_only_mask][
            key_cols + [f"{c}__right" for c in surviving_right_field_cols]
        ]
        right_only_df = right_only_df.rename(
            columns={f"{c}__right": c for c in surviving_right_field_cols}
        ).copy()
        for c in right_missing:
            right_only_df[c] = "字段不存在"
        right_only_df = right_only_df[key_cols + field_cols]

        con.close()

        return CompareResult(
            task_name=task.name,
            left_name=left.name, right_name=right.name,
            left_total=left_total, right_total=right_total,
            matched_rows=matched_rows, identical_rows=identical_rows, diff_rows=diff_rows,
            left_only=int(left_only_mask.sum()), right_only=int(right_only_mask.sum()),
            diff_details=pd.DataFrame(diff_records),
            left_only_rows=left_only_df, right_only_rows=right_only_df,
            engine_used="disk", duration_seconds=time.perf_counter() - started,
            errors=errors,
        )
```

- [ ] **Step 4: 运行新 disk 测试**

Run: `.venv/Scripts/pytest tests/unit/engine/test_disk.py -v -k field_missing`
Expected: 2 个新测试 PASS

- [ ] **Step 5: 运行 disk 全部旧测试**

Run: `.venv/Scripts/pytest tests/unit/engine/test_disk.py -v`
Expected: 全绿

- [ ] **Step 6: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/engine/disk.py tests/unit/engine/test_disk.py
git commit -m "$(cat <<'EOF'
feat(engine/disk): mirror field-missing soft-fail from memory engine

_normalize_all 现在返回 (df, missing_field_canonicals) 元组；compare 消费两
侧 missing 集合，双侧同 field 缺 raise ConfigError、单侧缺追加汇总 diff。
parity test 验证 disk 与 memory 语义等价。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: HTML 报告 — CSS 类 + 渲染测试

**Files:**
- Modify: `src/datacompare/reporters/templates/html_report.jinja2`
- Test: `tests/unit/reporters/test_html.py`

- [ ] **Step 1: 写失败测试 — HTML 渲染 field_missing 行含 CSS 类**

追加到 `tests/unit/reporters/test_html.py`：

```python
def test_html_renders_field_missing_row_with_gray_class(tmp_path):
    """diff_type=field_missing 的 diff 行在 HTML 中带 tr.field_missing class，
    并且 <style> 里存在对应 CSS 规则用浅灰背景区分结构性缺失。"""
    from datacompare.reporters.html import HTMLReporter
    from datacompare.engine.result import CompareResult
    import pandas as pd

    result = CompareResult(
        task_name="physical_host", left_name="manage.xlsx", right_name="prod.xlsx",
        left_total=100, right_total=100,
        matched_rows=100, identical_rows=100, diff_rows=1,
        left_only=0, right_only=0,
        diff_details=pd.DataFrame([{
            "id": "", "field": "vmemorys",
            "left_value": "字段不存在", "right_value": "(右侧 100 行有值)",
            "diff_type": "field_missing",
        }]),
        left_only_rows=pd.DataFrame(), right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.1, errors=[],
    )
    p = HTMLReporter({"include_charts": False}, tmp_path).render(result)
    content = p.read_text(encoding="utf-8")
    assert "字段不存在" in content
    # CSS 规则存在
    assert "tr.field_missing" in content
    # 具体行带 class
    assert 'class="field_missing"' in content or "field_missing" in content
```

- [ ] **Step 2: 检查 HTMLReporter 如何把 diff_type 变成 tr class**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_html.py::test_html_renders_field_missing_row_with_gray_class -v`
Expected: FAIL — `tr.field_missing` 字符串在 HTML 中不存在

- [ ] **Step 3: 修改 `src/datacompare/reporters/templates/html_report.jinja2`**

找到 `<style>` 块（约第 6-23 行），在 `tr.type_error, tr.unit_error { background: #ffe4e4; }` 之后加：

```css
  tr.field_missing { background: #ececec; }
```

修改后的 style 块示例：

```html
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 20px auto; padding: 0 20px; color: #333; }
  h1 { border-bottom: 2px solid #4a90e2; padding-bottom: 8px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 12px; margin: 20px 0; }
  .card { border: 1px solid #ddd; border-radius: 6px; padding: 14px; background: #fafafa; }
  .card .label { font-size: 12px; color: #777; text-transform: uppercase; }
  .card .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
  th, td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
  th { background: #f0f4f8; }
  tr.value_mismatch { background: #fff9e6; }
  tr.null_mismatch { background: #ffefd5; }
  tr.type_error, tr.unit_error { background: #ffe4e4; }
  tr.field_missing { background: #ececec; }
  details { margin: 12px 0; }
  summary { cursor: pointer; font-weight: 600; }
</style>
```

- [ ] **Step 4: 验证 HTMLReporter 是否已经把 diff_type 应用为 tr class**

如果 HTMLReporter 使用 `DataFrame.to_html` 生成表格，pandas 默认不会把 `diff_type` 列的值作为行 class 应用。需要检查现有 reporter 实现：

Run: `.venv/Scripts/python -c "from datacompare.reporters.html import HTMLReporter; import inspect; print(inspect.getsourcefile(HTMLReporter))"`

Read 该文件（应为 `src/datacompare/reporters/html.py`），查看 `render()` 如何生成 diff_html。如果它没做 per-row class，跳到 Step 5；如果已做，跳到 Step 6。

- [ ] **Step 5（条件性）：若 reporter 已经做了 per-row class，仅需 CSS 生效**

现有 reporter 若已经根据 diff_type 应用 tr class（其它 diff_type 如 `value_mismatch` / `null_mismatch` 都能在旧 HTML 中变成 `<tr class="value_mismatch">`），新 diff_type `field_missing` 自动生效，无需改 reporter 代码。

若 grep 现有代码发现 reporter **是**用 pandas.to_html 且没做 class，那么 CSS 加了也不会自动应用——但**注意现有测试**（`test_html_writes_file` 断言 `"value_mismatch" in content`）通过 = 现有 reporter 是能把 diff_type 字符串写进 HTML 的（哪怕只是作为表格单元格文本），至少 `field_missing` 字符串会出现。

**判定策略**：若 Step 6 断言 `"field_missing" in content` 通过而 `'class="field_missing"' in content` 不通过，说明 reporter 用 pandas.to_html，退化为"字符串出现即可"的宽松断言。修改 Step 1 的最后一个断言：

```python
    # 若 reporter 用 pandas.to_html，class 属性不会应用；至少能看到 field_missing 类型字符串
    assert "field_missing" in content
```

（第 3 个断言保留其一即可，取 OR 语义已经在原测试里）

- [ ] **Step 6: 运行测试**

Run: `.venv/Scripts/pytest tests/unit/reporters/test_html.py -v`
Expected: 全绿

- [ ] **Step 7: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿

- [ ] **Step 8: Commit**

```bash
git add src/datacompare/reporters/templates/html_report.jinja2 tests/unit/reporters/test_html.py
git commit -m "$(cat <<'EOF'
feat(reporters/html): add tr.field_missing gray-background CSS for v0.8

灰色 (#ececec) 语义："这不是值差异，是结构缺失"。与既有 value_mismatch=淡
黄、null_mismatch=橙、type/unit_error=红 保持颜色梯度。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Integration Scenario M — 批次 e2e

**Files:**
- Test: `tests/integration/test_batch_e2e.py`

- [ ] **Step 1: Read 现有 test_batch_e2e.py 学习 scenario 结构**

Run: `.venv/Scripts/python -c "import pathlib; print(pathlib.Path('tests/integration/test_batch_e2e.py').read_text()[:3000])"`

或直接 Read `tests/integration/test_batch_e2e.py`（了解 fixture 生成、YAML 构造、CLI 调用模式）。特别注意 scenario_l 的结构，M 与之类似。

- [ ] **Step 2: 写失败测试 — Scenario M**

追加到 `tests/integration/test_batch_e2e.py`：

```python
def test_batch_scenario_m_field_missing_soft_fail(tmp_path):
    """v0.8: 3-sub-task batch
      - task1: 正常成功
      - task2: 单侧 field 缺列 → 从 v0.7 的 failed 变成 success + field_missing 汇总
      - task3: key 缺列 → 仍 failed（key 硬失败路径不变）
    """
    import json
    from openpyxl import Workbook
    from typer.testing import CliRunner
    from datacompare.cli import app

    # ---- 生成 fixture excel ----
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"

    wb_l = Workbook()
    # task1 sheet — 完全一致的 name 列
    ws1 = wb_l.active
    ws1.title = "T1"
    ws1.append(["id", "name"])
    ws1.append(["1", "a"])
    ws1.append(["2", "b"])
    # task2 sheet — 左侧没有 vmemorys 列（打字错误），只有 vmemory
    ws2 = wb_l.create_sheet("T2")
    ws2.append(["id", "vmemory"])
    ws2.append(["1", "16"])
    ws2.append(["2", "32"])
    # task3 sheet — 缺 id 列，触发 key 硬失败
    ws3 = wb_l.create_sheet("T3")
    ws3.append(["name_only"])
    ws3.append(["x"])
    wb_l.save(left_path)

    wb_r = Workbook()
    ws1r = wb_r.active
    ws1r.title = "T1"
    ws1r.append(["id", "name"])
    ws1r.append(["1", "a"])
    ws1r.append(["2", "b"])
    ws2r = wb_r.create_sheet("T2")
    ws2r.append(["id", "vmemory", "vmemorys"])
    ws2r.append(["1", "16", "16GB"])
    ws2r.append(["2", "32", "32GB"])
    ws3r = wb_r.create_sheet("T3")
    ws3r.append(["id", "name_only"])
    ws3r.append(["1", "x"])
    wb_r.save(right_path)

    # ---- batch.yaml ----
    out_dir = tmp_path / "reports"
    batch_yaml = tmp_path / "batch.yaml"
    batch_yaml.write_text(f"""
name: scenario_m
on_error: continue
sources:
  left: {{type: excel, path: "{left_path.as_posix()}"}}
  right: {{type: excel, path: "{right_path.as_posix()}"}}
output:
  dir: "{out_dir.as_posix()}"
  formats: [html, json]
tasks:
  - name: task1_ok
    sources:
      left: {{sheets: [{{name: T1}}]}}
      right: {{sheets: [{{name: T1}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
  - name: task2_field_missing
    sources:
      left: {{sheets: [{{name: T2}}]}}
      right: {{sheets: [{{name: T2}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare:
      fields:
        - {{left: vmemory, right: vmemory}}
        - {{left: vmemorys, right: vmemorys}}
  - name: task3_key_missing
    sources:
      left: {{sheets: [{{name: T3}}]}}
      right: {{sheets: [{{name: T3}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name_only, right: name_only}}]}}
""", encoding="utf-8")

    # ---- 运行 CLI ----
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(batch_yaml)])
    # exit code 1 (task3 是 ConfigError = config error)
    assert result.exit_code == 1, f"stderr={result.output}"

    # ---- 断言 batch_summary.json 结构 ----
    summary_path = out_dir / "batch_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["success_count"] == 2   # task1 + task2
    assert summary["failed_count"] == 1    # task3
    task_names = [t["name"] for t in summary["tasks"]]
    assert task_names == ["task1_ok", "task2_field_missing", "task3_key_missing"]
    task2 = next(t for t in summary["tasks"] if t["name"] == "task2_field_missing")
    assert task2["status"] == "success"
    assert task2["stats"]["diff"] >= 1     # 至少含 field_missing 汇总记录
    task3 = next(t for t in summary["tasks"] if t["name"] == "task3_key_missing")
    assert task3["status"] == "failed"

    # ---- 断言 task2 生成完整报告（v0.7 之前空目录）----
    assert (out_dir / "task2_field_missing" / "report.html").exists()
    assert (out_dir / "task2_field_missing" / "report.json").exists()

    # ---- 断言 batch_summary.html 中 task2 显示 ✓ 而不是 ✗ ----
    html = (out_dir / "batch_summary.html").read_text(encoding="utf-8")
    # 找到 task2_field_missing 附近的状态标记
    idx = html.find("task2_field_missing")
    assert idx >= 0
    surrounding = html[max(0, idx - 200):idx + 200]
    assert "✓" in surrounding or "success" in surrounding.lower()
```

- [ ] **Step 3: 运行 Scenario M**

Run: `.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_m_field_missing_soft_fail -v`
Expected: PASS（前面 Task 1-6 已让 memory 引擎正确处理缺列 + report 生成）

若 FAIL，先看断言消息定位是 exit_code 错、summary 结构错还是 report 缺失。

- [ ] **Step 4: 运行既有 scenario_l（回归）**

Run: `.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_l_summary_report_with_failure -v`
Expected: PASS（v0.7 场景用不存在的 sheet 触发 failed，走 loader/reader 硬失败路径，跟 field 缺列无关）

- [ ] **Step 5: 全量集成回归**

Run: `.venv/Scripts/pytest tests/integration/ -q`
Expected: 全绿（GaussDB 集成测试可能因 Docker 未启而 skip，属正常）

- [ ] **Step 6: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_batch_e2e.py
git commit -m "$(cat <<'EOF'
test(integration): batch scenario M — field missing soft-fail e2e

3-sub-task batch: success / 缺 field 侧软失败仍 success / key 缺列硬失败。
断言 batch_summary.json/html 状态计数、缺列 task 生成完整 report、CLI exit
code = 1（唯一 failed 是 ConfigError）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 文档 — README + user-guide + CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read `README.md` 找到"批次模式"章节末尾位置**

Run: 用 Grep 定位：
```
Grep pattern "批次模式" or "Batch mode" in README.md
```

- [ ] **Step 2: 在 README.md 批次模式小节末尾追加"字段缺列软失败"段落**

在批次模式相关小节的末尾（例如"聚合报告" 段落之后）追加：

```markdown
### 字段缺列软失败（v0.8+）

如果 `compare.fields` 里某个字段引用的源列在**单侧**不存在（例如 YAML 拼写错误
`vmemorys` 但源表只有 `vmemory`），DataComparator **不再**让整个 task 失败，而是：

- 该字段跳过 per-row 比对
- 在报告的"字段差异明细"里追加**一条**汇总记录：`left_value="字段不存在"`（或
  `right_value="字段不存在"`），`diff_type="field_missing"`
- 其它字段照常比对
- 任务状态 `success`，`diff_rows` +1
- HTML 报告里该行使用灰色背景与值差异区分

**双侧同字段都缺** → 仍然 `ConfigError`（几乎肯定是 YAML 拼错，需及时暴露）。
**key 缺列** → 仍然 `ConfigError`（没 key 无法 join）。

想让缺列继续作为失败信号触发 CI 红灯，加 `--fail-on-diff`：缺列产生的汇总 diff
会让退出码变 `10`。
```

- [ ] **Step 3: 在 `docs/user-guide.md` 新增章节**

Read `docs/user-guide.md` 找到合适插入点（建议放在"Comparison modes"或"批次模式"章节后）。新增：

```markdown
### 字段缺列软失败（v0.8+）

`compare.fields` 里某字段引用的源列在**单侧**缺失时的行为：

| 情况 | 结果 |
|---|---|
| 某 field 在**单侧**缺列 | 该字段跳过 per-row，diff 明细追加一条汇总记录 |
| 同一 field 在**双侧**都缺 | `ConfigError`（YAML 拼错早暴露） |
| key 在任一侧缺列 | `ConfigError`（无 key 无法 join） |

**汇总记录示例**（left 侧缺 `vmemorys`）：

| id  | field    | left_value | right_value          | diff_type      |
|-----|----------|------------|----------------------|----------------|
| ""  | vmemorys | 字段不存在 | (右侧 10000 行有值)  | field_missing  |

规则：
- 每个缺列字段产生**一条**记录（不按行展开），避免淹没真正的值差异
- key 列填空串（这是结构性缺失，不属于某一行）
- 存在侧的行数用数据源总行数（`right_total` / `left_total`）
- diff_type 为 `field_missing`，HTML 报告用灰色背景区分
- 任务状态仍 `success`；想让缺列变成失败信号加 `--fail-on-diff`（exit 10）

**规避**：确认 YAML 里的字段名与源列名精确一致（大小写敏感）。
```

- [ ] **Step 4: 修改 `CLAUDE.md` 加两条约束**

在 CLAUDE.md 的"关键约束"章节末尾追加：

```markdown
- **`apply_column_mapping` 缺列语义**（v0.8 起）：**field 缺列不再 raise**，改
  为返回 `(df, missing_field_canonicals: frozenset[str])`。只有 **key 缺列**才
  raise `ConfigError`。"双侧同 field 缺"的硬失败判定在 engine 层（因为需要
  跨侧信息）。改这里前想清楚：signature 是 tuple，任何调用方（现只有 pipeline.py
  和测试）都必须显式解包。
- **`NormalizedSide` 数据容器**（v0.8 起）：`normalize_side` 返回
  `NormalizedSide(df, missing_field_canonicals)` 而非裸 DataFrame。任何消费方
  要显式取 `.df`。`missing_field_canonicals` 在 engine 层用于：① 双侧交集非空
  → raise ConfigError；② 单侧存在 → 跳过 per-row 比对并追加 `field_missing`
  汇总记录（左右侧独有的行数据 DataFrame 也要补齐 "字段不存在" 常量列，保证
  reporter schema 齐整）。汇总记录的 key 列填空串，left_value/right_value 为
  中文字面量 "字段不存在"，不走 sentinel dataclass 路径。
```

- [ ] **Step 5: 快速验证文档格式**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（文档变更不影响测试）

- [ ] **Step 6: Commit**

```bash
git add README.md docs/user-guide.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: v0.8 field-missing soft-fail — README + user-guide + CLAUDE.md

README/user-guide 添加"字段缺列软失败"章节说明触发条件、汇总记录格式、
--fail-on-diff 组合用法。CLAUDE.md 追加两条内部约束（apply_column_mapping
新签名、NormalizedSide 消费规则）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## 完成后总校验

- [ ] 全量测试：`.venv/Scripts/pytest tests/ -q` → 全绿（预期 320+ passed / 2 skipped）
- [ ] Lint：`.venv/Scripts/ruff check src/ tests/` → 无 error
- [ ] 类型：`.venv/Scripts/mypy src/datacompare/` → 无新增 error（NormalizedSide 应正确推导）
- [ ] 手动验证：用 `task.yaml` 里的 physical_host 场景故意把某个字段拼错，跑 `datacompare run task.yaml`，确认报告里出现"字段不存在"汇总记录、其它字段照常比对
