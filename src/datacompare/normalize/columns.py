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
) -> pd.DataFrame:
    """Rename columns to canonical names; drop unmapped columns; inject literal
    fields as constant-valued columns.

    Canonical name for a literal field = the non-literal side's column name
    (e.g. `{left_literal: "X", right: "type"}` → canonical is "type"). When
    both sides are literal, canonical = f.right (or f.left as fallback).
    """
    rename_map: dict[str, str] = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    literal_fields: list[tuple[str, str | None]] = []  # (canonical_name, literal_value)
    for f in fields:
        canonical = field_canonical_name(f)
        src = getattr(f, side)
        if src is not None:
            rename_map[src] = canonical
        else:
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
