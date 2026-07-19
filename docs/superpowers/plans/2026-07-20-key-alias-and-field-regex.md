# Key Alias 与 Field Regex 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL：用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务执行本计划。步骤用 checkbox（`- [ ]`）语法追踪。

**目标：** 给 `KeyMapping` 加 `alias` 支持自定义 canonical 名字避免撞车；给 `FieldRule` 加 `left_regex/right_regex` 支持对字段值做正则提取；重构 `apply_column_mapping` 允许同源列复制成多个 canonical 列；把 regex 应用从 pre-rename 移到 post-rename。

**架构：** 新增 `RegexError` sentinel 与 `DiffType.REGEX_ERROR` 平级于现有 `CoerceError`/`UnitError`。抽出 `apply_regex_on_canonical` 公共函数，支持 strict（key 用，抛异常）与 soft（field 用，返回 sentinel）两种模式。`apply_column_mapping` 从"整体 rename"改成"逐列复制 tasks 列表"，允许同一源列多次被引用。加载期在 loader 里新增 canonical 重复检查 fail-fast。

**技术栈：** Pydantic v2（`field_validator`），pandas 2.x（scalar 广播、object dtype 保留 None），pytest，ruamel.yaml。

**Spec：** `docs/superpowers/specs/2026-07-20-key-alias-and-field-regex-design.md`

---

## 文件结构映射

| 文件 | 改动 | 责任 |
|------|------|------|
| `src/datacompare/normalize/regex_errors.py` | **新建** | `RegexError` sentinel dataclass（`original`, `pattern`） |
| `src/datacompare/engine/result.py` | 修改 `DiffType` 枚举 | 新增 `REGEX_ERROR = "regex_error"` |
| `src/datacompare/config/models.py` | 修改 `KeyMapping` + `FieldRule` + 抽公共 validator | 加 alias/regex 字段与共享校验 |
| `src/datacompare/normalize/columns.py` | 新增 `key_canonical_name` + 重构 `apply_column_mapping` | canonical 命名统一 + 允许同源复制 |
| `src/datacompare/normalize/keys.py` | 新增 `apply_regex_on_canonical`，改写 `apply_key_regex` 为薄壳 | strict/soft 双模 regex 应用 |
| `src/datacompare/normalize/pipeline.py` | 修改 `normalize_side` 调用顺序 | regex 后置到 canonical 层 |
| `src/datacompare/engine/memory.py` + `disk.py` | `key_cols` 用 `key_canonical_name` | 引擎侧对齐 canonical |
| `src/datacompare/engine/memory.py` + `disk.py` | 处理 `RegexError` sentinel | classify 归为 `REGEX_ERROR`；errors 收集 |
| `src/datacompare/config/loader.py` | 新增 canonical 重复检查 | 加载期 fail-fast |
| 若干测试文件 | 追加 | 见各 Task |
| `README.md` / `docs/user-guide.md` / `CLAUDE.md` | 追加 | 文档 |

---

## Task 1: 新增 RegexError sentinel 与 DiffType.REGEX_ERROR 枚举

**Files:**
- Create: `src/datacompare/normalize/regex_errors.py`
- Modify: `src/datacompare/engine/result.py:8-12`
- Test: `tests/unit/engine/test_result.py`（若不存在则新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/normalize/test_regex_errors.py`：

```python
from datacompare.normalize.regex_errors import RegexError


def test_regex_error_is_frozen_dataclass():
    e = RegexError(original="Alice", pattern=r"(.*)@@.*")
    assert e.original == "Alice"
    assert e.pattern == r"(.*)@@.*"
    # frozen: assignment raises
    import pytest
    with pytest.raises(Exception):
        e.original = "changed"  # type: ignore


def test_regex_error_equality():
    a = RegexError(original="x", pattern="p")
    b = RegexError(original="x", pattern="p")
    c = RegexError(original="x", pattern="q")
    assert a == b
    assert a != c
