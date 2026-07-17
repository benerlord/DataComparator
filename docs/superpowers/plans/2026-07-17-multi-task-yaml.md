# Multi-Task YAML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "batch mode" to `datacompare run` where one YAML file declares N sub-tasks that share `defaults` via deep merge and each runs independently with its own output subdirectory + one aggregate `batch.log`.

**Architecture:** New pure-function `deep_merge` in `config/merge.py` combines a top-level defaults block with each sub-task's overrides; `load_task_or_batch` returns `TaskConfig | BatchConfig` depending on presence of `tasks:` key; `execute_batch` iterates sub-tasks sequentially, honoring `on_error: continue|fail_fast`, catches exceptions per sub-task, aggregates into `BatchResult`, writes structured `batch.log`. CLI's `run` command dispatches to `execute` or `execute_batch`. Fully backward compatible — single-task YAML unchanged.

**Tech Stack:** Python 3.11+, Pydantic v2 (`model_validate`), structlog (aggregate log), Typer CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-multi-task-yaml-design.md`

---

## Task 1: `deep_merge` pure function in `config/merge.py`

**Goal:** Pure merge algorithm; no I/O, no Pydantic. Rules: dict → recursive; list → replace; nested dict with different `type` key → replace; `None` in override clears defaults.

**Files:**
- Create: `src/datacompare/config/merge.py`
- Test: `tests/unit/config/test_merge.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/config/test_merge.py`:

```python
from datacompare.config.merge import deep_merge


def test_deep_merge_flat_dict():
    result = deep_merge({"a": 1, "b": 2}, {"b": 20, "c": 3})
    assert result == {"a": 1, "b": 20, "c": 3}


def test_deep_merge_nested_dict():
    d = {"a": 1, "b": {"c": 2, "d": 3}}
    o = {"b": {"d": 40, "e": 5}}
    assert deep_merge(d, o) == {"a": 1, "b": {"c": 2, "d": 40, "e": 5}}


def test_deep_merge_list_replaces_not_extends():
    d = {"formats": ["html", "json"]}
    o = {"formats": ["csv"]}
    assert deep_merge(d, o) == {"formats": ["csv"]}


def test_deep_merge_empty_list_replaces():
    d = {"formats": ["html"]}
    o = {"formats": []}
    assert deep_merge(d, o) == {"formats": []}


def test_deep_merge_none_in_override_clears_defaults():
    d = {"a": 1, "b": "keep"}
    o = {"b": None}
    assert deep_merge(d, o) == {"a": 1, "b": None}


def test_deep_merge_missing_key_inherits_from_defaults():
    d = {"a": 1, "b": 2}
    o = {"a": 10}
    assert deep_merge(d, o) == {"a": 10, "b": 2}


def test_deep_merge_type_change_in_nested_dict_replaces_whole_dict():
    """right.type=gaussdb defaults dropped when override switches to right.type=api."""
    d = {"right": {"type": "gaussdb", "connection": "prod", "timeout": 30}}
    o = {"right": {"type": "api", "url": "/v1/vms"}}
    assert deep_merge(d, o) == {"right": {"type": "api", "url": "/v1/vms"}}


def test_deep_merge_same_type_deep_merges_normally():
    d = {"right": {"type": "gaussdb", "connection": "prod", "timeout": 30}}
    o = {"right": {"type": "gaussdb", "query": "SELECT 1"}}
    assert deep_merge(d, o) == {
        "right": {"type": "gaussdb", "connection": "prod", "timeout": 30, "query": "SELECT 1"}
    }


def test_deep_merge_type_change_ignored_when_only_one_side_has_type():
    """If defaults has type but override doesn't specify type, deep-merge normally."""
    d = {"right": {"type": "gaussdb", "connection": "prod"}}
    o = {"right": {"query": "SELECT 1"}}
    assert deep_merge(d, o) == {
        "right": {"type": "gaussdb", "connection": "prod", "query": "SELECT 1"}
    }


