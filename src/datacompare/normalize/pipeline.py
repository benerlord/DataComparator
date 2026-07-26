"""Compose normalize steps into a per-side pipeline."""
from __future__ import annotations
from typing import Literal, Any
import pandas as pd
from datacompare.config.models import KeyMapping, CompareConfig
from datacompare.engine.result import FieldError
from .columns import apply_column_mapping, effective_rule, EffectiveRule, field_canonical_name, key_canonical_name
from .strings import normalize_string
from .types import coerce_type, CoerceError
from .units import parse_and_convert, UnitError
from .decimals import round_half_up
from .keys import apply_regex_on_canonical
from .regex_errors import RegexError


def _process_value(v: Any, rule: EffectiveRule) -> Any:
    # Sentinels flow through unchanged so engine can classify them via DiffType.
    if isinstance(v, RegexError):
        return v
    # 1. string preprocess (null equivalents, whitespace, case)
    if v is None or not isinstance(v, str):
        s = v
    else:
        s = normalize_string(
            v,
            ignore_whitespace=rule.ignore_whitespace,
            ignore_case=rule.ignore_case,
            null_equivalents=rule.null_equivalents,
        )
    if s is None:
        return None

    # 2. unit parsing (if configured)
    if rule.parse_unit and rule.unit_category and rule.normalize_to:
        converted = parse_and_convert(str(s), rule.unit_category, rule.normalize_to)
        if isinstance(converted, UnitError):
            return converted
        s = converted

    # 3. type coercion (for numeric mode with as_type; or explicit as_type)
    if rule.as_type is not None:
        s = coerce_type(str(s) if not isinstance(s, str) else s, rule.as_type, rule.datetime_format)
        if isinstance(s, CoerceError):
            return s
    elif rule.mode == "numeric" and not isinstance(s, (int, float)):
        s = coerce_type(str(s), "float", None)
        if isinstance(s, CoerceError):
            return s

    # 4. decimal rounding (numeric only)
    if rule.mode == "numeric" and rule.decimal_places is not None and isinstance(s, (int, float)):
        s = round_half_up(float(s), rule.decimal_places)

    return s


def normalize_side(
    df: pd.DataFrame,
    keys: list[KeyMapping],
    compare: CompareConfig,
    side: Literal["left", "right"],
) -> pd.DataFrame:
    """Normalize one side:
      1. rename+duplicate source columns to canonical names (apply_column_mapping)
      2. apply key regexes on canonical columns (strict mode)
      3. apply field regexes on canonical columns (soft mode -> RegexError sentinel)
      4. per-field _process_value (string preprocess -> unit -> type coerce -> decimals)
    """
    renamed, missing_field_canonicals = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [key_canonical_name(k) for k in keys]

    # Step 2: key regex on canonical (strict)
    key_regex_map: dict[str, str] = {}
    for k in keys:
        pattern = getattr(k, f"{side}_regex")
        if pattern is not None:
            key_regex_map[key_canonical_name(k)] = pattern
    apply_regex_on_canonical(
        renamed, key_regex_map, mode="strict",
        error_side=side, log_event="key_regex_mismatch",
    )

    # Step 3: field regex on canonical (soft — RegexError sentinel on mismatch)
    # Skip canonicals that are missing on this side
    field_regex_map: dict[str, str] = {}
    for f in compare.fields:
        canonical = field_canonical_name(f)
        if canonical in missing_field_canonicals:
            continue
        pattern = getattr(f, f"{side}_regex")
        if pattern is not None:
            field_regex_map[canonical] = pattern
    apply_regex_on_canonical(renamed, field_regex_map, mode="soft")

    # Step 4: per-field _process_value (skip missing canonicals)
    result = renamed.copy()
    for rule in compare.fields:
        col = field_canonical_name(rule)
        if col in missing_field_canonicals:
            continue
        eff = effective_rule(rule, compare.defaults)
        result[col] = result[col].map(lambda v, r=eff: _process_value(v, r))

    surviving_field_cols = [
        field_canonical_name(f)
        for f in compare.fields
        if field_canonical_name(f) not in missing_field_canonicals
    ]
    return result[key_cols + surviving_field_cols]