```

追加到 `tests/unit/engine/test_result.py`（如果不存在，创建之，参照 `test_result.py` 已有导入风格）：

```python
def test_diff_type_regex_error_enum():
    from datacompare.engine.result import DiffType
    assert DiffType.REGEX_ERROR.value == "regex_error"
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_regex_errors.py tests/unit/engine/test_result.py -v
```

预期：全部失败（`ModuleNotFoundError: No module named 'datacompare.normalize.regex_errors'` 与 `AttributeError: REGEX_ERROR`）。

- [ ] **Step 3: 实现 RegexError**

创建 `src/datacompare/normalize/regex_errors.py`：

```python
"""Sentinel value for regex-fullmatch failure on compare fields.

Soft-fail counterpart to KeyRegexMismatchError: field regex mismatch on any
single row returns a RegexError instance instead of aborting the task, so the
row surfaces as a REGEX_ERROR diff and other rows keep running.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RegexError:
    original: str
    pattern: str
```

- [ ] **Step 4: 实现 DiffType 枚举扩展**

编辑 `src/datacompare/engine/result.py`，把 `DiffType` 类扩成：

```python
class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    REGEX_ERROR = "regex_error"
    NULL_MISMATCH = "null_mismatch"
```

- [ ] **Step 5: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_regex_errors.py tests/unit/engine/test_result.py -v
```

预期：全部 pass。

- [ ] **Step 6: 全套回归**

```bash
.venv/Scripts/pytest tests/ -q
```

预期：全绿（新增枚举不影响老代码）。

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/normalize/regex_errors.py src/datacompare/engine/result.py \
        tests/unit/normalize/test_regex_errors.py tests/unit/engine/test_result.py
git commit -m "feat(normalize+engine): add RegexError sentinel and DiffType.REGEX_ERROR"
```

---

## Task 2: KeyMapping.alias + FieldRule regex 字段 + 共享 validator

**Files:**
- Modify: `src/datacompare/config/models.py:5, 68-95, 105-...`
- Test: `tests/unit/config/test_models.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/config/test_models.py`：

```python
class TestKeyMappingAlias:
    def test_alias_default_none(self):
        from datacompare.config.models import KeyMapping
        k = KeyMapping(left="a", right="b")
        assert k.alias is None

    def test_alias_saved(self):
        from datacompare.config.models import KeyMapping
        k = KeyMapping(left="a", right="b", alias="join_id")
        assert k.alias == "join_id"

    def test_alias_with_regex(self):
        from datacompare.config.models import KeyMapping
        k = KeyMapping(left="id", right="name",
                       right_regex=r".*@@(.*)", alias="join_id")
        assert k.alias == "join_id"
        assert k.right_regex == r".*@@(.*)"


class TestFieldRuleRegex:
    def test_left_regex_default_none(self):
        from datacompare.config.models import FieldRule
        f = FieldRule(left="a", right="b")
        assert f.left_regex is None
        assert f.right_regex is None

    def test_left_regex_saved(self):
        from datacompare.config.models import FieldRule
        f = FieldRule(left="a", right="b", left_regex=r"(.*)@@.*")
        assert f.left_regex == r"(.*)@@.*"

    def test_right_regex_saved(self):
        from datacompare.config.models import FieldRule
        f = FieldRule(left="a", right="b", right_regex=r"(.*)@@.*")
        assert f.right_regex == r"(.*)@@.*"

    def test_regex_two_groups_rejected(self):
        import pytest
        from pydantic import ValidationError
        from datacompare.config.models import FieldRule
        with pytest.raises(ValidationError, match="capture groups"):
            FieldRule(left="a", right="b", left_regex=r"(x)(y)")

    def test_regex_invalid_pattern_rejected(self):
        import pytest
        from pydantic import ValidationError
        from datacompare.config.models import FieldRule
        with pytest.raises(ValidationError, match="invalid regex"):
            FieldRule(left="a", right="b", right_regex=r"(unclosed")

    def test_regex_zero_groups_ok(self):
        from datacompare.config.models import FieldRule
        f = FieldRule(left="a", right="b", left_regex=r"[a-z]+")
        assert f.left_regex == r"[a-z]+"

    def test_regex_one_group_ok(self):
        from datacompare.config.models import FieldRule
        f = FieldRule(left="a", right="b", left_regex=r"(.*)@@.*")
        assert f.left_regex == r"(.*)@@.*"
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/config/test_models.py::TestKeyMappingAlias tests/unit/config/test_models.py::TestFieldRuleRegex -v
```

预期：全部失败（`unexpected keyword argument 'alias'` / `'left_regex'`）。

- [ ] **Step 3: 抽公共 regex validator，实现 KeyMapping.alias 与 FieldRule regex 字段**

编辑 `src/datacompare/config/models.py`。

首先在文件顶部（`class KeyMapping` 之前）加共享 validator 函数：

```python
def _validate_optional_regex(v: str | None) -> str | None:
    """Shared field_validator body for both KeyMapping and FieldRule regex fields.
    Accepts None, otherwise compiles the pattern and enforces 0 or 1 capture groups."""
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

然后修改 `KeyMapping`：把 `_validate_regex` 的内部实现替换为对 `_validate_optional_regex` 的调用，并新增 `alias` 字段：

```python
class KeyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    right: str
    left_regex: str | None = None
    right_regex: str | None = None
    alias: str | None = None

    @field_validator("left_regex", "right_regex")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        return _validate_optional_regex(v)
```

修改 `FieldRule`：在既有字段之后新增两个 regex 字段和一个 validator，位置放在 `datetime_format` 之后、`_check_source_specifiers` model_validator 之前：

```python
    left_regex: str | None = None
    right_regex: str | None = None

    @field_validator("left_regex", "right_regex")
    @classmethod
    def _validate_regex(cls, v: str | None) -> str | None:
        return _validate_optional_regex(v)
```

（既有的 `_check_source_specifiers` model_validator 保持原样。）

- [ ] **Step 4: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/config/test_models.py::TestKeyMappingAlias tests/unit/config/test_models.py::TestFieldRuleRegex -v
```

预期：全部 pass。

- [ ] **Step 5: 全套 config 测试回归**

```bash
.venv/Scripts/pytest tests/unit/config/ -q
```

预期：全绿。既有 `KeyMapping._validate_regex` 测试不受影响，因为行为等价（只是内部实现委托到 `_validate_optional_regex`）。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_models.py
git commit -m "feat(config): KeyMapping.alias + FieldRule.left_regex/right_regex with shared validator"
```

---

## Task 3: key_canonical_name helper + loader canonical 重复检查

**Files:**
- Modify: `src/datacompare/normalize/columns.py`（append 一个函数）
- Modify: `src/datacompare/config/loader.py`（在 Pydantic 校验之后追加检查）
- Test: `tests/unit/normalize/test_columns.py` + `tests/unit/config/test_loader.py`

- [ ] **Step 1: 写失败测试（key_canonical_name）**

追加到 `tests/unit/normalize/test_columns.py`：

```python
def test_key_canonical_name_no_alias_returns_right():
    from datacompare.normalize.columns import key_canonical_name
    k = KeyMapping(left="id", right="name")
    assert key_canonical_name(k) == "name"


def test_key_canonical_name_with_alias_returns_alias():
    from datacompare.normalize.columns import key_canonical_name
    k = KeyMapping(left="id", right="name", alias="join_id")
    assert key_canonical_name(k) == "join_id"
```

- [ ] **Step 2: 写失败测试（loader 重复检查）**

追加到 `tests/unit/config/test_loader.py`（若类不存在则新建 `TestCanonicalDuplicateCheck`）：

```python
class TestCanonicalDuplicateCheck:
    def _write(self, tmp_path, content):
        path = tmp_path / "task.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_key_field_same_canonical_no_alias_rejected(self, tmp_path):
        """key.right='name' and field.right='name' collide without alias."""
        from datacompare.config.loader import load_task_or_batch
        from datacompare.config.errors import ConfigError
        import pytest
        path = self._write(tmp_path, """
name: t
sources:
  left: {type: excel, path: /tmp/x.xlsx}
  right: {type: excel, path: /tmp/y.xlsx}
match:
  keys:
    - {left: id, right: name}
compare:
  fields:
    - {left: name, right: name}
output: {dir: /tmp/out}
""")
        with pytest.raises(ConfigError, match="canonical.*duplicate|duplicate.*canonical|重复"):
            load_task_or_batch(path)

    def test_key_field_alias_avoids_collision(self, tmp_path):
        """Same shape as above but with alias — must load cleanly."""
        from datacompare.config.loader import load_task_or_batch
        path = self._write(tmp_path, """
name: t
sources:
  left: {type: excel, path: /tmp/x.xlsx}
  right: {type: excel, path: /tmp/y.xlsx}
