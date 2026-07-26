"""CompareResult and related data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    REGEX_ERROR = "regex_error"
    NULL_MISMATCH = "null_mismatch"
    FIELD_MISSING = "field_missing"


@dataclass(frozen=True)
class FieldError:
    row_key: dict[str, str]
    field: str
    kind: str  # "type_error" | "unit_error"
    original: str


@dataclass
class CompareResult:
    """Result of one comparison run.

    Note on `diff_rows` (v0.8+): includes both per-row value diffs AND
    field-missing summary records (one per field absent on exactly one
    side). This means `diff_rows` may exceed `matched_rows` when many
    fields are missing on one side — this is deliberate, structural
    diffs count as diffs even though they aren't tied to a specific row.
    """
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


from typing import Literal


@dataclass
class SubTaskResult:
    task_name: str
    status: Literal["success", "failed", "skipped"]
    comparison_result: "CompareResult | None"
    error: Exception | None
    duration_ms: int

    @property
    def is_success(self) -> bool:
        return self.status == "success"


@dataclass
class BatchResult:
    batch_name: str
    task_results: list[SubTaskResult]
    total_duration_ms: int

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.task_results if r.status == "skipped")

    def compute_exit_code(self, fail_on_diff: bool) -> int:
        """Priority: 2 (runtime error) > 10 (diff+fail_on_diff) > 1 (config error) > 0."""
        from datacompare.config.errors import ConfigError
        has_runtime_error = False
        has_config_error = False
        has_diff = False
        for r in self.task_results:
            if r.status == "failed":
                if isinstance(r.error, ConfigError):
                    has_config_error = True
                else:
                    has_runtime_error = True
            elif r.status == "success" and r.comparison_result is not None:
                cr = r.comparison_result
                if cr.diff_rows > 0 or cr.left_only > 0 or cr.right_only > 0:
                    has_diff = True
        if has_runtime_error:
            return 2
        if fail_on_diff and has_diff:
            return 10
        if has_config_error:
            return 1
        return 0