def test_deep_merge_does_not_mutate_inputs():
    d = {"a": {"b": 1}}
    o = {"a": {"c": 2}}
    deep_merge(d, o)
    assert d == {"a": {"b": 1}}
    assert o == {"a": {"c": 2}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/config/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'datacompare.config.merge'`

- [ ] **Step 3: Implement `deep_merge`**

Create `src/datacompare/config/merge.py`:

```python
"""Pure-function deep merge for batch YAML defaults + sub-task overrides.

Rules (see docs/superpowers/specs/2026-07-17-multi-task-yaml-design.md § deep merge):
- dict: recursive merge; override keys win
- list: override replaces defaults entirely (no concat)
- nested dict with 'type' key differing between defaults and override:
  override wins wholesale (defaults' other keys dropped)
- None in override explicitly overrides (does NOT mean "inherit")
"""
from __future__ import annotations
import copy
from typing import Any


def deep_merge(defaults: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict merging override on top of defaults. Inputs are not mutated."""
    result: dict[str, Any] = copy.deepcopy(defaults)
    for key, override_val in override.items():
        if key not in result:
            result[key] = copy.deepcopy(override_val)
            continue
        default_val = result[key]
        if isinstance(default_val, dict) and isinstance(override_val, dict):
            # 'type' change → wholesale replace
            d_type = default_val.get("type")
            o_type = override_val.get("type")
            if d_type is not None and o_type is not None and d_type != o_type:
                result[key] = copy.deepcopy(override_val)
            else:
                result[key] = deep_merge(default_val, override_val)
        else:
            # list, scalar, None — replace
            result[key] = copy.deepcopy(override_val)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_merge.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/merge.py tests/unit/config/test_merge.py
git commit -m "$(cat <<'EOF'
feat(config): add deep_merge pure function for batch YAML defaults

Merges override on top of defaults with dict-recursive semantics, list
replacement (no concat), and wholesale replacement when a nested dict's
'type' key changes between the two sides. Returns a new dict without
mutating inputs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `BatchTaskOverride` + `BatchConfig` Pydantic models

**Goal:** Two new models. `BatchTaskOverride` = a sub-task entry accepting `extra="allow"` for freeform pre-merge fields. `BatchConfig` = top-level batch document.

**Files:**
- Modify: `src/datacompare/config/models.py` (append at end, near `TaskConfig`)
- Test: `tests/unit/config/test_batch_models.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/config/test_batch_models.py`:

```python
import pytest
from pydantic import ValidationError
from datacompare.config.models import BatchConfig, BatchTaskOverride


def _minimal_sub_task(name: str = "t1", **extra) -> dict:
    return {"name": name, **extra}


def test_batch_config_minimal_valid():
    cfg = BatchConfig(
        name="b",
        tasks=[BatchTaskOverride(**_minimal_sub_task())],
    )
    assert cfg.name == "b"
    assert cfg.on_error == "continue"  # default
    assert len(cfg.tasks) == 1


def test_batch_config_on_error_literal():
    BatchConfig(name="b", on_error="fail_fast",
                tasks=[BatchTaskOverride(**_minimal_sub_task())])
    with pytest.raises(ValidationError):
        BatchConfig(name="b", on_error="bogus",
                    tasks=[BatchTaskOverride(**_minimal_sub_task())])


def test_batch_config_tasks_min_length_one():
    with pytest.raises(ValidationError) as exc:
        BatchConfig(name="b", tasks=[])
    assert "at least 1" in str(exc.value).lower() or "min_length" in str(exc.value).lower()


def test_batch_task_names_must_be_unique():
    with pytest.raises(ValidationError) as exc:
        BatchConfig(name="b", tasks=[
            BatchTaskOverride(**_minimal_sub_task("dup")),
            BatchTaskOverride(**_minimal_sub_task("dup")),
        ])
    assert "unique" in str(exc.value).lower() or "duplicate" in str(exc.value).lower()


def test_batch_task_override_allows_extra_fields():
    """Pre-merge overrides may contain any structure; validated after merge."""
    t = BatchTaskOverride(
        name="t1",
        sources={"left": {"sheets": [{"name": "S1"}]}, "right": {"query": "SELECT 1"}},
        match={"keys": [{"left": "id", "right": "id"}]},
        compare={"fields": []},
    )
    assert t.name == "t1"
    # extra fields accessible as attributes or via model_extra
    assert t.model_extra is not None
    assert "sources" in t.model_extra


def test_batch_config_optional_defaults_blocks():
    """sources/match/compare/output/runtime are all optional at batch level."""
    cfg = BatchConfig(
        name="b",
        sources={"left": {"type": "excel", "path": "a"}, "right": {"type": "excel", "path": "b"}},
        tasks=[BatchTaskOverride(**_minimal_sub_task())],
    )
    assert cfg.sources == {"left": {"type": "excel", "path": "a"},
                            "right": {"type": "excel", "path": "b"}}
    assert cfg.match is None
    assert cfg.compare is None


def test_batch_config_extra_top_level_field_forbidden():
    """Top-level unknown key catches typos early."""
    with pytest.raises(ValidationError):
        BatchConfig(name="b", nonsense_key=1,
                    tasks=[BatchTaskOverride(**_minimal_sub_task())])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/config/test_batch_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'BatchConfig'`

- [ ] **Step 3: Add models to `src/datacompare/config/models.py`**

Append at the END of the file (after `TaskConfig` and connections):

```python
# ---------- Batch (multi-task) mode -----------------------------------------

class BatchTaskOverride(BaseModel):
    """Sub-task entry inside a BatchConfig. Freeform pre-merge; validated
    as a full TaskConfig after deep-merging with batch defaults.
    """
    model_config = ConfigDict(extra="allow")
    name: str


class BatchConfig(BaseModel):
    """Top-level batch document. Presence of 'tasks:' triggers multi mode."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    on_error: Literal["continue", "fail_fast"] = "continue"
    # All "defaults" blocks — pre-merge freeform dicts, validated per sub-task after merge.
    sources: dict[str, dict] | None = None
    match: dict | None = None
    compare: dict | None = None
    output: dict | None = None
    runtime: dict | None = None
    tasks: list[BatchTaskOverride] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def _unique_names(cls, v: list[BatchTaskOverride]) -> list[BatchTaskOverride]:
        names = [t.name for t in v]
        seen: set[str] = set()
        dups: list[str] = []
        for n in names:
            if n in seen:
                dups.append(n)
            seen.add(n)
        if dups:
            raise ValueError(f"sub-task names must be unique; duplicates: {dups}")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/config/test_batch_models.py tests/unit/config/ -v`
Expected: all 7 new tests PASS; all pre-existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_batch_models.py
git commit -m "$(cat <<'EOF'
feat(config): add BatchConfig and BatchTaskOverride models for multi-task mode

BatchConfig is the top-level batch document (name + on_error + optional
defaults + tasks list). BatchTaskOverride allows extra fields so sub-task
partial dicts can be deep-merged with defaults before full TaskConfig
validation. field_validator enforces unique sub-task names at load time.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `load_task_or_batch` with mode detection + per-sub-task merge/validation

**Goal:** New loader that returns `TaskConfig | BatchConfig`; when batch, it also validates each merged sub-task upfront (fail-fast on load), returning a `BatchConfig` whose `tasks` list still holds `BatchTaskOverride` — the fully-merged dicts are computed on demand by the runner via a helper.

Actually simpler: the loader validates each sub-task by trying `TaskConfig.model_validate(merged_dict)` at load time, so config errors surface before `execute_batch` runs.

**Files:**
- Modify: `src/datacompare/config/loader.py` (add `load_task_or_batch` + `merge_sub_task` helper)
- Test: `tests/unit/config/test_loader.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/config/test_loader.py`:

```python
import pytest
from pathlib import Path
from datacompare.config.loader import load_task_or_batch, merge_sub_task
from datacompare.config.models import TaskConfig, BatchConfig
from datacompare.config.errors import ConfigError


_SINGLE_YAML = """
name: single_task
sources:
  left: {type: excel, path: a.xlsx}
  right: {type: excel, path: b.xlsx}
match:
  keys: [{left: id, right: id}]
compare:
  fields: [{left: v, right: v}]
output:
  dir: ./out
  formats: [json]
"""

_BATCH_YAML = """
name: batch_x
on_error: continue
sources:
  left: {type: excel, path: manage.xlsx}
  right: {type: excel, path: right.xlsx}
match:
  keys: [{left: id, right: id}]
compare:
  fields: [{left: v, right: v}]
output:
  dir: ./out
  formats: [json]
tasks:
  - name: sub1
    sources:
      left: {sheets: [{name: "S1"}]}
      right: {path: right1.xlsx}
  - name: sub2
    sources:
      left: {sheets: [{name: "S2"}]}
      right: {path: right2.xlsx}
"""


def test_load_returns_taskconfig_when_no_tasks_key(tmp_path):
    p = tmp_path / "single.yaml"
    p.write_text(_SINGLE_YAML)
    cfg = load_task_or_batch(p, {})
    assert isinstance(cfg, TaskConfig)
    assert cfg.name == "single_task"


def test_load_returns_batchconfig_when_tasks_key_present(tmp_path):
    p = tmp_path / "batch.yaml"
    p.write_text(_BATCH_YAML)
    cfg = load_task_or_batch(p, {})
    assert isinstance(cfg, BatchConfig)
    assert cfg.name == "batch_x"
    assert len(cfg.tasks) == 2


def test_load_batch_with_empty_tasks_list_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("name: x\ntasks: []\n")
    with pytest.raises(ConfigError):
        load_task_or_batch(p, {})


def test_merge_sub_task_produces_full_task_dict():
    defaults = {
        "sources": {
            "left": {"type": "excel", "path": "manage.xlsx"},
            "right": {"type": "gaussdb", "connection": "c"},
        },
        "match": {"keys": [{"left": "id", "right": "id"}]},
        "compare": {"fields": [{"left": "v", "right": "v"}]},
        "output": {"dir": "./out", "formats": ["json"]},
    }
    sub = {
        "name": "s1",
        "sources": {
            "left": {"sheets": [{"name": "S1"}]},
            "right": {"query": "SELECT 1"},
        },
    }
    merged = merge_sub_task(defaults, sub)
    assert merged["name"] == "s1"
    assert merged["sources"]["left"]["path"] == "manage.xlsx"       # inherited
    assert merged["sources"]["left"]["sheets"] == [{"name": "S1"}]  # override
    assert merged["sources"]["right"]["connection"] == "c"           # inherited
    assert merged["sources"]["right"]["query"] == "SELECT 1"         # override


def test_load_batch_validates_each_sub_task_upfront(tmp_path):
    """Sub-task missing required field after merge → fail at load, not at run."""
    bad = """
name: bad_batch
sources:
  left: {type: excel, path: a.xlsx}
tasks:
  - name: incomplete
    sources:
      left: {sheets: [{name: S1}]}
    match:
      keys: [{left: id, right: id}]
    compare:
      fields: []
    output:
      dir: ./out
      formats: [json]
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ConfigError) as exc:
        load_task_or_batch(p, {})
    assert "incomplete" in str(exc.value) or "right" in str(exc.value)


def test_load_batch_reports_all_sub_task_errors(tmp_path):
    """Two bad sub-tasks — user should see both, not just the first."""
    bad = """
name: bad_batch
sources:
  left: {type: excel, path: a.xlsx}
  right: {type: gaussdb, connection: c}
match:
  keys: [{left: id, right: id}]
compare:
  fields: []
output:
  dir: ./out
  formats: [json]
tasks:
  - name: sub_a
    sources: {right: {}}
  - name: sub_b
    sources: {right: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ConfigError) as exc:
        load_task_or_batch(p, {})
    msg = str(exc.value)
    assert "sub_a" in msg and "sub_b" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/config/test_loader.py -v -k "batch or merge"`
Expected: FAIL with `ImportError: cannot import name 'load_task_or_batch'`

- [ ] **Step 3: Extend `src/datacompare/config/loader.py`**

Add these functions at the bottom of the file:

```python
from .merge import deep_merge
from .models import BatchConfig


def merge_sub_task(defaults: dict, sub_task: dict) -> dict:
    """Produce a full TaskConfig dict by merging defaults with a sub-task's overrides.

    Removes the 'name' key from sub_task before merging (name only lives at sub-task level)
    then re-attaches after merge so the produced dict is a valid TaskConfig payload.
    """
    sub_copy = dict(sub_task)
    name = sub_copy.pop("name")
    # Strip None fields from defaults so we merge only the fields that were actually provided.
    clean_defaults = {k: v for k, v in defaults.items() if v is not None}
    merged = deep_merge(clean_defaults, sub_copy)
    merged["name"] = name
    return merged


def load_task_or_batch(path: Path, params: dict[str, str] | None = None) -> TaskConfig | BatchConfig:
    """Parse YAML; return BatchConfig if 'tasks:' key present, else TaskConfig.

    For batch mode, every sub-task is merged with defaults and validated as a
    TaskConfig at load time — errors from all sub-tasks are collected and raised
    together so users can fix multiple issues in one pass.
    """
    params = params or {}
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f)
    if raw is None:
        raise ConfigError(f"empty task file: {path}")
    substituted = _walk_substitute(raw, params)

    if "tasks" in substituted:
        return _load_batch(substituted)
    return _load_single(substituted)


def _load_single(substituted: dict) -> TaskConfig:
    try:
        return TaskConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"task config validation failed:\n{errors}") from e


