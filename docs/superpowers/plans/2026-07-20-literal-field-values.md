# Literal Field Values Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let compare fields specify a constant literal string (or null) on one side instead of a source column, so a right-side column can be asserted against a fixed value when the left side has no matching column.

**Architecture:** Add two optional Pydantic fields `left_literal` / `right_literal` on `FieldRule`, enforce mutual exclusion via `model_validator` using `model_fields_set` (so `literal: null` is distinguishable from "not set"). In `apply_column_mapping`, after the existing rename step, inject one constant-valued pandas column per literal field with the field's canonical (`f.right`) name. The literal value then flows through the unchanged `_process_value` transform (mode/unit/coercion/rounding all apply naturally).

**Tech Stack:** Pydantic v2 (`model_validator`, `model_fields_set`), pandas 2.x (scalar broadcast on column assignment), pytest, ruamel.yaml.

**Spec reference:** `docs/superpowers/specs/2026-07-20-literal-field-values-design.md`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `src/datacompare/config/models.py` | modify `FieldRule` class (lines 105-119) | make `left`/`right` optional, add `left_literal`/`right_literal`, add mutual-exclusion validator |
| `src/datacompare/normalize/columns.py` | modify `apply_column_mapping` (lines 51-77) | skip literal fields in rename_map, inject them as constant columns after rename |
| `tests/unit/config/test_models.py` | append | validator unit tests (6 cases) |
| `tests/unit/normalize/test_columns.py` | append | injection unit tests (4 cases) |
| `tests/unit/normalize/test_pipeline.py` | append | end-to-end pipeline tests (numeric coercion, null literal) |
| `tests/integration/test_batch_e2e.py` | append one function | 1 batch scenario using `left_literal` vs. varying right column |
| `README.md` | insert short subsection | user-facing example |
| `docs/user-guide.md` | insert short subsection | detailed rules |
| `CLAUDE.md` | append one bullet under 关键约束 | note `model_fields_set` disambiguation for future editors |

---

## Task 1: Extend FieldRule with literal fields and mutual-exclusion validator

**Files:**
- Modify: `src/datacompare/config/models.py:105-119`
- Test: `tests/unit/config/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/config/test_models.py`:

```python
import pytest
from pydantic import ValidationError
from datacompare.config.models import FieldRule


class TestFieldRuleLiterals:
    def test_column_only_both_sides_ok(self):
        f = FieldRule(left="a", right="b")
        assert f.left == "a" and f.right == "b"
        assert f.left_literal is None and f.right_literal is None

    def test_left_literal_with_right_column_ok(self):
        f = FieldRule(left_literal="Azone", right="type")
        assert f.left is None
        assert f.left_literal == "Azone"
        assert f.right == "type"

    def test_left_literal_null_ok(self):
        # explicit null literal — asserts right column is None for matched rows
        f = FieldRule(left_literal=None, right="deleted_at")
        assert f.left is None
        assert f.left_literal is None
        assert "left_literal" in f.model_fields_set  # marker: explicitly set

    def test_right_literal_with_left_column_ok(self):
        f = FieldRule(left="name", right_literal="prod")
        assert f.right is None
        assert f.right_literal == "prod"

    def test_missing_left_specifier_raises(self):
        with pytest.raises(ValidationError, match="'left' or 'left_literal'"):
            FieldRule(right="b")

    def test_missing_right_specifier_raises(self):
        with pytest.raises(ValidationError, match="'right' or 'right_literal'"):
            FieldRule(left="a")

    def test_both_left_and_left_literal_raises(self):
        with pytest.raises(ValidationError, match="cannot specify both 'left'"):
            FieldRule(left="a", left_literal="X", right="b")

    def test_both_right_and_right_literal_raises(self):
        with pytest.raises(ValidationError, match="cannot specify both 'right'"):
            FieldRule(left="a", right="b", right_literal="Y")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py::TestFieldRuleLiterals -v`

Expected: All 8 tests fail with either `TypeError: unexpected keyword argument 'left_literal'` or `ValidationError` for the wrong reason (because `left`/`right` are still required strings).

- [ ] **Step 3: Update FieldRule model**

