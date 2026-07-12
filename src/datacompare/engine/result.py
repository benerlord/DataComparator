"""CompareResult and related data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    NULL_MISMATCH = "null_mismatch"


@dataclass(frozen=True)
class FieldError:
    row_key: dict[str, str]
    field: str
    kind: str  # "type_error" | "unit_error"
    original: str


@dataclass
class CompareResult:
    task_name: str
    left_name: str
    right_name: str

    left_total: int
    right_total: int
    matched_rows: int
    identical_rows: int
    diff_rows: int
    left_only: int
    right_only: int

    diff_details: pd.DataFrame
    left_only_rows: pd.DataFrame
    right_only_rows: pd.DataFrame

    engine_used: str
    duration_seconds: float
    errors: list[FieldError] = field(default_factory=list)

    def match_rate(self) -> float:
        total = self.left_total + self.right_total - self.matched_rows
        if total <= 0:
            return 0.0
        return self.identical_rows / total
