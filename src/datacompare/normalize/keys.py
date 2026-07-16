"""Key normalization step: apply per-side regex fullmatch to key columns.

Runs BEFORE column mapping and field normalization. Strict-fail semantics:
first mismatch raises KeyRegexMismatchError (subclass of ValueError).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from datacompare.config.models import KeyMapping


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
    if len(result) == 0:
        return result
    for k in keys:
        pattern_str = k.left_regex if side == "left" else k.right_regex
        if pattern_str is None:
            continue
        column = k.left if side == "left" else k.right
        _apply_pattern_to_column(result, column, pattern_str, side)
    return result


def _apply_pattern_to_column(
    df: pd.DataFrame, column: str, pattern_str: str, side: str,
) -> None:
    """Placeholder — real body in Task 4."""
    raise NotImplementedError("Task 4 will implement regex logic")
