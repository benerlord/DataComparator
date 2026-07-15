# Key Regex Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `left_regex` / `right_regex` on `KeyMapping` so that key values differing literally can be normalized (via `re.fullmatch`, 0 or 1 capture group) to a common form before the join. Strict-fail on mismatch with a structured error log.

**Architecture:** New pure-function module `normalize/keys.py` with `apply_key_regex()` runs as the **first** step of `normalize_side` (before column mapping and field normalization). New `KeyRegexMismatchError` (subclass of `ValueError`) travels through the existing `cli.py:61 except Exception → typer.Exit(2)` path — same as duplicate-key errors. Fully backward compatible: existing task.yaml files unchanged.

**Tech Stack:** Python 3.11+, Pydantic v2 (`field_validator`), pandas 2.x, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-key-regex-transform-design.md`

---

## Task 1: Add `left_regex` / `right_regex` to `KeyMapping` with validator

**Goal:** Extend the Pydantic model so YAML can carry optional regex per side, validated at load time (bad regex or ≥2 capture groups → `ValidationError`).

**Files:**
- Modify: `src/datacompare/config/models.py:67-70` (`KeyMapping` class)
- Test: `tests/unit/config/test_models.py` (append new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/config/test_models.py`:

```python
def test_key_mapping_defaults_regex_to_none():
    k = KeyMapping(left="a", right="b")
    assert k.left_regex is None
    assert k.right_regex is None


def test_key_mapping_accepts_valid_regex():
    k = KeyMapping(left="a", right="b", left_regex=r"ORD-\d+")
    assert k.left_regex == r"ORD-\d+"


def test_key_mapping_accepts_one_capture_group():
    k = KeyMapping(left="a", right="b", left_regex=r"ORD-0*(\d+)")
    assert k.left_regex == r"ORD-0*(\d+)"


def test_key_mapping_rejects_invalid_regex_syntax():
    with pytest.raises(ValidationError) as exc:
        KeyMapping(left="a", right="b", left_regex=r"ORD-[")
    assert "invalid regex" in str(exc.value)


def test_key_mapping_rejects_two_capture_groups():
    with pytest.raises(ValidationError) as exc:
        KeyMapping(left="a", right="b", right_regex=r"(\d+)-(\w+)")
    msg = str(exc.value)
    assert "capture groups" in msg
    assert "(?:...)" in msg


def test_key_mapping_allows_noncapturing_groups():
    k = KeyMapping(left="a", right="b", left_regex=r"(?:ORD|CUS)-(\d+)")
    assert k.left_regex == r"(?:ORD|CUS)-(\d+)"


def test_key_mapping_explicit_null_regex():
    k = KeyMapping(left="a", right="b", left_regex=None, right_regex=None)
    assert k.left_regex is None and k.right_regex is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/pytest tests/unit/config/test_models.py::test_key_mapping_accepts_valid_regex -v
```

Expected: FAIL with `TypeError: KeyMapping() got unexpected keyword argument 'left_regex'` (or similar Pydantic `ValidationError`).

- [ ] **Step 3: Modify `KeyMapping` in `src/datacompare/config/models.py`**

Add `import re` at top of file if not already present. Replace the existing `KeyMapping` class (currently at lines 67-70) with:

