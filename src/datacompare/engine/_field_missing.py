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


def merged_col_name(
    canonical: str,
    side: Literal["left", "right"],
    left_missing: frozenset[str],
    right_missing: frozenset[str],
) -> str:
    """Return the actual column name in a pandas outer-merged DataFrame.

    pandas outer-merge only adds __left/__right suffixes when a column exists
    in BOTH DataFrames; a column present on only one side keeps its bare name
    in the result. Callers building left_only_rows / right_only_rows must
    account for this — otherwise they KeyError on missing-field scenarios.
    """
    on_left = canonical not in left_missing
    on_right = canonical not in right_missing
    if on_left and on_right:
        return f"{canonical}__{side}"
    return canonical