match:
  keys:
    - {left: id, right: name, alias: join_id}
compare:
  fields:
    - {left: name, right: name}
output: {dir: /tmp/out}
""")
        cfg = load_task_or_batch(path)
        assert cfg.match.keys[0].alias == "join_id"

    def test_two_fields_same_canonical_rejected(self, tmp_path):
        """Two fields with the same f.right — pure field/field collision."""
        from datacompare.config.loader import load_task_or_batch
        from datacompare.config.errors import ConfigError
        import pytest
        path = self._write(tmp_path, """
name: t
sources:
  left: {type: excel, path: /tmp/x.xlsx}
  right: {type: excel, path: /tmp/y.xlsx}
match:
  keys:
    - {left: id, right: id}
compare:
  fields:
    - {left: a, right: name}
    - {left: b, right: name}
output: {dir: /tmp/out}
""")
        with pytest.raises(ConfigError, match="canonical.*duplicate|duplicate.*canonical|重复"):
            load_task_or_batch(path)
```

- [ ] **Step 3: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_columns.py::test_key_canonical_name_no_alias_returns_right tests/unit/normalize/test_columns.py::test_key_canonical_name_with_alias_returns_alias tests/unit/config/test_loader.py::TestCanonicalDuplicateCheck -v
```

预期：`key_canonical_name` 测试失败（ImportError），loader 测试失败（当前不做该检查，会通过 Pydantic 校验然后进入 pipeline 才炸）。

- [ ] **Step 4: 实现 key_canonical_name**

编辑 `src/datacompare/normalize/columns.py`。在 `field_canonical_name` 函数下方（大约第 20 行之后）新增：

```python
def key_canonical_name(k: "KeyMapping") -> str:
    """Return the canonical column name for a key mapping.
    Rule: k.alias if set, otherwise k.right. Used by apply_column_mapping,
    normalize_side (for regex application), and engine merge (for key_cols).
    All layers naming key columns must go through this helper."""
    return k.alias if k.alias is not None else k.right
```

Import `KeyMapping` at top（若尚未导入）：`from datacompare.config.models import KeyMapping, FieldRule`（应该已经有）。

- [ ] **Step 5: 实现 loader canonical 重复检查**

先看 `src/datacompare/config/loader.py` 的 `load_task_or_batch` 函数结构，找到 Pydantic 校验 `TaskConfig(**substituted)` 完成后、返回之前的位置。追加：

```python
def _check_canonical_uniqueness(task: TaskConfig) -> None:
    """Ensure key.canonical and field.canonical don't collide across the task.
    Fail-fast at load time with a clear ConfigError instead of surfacing as a
    pandas 'column label X is not unique' at merge time."""
    from datacompare.normalize.columns import key_canonical_name, field_canonical_name
    seen: dict[str, str] = {}  # canonical_name -> source description
    for k in task.match.keys:
        canonical = key_canonical_name(k)
        if canonical in seen:
            raise ConfigError(
                f"canonical column name '{canonical}' is duplicate: "
                f"already used by {seen[canonical]}, now also by key "
                f"(left={k.left!r}, right={k.right!r})",
                path="match.keys",
                suggestion=f"add 'alias' to one of the conflicting keys",
            )
        seen[canonical] = f"key (left={k.left!r}, right={k.right!r})"
    for f in task.compare.fields:
        canonical = field_canonical_name(f)
        if canonical in seen:
            raise ConfigError(
                f"canonical column name '{canonical}' is duplicate: "
                f"already used by {seen[canonical]}, now also by field "
                f"(left={f.left!r}, right={f.right!r})",
                path="compare.fields",
                suggestion=f"add 'alias' to the conflicting key, or rename the field",
            )
        seen[canonical] = f"field (left={f.left!r}, right={f.right!r})"
```

在 `load_task_or_batch` 里，构造出 `TaskConfig` 之后立即调用 `_check_canonical_uniqueness(task_config)`。具体两处：
1. `load_task` 函数（`loader.py:55`）在返回 `TaskConfig` 前调用一次
2. `_load_batch` 函数在每个 sub-task 完成 `TaskConfig(**merged)` 后、`SubTaskResult` 收集前调用一次（batch 里逐 sub-task 校验，任一失败按 batch fail-fast 规则处理）

- [ ] **Step 6: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_columns.py::test_key_canonical_name_no_alias_returns_right tests/unit/normalize/test_columns.py::test_key_canonical_name_with_alias_returns_alias tests/unit/config/test_loader.py::TestCanonicalDuplicateCheck -v
```

预期：5 个测试全 pass。

- [ ] **Step 7: 全套 config + normalize/columns 回归**

```bash
.venv/Scripts/pytest tests/unit/config/ tests/unit/normalize/test_columns.py -q
```

预期：全绿。

- [ ] **Step 8: Commit**

```bash
git add src/datacompare/normalize/columns.py src/datacompare/config/loader.py \
        tests/unit/normalize/test_columns.py tests/unit/config/test_loader.py
git commit -m "feat(config+normalize): key_canonical_name helper + loader canonical duplicate check"
```

---

## Task 4: apply_regex_on_canonical 公共函数（strict/soft 双模）

**Files:**
- Modify: `src/datacompare/normalize/keys.py`
- Test: `tests/unit/normalize/test_keys.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/normalize/test_keys.py`：

```python
class TestApplyRegexOnCanonical:
    def test_strict_mode_extracts_group_one(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", "Bob@@2"]})
        apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")
        assert df["c"].tolist() == ["1", "2"]

    def test_strict_mode_raises_on_mismatch(self):
        import pytest
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical, KeyRegexMismatchError
        df = pd.DataFrame({"c": ["Alice@@1", "no_at_at"]})
        with pytest.raises(KeyRegexMismatchError):
            apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")

    def test_soft_mode_extracts_group_one(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", "Bob@@2"]})
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        assert df["c"].tolist() == ["Alice", "Bob"]

    def test_soft_mode_returns_sentinel_on_mismatch(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        from datacompare.normalize.regex_errors import RegexError
        df = pd.DataFrame({"c": ["Alice@@1", "no_at_at", "Carol@@3"]})
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        vals = df["c"].tolist()
        assert vals[0] == "Alice"
        assert isinstance(vals[1], RegexError)
        assert vals[1].original == "no_at_at"
        assert vals[1].pattern == r"(.*)@@.*"
        assert vals[2] == "Carol"

    def test_none_values_passthrough_strict(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", None]}, dtype=object)
        apply_regex_on_canonical(df, {"c": r".*@@(.*)"}, mode="strict")
        assert df["c"].tolist() == ["1", None]

    def test_none_values_passthrough_soft(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["Alice@@1", None]}, dtype=object)
        apply_regex_on_canonical(df, {"c": r"(.*)@@.*"}, mode="soft")
        assert df["c"].tolist() == ["Alice", None]

    def test_zero_groups_uses_group_zero(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["abc", "xyz"]})
        apply_regex_on_canonical(df, {"c": r"[a-z]+"}, mode="strict")
        assert df["c"].tolist() == ["abc", "xyz"]

    def test_multi_column_regex_map(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({
            "a": ["X@@1", "Y@@2"],
            "b": ["P@@Q", "R@@S"],
        })
        apply_regex_on_canonical(df, {
            "a": r".*@@(.*)",
            "b": r"(.*)@@.*",
        }, mode="strict")
        assert df["a"].tolist() == ["1", "2"]
        assert df["b"].tolist() == ["P", "R"]

    def test_empty_regex_map_noop(self):
        import pandas as pd
        from datacompare.normalize.keys import apply_regex_on_canonical
        df = pd.DataFrame({"c": ["a", "b"]})
        apply_regex_on_canonical(df, {}, mode="strict")
        assert df["c"].tolist() == ["a", "b"]
```

同时保留现有 `apply_key_regex` 的测试——不要删。它会在 Step 3 里改成薄壳后仍应通过。

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_keys.py::TestApplyRegexOnCanonical -v
```

预期：全部失败（`ImportError: cannot import name 'apply_regex_on_canonical'`）。

- [ ] **Step 3: 实现 apply_regex_on_canonical 并把 apply_key_regex 改成薄壳**

编辑 `src/datacompare/normalize/keys.py`。在文件顶部 import 处追加：

```python
from datacompare.normalize.regex_errors import RegexError
```

在 `_apply_pattern_to_column` 后追加新公共函数：

```python
def apply_regex_on_canonical(
    df: pd.DataFrame,
    regex_map: dict[str, str],
    mode: Literal["strict", "soft"],
) -> None:
    """Apply regex fullmatch to columns of df in place.

    Args:
        df: DataFrame to mutate (columns must exist).
        regex_map: canonical_column_name -> pattern_string.
        mode:
          - "strict": mismatch on any row raises KeyRegexMismatchError (key semantics).
          - "soft": mismatch returns RegexError(original, pattern) sentinel; other
                    rows continue (field semantics).

    Behavior:
        - None values pass through unchanged (not fed to the regex).
        - With 0 capture groups: use m.group(0).
        - With 1 capture group: use m.group(1).
        - Empty regex_map is a no-op.
    """
    if len(df) == 0 or not regex_map:
        return
    for column, pattern_str in regex_map.items():
        pattern = re.compile(pattern_str)
        use_group_one = pattern.groups == 1

        new_values: list = []
        for i, v in enumerate(df[column].tolist()):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                new_values.append(None)
                continue
            s = v if isinstance(v, str) else str(v)
            m = pattern.fullmatch(s)
            if m is None:
                if mode == "strict":
                    _logger.error(
                        "regex_mismatch",
                        mode=mode,
                        column=column,
                        row_index=i,
                        value=s,
                        pattern=pattern_str,
                    )
                    raise KeyRegexMismatchError(
                        side="canonical",
                        column=column,
                        value=s,
                        pattern=pattern_str,
                        row_index=i,
                    )
                new_values.append(RegexError(original=s, pattern=pattern_str))
                continue
            new_values.append(m.group(1) if use_group_one else m.group(0))
        df[column] = pd.Series(new_values, dtype=object, index=df.index)
```

把现有 `apply_key_regex` 改成委托实现（保留公共 API 与 side/column 语义，供尚未迁移的调用点用）：

```python
def apply_key_regex(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Legacy shim (pre-canonical) — kept for callers that still work with
    source column names. New code should call apply_regex_on_canonical instead
    with a canonical_name -> pattern map. See spec §Regex 应用顺序调整."""
    result = df.copy()
    regex_map: dict[str, str] = {}
    for k in keys:
        pattern_str = k.left_regex if side == "left" else k.right_regex
        if pattern_str is None:
            continue
        column = k.left if side == "left" else k.right
        regex_map[column] = pattern_str
    apply_regex_on_canonical(result, regex_map, mode="strict")
    return result