```python
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

Ensure `field_validator` is imported at the top:
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
```
(Add `field_validator` if it isn't already imported.)

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/Scripts/pytest tests/unit/config/test_models.py -v
```

Expected: all 7 new tests PASS; all pre-existing tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_models.py
git commit -m "$(cat <<'EOF'
feat(config): add left_regex/right_regex to KeyMapping with validator

Pydantic field_validator rejects invalid regex syntax and >=2 capture
groups at load time so datacompare validate catches config problems
before run.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create `KeyRegexMismatchError` exception in `normalize/keys.py`

**Goal:** Add the exception class that `apply_key_regex` will raise on mismatch. Keep it in the new module (`normalize/keys.py`) so consumers can `from datacompare.normalize.keys import KeyRegexMismatchError`.

**Files:**
- Create: `src/datacompare/normalize/keys.py`
- Test: `tests/unit/normalize/test_keys.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/normalize/test_keys.py`:

```python
import pytest
from datacompare.normalize.keys import KeyRegexMismatchError


def test_key_regex_mismatch_error_carries_all_fields():
    err = KeyRegexMismatchError(
        side="left",
        column="order_no",
        value="CANCEL-999",
        pattern=r"ORD-\d+",
        row_index=3,
    )
    assert err.side == "left"
    assert err.column == "order_no"
    assert err.value == "CANCEL-999"
    assert err.pattern == r"ORD-\d+"
    assert err.row_index == 3
    assert isinstance(err, ValueError)


def test_key_regex_mismatch_error_message_includes_all_fields():
    err = KeyRegexMismatchError(
        side="right", column="id", value="abc", pattern=r"\d+", row_index=0,
    )
    msg = str(err)
    assert "right" in msg
    assert "'id'" in msg
    assert "'abc'" in msg
    assert r"'\\d+'" in msg or r"\d+" in msg
    assert "row_index=0" in msg
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'datacompare.normalize.keys'`.

- [ ] **Step 3: Create `src/datacompare/normalize/keys.py`**

```python
"""Key normalization step: apply per-side regex fullmatch to key columns.

Runs BEFORE column mapping and field normalization. Strict-fail semantics:
first mismatch raises KeyRegexMismatchError (subclass of ValueError).
"""
from __future__ import annotations


class KeyRegexMismatchError(ValueError):
    """Raised when a key value fails to fullmatch the configured regex.

    Fail-fast: first mismatch aborts the task with exit code 2
    (see design spec §CLI 退出码).
    """
    def __init__(
        self,
        side: str,
        column: str,
        value: str,
        pattern: str,
        row_index: int,
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

- [ ] **Step 4: Run test to verify it passes**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/keys.py tests/unit/normalize/test_keys.py
git commit -m "$(cat <<'EOF'
feat(normalize): add KeyRegexMismatchError skeleton for key regex step

New module normalize/keys.py holds the strict-fail exception used by
the upcoming apply_key_regex() function.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `apply_key_regex` — pass-through & null handling

**Goal:** Land the function skeleton that returns the DataFrame unchanged when no regex is configured for a side, and passes `None` values through untouched. This is the baseline behavior (no regex logic yet).

**Files:**
- Modify: `src/datacompare/normalize/keys.py`
- Test: `tests/unit/normalize/test_keys.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_keys.py`:

```python
import pandas as pd
from datacompare.config.models import KeyMapping
from datacompare.normalize.keys import apply_key_regex


def test_apply_key_regex_no_regex_returns_df_unchanged():
    df = pd.DataFrame({"order_id": ["A1", "A2"], "amount": ["100", "200"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_id"]) == ["A1", "A2"]
    assert list(result["amount"]) == ["100", "200"]


def test_apply_key_regex_returns_copy_not_original():
    df = pd.DataFrame({"order_id": ["A1"], "amount": ["100"]})
    keys = [KeyMapping(left="order_id", right="order_id")]
    result = apply_key_regex(df, keys, side="left")
    assert result is not df


def test_apply_key_regex_empty_dataframe():
    df = pd.DataFrame({"order_id": [], "amount": []}).astype(object)
    keys = [KeyMapping(left="order_id", right="order_id", left_regex=r"\d+")]
    result = apply_key_regex(df, keys, side="left")
    assert len(result) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py::test_apply_key_regex_no_regex_returns_df_unchanged -v
```

Expected: FAIL with `ImportError` / `AttributeError: apply_key_regex`.

- [ ] **Step 3: Implement `apply_key_regex` (baseline)**

Add to `src/datacompare/normalize/keys.py`:

```python
import re
from typing import Literal
import pandas as pd
from datacompare.config.models import KeyMapping


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
    """
    result = df.copy()
    for k in keys:
        pattern_str = k.left_regex if side == "left" else k.right_regex
        if pattern_str is None:
            continue
        # Real regex logic added in Task 4; for now this branch is unreachable
        # in tests because they only exercise the None branch.
        _apply_pattern_to_column(
            result, k.left if side == "left" else k.right, pattern_str, side,
        )
    return result


def _apply_pattern_to_column(
    df: pd.DataFrame, column: str, pattern_str: str, side: str,
) -> None:
    """Placeholder — real body in Task 4."""
    raise NotImplementedError("Task 4 will implement regex logic")
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: all 5 tests PASS (2 from Task 2 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/keys.py tests/unit/normalize/test_keys.py
git commit -m "$(cat <<'EOF'
feat(normalize): apply_key_regex baseline — pass-through when no regex

Implements the no-op path for keys without left_regex/right_regex.
Regex matching itself lands in a subsequent commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `apply_key_regex` — regex fullmatch with 0 and 1 capture groups

**Goal:** Implement the actual regex logic. Rule: `re.fullmatch`; use `m.group(1)` if the compiled pattern has 1 group, else `m.group(0)`. `None` values still pass through unchanged.

**Files:**
- Modify: `src/datacompare/normalize/keys.py` (replace the `_apply_pattern_to_column` placeholder)
- Test: `tests/unit/normalize/test_keys.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_keys.py`:

```python
def test_apply_key_regex_capture_group_one_extracts_group_1():
    df = pd.DataFrame({"order_no": ["ORD-000123", "ORD-000456"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_no"]) == ["123", "456"]


def test_apply_key_regex_no_capture_group_uses_full_match():
    df = pd.DataFrame({"code": ["ABC123", "XYZ789"]})
    keys = [KeyMapping(left="code", right="code", left_regex=r"[A-Z]+\d+")]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["code"]) == ["ABC123", "XYZ789"]


def test_apply_key_regex_none_value_passes_through():
    df = pd.DataFrame({"order_no": ["ORD-001", None]}).astype(object)
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="left")
    vals = result["order_no"].tolist()
    assert vals[0] == "1"
    assert vals[1] is None


def test_apply_key_regex_right_side_uses_right_regex():
    df = pd.DataFrame({"order_id": ["ORD-000123"]})
    keys = [KeyMapping(left="order_no", right="order_id", right_regex=r"ORD-0*(\d+)")]
    result = apply_key_regex(df, keys, side="right")
    assert list(result["order_id"]) == ["123"]


def test_apply_key_regex_side_specific_only_transforms_configured_side():
    df_left = pd.DataFrame({"order_no": ["ORD-000123"]})
    df_right = pd.DataFrame({"order_id": ["123"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-0*(\d+)")]
    left_out = apply_key_regex(df_left, keys, side="left")
    right_out = apply_key_regex(df_right, keys, side="right")
    assert list(left_out["order_no"]) == ["123"]
    assert list(right_out["order_id"]) == ["123"]  # right had no regex — unchanged


def test_apply_key_regex_composite_keys_independent_regexes():
    df = pd.DataFrame({
        "order_no": ["ORD-000123", "ORD-000456"],
        "region_code": ["REG_BJ", "REG_SH"],
    })
    keys = [
        KeyMapping(left="order_no", right="oid", left_regex=r"ORD-0*(\d+)"),
        KeyMapping(left="region_code", right="reg", left_regex=r"REG_([A-Z]+)"),
    ]
    result = apply_key_regex(df, keys, side="left")
    assert list(result["order_no"]) == ["123", "456"]
    assert list(result["region_code"]) == ["BJ", "SH"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: 6 new tests FAIL with `NotImplementedError: Task 4 will implement regex logic`.

- [ ] **Step 3: Replace `_apply_pattern_to_column` with real logic**

In `src/datacompare/normalize/keys.py`, replace the placeholder function with:

```python
def _apply_pattern_to_column(
    df: pd.DataFrame, column: str, pattern_str: str, side: str,
) -> None:
    """Transform df[column] in place using pattern_str fullmatch.

    - None values pass through unchanged.
    - If pattern has 1 capture group, use m.group(1); else use m.group(0).
    - Mismatch handling: added in Task 5.
    """
    pattern = re.compile(pattern_str)
    use_group_one = pattern.groups == 1

    new_values = []
    for i, v in enumerate(df[column].tolist()):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            new_values.append(None)
            continue
        s = v if isinstance(v, str) else str(v)
        m = pattern.fullmatch(s)
        if m is None:
            # Task 5 replaces this with structured log + KeyRegexMismatchError.
            raise NotImplementedError("Task 5 will implement mismatch handling")
        new_values.append(m.group(1) if use_group_one else m.group(0))
    df[column] = new_values
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: all 11 tests PASS (5 pre-existing + 6 new). No test should hit the `NotImplementedError` branch.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/keys.py tests/unit/normalize/test_keys.py
git commit -m "$(cat <<'EOF'
feat(normalize): apply_key_regex — fullmatch with 0 or 1 capture group

Uses re.fullmatch; picks group(1) when pattern has one capture group,
else group(0). None values still pass through untouched. Mismatch
handling stubbed to NotImplementedError (Task 5 replaces it).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `apply_key_regex` — mismatch raises `KeyRegexMismatchError` with structured log

**Goal:** Replace the mismatch `NotImplementedError` with a structlog `error` event followed by `raise KeyRegexMismatchError(...)`. Fail-fast — first mismatch aborts.

**Files:**
- Modify: `src/datacompare/normalize/keys.py`
- Test: `tests/unit/normalize/test_keys.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_keys.py`:

```python
import structlog


def test_apply_key_regex_partial_match_raises_because_fullmatch():
    df = pd.DataFrame({"code": ["abc123def"]})
    keys = [KeyMapping(left="code", right="code", left_regex=r"\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    err = exc.value
    assert err.side == "left"
    assert err.column == "code"
    assert err.value == "abc123def"
    assert err.pattern == r"\d+"
    assert err.row_index == 0


def test_apply_key_regex_complete_mismatch_raises():
    df = pd.DataFrame({"order_no": ["ORD-001", "ORD-002", "CANCEL-999"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    err = exc.value
    assert err.row_index == 2  # third row, 0-based
    assert err.value == "CANCEL-999"


def test_apply_key_regex_first_mismatch_wins_fail_fast():
    df = pd.DataFrame({"order_no": ["BAD1", "BAD2"]})
    keys = [KeyMapping(left="order_no", right="order_id", left_regex=r"ORD-\d+")]
    with pytest.raises(KeyRegexMismatchError) as exc:
        apply_key_regex(df, keys, side="left")
    assert exc.value.row_index == 0  # first mismatch, not second
    assert exc.value.value == "BAD1"


def test_apply_key_regex_emits_structured_log_on_mismatch():
    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[cap])
    try:
        df = pd.DataFrame({"order_no": ["CANCEL-1"]})
        keys = [KeyMapping(
            left="order_no", right="order_id", left_regex=r"ORD-\d+",
        )]
        with pytest.raises(KeyRegexMismatchError):
            apply_key_regex(df, keys, side="left")
        assert len(cap.entries) >= 1
        entry = next(e for e in cap.entries if e["event"] == "key_regex_mismatch")
        assert entry["side"] == "left"
        assert entry["column"] == "order_no"
        assert entry["value"] == "CANCEL-1"
        assert entry["pattern"] == r"ORD-\d+"
        assert entry["row_index"] == 0
        assert entry["log_level"] == "error"
    finally:
        # restore default configuration to avoid leaking test config
        structlog.reset_defaults()
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: 4 new tests FAIL with `NotImplementedError: Task 5 will implement mismatch handling`.

- [ ] **Step 3: Replace mismatch stub with real logging + raise**

In `src/datacompare/normalize/keys.py`:

1. Add module-level logger at the top (below existing imports):

```python
import structlog

_logger = structlog.get_logger("datacompare.normalize.keys")
```

2. Replace the `if m is None: raise NotImplementedError(...)` block inside `_apply_pattern_to_column` with:

```python
        if m is None:
            _logger.error(
                "key_regex_mismatch",
                side=side,
                column=column,
                row_index=i,
                value=s,
                pattern=pattern_str,
            )
            raise KeyRegexMismatchError(
                side=side,
                column=column,
                value=s,
                pattern=pattern_str,
                row_index=i,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

Expected: all 15 tests PASS. Watch specifically for the structlog capture test — if it fails to find the event, verify the processor list includes `LogCapture` before any renderer that consumes/drops entries.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/keys.py tests/unit/normalize/test_keys.py
git commit -m "$(cat <<'EOF'
feat(normalize): apply_key_regex — structured log + raise on mismatch

First unmatched key value fires structlog error(event=key_regex_mismatch)
with side/column/row_index/value/pattern fields, then raises
KeyRegexMismatchError (fail-fast, no collect-all). Value is not masked
(see spec §日志).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire `apply_key_regex` into `normalize_side` pipeline

**Goal:** Insert the key regex step at the very front of `normalize_side`, before `apply_column_mapping`. Add integration tests that exercise the wired-up path via `normalize_side`.

**Files:**
- Modify: `src/datacompare/normalize/pipeline.py:52-67`
- Test: `tests/unit/normalize/test_pipeline.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/normalize/test_pipeline.py`. Note: `test_pipeline.py` does not yet import `pytest`; add both imports:

```python
import pytest
from datacompare.normalize.keys import KeyRegexMismatchError


def test_pipeline_applies_left_regex_before_join():
    df = pd.DataFrame({"order_no": ["ORD-000123"], "amount": ["100"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       left_regex=r"ORD-0*(\d+)")]
    fields = [FieldRule(left="amount", right="amount")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert list(result.columns) == ["order_id", "amount"]
    assert result.iloc[0]["order_id"] == "123"


def test_pipeline_applies_right_regex():
    df = pd.DataFrame({"order_id": ["ORD-000456"], "amount": ["200"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       right_regex=r"ORD-0*(\d+)")]
    fields = [FieldRule(left="amount", right="amount")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert result.iloc[0]["order_id"] == "456"


def test_pipeline_raises_key_regex_mismatch_error():
    df = pd.DataFrame({"order_no": ["CANCEL-999"], "amount": ["100"]})
    keys = [KeyMapping(left="order_no", right="order_id",
                       left_regex=r"ORD-\d+")]
    fields = [FieldRule(left="amount", right="amount")]
    with pytest.raises(KeyRegexMismatchError):
        normalize_side(df, keys, _cfg(fields), side="left")


def test_pipeline_backward_compatible_without_regex():
    """Existing configs without left_regex/right_regex must behave identically."""
    df = pd.DataFrame({"订单号": ["A1"], "金额": ["100.50"]})
    keys = [KeyMapping(left="订单号", right="order_id")]
    fields = [FieldRule(left="金额", right="amount", mode="numeric", decimal_places=2)]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert result.iloc[0]["order_id"] == "A1"
    assert result.iloc[0]["amount"] == 100.50
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py::test_pipeline_applies_left_regex_before_join -v
```

Expected: FAIL — the regex is not applied, `result.iloc[0]["order_id"]` will still be `"ORD-000123"`.

- [ ] **Step 3: Modify `normalize_side` to call `apply_key_regex` first**

Edit `src/datacompare/normalize/pipeline.py`:

1. Add import at the top of the file:
```python
from .keys import apply_key_regex
```

2. In `normalize_side` (currently starts at line 52), insert the key regex call as the first operation:

```python
def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Apply key regex -> rename -> filter -> per-field transform."""
    df = apply_key_regex(df, keys, side)
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [k.right for k in keys]

    result = renamed.copy()
    for rule in compare.fields:
        eff = effective_rule(rule, compare.defaults)
        col = eff.right
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
    return result[key_cols + [f.right for f in compare.fields]]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/Scripts/pytest tests/unit/normalize/ -v
```

Expected: all pipeline tests PASS (including 4 new + all pre-existing).

Then run the full unit suite to catch regressions:
```
.venv/Scripts/pytest tests/unit/ -q
```

Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/normalize/pipeline.py tests/unit/normalize/test_pipeline.py
git commit -m "$(cat <<'EOF'
feat(normalize): wire apply_key_regex as first step of normalize_side

Key regex transform now runs before column mapping so left_regex/
right_regex operate on original column names. Duplicate-key detection
still fires after regex, so configs that fold distinct raw values into
one canonical key surface as duplicate-key errors (correct behavior).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Engine parity + end-to-end tests

**Goal:** Verify (a) `InMemoryEngine` and `DiskEngine` produce identical results when a key has `left_regex`; (b) full `datacompare run` succeeds end-to-end with regex; (c) `datacompare run` exits with code 2 and emits `key_regex_mismatch` on bad data.

**Files:**
- Create: `tests/integration/test_key_regex_e2e.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/integration/test_key_regex_e2e.py`:

```python
"""End-to-end + engine parity tests for key regex transform.

Uses Excel-vs-Excel (no external services) so tests are self-contained.
"""
import json
from pathlib import Path
import pandas as pd
import pytest
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from datacompare.cli import app
from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig, RuntimeConfig,
)
from datacompare.engine.memory import InMemoryEngine
from datacompare.engine.disk import DiskEngine
from datacompare.sources.excel import ExcelSource


runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def _task_yaml(left_path: Path, right_path: Path, out_dir: Path) -> dict:
    return {
        "name": "key_regex_e2e",
        "sources": {
            "left": {"type": "excel", "path": str(left_path)},
            "right": {"type": "excel", "path": str(right_path)},
        },
        "match": {"keys": [
            {"left": "order_no", "right": "order_id",
             "left_regex": r"ORD-\d{4}-0*(\d+)"},
        ]},
        "compare": {"fields": [
            {"left": "amount", "right": "amount",
             "mode": "numeric", "decimal_places": 2},
        ]},
        "output": {"dir": str(out_dir),
                   "formats": ["json"]},
    }


def _build_task(left_path: Path, right_path: Path, engine: str) -> TaskConfig:
    return TaskConfig(
        name="parity",
        sources={
            "left": ExcelSourceConfig(path=str(left_path)),
            "right": ExcelSourceConfig(path=str(right_path)),
        },
        match=MatchConfig(keys=[KeyMapping(
            left="order_no", right="order_id",
            left_regex=r"ORD-\d{4}-0*(\d+)",
        )]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(left="amount", right="amount",
                              mode="numeric", decimal_places=2)],
        ),
        output=OutputConfig(dir="./out", formats=["json"]),
        runtime=RuntimeConfig(engine=engine, memory_threshold_rows=500_000),
    )


def test_engine_parity_with_left_regex(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["ORD-2026-000002", "200.00"],
        ["ORD-2026-000003", "300.00"],
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
        ["2", "200.50"],   # value diff
        ["4", "400.00"],   # right-only
    ])

    left_src = ExcelSource(sources_cfg=ExcelSourceConfig(path=str(left_path)), name="left")
    right_src = ExcelSource(sources_cfg=ExcelSourceConfig(path=str(right_path)), name="right")

    mem_task = _build_task(left_path, right_path, engine="memory")
    disk_task = _build_task(left_path, right_path, engine="disk")

    mem_result = InMemoryEngine().compare(left_src, right_src, mem_task)
    disk_result = DiskEngine().compare(left_src, right_src, disk_task)

    assert mem_result.matched_rows == disk_result.matched_rows
    assert mem_result.diff_rows == disk_result.diff_rows
    assert mem_result.left_total == disk_result.left_total
    assert mem_result.right_total == disk_result.right_total
    assert len(mem_result.field_errors) == len(disk_result.field_errors)
    # Row keys should match set-wise (order not guaranteed across engines)
    mem_keys = sorted(tuple(sorted(fe.row_key.items())) for fe in mem_result.field_errors)
    disk_keys = sorted(tuple(sorted(fe.row_key.items())) for fe in disk_result.field_errors)
    assert mem_keys == disk_keys


def test_cli_run_succeeds_with_key_regex(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["ORD-2026-000002", "200.00"],
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
        ["2", "200.00"],
    ])

    task_path = tmp_path / "task.yaml"
    out_dir = tmp_path / "out"
    task_path.write_text(yaml.safe_dump(_task_yaml(left_path, right_path, out_dir)))

    result = runner.invoke(app, [
        "run", str(task_path),
        "--connections", str(tmp_path / "nonexistent.yaml"),
    ])
    assert result.exit_code == 0, result.output

    json_files = list(out_dir.glob("*.json"))
    assert len(json_files) == 1
    report = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert report["matched_rows"] == 2
    assert report["diff_rows"] == 0


def test_cli_run_exits_2_and_logs_on_regex_mismatch(tmp_path):
    left_path = tmp_path / "left.xlsx"
    right_path = tmp_path / "right.xlsx"
    _make_xlsx(left_path, [
        ["order_no", "amount"],
        ["ORD-2026-000001", "100.00"],
        ["CANCEL-999", "100.00"],   # regex mismatch
    ])
    _make_xlsx(right_path, [
        ["order_id", "amount"],
        ["1", "100.00"],
    ])

    task_path = tmp_path / "task.yaml"
    out_dir = tmp_path / "out"
    task_path.write_text(yaml.safe_dump(_task_yaml(left_path, right_path, out_dir)))

    result = runner.invoke(app, [
        "run", str(task_path),
        "--connections", str(tmp_path / "nonexistent.yaml"),
    ])
    assert result.exit_code == 2, result.output
    combined = (result.output or "") + (result.stderr or "")
    assert "CANCEL-999" in combined or "key regex mismatch" in combined
    # Report files should NOT be produced
    assert not out_dir.exists() or not list(out_dir.glob("*.json"))
```

- [ ] **Step 2: Run tests to verify they fail (initially some may pass because plumbing works)**

```
.venv/Scripts/pytest tests/integration/test_key_regex_e2e.py -v
```

Expected: all three tests should actually PASS because Tasks 1-6 already delivered the wiring. If any fails, the failure indicates a real bug — fix it before proceeding. Do NOT skip tests.

- [ ] **Step 3: If any test fails, diagnose and fix**

Common issues to check:
- `ExcelSource` constructor signature — confirm `ExcelSource(sources_cfg=..., name=...)` matches the real class. If different (e.g., `ExcelSource(cfg=...)`), adjust.
- `runner.invoke` may need `mix_stderr=False` if stderr assertion fails to find text.
- Output dir may exist even on failure (empty) — the third test uses `not list(out_dir.glob("*.json"))` which handles that.

If you make changes to production code to satisfy a test, they belong in the appropriate task above — commit those changes as a fix-up.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```
.venv/Scripts/pytest tests/ -q
```

Expected: green (integration Docker-gated GaussDB tests may skip, that's fine).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_key_regex_e2e.py
git commit -m "$(cat <<'EOF'
test(integration): engine parity + e2e for key regex transform

Adds three tests: memory-vs-disk parity on a regex-transformed key,
CLI success path (exit 0, report emitted), and CLI failure path
(exit 2 on mismatch, no report emitted, error message includes bad
value).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update templates + docs

**Goal:** Users discover the feature via `init` templates and README. Add a comment example to each template (`.yaml`) and short prose sections to README/user-guide/CLAUDE.md.

**Files:**
- Modify: `src/datacompare/templates/excel_vs_gaussdb.yaml`
- Modify: `src/datacompare/templates/excel_vs_gaussdb_t.yaml`
- Modify: `src/datacompare/templates/api_vs_gaussdb.yaml`
- Modify: `src/datacompare/templates/excel_vs_api.yaml`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Add comment example to `excel_vs_gaussdb.yaml`**

Locate the `match: keys:` block. Immediately after the last `- left: … / right: …` entry, add a commented example. The current file (lines 20-25) has two key entries. After them, insert:

```yaml
    # Optional: normalize the key with a regex fullmatch before joining.
    # Both left_regex and right_regex are optional and default to no transformation.
    # Pattern must fullmatch and have 0 or 1 capture group; group 1 wins if present.
    # Example:
    #   - left: order_no
    #     right: order_id
    #     left_regex: 'ORD-\d{4}-0*(\d+)'   # extracts "123" from "ORD-2026-000123"
```

- [ ] **Step 2: Repeat the same comment block for the other three templates**

Add the identical (or minimally adjusted) comment block after the `match: keys:` entries in:
- `src/datacompare/templates/excel_vs_gaussdb_t.yaml`
- `src/datacompare/templates/api_vs_gaussdb.yaml`
- `src/datacompare/templates/excel_vs_api.yaml`

- [ ] **Step 3: Update `CLAUDE.md` "关键约束"**

Open `CLAUDE.md` and locate the "关键约束（改代码前务必了解）" section. After the `**GaussDBConnection**` bullet, append a new bullet:

```markdown
- **KeyMapping 支持 `left_regex` / `right_regex`**（v0.3 起）：可选，跑 `re.fullmatch`，允许 0 或 1 个捕获组（≥2 组加载时报错）。有捕获组用 `group(1)`，否则用 `group(0)`。**严格失败**：任一行不匹配 → 抛 `KeyRegexMismatchError`（`ValueError` 子类）→ CLI exit 2。null 值透传不参与匹配。归属层：`normalize/keys.py`。运行位置：`normalize_side` 首行，在 `apply_column_mapping` 之前。
```

- [ ] **Step 4: Add a section to `README.md`**

Locate the section describing `match:` / `keys:` (search for "match" or "keys" in the file). Add a new subsection:

```markdown
### 键值正则归一化（v0.3+）

当左右两侧 key 字面不同但可通过正则映射到同一形式时（如左 `"ORD-2026-000123"` 对右 `"123"`），在 key 上配 `left_regex` / `right_regex`：

```yaml
match:
  keys:
    - left: order_no
      right: order_id
      left_regex: 'ORD-\d{4}-0*(\d+)'   # 提取 "123"
```

规则：
- 用 Python `re.fullmatch`，整串必须匹配
- 0 或 1 个捕获组；有捕获组时用 `group(1)`，无则用 `group(0)`
- ≥2 个捕获组在 `datacompare validate` 阶段就报错（用非捕获组 `(?:...)` 分组）
- 任一行不匹配 → 立即失败，退出码 2，日志有 `key_regex_mismatch` 事件
- `None` 值原样透传，不参与正则

想要 case-insensitive 或多行模式？用内联 flag：`(?i)ord-\d+`。
```

- [ ] **Step 5: Add a corresponding section to `docs/user-guide.md`**

Add the same YAML example and rule list to `docs/user-guide.md`. Place it in the section that discusses match/keys configuration.

- [ ] **Step 6: Verify template loading still works**

Templates are read via `importlib.resources` in `cli.py:96-102`. Sanity check by running:

```
.venv/Scripts/python -m datacompare.cli init excel-vs-gaussdb | head -30
```

Expected: output includes the new commented `left_regex` example.

Repeat for all four templates.

- [ ] **Step 7: Full test suite one last time**

```
.venv/Scripts/pytest tests/ -q
```

Expected: all green (Docker-gated tests may skip).

- [ ] **Step 8: Commit**

```bash
git add src/datacompare/templates/*.yaml CLAUDE.md README.md docs/user-guide.md
git commit -m "$(cat <<'EOF'
docs: document key regex transform (templates, README, user-guide, CLAUDE)

Adds inline commented example to all four init templates and prose
sections to README + user-guide. CLAUDE.md gains a bullet in the
critical-constraints section describing the fullmatch/capture-group
semantics and exit-code contract.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Summary

**Spec coverage check** (against `docs/superpowers/specs/2026-07-16-key-regex-transform-design.md`):

| Spec section | Implemented in |
|---|---|
| §需求范围 – 每对 key 支持 left_regex/right_regex | Task 1, 4 |
| §需求范围 – 严格模式失败 | Task 5 |
| §需求范围 – 结构化错误日志 | Task 5 |
| §架构 – 位置在管线最前面 | Task 6 |
| §架构 – 新文件 normalize/keys.py | Task 2, 3 |
| §配置形状 – Pydantic 模型 + validator | Task 1 |
| §配置形状 – 向后兼容 | Task 6 (backward-compat test) |
| §配置形状 – 模板更新 | Task 8 |
| §正则语义 – re.fullmatch | Task 4 |
| §正则语义 – 0/1 捕获组规则 | Task 1 (validator), Task 4 (matching) |
| §正则语义 – ≥2 组加载报错 | Task 1 |
| §正则语义 – Flags 用 inline | (documented in Task 8, no code needed) |
| §错误语义 – 异常类型 | Task 2 |
| §错误语义 – Fail-fast | Task 5 (first-mismatch-wins test) |
| §错误语义 – null 值处理 | Task 3 (test) + Task 4 (impl) |
| §错误语义 – 结构化日志 | Task 5 |
| §错误语义 – CLI 退出码 2 | Task 7 (e2e test) |
| §契约签名 – apply_key_regex 签名 | Task 3 |
| §测试策略 – 单元测试全表 | Tasks 2-5 |
| §测试策略 – 配置模型测试 | Task 1 |
| §测试策略 – 引擎 parity | Task 7 |
| §测试策略 – 端到端 | Task 7 |
| §影响的现有文件 – 全部 | Tasks 1, 6, 8 |

**Type consistency check:** `apply_key_regex(df, keys, side)` signature stays identical across Task 3 → 4 → 5 (only body evolves). `KeyRegexMismatchError` constructor signature `(side, column, value, pattern, row_index)` stays identical from Task 2 through Task 5 (test in Task 2 pins it, tests in Task 5 verify the same fields via a real raise).

**Placeholder check:** None. Every code step has literal code; every command has exact expected output description.