def _load_batch(substituted: dict) -> BatchConfig:
    try:
        batch = BatchConfig.model_validate(substituted)
    except ValidationError as e:
        errors = "\n".join(f"  · {err['loc']}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"batch config validation failed:\n{errors}") from e

    # Now validate each merged sub-task as a TaskConfig, collecting all errors.
    defaults_dict = {
        k: v for k, v in {
            "sources": batch.sources,
            "match": batch.match,
            "compare": batch.compare,
            "output": batch.output,
            "runtime": batch.runtime,
        }.items() if v is not None
    }
    per_sub_errors: list[str] = []
    for sub in batch.tasks:
        sub_dict = {"name": sub.name, **(sub.model_extra or {})}
        merged = merge_sub_task(defaults_dict, sub_dict)
        try:
            TaskConfig.model_validate(merged)
        except ValidationError as e:
            errs = "; ".join(f"{err['loc']}: {err['msg']}" for err in e.errors())
            per_sub_errors.append(f"  · [{sub.name}] {errs}")
    if per_sub_errors:
        raise ConfigError(
            "batch sub-task validation failed:\n" + "\n".join(per_sub_errors)
        )
    return batch
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/config/ -v`
Expected: all new tests PASS; all pre-existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/config/loader.py tests/unit/config/test_loader.py
git commit -m "$(cat <<'EOF'
feat(config): load_task_or_batch dispatches by 'tasks:' key presence

Batch mode validates each merged sub-task upfront as a TaskConfig,
collecting all per-sub-task errors before raising a single ConfigError.
Users see every problem in one pass instead of fixing one at a time.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `BatchResult` + `SubTaskResult` dataclasses

**Goal:** Result types the runner produces so CLI and tests can inspect batch outcomes.

**Files:**
- Modify: `src/datacompare/engine/result.py`
- Test: `tests/unit/engine/test_result.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/engine/test_result.py`:

```python
from datacompare.engine.result import BatchResult, SubTaskResult, CompareResult
import pandas as pd


def _dummy_compare(name: str = "t") -> CompareResult:
    return CompareResult(
        task_name=name, left_name="l", right_name="r",
        left_total=1, right_total=1, matched_rows=1, identical_rows=1,
        diff_rows=0, left_only=0, right_only=0,
        diff_details=pd.DataFrame(), left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=0.1,
    )


def test_sub_task_result_success():
    st = SubTaskResult(
        task_name="s1", status="success",
        comparison_result=_dummy_compare("s1"),
        error=None, duration_ms=1234,
    )
    assert st.status == "success"
    assert st.is_success


def test_sub_task_result_failed_carries_error():
    err = ValueError("boom")
    st = SubTaskResult(task_name="s2", status="failed",
                       comparison_result=None, error=err, duration_ms=50)
    assert st.status == "failed"
    assert not st.is_success
    assert st.error is err


def test_sub_task_result_skipped():
    st = SubTaskResult(task_name="s3", status="skipped",
                       comparison_result=None, error=None, duration_ms=0)
    assert st.status == "skipped"


def test_batch_result_aggregates_counts():
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "success", _dummy_compare(), None, 100),
            SubTaskResult("s2", "failed", None, ValueError("x"), 50),
            SubTaskResult("s3", "skipped", None, None, 0),
        ],
        total_duration_ms=150,
    )
    assert br.success_count == 1
    assert br.failed_count == 1
    assert br.skipped_count == 1


def test_batch_result_exit_code_all_success_no_diff():
    br = BatchResult(
        batch_name="b",
        task_results=[SubTaskResult("s1", "success", _dummy_compare(), None, 100)],
        total_duration_ms=100,
    )
    assert br.compute_exit_code(fail_on_diff=False) == 0


def test_batch_result_exit_code_all_success_with_diff_fail_on_diff():
    cr = _dummy_compare()
    cr.diff_rows = 1
    br = BatchResult(
        batch_name="b",
        task_results=[SubTaskResult("s1", "success", cr, None, 100)],
        total_duration_ms=100,
    )
    assert br.compute_exit_code(fail_on_diff=True) == 10


def test_batch_result_exit_code_config_error_wins_over_runtime():
    """priority: 2 > 10 > 1 > 0 — but ConfigError should be 1, runtime should be 2."""
    from datacompare.config.errors import ConfigError
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "failed", None, ConfigError("bad"), 50),
            SubTaskResult("s2", "failed", None, ValueError("runtime"), 100),
        ],
        total_duration_ms=150,
    )
    # runtime error (2) beats config error (1)
    assert br.compute_exit_code(fail_on_diff=False) == 2


def test_batch_result_exit_code_config_error_only():
    from datacompare.config.errors import ConfigError
    br = BatchResult(
        batch_name="b",
        task_results=[
            SubTaskResult("s1", "failed", None, ConfigError("bad"), 50),
            SubTaskResult("s2", "success", _dummy_compare(), None, 100),
        ],
        total_duration_ms=150,
    )
    assert br.compute_exit_code(fail_on_diff=False) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py -v -k "sub_task or batch"`
Expected: FAIL with `ImportError: cannot import name 'BatchResult'`

- [ ] **Step 3: Add dataclasses to `src/datacompare/engine/result.py`**

Append at the end of the file:

```python
from typing import Literal


@dataclass
class SubTaskResult:
    task_name: str
    status: Literal["success", "failed", "skipped"]
    comparison_result: "CompareResult | None"
    error: Exception | None
    duration_ms: int

    @property
    def is_success(self) -> bool:
        return self.status == "success"


@dataclass
class BatchResult:
    batch_name: str
    task_results: list[SubTaskResult]
    total_duration_ms: int

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "skipped")

    def compute_exit_code(self, fail_on_diff: bool) -> int:
        """Priority: 2 (runtime error) > 10 (diff+fail_on_diff) > 1 (config error) > 0."""
        from datacompare.config.errors import ConfigError
        has_runtime_error = False
        has_config_error = False
        has_diff = False
        for r in self.task_results:
            if r.status == "failed":
                if isinstance(r.error, ConfigError):
                    has_config_error = True
                else:
                    has_runtime_error = True
            elif r.status == "success" and r.comparison_result is not None:
                cr = r.comparison_result
                if cr.diff_rows > 0 or cr.left_only > 0 or cr.right_only > 0:
                    has_diff = True
        if has_runtime_error:
            return 2
        if fail_on_diff and has_diff:
            return 10
        if has_config_error:
            return 1
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/engine/test_result.py -v`
Expected: all new tests PASS; all pre-existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/engine/result.py tests/unit/engine/test_result.py
git commit -m "$(cat <<'EOF'
feat(engine): add BatchResult and SubTaskResult dataclasses

BatchResult aggregates per-sub-task results and computes the CLI exit
code from the priority ladder (2 > 10 > 1 > 0). SubTaskResult carries
per-task status/error/comparison_result/duration.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `execute_batch` — sequential run, `on_error=continue` default, per-sub-task output dir

**Goal:** Run each sub-task via existing `execute()`, catch exceptions per sub-task, populate `BatchResult`. Handle `on_error=continue` (default). Compute per-sub-task output dir: if sub-task raw dict has `output.dir` → use it; else `{defaults.output.dir}/{sub_task.name}/`.

**Files:**
- Modify: `src/datacompare/runner.py` (add `execute_batch`)
- Test: `tests/unit/test_runner_batch.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_runner_batch.py`:

```python
from pathlib import Path
import pytest
from openpyxl import Workbook
from datacompare.config.loader import load_task_or_batch
from datacompare.runner import execute_batch
from datacompare.engine.result import BatchResult