```

**保留旧函数 `_apply_pattern_to_column`** 不动（可能被其他测试引用）。

- [ ] **Step 4: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_keys.py -v
```

预期：新增的 9 个测试 pass，既有 `apply_key_regex` 测试全部 pass（薄壳等价）。

- [ ] **Step 5: 全套 normalize 回归**

```bash
.venv/Scripts/pytest tests/unit/normalize/ -q
```

预期：全绿。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/normalize/keys.py tests/unit/normalize/test_keys.py
git commit -m "feat(normalize): apply_regex_on_canonical public function with strict/soft modes"
```

---

## Task 5: apply_column_mapping 重构（tasks 列表 + 同源复制）

**Files:**
- Modify: `src/datacompare/normalize/columns.py::apply_column_mapping`
- Test: `tests/unit/normalize/test_columns.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/normalize/test_columns.py`：

```python
def test_apply_column_mapping_key_alias_uses_alias_as_canonical():
    """Key with alias — canonical name comes from alias, not k.right."""
    df = pd.DataFrame({"id": ["1", "2"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = []
    result = apply_column_mapping(df, keys, fields, side="left")
    assert list(result.columns) == ["join_id"]
    assert result["join_id"].tolist() == ["1", "2"]


def test_apply_column_mapping_same_source_column_duplicated_for_key_and_field():
    """Right side: 'name' column used by BOTH key (canonical join_id via alias)
    AND field (canonical name). Both canonical columns must exist and contain
    the SAME source values (regex not applied here — that's a later step)."""
    df = pd.DataFrame({"name": ["Alice@@1", "Bob@@2"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result = apply_column_mapping(df, keys, fields, side="right")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["Alice@@1", "Bob@@2"]
    assert result["name"].tolist() == ["Alice@@1", "Bob@@2"]


def test_apply_column_mapping_left_side_with_key_alias_and_stray_col():
    """Left has 'id' and 'name'; key {left: id, right: name, alias: join_id};
    field {left: name, right: name}. Both must survive with correct values."""
    df = pd.DataFrame({"id": ["1", "2"], "name": ["Alice", "Bob"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result = apply_column_mapping(df, keys, fields, side="left")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2"]
    assert result["name"].tolist() == ["Alice", "Bob"]
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_columns.py -k "alias or duplicated" -v
```

预期：新增 3 个测试全部失败（现在 `apply_column_mapping` 不认识 `alias`，且不允许同源复制）。

- [ ] **Step 3: 重构 apply_column_mapping**

编辑 `src/datacompare/normalize/columns.py`。用下面版本完整替换现有 `apply_column_mapping`：

```python
def apply_column_mapping(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    fields: list[FieldRule],
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Build a new DataFrame with canonical-named columns.

    Task-list model (v0.6+): each key/field produces a (source_col, canonical)
    pair. A source column may appear in multiple pairs — it gets copied under
    each canonical name (needed when a column serves as both join key and
    compare field on one side, e.g. right's 'name' → both 'join_id' and 'name').

    Literal fields (side has no source column) are injected as scalar columns.

    Canonical rules:
      - key: k.alias if set, else k.right (via key_canonical_name)
      - field: f.right if set, else f.left, else "_literal" (via field_canonical_name)
    """
    tasks: list[tuple[str, str]] = []                  # (source_col, canonical)
    literal_fields: list[tuple[str, str | None]] = []  # (canonical, literal_value)
    for k in keys:
        tasks.append((getattr(k, side), key_canonical_name(k)))
    for f in fields:
        src = getattr(f, side)
        canonical = field_canonical_name(f)
        if src is not None:
            tasks.append((src, canonical))
        else:
            literal_fields.append((canonical, getattr(f, f"{side}_literal")))

    # Validate all source columns exist
    missing = [src for src, _ in tasks if src not in df.columns]
    if missing:
        from datacompare.config.errors import ConfigError
        raise ConfigError(
            f"columns not found in {side} source: {missing}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )

    # Build result: copy each (src -> canonical) pair. Same source referenced
    # multiple times produces multiple canonical columns. Canonical duplicates
    # across the task are prevented at load time by loader's canonical-uniqueness
    # check, so no in-loop collision guard needed here.
    result = pd.DataFrame(index=df.index)
    for src, canonical in tasks:
        result[canonical] = df[src].values

    for canonical, literal_val in literal_fields:
        result[canonical] = literal_val

    return result
```

- [ ] **Step 4: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_columns.py -v
```

预期：新增的 3 个测试 pass；**既有测试**（`test_apply_column_mapping_left_side`、`test_apply_column_mapping_right_side_no_rename_needed`、literal 相关测试、collision 相关测试）**也应全部 pass**——tasks 列表模型对老 config 等价（每个 key/field 各贡献一个 task，与老 rename_map 单射行为一致）。

若有既有测试失败，读失败信息定位原因；常见可能：`test_apply_column_mapping_right_side_no_rename_needed` 依赖 rename 保持行 index，新实现用 `.values` 拷贝值保留 df.index，应等价。

- [ ] **Step 5: 全套 normalize + engine 回归**

```bash
.venv/Scripts/pytest tests/unit/normalize/ tests/unit/engine/ -q
```

预期：全绿。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/normalize/columns.py tests/unit/normalize/test_columns.py
git commit -m "refactor(normalize): apply_column_mapping tasks-list model with source column duplication"
```

---

## Task 6: normalize_side pipeline 重排（regex 后置到 canonical）

**Files:**
- Modify: `src/datacompare/normalize/pipeline.py::normalize_side`
- Test: `tests/unit/normalize/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/normalize/test_pipeline.py`：

```python
def test_pipeline_key_alias_and_field_regex_end_to_end_right_side():
    """Right side: source 'name' feeds both key (regex .*@@(.*), canonical join_id)
    and field (regex (.*)@@.*, canonical name)."""
    df = pd.DataFrame({"name": ["Alice@@1", "Bob@@2", "Carol@@3"]})
    keys = [KeyMapping(left="id", right="name",
                       right_regex=r".*@@(.*)", alias="join_id")]
    fields = [FieldRule(left="name", right="name",
                        right_regex=r"(.*)@@.*")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2", "3"]
    assert result["name"].tolist() == ["Alice", "Bob", "Carol"]


def test_pipeline_key_alias_left_side_no_regex():
    """Left side: no regex on either key or field; alias renames key canonical."""
    df = pd.DataFrame({"id": ["1", "2"], "name": ["Alice", "Bob"]})
    keys = [KeyMapping(left="id", right="name", alias="join_id")]
    fields = [FieldRule(left="name", right="name")]
    result = normalize_side(df, keys, _cfg(fields), side="left")
    assert set(result.columns) == {"join_id", "name"}
    assert result["join_id"].tolist() == ["1", "2"]
    assert result["name"].tolist() == ["Alice", "Bob"]


def test_pipeline_field_regex_soft_failure_returns_sentinel():
    """Row that doesn't match field regex becomes RegexError, other rows fine."""
    from datacompare.normalize.regex_errors import RegexError
    df = pd.DataFrame({"id": ["1", "2", "3"], "code": ["A@@X", "no_at", "B@@Y"]})
    keys = [KeyMapping(left="id", right="id")]
    fields = [FieldRule(left="code", right="code", right_regex=r"(.*)@@.*")]
    result = normalize_side(df, keys, _cfg(fields), side="right")
    vals = result["code"].tolist()
    assert vals[0] == "A"
    assert isinstance(vals[1], RegexError)
    assert vals[1].original == "no_at"
    assert vals[2] == "B"


def test_pipeline_key_regex_still_strict_after_reorder():
    """After moving key regex post-rename, strict semantics preserved:
    mismatch aborts the entire task via KeyRegexMismatchError."""
    import pytest
    from datacompare.normalize.keys import KeyRegexMismatchError
    df = pd.DataFrame({"name": ["Alice@@1", "no_at_at"]})
    keys = [KeyMapping(left="id", right="name",
                       right_regex=r".*@@(.*)", alias="join_id")]
    fields = []
    with pytest.raises(KeyRegexMismatchError):
        normalize_side(df, keys, _cfg(fields), side="right")
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -k "alias or field_regex or key_regex_still" -v
```

预期：前三个失败（当前 pipeline 不处理 field regex，key regex 也在 pre-rename），第四个可能 pass（老 apply_key_regex 仍能 catch）也可能失败。

- [ ] **Step 3: 重排 normalize_side**

编辑 `src/datacompare/normalize/pipeline.py`。用下面版本完整替换 `normalize_side`：

```python
def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Normalize one side:
      1. rename+duplicate source columns to canonical names (apply_column_mapping)
      2. apply key regexes on canonical columns (strict mode)
      3. apply field regexes on canonical columns (soft mode → RegexError sentinel)
      4. per-field _process_value (string preprocess → unit → type coerce → decimals)
    """
    from .keys import apply_regex_on_canonical
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [key_canonical_name(k) for k in keys]

    # Step 2: key regex on canonical (strict)
    key_regex_map: dict[str, str] = {}
    for k in keys:
        pattern = getattr(k, f"{side}_regex")
        if pattern is not None:
            key_regex_map[key_canonical_name(k)] = pattern
    apply_regex_on_canonical(renamed, key_regex_map, mode="strict")

    # Step 3: field regex on canonical (soft — RegexError sentinel on mismatch)
    field_regex_map: dict[str, str] = {}
    for f in compare.fields:
        pattern = getattr(f, f"{side}_regex")
        if pattern is not None:
            field_regex_map[field_canonical_name(f)] = pattern
    apply_regex_on_canonical(renamed, field_regex_map, mode="soft")

    # Step 4: per-field _process_value
    result = renamed.copy()
    for rule in compare.fields:
        eff = effective_rule(rule, compare.defaults)
        col = field_canonical_name(rule)
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))
    return result[key_cols + [field_canonical_name(f) for f in compare.fields]]
```

**关键改动：**
1. 去掉 `df = apply_key_regex(df, keys, side)`（老的 pre-rename 调用）
2. 用 `apply_regex_on_canonical(renamed, ..., mode="strict")` 替代
3. 追加对 field 的 `apply_regex_on_canonical(..., mode="soft")`

- [ ] **Step 4: `_process_value` 需要认识 RegexError sentinel**

`_process_value` 在 `pipeline.py` 里。当前逻辑：
```python
if v is None or not isinstance(v, str):
    s = v
```
`RegexError` 不是 str 也不是 None → `s = v`（RegexError 实例），后续 `if s is None: return None` 不会命中，会掉进后续管线（`isinstance(s, str)` 分支）——需要提前 return sentinel 不变。

在 `_process_value` 开头补一句（放在 `v is None` 判断之后）：

```python
def _process_value(v: Any, rule: EffectiveRule) -> Any:
    # Sentinel-like errors flow through the pipeline unchanged so downstream
    # engine can classify them via DiffType.
    from .regex_errors import RegexError
    if isinstance(v, RegexError):
        return v
    # ... 原有逻辑
```

- [ ] **Step 5: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/normalize/test_pipeline.py -v
```

预期：全绿（新测试 pass，老测试仍 pass）。

- [ ] **Step 6: 全套 normalize + engine 回归**

```bash
.venv/Scripts/pytest tests/unit/normalize/ tests/unit/engine/ -q
```

预期：全绿。

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/normalize/pipeline.py tests/unit/normalize/test_pipeline.py
git commit -m "feat(normalize): pipeline runs regex post-rename on canonical columns (key strict, field soft)"
```

---

## Task 7: 引擎侧使用 key_canonical_name + 识别 RegexError

**Files:**
- Modify: `src/datacompare/engine/memory.py`
- Modify: `src/datacompare/engine/disk.py`
- Test: `tests/unit/engine/test_same_column_name_collision.py`（既有回归文件）

- [ ] **Step 1: 写失败测试（端到端 key alias + field regex）**

追加到 `tests/unit/engine/test_same_column_name_collision.py`：

```python
def test_key_alias_and_field_regex_end_to_end(tmp_path):
    """End-to-end regression: right's 'name' column serves as both join key
    (regex to extract ID suffix, alias=join_id) and compare field (regex to
    extract name prefix). Left has real 'id' and 'name' columns.
    Verifies canonical column handling flows all the way through the engine's
    merge and diff report."""
    _xlsx(tmp_path / "left.xlsx", [
        ["id", "name"],
        ["1", "Alice"],
        ["2", "Bob"],
        ["3", "Carol"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["name"],
        ["Alice@@1"],
        ["Bob@@2"],
        ["Different@@3"],  # produces a name diff (Carol vs Different)
    ])

    task = TaskConfig(
        name="key_alias_field_regex_e2e",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(
            left="id", right="name",
            right_regex=r".*@@(.*)", alias="join_id",
        )]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(
                left="name", right="name",
                right_regex=r"(.*)@@.*",
            )],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    assert result.matched_rows == 3
    assert result.identical_rows == 2   # rows 1,2 match; row 3 diffs on name
    assert result.diff_rows == 1
    diff_fields = set(result.diff_details["field"])
    assert diff_fields == {"name"}  # canonical field name (not join_id)


def test_field_regex_mismatch_reports_as_regex_error(tmp_path):
    """Regression: a field regex mismatch on one row surfaces as a RegexError
    sentinel and gets classified as DiffType.REGEX_ERROR in the report; other
    rows keep comparing normally."""
    _xlsx(tmp_path / "left.xlsx", [
        ["id", "code"],
        ["1", "A"],
        ["2", "B"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["id", "code"],
        ["1", "A@@X"],
        ["2", "no_at_at"],  # regex fails softly
    ])

    task = TaskConfig(
        name="field_regex_soft_fail_e2e",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(left="code", right="code",
                              right_regex=r"(.*)@@.*")],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    # Row 1: left code="A", right code post-regex="A" → identical
    # Row 2: left code="B", right code post-regex=RegexError → diff, classified regex_error
    assert result.matched_rows == 2
    assert result.identical_rows == 1
    assert result.diff_rows == 1
    diff_types = set(result.diff_details["diff_type"])
    assert "regex_error" in diff_types
```

- [ ] **Step 2: 跑测试验证 red**

```bash
.venv/Scripts/pytest tests/unit/engine/test_same_column_name_collision.py::test_key_alias_and_field_regex_end_to_end tests/unit/engine/test_same_column_name_collision.py::test_field_regex_mismatch_reports_as_regex_error -v
```

预期：第一个测试可能失败（`memory.py` 的 `key_cols` 还硬编码 `k.right` = `"name"`，与 field canonical `"name"` 撞车但 loader 校验又拦不住因为**用了 alias 后 canonical 应该是 `join_id`**——所以取决于 engine 是否用了 `key_canonical_name`）。第二个测试失败（引擎不识别 `RegexError` sentinel）。

- [ ] **Step 3: 更新 engine/memory.py 使用 key_canonical_name**

编辑 `src/datacompare/engine/memory.py`。在文件顶部 import 增加：

```python
from datacompare.normalize.columns import field_canonical_name, key_canonical_name
from datacompare.normalize.regex_errors import RegexError
```

修改 `compare` 方法内 `key_cols` 那一行（大约第 56 行）：

```python
# 老
key_cols = [k.right for k in task.match.keys]
# 新
key_cols = [key_canonical_name(k) for k in task.match.keys]
```

修改 `_classify` 函数（在同文件 `memory.py:26`）增加对 `RegexError` 的识别。当前 `_classify` 大致长这样：

```python
def _classify(l: Any, r: Any) -> str:
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    return DiffType.VALUE_MISMATCH.value
```

改成（在 UnitError 分支之后加一分支）：

```python
def _classify(l: Any, r: Any) -> str:
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    if isinstance(l, RegexError) or isinstance(r, RegexError):
        return DiffType.REGEX_ERROR.value
    return DiffType.VALUE_MISMATCH.value
```

`_values_equal` 需要也识别 `RegexError`（当前对 `CoerceError`/`UnitError` 已判 `False`）：

```python
def _values_equal(l: Any, r: Any) -> bool:
    if l is None and r is None:
        return True
    if l is None or r is None:
        return False
    if isinstance(l, (CoerceError, UnitError, RegexError)) or isinstance(r, (CoerceError, UnitError, RegexError)):
        return False
    return l == r
```

`_display` 也要处理 `RegexError`（当前对 CoerceError/UnitError 用 `.original`）：

```python
def _display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (CoerceError, UnitError, RegexError)):
        return v.original
    return str(v)
```

最后：在 engine 的每字段循环里（`for f in task.compare.fields:` 那段），处理 `FieldError` 收集时若发现 `RegexError`，也应加进 `errors` 列表：

```python
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
# 同理处理 rv
```

- [ ] **Step 4: 同样修改 engine/disk.py**

对 `src/datacompare/engine/disk.py` 做完全对称的修改：
1. import `key_canonical_name` 和 `RegexError`
2. `key_cols = [key_canonical_name(k) for k in task.match.keys]`
3. `_classify`/`_values_equal`/`_display` 加 `RegexError` 分支（若这些是各自 engine 文件私有的）
4. errors 收集加 `RegexError` 分支

`disk.py` 的 `_values_equal`（`disk.py:21`）、`_classify`（`disk.py:31`）、`_display`（`disk.py:41`）是与 `memory.py` 平行的私有 copy——完全对称地修改，加同样的 `RegexError` 分支。

- [ ] **Step 5: 跑测试验证 green**

```bash
.venv/Scripts/pytest tests/unit/engine/ -v
```

预期：新增 2 个测试 pass；既有测试全 pass（`key_canonical_name` 对无 alias 的老 key 行为等价，`RegexError` 分支只在有 field regex 时才触发）。

- [ ] **Step 6: 全套回归**

```bash
.venv/Scripts/pytest tests/ -q
```

预期：全绿。

- [ ] **Step 7: Commit**

```bash
git add src/datacompare/engine/memory.py src/datacompare/engine/disk.py \
        tests/unit/engine/test_same_column_name_collision.py
git commit -m "feat(engine): use key_canonical_name and classify RegexError as DiffType.REGEX_ERROR"
```

---

## Task 8: Batch e2e scenario K

**Files:**
- Modify: `tests/integration/test_batch_e2e.py`

- [ ] **Step 1: 追加测试**

追加到 `tests/integration/test_batch_e2e.py`：

```python
def test_batch_scenario_k_key_alias_and_field_regex(tmp_path):
    """Scenario K: batch sub-task uses key alias + field regex to compare
    a compound right-side column against split left-side columns.

    Left: {id, name}. Right: {name} = "prefix@@id" pattern.
    Join on right's regex-extracted ID via alias=join_id (avoids name collision).
    Compare left.name against right.name regex-extracted prefix."""
    _make_xlsx(tmp_path / "left.xlsx", {
        "USERS": [["id", "name"], ["1", "Alice"], ["2", "Bob"], ["3", "Carol"]],
    })
    _make_xlsx(tmp_path / "right.xlsx", {
        "COMPOUND": [["name"], ["Alice@@1"], ["Diff@@2"], ["Carol@@3"]],
    })
    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: alias_and_field_regex_batch
sources:
  left: {{type: excel, path: {tmp_path}/left.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: users_vs_compound
    sources:
      left: {{sheets: [{{name: USERS}}]}}
      right: {{type: excel, path: {tmp_path}/right.xlsx, sheets: [{{name: COMPOUND}}]}}
    match:
      keys:
        - {{left: id, right: name, right_regex: '.*@@(.*)', alias: join_id}}
    compare:
      fields:
        - {{left: name, right: name, right_regex: '(.*)@@.*'}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0, result.output
    report = json.loads(
        (tmp_path / "reports" / "users_vs_compound" / "report.json").read_text(encoding="utf-8")
    )
    assert report["summary"]["matched"] == 3
    assert report["summary"]["identical"] == 2  # rows 1,3 match; row 2 diffs
    assert report["summary"]["diff"] == 1
```

- [ ] **Step 2: 跑测试**

```bash
.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_k_key_alias_and_field_regex -v
```

预期：PASS（Tasks 1-7 已实现所有底层能力）。

若失败：定位真实原因，**不要**试图改生产代码——报告失败停下，因为 plan 预期这里应该一次过。

- [ ] **Step 3: 全套集成回归**

```bash
.venv/Scripts/pytest tests/integration/ -q
```

预期：全绿（Docker 相关可能 skip）。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_batch_e2e.py
git commit -m "test(integration): batch scenario K — key alias + field regex + source column duplication"
```

---

## Task 9: 文档

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: README.md**

打开 `README.md`，找到"字面量字段（v0.5+）"小节（v0.5 那次加的）。在它后面追加两个新小节：

````markdown
#### KeyMapping alias（v0.6+）

当 `k.right` 与某个 `f.right` 撞名（左侧同源列作 join key 又作 compare
field），加 `alias` 给 key canonical 起个别名避免冲突：

```yaml
match:
  keys:
    # 不加 alias → canonical = "name"，与下面 field 的 canonical 撞车 → 加载报错
    # 加 alias → canonical = "join_id"，与 field canonical "name" 分开
    - {left: id, right: name, right_regex: '.*@@(.*)', alias: join_id}

compare:
  fields:
    - {left: name, right: name, right_regex: '(.*)@@.*'}
```

若 canonical 撞名且未加 alias，`datacompare validate` / `run` 在加载期
fail-fast 报错，不会跑到 pandas merge 才炸。

#### 字段级 regex（v0.6+）

`FieldRule` 也可跑 regex 提取，语义与 `KeyMapping.left_regex/right_regex`
一致（`re.fullmatch`、0/1 捕获组、None 透传）：

```yaml
compare:
  fields:
    # 从右侧 "prefix@@1234" 提取 prefix 部分再与左侧比对
    - {left: name, right: name, right_regex: '(.*)@@.*'}
```

**失败语义差异**：key regex 不匹配 → 整个任务失败（exit 2）；
field regex 不匹配 → 该行值变 `RegexError` sentinel、diff 报告归
`regex_error` 类型，其他行照常。
````

- [ ] **Step 2: docs/user-guide.md**

打开 `docs/user-guide.md`，找到 `### Key regex normalization (v0.3+)` 小节。在它后面追加两个新小节：

````markdown
### Key alias for canonical name conflicts (v0.6+)

Give a key a custom canonical column name via `alias` when `k.right` would
collide with a field's canonical:

```yaml
match:
  keys:
    - left: id
      right: name
      right_regex: '.*@@(.*)'
      alias: join_id     # key canonical becomes "join_id" instead of "name"
```

Rules:
- `alias` is optional; when unset, canonical = `k.right` (unchanged behavior)
- Any non-empty string is valid
- If `key_canonical_name(k) == field_canonical_name(f)` for any pair in
  the same task, loader raises `ConfigError` — add `alias` to disambiguate

### Field regex normalization (v0.6+)

Mirror of `KeyMapping.left_regex/right_regex` for compare fields:

```yaml
compare:
  fields:
    - left: name
      right: name
      right_regex: '(.*)@@.*'
```

Rules:
- Uses Python `re.fullmatch`; the whole string must match
- 0 or 1 capture group; with a capture group `group(1)` wins, otherwise
  `group(0)`
- 2 or more capture groups fail at `datacompare validate` time (use
  non-capturing groups `(?:...)`)
- `None` values pass through unchanged
- **Failure semantics** (differs from key regex): row that fails to match
  → value becomes `RegexError` sentinel, gets classified as
  `regex_error` diff type in the report; other rows keep comparing.
  This is deliberate: bad key kills the join, bad field is just a data
  quality issue.

### Source column duplication (v0.6+)

If the same source column is referenced by both a key and a field
(e.g. right's `name` is used as join key via alias AND as compare field),
`apply_column_mapping` produces two canonical columns from that one source.
This is what makes the combination "key regex + field regex" on the same
column work — the source column is copied per canonical before regexes
apply, so each canonical column gets its own regex without interfering.
````

- [ ] **Step 3: CLAUDE.md**

打开 `CLAUDE.md`，找到 `## 关键约束（改代码前务必了解）` 章节。在末尾追加新 bullet（在 `FieldRule 支持 left_literal / right_literal` 那条之后）：

```markdown
- **`KeyMapping` 支持 `alias`**（v0.6 起）：给 join key 自定义 canonical
  列名，避免与 field canonical 撞车。canonical 命名规则由
  `normalize/columns.py::key_canonical_name`（`alias` 优先，回退 `k.right`）
  集中管理。engine 和 normalize 都通过这个 helper 拿 join key 列名，别
  硬编码 `k.right`。**加载期 canonical 重复检查**在 `config/loader.py`
  的 `_check_canonical_uniqueness`——任何 key/field canonical 撞车都在这里
  fail-fast，不到 pandas 层才炸。
- **`FieldRule` 支持 `left_regex` / `right_regex`**（v0.6 起）：语义与
  `KeyMapping` 的 regex 一致（`re.fullmatch`、0/1 捕获组、None 透传），
  **但失败模式相反**——key regex 不匹配 → 严格失败（`KeyRegexMismatchError`
  → CLI exit 2）；field regex 不匹配 → **软失败**（`RegexError` sentinel，
  engine 归 `DiffType.REGEX_ERROR`，其他行不影响）。原因：坏 key 让
  整个 join 无意义，坏 field 只是一行数据问题。
- **Regex 应用顺序**（v0.6 起）：`normalize_side` 先 `apply_column_mapping`
  复制+改名，**再**跑 key regex（strict）和 field regex（soft），都作用在
  canonical 列上。别改回 pre-rename——右侧同一个源列可能同时被 key
  和 field 引用（如右侧 `name` = "prefix@@id" 双用），只有先复制再分别
  跑 regex 才不互相污染。
- **`apply_column_mapping` 是"tasks 列表"模型**（v0.6 起）：每个 key/field
  贡献一个 `(source_col, canonical)` 对，同源列多次出现 = 复制成多个
  canonical 列（不是 rename）。canonical 撞名靠 loader fail-fast 挡住，
  运行时不用再查重。
```

- [ ] **Step 4: 验证**

```bash
grep -n "alias\|left_regex\|right_regex\|RegexError" README.md docs/user-guide.md CLAUDE.md | head -20
```

预期：每个文件都有若干 match。

```bash
.venv/Scripts/pytest tests/ -q
```

预期：全绿（docs 变更不动代码）。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/user-guide.md CLAUDE.md
git commit -m "docs: KeyMapping.alias + FieldRule.left_regex/right_regex + source column duplication"
```

---

## 实现后 checklist

全部 9 个任务提交后：

- [ ] 全套跑一遍：`.venv/Scripts/pytest tests/ -q`
- [ ] Ruff 无回归：`.venv/Scripts/ruff check src/ tests/`
- [ ] mypy 无回归：`.venv/Scripts/mypy src/datacompare/`
- [ ] Push：`git push`

任一失败就地修，别推破的 suite。
