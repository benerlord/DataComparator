"""Key normalization step: apply per-side regex fullmatch to key columns.

Runs BEFORE column mapping and field normalization. Strict-fail semantics:
first mismatch raises KeyRegexMismatchError (subclass of ValueError).
"""
from __future__ import annotations


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