def _make_xlsx(path: Path, rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)


def _write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def _batch_two_success(tmp_path: Path) -> Path:
    _make_xlsx(tmp_path / "left.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"], ["A2", "2.00"],
    ])
    _make_xlsx(tmp_path / "right.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"], ["A2", "2.00"],
    ])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: [{{left: amount, right: amount, mode: numeric, decimal_places: 2}}]
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
""")
    return task


def test_execute_batch_all_success(tmp_path):
    task_path = _batch_two_success(tmp_path)
    batch = load_task_or_batch(task_path, {})
    result = execute_batch(batch, connections={})
    assert isinstance(result, BatchResult)
    assert result.success_count == 2
    assert result.failed_count == 0
    assert (tmp_path / "out" / "sub1" / "report.json").exists()
    assert (tmp_path / "out" / "sub2" / "report.json").exists()


def test_execute_batch_continues_on_sub_task_failure(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"],
    ])
    _make_xlsx(tmp_path / "right.xlsx", [
        ["order_id", "amount"], ["A1", "1.00"],
    ])
    # sub2 will fail: points at a non-existent file
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
on_error: continue
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: [{{left: amount, right: amount, mode: numeric, decimal_places: 2}}]
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
    sources:
      left: {{path: {tmp_path}/missing.xlsx}}
""")
    batch = load_task_or_batch(task, {})
    result = execute_batch(batch, connections={})
    assert result.success_count == 1
    assert result.failed_count == 1
    assert result.task_results[0].status == "success"
    assert result.task_results[1].status == "failed"
    assert result.task_results[1].error is not None


def test_execute_batch_sub_task_explicit_output_dir_overrides_autopath(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    custom_dir = tmp_path / "custom_place"
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub_custom
    output:
      dir: {custom_dir}
""")
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    assert (custom_dir / "report.json").exists()
    # auto-path NOT used
    assert not (tmp_path / "out" / "sub_custom").exists() or not (tmp_path / "out" / "sub_custom" / "report.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py -v`
Expected: FAIL with `ImportError: cannot import name 'execute_batch'`

- [ ] **Step 3: Implement `execute_batch` in `src/datacompare/runner.py`**

At the top of `runner.py`, add new imports:

```python
import time
from datacompare.config.models import BatchConfig
from datacompare.config.loader import merge_sub_task
from datacompare.engine.result import BatchResult, SubTaskResult
```

Append at the bottom of `runner.py`:

```python
def _build_defaults_dict(batch: BatchConfig) -> dict:
    """Extract non-None defaults blocks for merge."""
    return {
        k: v for k, v in {
            "sources": batch.sources,
            "match": batch.match,
            "compare": batch.compare,
            "output": batch.output,
            "runtime": batch.runtime,
        }.items() if v is not None
    }


def _resolve_sub_task_output_dir(sub_raw: dict, merged: dict, default_dir: str, sub_name: str) -> str:
    """Explicit sub-task output.dir wins; else auto-append sub_name to default_dir."""
    if isinstance(sub_raw.get("output"), dict) and "dir" in sub_raw["output"]:
        return sub_raw["output"]["dir"]
    return str(Path(default_dir) / sub_name)


def execute_batch(batch: BatchConfig, connections: dict[str, AnyConnection]) -> BatchResult:
    """Run each sub-task sequentially. Honors on_error (continue default here; fail_fast in T6)."""
    defaults = _build_defaults_dict(batch)
    default_out_dir = (batch.output or {}).get("dir", "./reports")
    results: list[SubTaskResult] = []
    batch_start = time.monotonic()

    for sub in batch.tasks:
        sub_raw = {"name": sub.name, **(sub.model_extra or {})}
        merged = merge_sub_task(defaults, sub_raw)
        sub_out_dir = _resolve_sub_task_output_dir(sub_raw, merged, default_out_dir, sub.name)
        merged.setdefault("output", {})
        merged["output"]["dir"] = sub_out_dir

        sub_task_start = time.monotonic()
        try:
            task = TaskConfig.model_validate(merged)
            cr = execute(task, connections)
            results.append(SubTaskResult(
                task_name=sub.name, status="success",
                comparison_result=cr, error=None,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))
        except Exception as e:
            results.append(SubTaskResult(
                task_name=sub.name, status="failed",
                comparison_result=None, error=e,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))

    return BatchResult(
        batch_name=batch.name,
        task_results=results,
        total_duration_ms=int((time.monotonic() - batch_start) * 1000),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py tests/ -q`
Expected: all new tests PASS; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/runner.py tests/unit/test_runner_batch.py
git commit -m "$(cat <<'EOF'
feat(runner): execute_batch runs sub-tasks sequentially with continue-on-error

Each sub-task's per-directory output path defaults to
{defaults.output.dir}/{sub_task.name}/ unless the sub-task explicitly
writes output.dir. Exceptions are caught per sub-task and recorded as
failed status; batch always completes. fail_fast handling and the
aggregate batch.log arrive in subsequent tasks.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `on_error=fail_fast` + skipped status

**Goal:** When `on_error=fail_fast` and a sub-task fails, remaining sub-tasks are recorded as `skipped` (not run).

**Files:**
- Modify: `src/datacompare/runner.py` (extend `execute_batch`)
- Test: `tests/unit/test_runner_batch.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_runner_batch.py`:

```python
def test_execute_batch_fail_fast_skips_remaining(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
on_error: fail_fast
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: ok1
  - name: broken
    sources: {{left: {{path: {tmp_path}/missing.xlsx}}}}
  - name: never_runs
  - name: also_skipped
""")
    batch = load_task_or_batch(task, {})
    result = execute_batch(batch, connections={})
    assert result.success_count == 1
    assert result.failed_count == 1
    assert result.skipped_count == 2
    assert result.task_results[0].status == "success"
    assert result.task_results[1].status == "failed"
    assert result.task_results[2].status == "skipped"
    assert result.task_results[3].status == "skipped"
    # skipped sub-tasks should NOT have created output dirs
    assert not (tmp_path / "out" / "never_runs").exists()
    assert not (tmp_path / "out" / "also_skipped").exists()


