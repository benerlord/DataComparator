"""Helper for constructing field-missing summary diff records.

Used by memory and disk engines when a compare field's column is absent on
exactly one side (single-side miss). Both-sides miss raises earlier;
key miss raises even earlier in apply_column_mapping.
"""
from __future__ import annotations
from typing import Literal
from .result import DiffType


def _build_field_missing_record(
    field_canonical: str,
    side_missing: Literal["left", "right"],
    key_cols: list[str],
    other_side_row_count: int,
) -> dict:
    """Build one summary diff row for a field that is missing on `side_missing`.

    Key columns are filled with empty strings — this record is structural, not
    row-specific. The present side's value describes total row count on that
    side (not matched row count), because "how many rows would have compared"
    is meaningless when a whole column is absent.
    """
    record: dict = {k: "" for k in key_cols}
    record["field"] = field_canonical
    if side_missing == "left":
        record["left_value"] = "字段不存在"
        record["right_value"] = f"(右侧 {other_side_row_count} 行有值)"
    else:
        record["left_value"] = f"(左侧 {other_side_row_count} 行有值)"
        record["right_value"] = "字段不存在"
    record["diff_type"] = DiffType.FIELD_MISSING.value
    return record
