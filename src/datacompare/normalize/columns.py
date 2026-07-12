"""Column renaming and per-field effective rule merging."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import pandas as pd
from datacompare.config.models import KeyMapping, FieldRule, CompareDefaults


@dataclass(frozen=True)
class EffectiveRule:
    """FieldRule merged with defaults; no None values for behavioral flags."""
    left: str
    right: str
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
    """Rename columns to canonical (right-side) names; drop unmapped columns."""
    rename_map: dict[str, str] = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    for f in fields:
        rename_map[getattr(f, side)] = f.right
    missing = [src for src in rename_map if src not in df.columns]
    if missing:
        from datacompare.config.errors import ConfigError
        raise ConfigError(
            f"columns not found in {side} source: {missing}",
            path=f"sources.{side}",
            suggestion=f"available columns: {list(df.columns)}",
        )
    keep = list(rename_map.values())
    return df.rename(columns=rename_map)[keep]