def test_execute_batch_fail_fast_reports_zero_duration_for_skipped(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
on_error: fail_fast
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/left.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: fail_me
    sources: {{left: {{path: {tmp_path}/nope.xlsx}}}}
  - name: skipped_task
""")
    batch = load_task_or_batch(task, {})
    result = execute_batch(batch, connections={})
    assert result.task_results[1].status == "skipped"
    assert result.task_results[1].duration_ms == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py -v -k "fail_fast or skipped"`
Expected: FAIL because current `execute_batch` always runs all sub-tasks.

- [ ] **Step 3: Add fail_fast branch**

In `execute_batch`, wrap the loop body so that after a failure under `fail_fast`, remaining sub-tasks are recorded as `skipped`. Replace the current `for sub in batch.tasks:` block with:

```python
    aborted = False
    for sub in batch.tasks:
        if aborted:
            results.append(SubTaskResult(
                task_name=sub.name, status="skipped",
                comparison_result=None, error=None, duration_ms=0,
            ))
            continue

        sub_raw = {"name": sub.name, **(sub.model_extra or {})}
        merged = merge_sub_task(defaults, sub_raw)
        sub_out_dir = _resolve_sub_task_output_dir(sub_raw, merged, default_out_dir, sub.name)
        merged.setdefault("output", {})
        merged["output"]["dir"] = sub_out_dir

        sub_task_start = time.monotonic()
        try:
            task = TaskConfig.model_validate(merged)
            cr = execute(task, connections)
            results.append(SubTaskResult(
                task_name=sub.name, status="success",
                comparison_result=cr, error=None,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))
        except Exception as e:
            results.append(SubTaskResult(
                task_name=sub.name, status="failed",
                comparison_result=None, error=e,
                duration_ms=int((time.monotonic() - sub_task_start) * 1000),
            ))
            if batch.on_error == "fail_fast":
                aborted = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py tests/ -q`
Expected: all pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/runner.py tests/unit/test_runner_batch.py
git commit -m "$(cat <<'EOF'
feat(runner): honor on_error=fail_fast in execute_batch

After a sub-task failure under fail_fast, remaining sub-tasks are
recorded with status=skipped (no execution attempted, no output dir
created). Continue mode is unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `batch.log` aggregate structured log

**Goal:** During `execute_batch`, write structlog JSON events to `{defaults.output.dir}/batch.log`: `batch_start`, one `task_start`+`task_end` per sub-task, `batch_end`.

**Files:**
- Modify: `src/datacompare/runner.py` (add file handler + emit events)
- Test: `tests/unit/test_runner_batch.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_runner_batch.py`:

```python
import json


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_execute_batch_writes_batch_log_with_start_and_end(tmp_path):
    task = _batch_two_success(tmp_path)
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    batch_log = tmp_path / "out" / "batch.log"
    assert batch_log.exists()
    entries = _read_jsonl(batch_log)
    events = [e["event"] for e in entries]
    assert events[0] == "batch_start"
    assert events[-1] == "batch_end"
    assert events.count("task_start") == 2
    assert events.count("task_end") == 2


def test_batch_log_task_end_carries_status_and_counts(tmp_path):
    task = _batch_two_success(tmp_path)
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    entries = _read_jsonl(tmp_path / "out" / "batch.log")
    task_ends = [e for e in entries if e["event"] == "task_end"]
    assert all(e["status"] == "success" for e in task_ends)
    assert all("matched" in e and "diff" in e for e in task_ends)
    assert all(isinstance(e["duration_ms"], int) for e in task_ends)


def test_batch_log_records_failure_with_error_type_and_message(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    _write(task, f"""
name: b
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: broken
    sources: {{left: {{path: {tmp_path}/missing.xlsx}}}}
""")
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    entries = _read_jsonl(tmp_path / "out" / "batch.log")
    task_end = next(e for e in entries if e["event"] == "task_end")
    assert task_end["status"] == "failed"
    assert "error_type" in task_end
    assert "error_message" in task_end


def test_batch_log_end_event_has_final_counts(tmp_path):
    task = _batch_two_success(tmp_path)
    batch = load_task_or_batch(task, {})
    execute_batch(batch, connections={})
    entries = _read_jsonl(tmp_path / "out" / "batch.log")
    end = next(e for e in entries if e["event"] == "batch_end")
    assert end["success"] == 2
    assert end["failed"] == 0
    assert end["skipped"] == 0
    assert isinstance(end["total_duration_ms"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py -v -k "batch_log or log"`
Expected: FAIL because `batch.log` is not being written.

- [ ] **Step 3: Add batch.log emission in `execute_batch`**

At top of `runner.py`, add:

```python
import logging
import structlog
```

Add a helper near the top of `runner.py`:

```python
def _init_batch_logger(batch_log_path: Path) -> tuple[structlog.stdlib.BoundLogger, logging.FileHandler]:
    """Attach a dedicated file handler that writes structlog JSON events to batch_log_path.

    Returns the logger and handler so the caller can detach when done (avoid leaking
    handlers into the root logger across runs).
    """
    batch_log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(batch_log_path), encoding="utf-8", mode="w")
    handler.setFormatter(logging.Formatter("%(message)s"))
    # Use a named logger so we can add/remove the handler without touching root.
    py_logger = logging.getLogger("datacompare.batch")
    py_logger.addHandler(handler)
    py_logger.setLevel(logging.INFO)
    py_logger.propagate = False  # don't duplicate to stderr root
    return structlog.get_logger("datacompare.batch"), handler
```

Now modify `execute_batch` to emit events. The full updated function:

```python
def execute_batch(batch: BatchConfig, connections: dict[str, AnyConnection]) -> BatchResult:
    defaults = _build_defaults_dict(batch)
    default_out_dir = (batch.output or {}).get("dir", "./reports")
    Path(default_out_dir).mkdir(parents=True, exist_ok=True)
    batch_log_path = Path(default_out_dir) / "batch.log"
    logger, handler = _init_batch_logger(batch_log_path)

    results: list[SubTaskResult] = []
    batch_start = time.monotonic()
    logger.info("batch_start", batch_name=batch.name,
                task_count=len(batch.tasks), on_error=batch.on_error)

    try:
        aborted = False
        for i, sub in enumerate(batch.tasks, start=1):
            if aborted:
                results.append(SubTaskResult(
                    task_name=sub.name, status="skipped",
                    comparison_result=None, error=None, duration_ms=0,
                ))
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="skipped",
                            duration_ms=0)
                continue

            logger.info("task_start", task_name=sub.name, index=i, total=len(batch.tasks))

            sub_raw = {"name": sub.name, **(sub.model_extra or {})}
            merged = merge_sub_task(defaults, sub_raw)
            sub_out_dir = _resolve_sub_task_output_dir(sub_raw, merged, default_out_dir, sub.name)
            merged.setdefault("output", {})
            merged["output"]["dir"] = sub_out_dir

            sub_task_start = time.monotonic()
            try:
                task = TaskConfig.model_validate(merged)
                cr = execute(task, connections)
                dur = int((time.monotonic() - sub_task_start) * 1000)
                results.append(SubTaskResult(
                    task_name=sub.name, status="success",
                    comparison_result=cr, error=None, duration_ms=dur,
                ))
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="success",
                            matched=cr.matched_rows, diff=cr.diff_rows,
                            left_only=cr.left_only, right_only=cr.right_only,
                            duration_ms=dur)
            except Exception as e:
                dur = int((time.monotonic() - sub_task_start) * 1000)
                results.append(SubTaskResult(
                    task_name=sub.name, status="failed",
                    comparison_result=None, error=e, duration_ms=dur,
                ))
                logger.info("task_end", task_name=sub.name, index=i,
                            total=len(batch.tasks), status="failed",
                            error_type=type(e).__name__,
                            error_message=str(e), duration_ms=dur)
                if batch.on_error == "fail_fast":
                    aborted = True

        total_dur = int((time.monotonic() - batch_start) * 1000)
        result = BatchResult(
            batch_name=batch.name, task_results=results, total_duration_ms=total_dur,
        )
        logger.info("batch_end", batch_name=batch.name,
                    success=result.success_count, failed=result.failed_count,
                    skipped=result.skipped_count, total_duration_ms=total_dur)
        return result
    finally:
        logging.getLogger("datacompare.batch").removeHandler(handler)
        handler.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/test_runner_batch.py tests/ -q`
Expected: all pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/runner.py tests/unit/test_runner_batch.py
git commit -m "$(cat <<'EOF'
feat(runner): write structured batch.log aggregate events

execute_batch emits batch_start / task_start / task_end / batch_end
JSON events via a dedicated 'datacompare.batch' logger with its own
file handler. Handler is attached at start and detached in a finally
block so batch.log has no cross-run leakage. Sub-task detailed logs
still live in each sub-task's own run-{ts}.log.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: CLI dispatch, batch console output, exit code aggregation, `--dry-run`

**Goal:** `datacompare run task.yaml` auto-detects single vs batch. Batch mode shows per-sub-task progress lines, a summary, and returns aggregated exit code. `--dry-run` validates and prints per-sub-task summary without executing.

**Files:**
- Modify: `src/datacompare/cli.py`
- Test: `tests/integration/test_cli_batch_dispatch.py` (new, small tests to exercise CLI path)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_cli_batch_dispatch.py`:

```python
from pathlib import Path
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app


runner = CliRunner()


def _make_xlsx(path: Path, rows):
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    wb.save(path)


def _batch_two_success_yaml(tmp_path: Path) -> Path:
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: cli_batch
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub1
  - name: sub2
""", encoding="utf-8")
    return task


