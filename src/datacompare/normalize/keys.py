"""Key/field regex normalization: apply fullmatch to canonical columns.

apply_regex_on_canonical is the public entry point (called by normalize_side
post-rename, once per side, with a canonical_column -> pattern map). Strict
mode raises KeyRegexMismatchError on the first mismatch; soft mode returns a
RegexError sentinel for the mismatched row and keeps going.

apply_key_regex is a legacy pre-canonical shim, kept for backwards-compatible
callers; new code should call apply_regex_on_canonical directly.
"""
from __future__ import annotations

import re
from typing import Literal

import pandas as pd
import structlog

from datacompare.config.models import KeyMapping
from datacompare.normalize.regex_errors import RegexError

_logger = structlog.get_logger("datacompare.normalize.keys")


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


def apply_regex_on_canonical(
    df: pd.DataFrame,
    regex_map: dict[str, str],
    mode: Literal["strict", "soft"],
    error_side: str = "canonical",
    log_event: str = "regex_mismatch",
) -> None:
    """Apply regex fullmatch to columns of df in place.

    Args:
        df: DataFrame to mutate (columns must exist).
        regex_map: canonical_column_name -> pattern_string.
        mode:
          - "strict": mismatch on any row raises KeyRegexMismatchError (key semantics).
          - "soft": mismatch returns RegexError(original, pattern) sentinel; other
                    rows continue (field semantics).
        error_side / log_event: only affect the strict-mode KeyRegexMismatchError
          and structlog event. Kept for the apply_key_regex shim so old callers
          see side="left"/"right" and event="key_regex_mismatch" verbatim.

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
                        log_event,
                        side=error_side,
                        column=column,
                        row_index=i,
                        value=s,
                        pattern=pattern_str,
                    )
                    raise KeyRegexMismatchError(
                        side=error_side,
                        column=column,
                        value=s,
                        pattern=pattern_str,
                        row_index=i,
                    )
                new_values.append(RegexError(original=s, pattern=pattern_str))
                continue
            new_values.append(m.group(1) if use_group_one else m.group(0))
        df[column] = pd.Series(new_values, dtype=object, index=df.index)


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
    apply_regex_on_canonical(
        result, regex_map, mode="strict",
        error_side=side, log_event="key_regex_mismatch",
    )
    return result


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
        new_values.append(m.group(1) if use_group_one else m.group(0))
    # Assign via a Series with object dtype so None survives (default __setitem__
    # coerces None -> NaN in an object column on pandas 2.x).
    df[column] = pd.Series(new_values, dtype=object, index=df.index)
