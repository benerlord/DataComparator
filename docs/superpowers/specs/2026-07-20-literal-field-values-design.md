# Literal Field Values — Design Spec

**Date:** 2026-07-20
**Status:** Approved for implementation
**Scope:** One PR / single implementation plan

## Problem

When comparing two sources, users sometimes need a compare field where one
side has no matching column but should be treated as a fixed constant
against a real column on the other side. Real scenario surfaced in batch
mode: an Excel sheet has no `zone` column, but the corresponding GaussDB
table has a `type` column that should always equal `"Azone"` for matched
rows. Today the user must either preprocess the Excel or skip the check.

## Solution Overview

Add two optional Pydantic fields to `FieldRule`: `left_literal` and
`right_literal`. Each holds a `str | None` value that is broadcast to
every row on that side during normalize, replacing what would otherwise
be a source-column lookup. The literal flows through the standard
per-field transform pipeline (string preprocess → unit → type coerce →
decimal round), so `mode: numeric` etc. work uniformly.

Only compare fields (`FieldRule`) support literals. Match keys
(`KeyMapping`) do not — a literal join key would create a cartesian
product and has no meaningful semantics.

## YAML Surface

```yaml
compare:
  fields:
    # Existing (unchanged behavior)
    - {left: real_col, right: real_col}

    # NEW: left is a constant string
    - {left_literal: "Azone", right: type}

    # NEW: left is literal null (assert right column is null for matched rows)
    - {left_literal: null, right: deleted_at}

    # NEW: right is a constant (symmetric)
    - {left: name, right_literal: "prod"}

    # NEW: literal + numeric mode → literal coerced through same pipeline
    - {left_literal: "30", right: memory,
       mode: numeric, decimal_places: 2}
```

## Validation Rules

On `FieldRule` via `@model_validator(mode="after")`:

- For each side (`left`, `right`) **exactly one of** `<side>` or
  `<side>_literal` must be provided. Both provided → error. Neither
  provided → error.
- "Provided" is judged by Pydantic v2's `model_fields_set`, **not** by
  checking `value is None`. This lets `left_literal: null` (explicit
  YAML `null`) be distinguishable from "left_literal not written at
  all". Both yield `.left_literal == None` at runtime, but the former is
  in `model_fields_set` and the latter isn't.
- Both sides being literal (`{left_literal: "A", right_literal: "A"}`)
  is allowed. It's pointless — always matches or always differs — but
  YAGNI on that validation.

## Model Changes

`src/datacompare/config/models.py::FieldRule`:

```python
class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str | None = None          # was: str
    right: str | None = None         # was: str
    left_literal: str | None = None  # NEW
    right_literal: str | None = None # NEW
    # ... existing mode / decimal_places / ... unchanged

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

**Backward compatibility:** any existing `{left: "col", right: "col"}`
still passes (both `left` and `right` in `model_fields_set`, neither
`_literal` set). No behavior change for existing configs.

## Pipeline Changes

`src/datacompare/normalize/columns.py::apply_column_mapping`:

```python
def apply_column_mapping(df, keys, fields, side):
    rename_map = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    for f in fields:
        src = getattr(f, side)  # may be None for literal fields
        if src is not None:
            rename_map[src] = f.right

    missing = [src for src in rename_map if src not in df.columns]
    if missing:
        raise ConfigError(...)  # unchanged

    src_cols = list(rename_map.keys())
    result = df[src_cols].rename(columns=rename_map)

    # NEW: inject literal columns as constants
    for f in fields:
        if getattr(f, side) is None:
            literal_val = getattr(f, f"{side}_literal")
            result[f.right] = literal_val  # pandas broadcasts scalar

    return result
```

**Zero-row DataFrame:** `result[f.right] = "Azone"` on an empty
DataFrame creates an empty column of dtype object. No crash. Downstream
merge produces no matched rows, which is correct.

**Pipeline injection point:** `apply_column_mapping` is the only
touched function. `normalize_side` in `pipeline.py` is unchanged —
the literal column, once injected, is indistinguishable from a real
column and flows through `_process_value` per the field's rule
(`mode`, `null_equivalents`, `parse_unit`, etc. all apply naturally).

**Effect of `null_equivalents`:** if user writes
`left_literal: "NULL"` and `null_equivalents` contains `"NULL"`, the
literal becomes `None`. Users who genuinely want None should write
`left_literal: null`.

## What Does NOT Change

- `KeyMapping` — no `left_literal` / `right_literal` on join keys.
- Engine layer (`memory.py`, `disk.py`) — merge and diff logic
  unchanged; the canonical DataFrame passed in already has literal
  columns materialized.
- Reporters — literal-valued diffs render exactly like any other
  value diff (`left_value: "Azone"`, `right_value: "Bzone"`, etc.).
- Batch mode — `fields:` lists replace wholesale during deep merge
  (per existing rule), so a sub-task overriding a defaults field with
  a literal version doesn't create merge collisions.

## Testing

**Model validation** (`tests/unit/config/test_models.py`):
- `FieldRule(left="a", right="b")` → OK
- `FieldRule(left_literal="X", right="b")` → OK
- `FieldRule(left_literal=None, right="b")` → OK (explicit null literal)
- `FieldRule(left="a", right_literal="X")` → OK
- `FieldRule(right="b")` → ValidationError (neither left nor left_literal)
- `FieldRule(left="a", left_literal="X", right="b")` → ValidationError

**Column injection** (`tests/unit/normalize/test_columns.py`):
- `apply_column_mapping` with a `left_literal` field: result has the
  synthetic column with the constant value broadcast to all rows.
- Same with `right_literal` on side="right".
- `left_literal: None` → column of None values.
- Zero-row DataFrame + literal → empty column, no crash.

**End-to-end via pipeline** (`tests/unit/normalize/test_pipeline.py`):
- `{left_literal: "30", right: "amt", mode: numeric, decimal_places: 2}`
  with a left DataFrame lacking `amt` → normalized left has `amt`
  column of `30.0` values.
- `{left_literal: null, right: "deleted_at"}` → normalized left has
  `deleted_at` column of `None` values.

**Integration** (`tests/integration/test_batch_e2e.py`):
- New sub-task in a batch: Excel (no `type` column) vs. inline right
  Excel with a `type` column that varies per row. Assert diffs land
  only for rows where right's `type != literal`.

## Documentation

- `README.md`: add "字面量字段" (literal fields) subsection under
  比对规则. Short example matching the YAML surface above.
- `docs/user-guide.md`: same, under Comparison modes section, with
  the null-literal case and the numeric-coercion note.
- `CLAUDE.md`: append a bullet under 关键约束 noting the literal
  feature and the `model_fields_set` disambiguation trick (so future
  editors don't accidentally use `is None` checks that break null
  literals).

## Estimated Scope

- Model: ~15 lines (2 field additions + validator method)
- `apply_column_mapping`: ~8 lines (loop + injection)
- Tests: ~80 lines across 3 files
- Docs: ~30 lines across 3 files

Single commit, single PR. No dependency additions.