def test_cli_run_dispatches_to_batch_mode_exit_0(tmp_path):
    task = _batch_two_success_yaml(tmp_path)
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 0, result.output
    # Console shows batch header and per-sub-task lines
    assert "cli_batch" in result.output or "Batch" in result.output
    assert "sub1" in result.output and "sub2" in result.output
    assert "succeeded" in result.output.lower() or "success" in result.output.lower()
    # batch.log and per-sub-task reports produced
    assert (tmp_path / "out" / "batch.log").exists()
    assert (tmp_path / "out" / "sub1" / "report.json").exists()
    assert (tmp_path / "out" / "sub2" / "report.json").exists()


def test_cli_batch_failure_returns_exit_2(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: mixed
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: excel, path: {tmp_path}/right.xlsx}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: ok
  - name: bad
    sources: {{left: {{path: {tmp_path}/missing.xlsx}}}}
""", encoding="utf-8")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"),
    ])
    assert result.exit_code == 2, result.output


def test_cli_dry_run_batch_valid_exit_0(tmp_path):
    _make_xlsx(tmp_path / "left.xlsx", [["order_id"], ["A1"]])
    _make_xlsx(tmp_path / "right.xlsx", [["order_id"], ["A1"]])
    task = _batch_two_success_yaml(tmp_path)
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output.lower()
    assert "sub1" in result.output and "sub2" in result.output


def test_cli_dry_run_batch_invalid_lists_all_sub_task_errors(tmp_path):
    """Two sub-tasks with missing right.query — both should be listed."""
    task = tmp_path / "bad.yaml"
    task.write_text(f"""
name: bad_batch
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
  right: {{type: gaussdb, connection: c}}
match:
  keys: [{{left: order_id, right: order_id}}]
compare:
  fields: []
output:
  dir: {tmp_path}/out
  formats: [json]
tasks:
  - name: sub_a
  - name: sub_b
""", encoding="utf-8")
    result = runner.invoke(app, [
        "run", str(task), "--connections", str(tmp_path / "none.yaml"), "--dry-run",
    ])
    assert result.exit_code == 1
    assert "sub_a" in result.output and "sub_b" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/integration/test_cli_batch_dispatch.py -v`
Expected: FAIL — CLI doesn't dispatch to batch mode yet.

- [ ] **Step 3: Modify `src/datacompare/cli.py` `run` command**

Change imports at top:

```python
from datacompare.config.loader import load_task_or_batch, load_connections
from datacompare.config.models import TaskConfig, BatchConfig
```

Replace the `load_task` call and everything downstream in the `run` command. The updated body (from `try: task = load_task(...)` onward) becomes:

```python
    try:
        cfg = load_task_or_batch(Path(task_file).expanduser(), params_dict)
        conn_path = Path(connections).expanduser()
        conns = load_connections(conn_path) if conn_path.exists() else {}
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        if isinstance(cfg, BatchConfig):
            # Sub-task validation already ran during load; getting here means all pass.
            typer.echo(f"✓ Batch config valid ({len(cfg.tasks)} tasks)")
            for i, sub in enumerate(cfg.tasks, start=1):
                typer.echo(f"  [{i}] {sub.name}")
            raise typer.Exit(0)
        typer.echo("✓ configuration is valid (dry-run)")
        raise typer.Exit(0)

    # Phase 2: log file path (uses cfg's output dir when single-task; batch handles its own dirs)
    if log_file:
        log_path: Path | None = Path(log_file).expanduser()
    elif isinstance(cfg, TaskConfig):
        effective_out_dir = Path(output_dir).expanduser() if output_dir else Path(cfg.output.dir).expanduser()
        effective_out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        log_path = effective_out_dir / f"run-{stamp}.log"
    else:
        # Batch mode: batch.log is written by execute_batch; per-sub-task logs by execute().
        log_path = None
    effective_level = log_level or (
        cfg.runtime.log_level if isinstance(cfg, TaskConfig)
        else (cfg.runtime or {}).get("log_level", "INFO")
    )
    configure_logging(level=effective_level, log_file=log_path)

    if isinstance(cfg, BatchConfig):
        from datacompare.runner import execute_batch
        typer.echo(f"▶ Batch: {cfg.name} ({len(cfg.tasks)} tasks, on_error={cfg.on_error})\n")
        batch_result = execute_batch(cfg, conns)
        for i, r in enumerate(batch_result.task_results, start=1):
            n = len(batch_result.task_results)
            label = f"[{i}/{n}] {r.task_name}".ljust(45, ".")
            if r.status == "success":
                cr = r.comparison_result
                typer.echo(
                    f"{label} ✓ matched={cr.matched_rows}, diff={cr.diff_rows} "
                    f"({r.duration_ms/1000:.1f}s)"
                )
            elif r.status == "failed":
                msg = (str(r.error) or "").splitlines()[0][:80]
                typer.echo(f"{label} ✗ {type(r.error).__name__}: {msg}")
            else:
                typer.echo(f"{label} - skipped")
        typer.echo(
            f"\nSummary: {batch_result.success_count} succeeded, "
            f"{batch_result.failed_count} failed, {batch_result.skipped_count} skipped, "
            f"total {batch_result.total_duration_ms/1000:.1f}s"
        )
        typer.echo(f"Reports: {(cfg.output or {}).get('dir', './reports')}/")
        raise typer.Exit(batch_result.compute_exit_code(fail_on_diff))

    # Single-task path (unchanged)
    try:
        result = execute(cfg, conns, output_dir_override=output_dir,
                         formats_override=fmt or None, engine_override=engine)
    except ConfigError as e:
        typer.echo(f"❌ {e}", err=True); raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"❌ error: {e}", err=True); raise typer.Exit(2)
    if fail_on_diff and (result.diff_rows > 0 or result.left_only > 0 or result.right_only > 0):
        raise typer.Exit(10)
    raise typer.Exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/integration/test_cli_batch_dispatch.py tests/ -q`
Expected: all pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/datacompare/cli.py tests/integration/test_cli_batch_dispatch.py
git commit -m "$(cat <<'EOF'
feat(cli): dispatch run command to batch mode when tasks: key present

Batch mode shows per-sub-task progress lines, a summary footer, and
returns aggregated exit code via BatchResult.compute_exit_code
(priority 2 > 10 > 1 > 0). --dry-run for batches lists sub-tasks;
validation errors from all sub-tasks are already surfaced during load.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Init template for batch mode + CLI wire-up

**Goal:** `datacompare init batch-example -o batch.yaml` produces a runnable batch template.

**Files:**
- Create: `src/datacompare/templates/batch_example.yaml`
- Modify: `src/datacompare/cli.py` (`init` command's help text and template list)
- Test: `tests/unit/test_cli_init.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_cli_init.py`:

```python
def test_init_batch_example_writes_valid_yaml(tmp_path):
    from ruamel.yaml import YAML
    out = tmp_path / "batch.yaml"
    result = runner.invoke(app, ["init", "batch-example", "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    data = YAML(typ="safe").load(out.read_text(encoding="utf-8"))
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) >= 2


def test_init_batch_example_content_documents_defaults_and_overrides(tmp_path):
    out = tmp_path / "batch.yaml"
    result = runner.invoke(app, ["init", "batch-example", "-o", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "defaults" in text.lower() or "sources:" in text
    assert "on_error" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py -v -k batch`
Expected: FAIL — template doesn't exist yet.

- [ ] **Step 3: Create the template**

Create `src/datacompare/templates/batch_example.yaml`:

```yaml
# Batch mode: 一份 YAML 声明多个 sub-task，共享 defaults，各自出报告
# 详见 docs/superpowers/specs/2026-07-17-multi-task-yaml-design.md
name: cmdb_multi_sync
description: CMDB 数据一致性核对（示例：同 Excel 多 sheet vs 多 GaussDB 表）
on_error: continue        # continue（默认）| fail_fast

# 顶层字段 = defaults，被每个 sub-task 深度合并覆盖
sources:
  left:
    type: excel
    path: ./data/manage.xlsx
  right:
    type: gaussdb
    connection: prod_cmdb
output:
  dir: ./reports
  formats: [html, json]
runtime:
  log_level: INFO

tasks:
  - name: physical_host
    sources:
      left:
        sheets: [{name: "CMDB系统_SYS_PHYSICALHOST"}]   # 继承 path
      right:
        query: "SELECT id, name, host_ip FROM sys_physicalhost"  # 继承 connection
    match:
      keys: [{left: id, right: id}]
    compare:
      fields:
        - {left: name, right: name}
        - {left: hostIp, right: host_ip}

  - name: cloud_vm
    sources:
      left:
        sheets: [{name: "CMDB系统_CLOUD_VM"}]
      right:
        query: "SELECT id, name, ip_address FROM cloud_vm"
    match:
      keys: [{left: id, right: id}]
    compare:
      fields:
        - {left: name, right: name}
        - {left: ipAddress, right: ip_address}

  # 示例：完全覆盖 right 到另一种 type（要补齐所有必填字段）
  # - name: vs_api
  #   sources:
  #     left:
  #       sheets: [{name: "EXTERNAL_VMS"}]
  #     right:
  #       type: api
  #       connection: cloud_platform
  #       url: /v1/vms
  #       pagination: {type: page, page_param: page, size_param: size, size: 200}
  #       data_path: $.data.list[*]
  #   match:
  #     keys: [{left: id, right: id}]
  #   compare:
  #     fields:
  #       - {left: name, right: name}
```

- [ ] **Step 4: Update `init` help text in `src/datacompare/cli.py`**

In the `init` command signature:

```python
def init(
    template: str = typer.Argument(..., help="excel-vs-gaussdb | excel-vs-gaussdb-t | api-vs-gaussdb | excel-vs-api | batch-example"),
    ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/unit/test_cli_init.py tests/ -q`
Expected: all pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/templates/batch_example.yaml src/datacompare/cli.py tests/unit/test_cli_init.py
git commit -m "$(cat <<'EOF'
feat(cli): add batch-example init template

`datacompare init batch-example -o batch.yaml` emits a multi-task
YAML with two sub-tasks sharing defaults plus a commented-out third
sub-task that overrides right.type to demonstrate scenario B.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: End-to-end integration tests + docs updates

**Goal:** Scenarios G, H, I from the spec (heterogeneous batch, mixed pass/fail, cross-sheet). Update README, CLAUDE.md, user-guide.

**Files:**
- Create: `tests/integration/test_batch_e2e.py`
- Modify: `CLAUDE.md`, `README.md`, `docs/user-guide.md`

- [ ] **Step 1: Write the failing test file (scenarios G, H, I)**

Create `tests/integration/test_batch_e2e.py`:

```python
"""End-to-end batch tests: heterogeneous right sides, mixed pass/fail, cross-sheet."""
import json
from pathlib import Path
import httpx
import respx
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner
from datacompare.cli import app


runner = CliRunner()


def _make_xlsx(path: Path, sheets: dict[str, list[list]]):
    wb = Workbook()
    default_ws = wb.active
    default_ws.title = "_placeholder"
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for r in rows:
            ws.append(r)
    if "_placeholder" in wb.sheetnames:
        del wb["_placeholder"]
    wb.save(path)


@respx.mock
def test_batch_scenario_g_heterogeneous_success(tmp_path):
    """Scenario G: 3 sub-tasks — Excel→Excel(sheet), Excel→Excel(other file), Excel→API."""
    _make_xlsx(tmp_path / "manage.xlsx", {
        "PHYSICAL": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
        "VM": [["id", "name"], ["v1", "vm-1"], ["v2", "vm-2"]],
        "API_DATA": [["id", "value"], ["a1", "10"], ["a2", "20"]],
    })
    # Right side #1: another sheet in the SAME excel (cross-sheet inside one file)
    # Right side #2: another excel file
    _make_xlsx(tmp_path / "snapshot.xlsx", {
        "PHYSICAL": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
    })
    _make_xlsx(tmp_path / "vm_ref.xlsx", {
        "VM": [["id", "name"], ["v1", "vm-1"], ["v2", "vm-2"]],
    })
    respx.get("http://api.test/v1/data").mock(
        return_value=httpx.Response(200, json={"data": {"list": [
            {"id": "a1", "value": "10"}, {"id": "a2", "value": "20"},
        ]}})
    )
    conns = tmp_path / "conns.yaml"
    conns.write_text("""
