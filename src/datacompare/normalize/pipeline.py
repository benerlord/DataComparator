"""Compose normalize steps into a per-side pipeline."""
from __future__ import annotations
from typing import Literal, Any
import pandas as pd
from datacompare.config.models import KeyMapping, CompareConfig
from datacompare.engine.result import FieldError
from .columns import apply_column_mapping, effective_rule, EffectiveRule
from .strings import normalize_string
from .types import coerce_type, CoerceError
from .units import parse_and_convert, UnitError
from .decimals import round_half_up
from .keys import apply_key_regex


def _process_value(v: Any, rule: EffectiveRule) -> Any:
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
    """Apply key regex -> rename+inject -> per-field transform."""
    df = apply_key_regex(df, keys, side)
    renamed = apply_column_mapping(df, keys, compare.fields, side=side)
    key_cols = [k.right for k in keys]

    def _canonical(f):
        # Mirrors apply_column_mapping's canonical-name rule: prefer f.right,
        # fall back to f.left when right side is literal, then "_literal"
        # sentinel when both sides are literal.
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