Edit `src/datacompare/config/models.py`. Change the import line 5 to add `model_validator`:

```python
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
```

Replace `FieldRule` (lines 105-119) with:

```python
class FieldRule(BaseModel):
    """Field-level rule. `None` on behavioral flags = inherit from CompareDefaults.

    Each side must provide exactly one of `<side>` (column name) or
    `<side>_literal` (constant string or null broadcast to every row).
    "Provided" is judged by Pydantic's `model_fields_set` so `left_literal: null`
    is distinguishable from "left_literal not written". Do NOT rewrite this
    check as `value is None`.
    """
    model_config = ConfigDict(extra="forbid")
    left: str | None = None
    right: str | None = None
    left_literal: str | None = None
    right_literal: str | None = None
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

    @model_validator(mode="after")
    def _check_source_specifiers(self):
        for side in ("left", "right"):
            col_set = side in self.model_fields_set
            lit_set = f"{side}_literal" in self.model_fields_set
            if not col_set and not lit_set:
                raise ValueError(
                    f"field must specify '{side}' or '{side}_literal'"
                )
            if col_set and lit_set:
                raise ValueError(
                    f"cannot specify both '{side}' and '{side}_literal'"
                )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py::TestFieldRuleLiterals -v`

Expected: 8 passed.

- [ ] **Step 5: Run full model + loader test files to check nothing else broke**

Run: `.venv/Scripts/pytest tests/unit/config/ -q`