api_svc:
  type: api
  base_url: http://api.test
""", encoding="utf-8")
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: hetero
sources:
  left: {{type: excel, path: {tmp_path}/manage.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: cross_sheet
    sources:
      left: {{sheets: [{{name: PHYSICAL}}]}}
      right: {{type: excel, path: {tmp_path}/snapshot.xlsx, sheets: [{{name: PHYSICAL}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
  - name: vs_another_excel
    sources:
      left: {{sheets: [{{name: VM}}]}}
      right: {{type: excel, path: {tmp_path}/vm_ref.xlsx, sheets: [{{name: VM}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
  - name: vs_api
    sources:
      left: {{sheets: [{{name: API_DATA}}]}}
      right:
        type: api
        connection: api_svc
        url: /v1/data
        pagination: {{type: page, page_param: page, size_param: size, size: 100}}
        data_path: $.data.list[*]
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: value, right: value}}]}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(conns)])
    assert result.exit_code == 0, result.output
    for sub in ["cross_sheet", "vs_another_excel", "vs_api"]:
        assert (tmp_path / "reports" / sub / "report.json").exists()
    # batch.log has 3 successful task_end events
    batch_log = tmp_path / "reports" / "batch.log"
    entries = [json.loads(l) for l in batch_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    task_ends = [e for e in entries if e["event"] == "task_end"]
    assert len(task_ends) == 3
    assert all(e["status"] == "success" for e in task_ends)


@respx.mock
def test_batch_scenario_h_mixed_failure_continue(tmp_path):
    """Scenario H: 3 sub-tasks — 1 success + 1 missing file + 1 API 500."""
    _make_xlsx(tmp_path / "manage.xlsx", {
        "OK_SHEET": [["id"], ["x1"]],
        "MISSING_RIGHT": [["id"], ["y1"]],
        "API_500": [["id"], ["z1"]],
    })
    _make_xlsx(tmp_path / "ok_right.xlsx", {
        "OK_SHEET": [["id"], ["x1"]],
    })
    respx.get("http://api.test/broken").mock(return_value=httpx.Response(500))
    conns = tmp_path / "conns.yaml"
    conns.write_text("api_svc: {type: api, base_url: http://api.test}\n", encoding="utf-8")
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: mixed
on_error: continue
sources:
  left: {{type: excel, path: {tmp_path}/manage.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: ok_task
    sources:
      left: {{sheets: [{{name: OK_SHEET}}]}}
      right: {{type: excel, path: {tmp_path}/ok_right.xlsx, sheets: [{{name: OK_SHEET}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: file_missing
    sources:
      left: {{sheets: [{{name: MISSING_RIGHT}}]}}
      right: {{type: excel, path: {tmp_path}/DOES_NOT_EXIST.xlsx}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
  - name: api_broken
    sources:
      left: {{sheets: [{{name: API_500}}]}}
      right:
        type: api
        connection: api_svc
        url: /broken
        pagination: {{type: page, page_param: page, size_param: size, size: 100}}
        data_path: $.data
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: []}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(conns)])
    assert result.exit_code == 2
    # Successful sub-task has a report
    assert (tmp_path / "reports" / "ok_task" / "report.json").exists()
    # Failed sub-tasks did not produce reports but batch.log records their status
    batch_log = tmp_path / "reports" / "batch.log"
    entries = [json.loads(l) for l in batch_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    task_ends = {e["task_name"]: e for e in entries if e["event"] == "task_end"}
    assert task_ends["ok_task"]["status"] == "success"
    assert task_ends["file_missing"]["status"] == "failed"
    assert task_ends["api_broken"]["status"] == "failed"


def test_batch_scenario_i_same_excel_cross_sheet(tmp_path):
    """Scenario I: sub-task compares two sheets from the same Excel file."""
    _make_xlsx(tmp_path / "same.xlsx", {
        "LEFT_SHEET": [["id", "v"], ["a", "1"], ["b", "2"]],
        "RIGHT_SHEET": [["id", "v"], ["a", "1"], ["b", "2"]],
    })
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: same_file_cross_sheet
sources:
  left: {{type: excel, path: {tmp_path}/same.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: sheet_a_vs_sheet_b
    sources:
      left: {{sheets: [{{name: LEFT_SHEET}}]}}
      right: {{type: excel, path: {tmp_path}/same.xlsx, sheets: [{{name: RIGHT_SHEET}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: v, right: v}}]}}
""", encoding="utf-8")
    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "reports" / "sheet_a_vs_sheet_b" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["matched"] == 2
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/pytest tests/integration/test_batch_e2e.py -v`
Expected: after implementation from T1-T9, all 3 tests PASS. If any fails, diagnose:
- Excel constructor / result shape mismatches — see T7 of the v0.3 plan (same pitfalls apply)
- respx URL routing — confirm `base_url` from connection + `url` from source concatenate correctly

Do not change production code to satisfy tests — adjust test assertions only if a mismatch is a test-side error (e.g., wrong report key name).

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, under the "关键约束（改代码前务必了解）" section, add a bullet after the existing key-regex one:

```markdown
- **批次模式 `tasks:`**（v0.4 起）：task.yaml 顶层出现 `tasks:` 键 → `load_task_or_batch` 返回 `BatchConfig`；`execute_batch` 顺序跑每个 sub-task。每个 sub-task 深度合并 defaults：dict 递归、list 替换、嵌套 dict 的 `type` 变化时 replace。`on_error: continue`（默认）或 `fail_fast`。CLI 退出码优先级 `2 > 10 > 1 > 0`。批次总日志 `batch.log` 只记元事件，sub-task 详细日志仍在各自目录。**加载阶段**（YAML 解析、defaults 合并冲突、sub-task 唯一性、每个 sub-task 完整 Pydantic 校验）**永远 fail-fast**，不受 `on_error` 影响。
```

- [ ] **Step 4: Update README.md**

In README, near the existing single-task example, add a new subsection:

````markdown
### 批次模式（v0.4+）：一份 YAML 跑 N 个比对

当一个 Excel 有几十个 sheet，每个 sheet schema 不同，或者一批数据源要各自比对时，用批次模式：

```yaml
name: cmdb_multi_sync
on_error: continue           # continue（默认）| fail_fast

