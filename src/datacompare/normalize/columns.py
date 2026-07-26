"""Column renaming and per-field effective rule merging."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import pandas as pd
from datacompare.config.models import KeyMapping, FieldRule, CompareDefaults


def field_canonical_name(f: FieldRule) -> str:
    """Return the canonical column name for a field regardless of literal status.
    Rule: prefer f.right, fall back to f.left when right side is literal, then
    "_literal" sentinel when both sides are literal (edge case, spec-allowed
    but has no useful engine semantics). All layers that name field columns
    (apply_column_mapping, normalize_side, engine merge/diff) must use this
    helper so their names agree."""
    if f.right is not None:
        return f.right
    if f.left is not None:
        return f.left
    return "_literal"


def key_canonical_name(k: KeyMapping) -> str:
    """Return the canonical column name for a key mapping.
    Rule: k.alias if set, otherwise k.right. Used by apply_column_mapping,
    normalize_side (for regex application), and engine merge (for key_cols).
    All layers naming key columns must go through this helper."""
    return k.alias if k.alias is not None else k.right


@dataclass(frozen=True)
class EffectiveRule:
    """FieldRule merged with defaults; no None values for behavioral flags."""
    left: str | None
    right: str | None
    mode: str
    decimal_places: int | None
    parse_unit: bool
    unit_category: str | None
    normalize_to: str | None
    ignore_whitespace: bool
    ignore_case: bool
    null_equivalents: list[str]
    as_type: str | None
    datetime_format: str | None


def effective_rule(rule: FieldRule, defaults: CompareDefaults) -> EffectiveRule:
    return EffectiveRule(
        left=rule.left,
        right=rule.right,
        mode=rule.mode if rule.mode is not None else defaults.mode,
        decimal_places=rule.decimal_places,
        parse_unit=rule.parse_unit if rule.parse_unit is not None else False,
        unit_category=rule.unit_category,
        normalize_to=rule.normalize_to,
        ignore_whitespace=(
            rule.ignore_whitespace if rule.ignore_whitespace is not None
            else defaults.ignore_whitespace
        ),
        ignore_case=(
            rule.ignore_case if rule.ignore_case is not None else defaults.ignore_case
        ),
        null_equivalents=(
            rule.null_equivalents if rule.null_equivalents is not None
            else defaults.null_equivalents
        ),
        as_type=rule.as_type,
        datetime_format=rule.datetime_format,
    )


def apply_column_mapping(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    fields: list[FieldRule],
    side: Literal["left", "right"],
) -> tuple[pd.DataFrame, frozenset[str]]:
    """Build a new DataFrame with canonical-named columns.

    Task-list model (v0.6+): each key/field produces a (source_col, canonical)
    pair. A source column may appear in multiple pairs — it gets copied under
    each canonical name (needed when a column serves as both join key and
    compare field on one side, e.g. right's 'name' -> both 'join_id' and
    'name'). Literal fields (no source column on this side) are injected as
    scalar columns.

    v0.8 缺列语义：
      - key 缺列 → 立即抛 ConfigError（key 是硬约束，没 key 无法 join）
      - field 缺列 → 从结果 df 剔除，其 canonical 加入 missing_field_canonicals
        返回集；下游 engine 决定汇总行为
      - literal 字段（该侧无 source 列）不进 missing 检测

    Canonical rules:
      - key: key_canonical_name(k) — k.alias if set, else k.right
      - field: field_canonical_name(f) — f.right, else f.left, else '_literal'

    Canonical duplicates across the task are prevented at load time by loader's
    canonical-uniqueness check (_check_canonical_uniqueness), so no in-loop
    collision guard is needed here.

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

    # Copy each (src -> canonical) pair. Same source referenced multiple times
    # produces multiple canonical columns. Uses .values to sever pandas view
    # relationships so downstream mutations don't reach back into df.
    result = pd.DataFrame(index=df.index)
    for src, canonical in key_tasks:
        result[canonical] = df[src].values
    for src, canonical in surviving_field_tasks:
        result[canonical] = df[src].values
    for canonical, literal_val in literal_fields:
        result[canonical] = literal_val

    return result, frozenset(missing_field_canonicals)