Expected: all pass. If any existing test constructed `FieldRule(left="a", right="b", ...)` it still works because both are still valid values just via mutually-exclusive branch.

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_models.py
git commit -m "feat(config): FieldRule accepts left_literal / right_literal with mutual exclusion"
```

---

## Task 2: Inject literal constant columns in apply_column_mapping

**Files:**
- Modify: `src/datacompare/normalize/columns.py:51-77`
- Test: `tests/unit/normalize/test_columns.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_columns.py`:

```python
def test_apply_column_mapping_left_literal_injects_constant_column():
    """Left has no 'zone' column but field is {left_literal: 'Azone', right: 'zone'}.
    Result must contain a 'zone' column filled with 'Azone' for every row."""
    df = pd.DataFrame({"id": ["1", "2", "3"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "zone"]
    assert result["zone"].tolist() == ["Azone", "Azone", "Azone"]


def test_apply_column_mapping_right_literal_injects_constant_column():
    """Symmetric: right side literal."""
    df = pd.DataFrame({"id": ["1", "2"], "name": ["a", "b"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="name", right_literal="prod")]
    result = apply_column_mapping(df, keys, fields, side="right")
    # Right side: 'name' column doesn't exist here since only right cols matter,
    # but keys use right column 'id'. The literal field's canonical name is
    # whatever f.right is — but f.right is None. The literal field itself uses
    # f.left ('name') as the canonical name on right side too (see spec).
    # Actually re-read spec: canonical name is f.right when only left is literal;
    # when only right is literal, canonical must be f.left.
    # So injected column name = f.left = 'name'.
    assert "name" in result.columns
    assert result["name"].tolist() == ["prod", "prod"]


def test_apply_column_mapping_left_literal_null():
    """left_literal: null → column of None values."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal=None, right="deleted_at")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "deleted_at"]
    assert result["deleted_at"].isna().all()


def test_apply_column_mapping_literal_on_empty_dataframe():
    """Empty DataFrame + literal → empty column, no crash."""
    df = pd.DataFrame({"id": pd.Series([], dtype=object)})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="X", right="zone")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["id", "zone"]
    assert len(result) == 0


def test_apply_column_mapping_mixed_column_and_literal_fields():
    """Some fields have literal, others have real columns."""
    df = pd.DataFrame({"id": ["1"], "amt": ["100"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [
        FieldRule(left="amt", right="amount"),
        FieldRule(left_literal="Azone", right="zone"),
    ]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert set(result.columns) == {"id", "amount", "zone"}
    assert result.iloc[0]["amount"] == "100"
    assert result.iloc[0]["zone"] == "Azone"
```

**Important note on canonical column name:** When only ONE side is literal, the canonical name for that field in the normalized DataFrame is **the other side's column name**. That is, `getattr(f, side) or getattr(f, other_side)` — pick the non-None one. This is because both left and right normalized DataFrames must have matching column names for the merge/compare step, and the non-literal side dictates that name.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -k "literal" -v`

Expected: All 5 tests fail. The first (`left_literal_injects_constant`) fails with `KeyError: 'left'` or similar in the rename_map loop, because current code does `rename_map[getattr(k, side)] = k.right` and `getattr(f, side)` is None → dict key None.

- [ ] **Step 3: Update apply_column_mapping**

Edit `src/datacompare/normalize/columns.py`. Replace `apply_column_mapping` (lines 51-72) with:

```python
def apply_column_mapping(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    fields: list[FieldRule],
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Rename columns to canonical names; drop unmapped columns; inject literal
    fields as constant-valued columns.

    Canonical name for a literal field = the non-literal side's column name
    (e.g. `{left_literal: "X", right: "type"}` → canonical is "type").
    """
    other = "right" if side == "left" else "left"
    rename_map: dict[str, str] = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    literal_fields: list[tuple[str, str]] = []  # (canonical_name, literal_value)
    for f in fields:
        src = getattr(f, side)
        if src is not None:
            canonical = getattr(f, other) if getattr(f, other) is not None else src
            rename_map[src] = canonical
        else:
            # literal on this side; canonical name comes from the other side's column
            canonical = getattr(f, other)
            if canonical is None:
                # both sides literal — use f.right as name (arbitrary but stable)
                canonical = f.right if f.right is not None else "_literal"
            literal_fields.append((canonical, getattr(f, f"{side}_literal")))
    missing = [src for src in rename_map if src not in df.columns]
    if missing:
        from datacompare.config.errors import ConfigError
        raise ConfigError(
            f"columns not found in {side} source: {missing}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )
    # Filter to mapped source columns FIRST, then rename. Prevents an unmapped
    # source column whose name equals a target name (e.g. left has stray 'name'
    # while id→name) from colliding with the renamed column.
    src_cols = list(rename_map.keys())
    result = df[src_cols].rename(columns=rename_map)
    # Inject literal fields as constant columns (pandas broadcasts a scalar).
    for canonical, literal_val in literal_fields:
        result[canonical] = literal_val
    return result
```

**Note:** the "canonical name = other side's column name" rule means the two calls to `apply_column_mapping` (one per side) produce DataFrames whose comparable columns share names. The engine's merge and per-field iteration in `normalize_side` currently uses `f.right` as the canonical name — that still works when neither side is literal (`f.right` is truthy) and when only `left_literal` is set (`f.right` is truthy). It stops working when only `right_literal` is set. Task 3 handles the `normalize_side` change for that case.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -k "literal" -v`

Expected: 5 passed.

- [ ] **Step 5: Run full columns test file**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_columns.py -q`

Expected: all pass, including the pre-existing `test_apply_column_mapping_left_col_named_like_right_key_no_collision` from the recent fix.

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/normalize/columns.py tests/unit/normalize/test_columns.py
git commit -m "feat(normalize): inject literal fields as constant columns in apply_column_mapping"
```

---

## Task 3: Wire literal fields into normalize_side pipeline

**Files:**
- Modify: `src/datacompare/normalize/pipeline.py:53-69`
- Test: `tests/unit/normalize/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_pipeline.py`:

```python
def test_pipeline_left_literal_with_numeric_mode_coerces():
    """left_literal: '30' + mode: numeric + decimal_places: 2 → 30.0."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="30", right="memory",
                        mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["id", "memory"]
    assert result["memory"].tolist() == [30.0, 30.0]


def test_pipeline_left_literal_null_produces_none_column():
    """left_literal: null → column of None on all rows."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal=None, right="deleted_at")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result["deleted_at"].isna().all()


def test_pipeline_left_literal_string_mode_broadcasts():
    """Constant string flows through string-mode transforms."""
    df = pd.DataFrame({"id": ["1", "2", "3"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left_literal="Azone", right="zone", mode="string")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result["zone"].tolist() == ["Azone", "Azone", "Azone"]


def test_pipeline_right_literal_canonical_name_uses_left():
    """When right side is literal, canonical column name comes from f.left."""
    df = pd.DataFrame({"id": ["1"], "name": ["a"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="name", right_literal="prod")]
    # Side=right: no 'name' column in df; literal fills it.
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert "name" in result.columns
    assert result["name"].tolist() == ["prod"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -k "literal" -v`

Expected: The first 3 tests may already pass because Task 2's injection uses canonical = `f.right` when `f.right is not None`, which matches how `normalize_side` reads the field. The **fourth test** (`right_literal_canonical_name_uses_left`) fails because `normalize_side` line 69 does `result[key_cols + [f.right for f in compare.fields]]` and `f.right` is None for a right-literal field.

- [ ] **Step 3: Update normalize_side to compute canonical field name**

Edit `src/datacompare/normalize/pipeline.py`. Replace `normalize_side` (lines 53-69) with:

```python
def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Apply key regex -> rename+inject -> per-field transform."""
    df = apply_key_regex(df, keys, side)
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [k.right for k in keys]

    def _canonical(f):
        # Mirrors apply_column_mapping's canonical-name rule: prefer f.right,
        # fall back to f.left when right side is literal.
        if f.right is not None:
            return f.right
        if f.left is not None:
            return f.left
        return "_literal"

    result = renamed.copy()
    for rule in compare.fields:
        eff = effective_rule(rule, compare.defaults)
        col = _canonical(rule)
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
    return result[key_cols + [_canonical(f) for f in compare.fields]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -k "literal" -v`

Expected: 4 passed.

- [ ] **Step 5: Run full normalize test tree**

Run: `.venv/Scripts/pytest tests/unit/normalize/ -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/normalize/pipeline.py tests/unit/normalize/test_pipeline.py
git commit -m "feat(normalize): pipeline handles literal fields via canonical-name fallback"
```

---

## Task 4: End-to-end batch integration test with left_literal

**Files:**
- Modify: `tests/integration/test_batch_e2e.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_batch_e2e.py`:

```python
def test_batch_scenario_j_left_literal_asserts_right_column_value(tmp_path):
    """Scenario J: sub-task uses `left_literal` to assert that a right-side
    column always equals a fixed value for every matched row.

    Left Excel has only `id` column. Right Excel has `id` and `zone` columns
    where zone varies per row. The compare field `{left_literal: 'Azone',
    right: 'zone'}` should produce diffs for exactly the rows where right's
    `zone != 'Azone'`.
    """
    _make_xlsx(tmp_path / "left.xlsx", {
        "IDS": [["id"], ["r1"], ["r2"], ["r3"]],
    })
    _make_xlsx(tmp_path / "right.xlsx", {
        "ZONES": [
            ["id", "zone"],
            ["r1", "Azone"],   # matches literal
            ["r2", "Bzone"],   # diff
            ["r3", "Azone"],   # matches
        ],
    })
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: literal_assertion
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: assert_zone_is_Azone
    sources:
      left: {{sheets: [{{name: IDS}}]}}
      right: {{type: excel, path: {tmp_path}/right.xlsx, sheets: [{{name: ZONES}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare:
      fields:
        - {{left_literal: "Azone", right: zone}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0, result.output
    report = json.loads(
        (tmp_path / "reports" / "assert_zone_is_Azone" / "report.json").read_text(encoding="utf-8")
    )
    assert report["summary"]["matched"] == 3
    assert report["summary"]["identical"] == 2
    assert report["summary"]["diff"] == 1
```

- [ ] **Step 2: Run test to verify current expected behavior**

Run: `.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_j_left_literal_asserts_right_column_value -v`

Expected: **PASS** (Tasks 1–3 already implement the feature end-to-end; this test just proves batch mode + CLI + JSON reporter all work with a literal field).

If it fails, investigate before proceeding. Do not modify code without understanding the failure.

- [ ] **Step 3: Run all integration tests to catch regressions**

Run: `.venv/Scripts/pytest tests/integration/ -q`

Expected: all pass (Docker-dependent tests may skip; that's fine).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_batch_e2e.py
git commit -m "test(integration): batch sub-task using left_literal to assert right column value"
```

---

## Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add README section**

Find the "比对规则" / "compare" area in `README.md` (search for `mode: exact` or `字段比对` — the section that shows sample `fields:` YAML). Immediately after the standard fields example, insert this exact block (triple-backticks are literal):

````markdown
#### 字面量字段（v0.5+）

某一侧没有对应列，想把一个固定字符串（或 null）与另一侧列比对时，用
`left_literal` / `right_literal`（与 `left` / `right` 互斥，每侧二选一）：

```yaml
compare:
  fields:
    # 断言右侧 zone 列对所有匹配行都等于 "Azone"
    - {left_literal: "Azone", right: zone}
    # 断言右侧 deleted_at 对所有匹配行都是 null
    - {left_literal: null, right: deleted_at}
    # 数值模式：字面量与列值走同一条转换管线
    - {left_literal: "30", right: memory, mode: numeric, decimal_places: 2}
```

用 `null_equivalents` 里包含的字符串（比如 `"NULL"`）当字面量会被判为 None——
真想传 null 就直接写 `left_literal: null`。
````

- [ ] **Step 2: Add user-guide section**

Find the `### 比对模式` (Comparison modes) section in `docs/user-guide.md`. Immediately after that table, insert this exact block:

````markdown
### 字面量字段值（v0.5+）

比对字段每侧必须恰好指定 `<side>` 或 `<side>_literal` 之一：

```yaml
compare:
  fields:
    - {left: real_col, right: real_col}          # 常规：两侧都是列名
    - {left_literal: "Azone", right: type}       # 左侧字面量字符串
    - {left_literal: null, right: deleted_at}    # 左侧字面 null
    - {left: name, right_literal: "prod"}        # 右侧字面量
```

规则：
- 每侧的 `<side>` 和 `<side>_literal` **互斥**，`datacompare validate` 时报错
- 字面量走与列值**完全相同**的 normalize 管线：`mode` / `parse_unit` /
  `null_equivalents` / `decimal_places` 等全部生效
- 字面量 `null` 用 YAML `null`（不是空串）
- 不适用于 match keys（`match.keys` 只能是列名——字面量 join key 会造成
  笛卡尔积无意义）
- 常见用途：右侧库表某字段应为固定枚举值 / 应为 null / 应为固定数字
````

- [ ] **Step 3: Add CLAUDE.md editor note**

Find the 关键约束（改代码前务必了解）section in `CLAUDE.md`. Append this bullet at the end:

```markdown
- **`FieldRule` 支持 `left_literal` / `right_literal`**（v0.5 起）：每侧必须恰好
  指定 `<side>` 或 `<side>_literal` 之一。验证器用 `model_fields_set` 判定"是否
  提供"，**不**用 `value is None`——`left_literal: null` 是合法的（表示"断言另
  一侧为 null"），跟"未提供 left_literal"运行时值相同但语义不同。改这条约束前
  想清楚会不会把 null 字面量误判为未设置。canonical 列名规则：非字面量侧的列名
  优先，两侧都字面量时用 `f.right`（见 `normalize/columns.py`）。
```

- [ ] **Step 4: Verify docs render / links / no typos**

Run: `.venv/Scripts/pytest tests/ -q`

Expected: still all pass (docs commits shouldn't affect tests, but confirms we didn't accidentally touch code).

Also grep for the new anchors to be sure they exist:
```bash
grep -n "left_literal" README.md docs/user-guide.md CLAUDE.md
```

Expected: at least one match per file.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/user-guide.md CLAUDE.md
git commit -m "docs: document left_literal / right_literal on FieldRule"
```

---

## Post-implementation checklist

After all 5 tasks committed:

- [ ] Run the full suite one final time: `.venv/Scripts/pytest tests/ -q`
- [ ] Confirm no `ruff` regressions: `.venv/Scripts/ruff check src/ tests/`
- [ ] Confirm no `mypy` regressions: `.venv/Scripts/mypy src/datacompare/`
- [ ] Push: `git push`

If any of the above fail, fix inline (not in a new "cleanup" PR) — do not push a broken suite.