sources:                     # ↓ defaults，被每个 sub-task 深度合并
  left: {type: excel, path: manage.xlsx}
  right: {type: gaussdb, connection: prod_cmdb}

output:
  dir: ./reports             # 每个 sub-task 会自动放到 ./reports/{sub_task.name}/
  formats: [html, json]

tasks:
  - name: physical_host
    sources:
      left: {sheets: [{name: "PHYSICAL_HOST"}]}      # 只写 sheets，path 继承
      right: {query: "SELECT ... FROM physical_host"} # 只写 query，connection 继承
    match: {keys: [{left: id, right: id}]}
    compare: {fields: [...]}

  - name: cloud_vm
    sources:
      left: {sheets: [{name: "CLOUD_VM"}]}
      right: {query: "SELECT ... FROM cloud_vm"}
    match: {keys: [{left: id, right: id}]}
    compare: {fields: [...]}
```

规则要点：
- **有 `tasks:` 键 = 批次模式**；无则为单任务（现有行为完全不变）
- **深度合并**：dict 递归、list 整体替换、嵌套 dict 的 `type` 变化时整体替换（避免 gaussdb→api 时残留 connection）
- **每个 sub-task 一个子目录**：`./reports/{sub_task.name}/report.*` + `run-{ts}.log`
- **`./reports/batch.log`**：聚合元事件日志，扫全景用
- **退出码**：`2` > `10` > `1` > `0`（运行错 > diff+fail_on_diff > 配置错 > 成功）

生成模板：
```bash
datacompare init batch-example -o batch.yaml
```
````

- [ ] **Step 5: Update `docs/user-guide.md`**

Add the same batch-mode section to `docs/user-guide.md` in an appropriate location (near the section describing single-task YAML).

- [ ] **Step 6: Full suite one final time**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: green (Docker-gated tests skip).

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_batch_e2e.py CLAUDE.md README.md docs/user-guide.md
git commit -m "$(cat <<'EOF'
docs+test: batch mode e2e (heterogeneous, mixed failure, cross-sheet)

E2e coverage: scenario G (Excel-vs-Excel-sheet + Excel-vs-other-Excel
+ Excel-vs-API in one batch), scenario H (continue-on-error with mixed
missing-file and API 500), scenario I (two sheets in the same Excel
compared). CLAUDE.md + README.md + user-guide.md gain batch mode
sections.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Summary

**Spec coverage** (against `docs/superpowers/specs/2026-07-17-multi-task-yaml-design.md`):

| Spec section | Implemented in |
|---|---|
| §需求范围 – 一份 YAML 多 sub-task 顺序执行 | T5 |
| §需求范围 – 顶层 defaults 深度合并 | T1 (merge), T3 (integration) |
| §需求范围 – Sub-task type 覆盖 replace | T1 (rule), T5 (via merge_sub_task) |
| §需求范围 – on_error continue / fail_fast | T5 (continue), T6 (fail_fast) |
| §需求范围 – 每 sub-task 子目录 + batch.log | T5 (dir), T7 (batch.log) |
| §需求范围 – 单/多模式自动检测 | T3 (loader), T8 (CLI dispatch) |
| §配置示例 – 完整 YAML shape | T2 (models), T9 (template) |
| §深度合并规则 – dict/list/type/None | T1 (all covered by unit tests) |
| §文件系统布局 – 每 sub-task 子目录 | T5 (auto path), T5 test (explicit override) |
| §文件系统布局 – batch.log 元事件 | T7 |
| §CLI 行为 – 控制台输出 | T8 |
| §CLI 行为 – 退出码优先级 | T4 (compute_exit_code), T8 (CLI wiring) |
| §CLI 行为 – --dry-run 语义 | T8 (dry-run branch) |
| §错误处理 – 加载阶段 fail-fast 永远 | T3 (all sub-task errors collected at load) |
| §错误处理 – 运行错受 on_error 控制 | T5, T6 |
| §向后兼容 – 单任务 YAML 零改动 | T3 (auto-detect), T8 (dispatch), verified by regression |
| §契约签名 – deep_merge / merge_sub_task | T1, T3 |
| §契约签名 – BatchConfig / BatchTaskOverride | T2 |
| §契约签名 – execute_batch | T5-T7 |
| §契约签名 – BatchResult / SubTaskResult | T4 |
| §测试策略 – 单元测试全表 | T1-T7 |
| §测试策略 – 集成测试 A-F | T5-T8 tests |
| §测试策略 – 集成测试 G/H/I | T10 |

**Placeholder check:** None. Every code step has literal code; every command has exact expected output description. The one `...` in the template docstring (`fields: [...]`) is illustrative content in template text, not a plan placeholder.

**Type consistency check:**
- `deep_merge(defaults, override) -> dict` — consistent T1 → T3.
- `merge_sub_task(defaults, sub_task) -> dict` — consistent T3 → T5.
- `BatchConfig(name, description, on_error, sources, match, compare, output, runtime, tasks)` — consistent T2 → T3 → T5 → T8.
- `BatchTaskOverride(name, **extra)` with `model_config = ConfigDict(extra="allow")` — consistent T2 → T5.
- `SubTaskResult(task_name, status, comparison_result, error, duration_ms)` — consistent T4 → T5 → T6 → T7.
- `BatchResult(batch_name, task_results, total_duration_ms)` — consistent T4 → T5 → T6 → T7 → T8.
- `BatchResult.compute_exit_code(fail_on_diff: bool) -> int` — consistent T4 → T8.
- `execute_batch(batch, connections) -> BatchResult` — consistent T5 → T6 → T7 → T8 → T10.
