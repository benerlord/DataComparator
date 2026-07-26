"""DuckDB-backed disk comparison engine.

MVP note: v0.1 uses pandas outer-join for correctness parity with InMemoryEngine.
Real DuckDB SQL JOIN with sentinel serialization is a v1.0 optimization (see plan §Known Deviations).
"""
from __future__ import annotations
import time
from typing import Any
import duckdb
import pandas as pd
from datacompare.config.models import TaskConfig
from datacompare.config.errors import ConfigError
from datacompare.sources.base import DataSource
from datacompare.normalize.pipeline import normalize_side
from datacompare.normalize.types import CoerceError
from datacompare.normalize.units import UnitError
from datacompare.normalize.regex_errors import RegexError
from .base import CompareEngine
from .result import CompareResult, DiffType, FieldError
from ._field_missing import _build_field_missing_record, merged_col_name
from datacompare.normalize.columns import field_canonical_name, key_canonical_name


def _values_equal(l: Any, r: Any) -> bool:
    if l is None and r is None:
        return True
    if l is None or r is None:
        return False
    if isinstance(l, (CoerceError, UnitError, RegexError)) or isinstance(r, (CoerceError, UnitError, RegexError)):
        return False
    return l == r


def _classify(l: Any, r: Any) -> str:
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    if isinstance(l, RegexError) or isinstance(r, RegexError):
        return DiffType.REGEX_ERROR.value
    return DiffType.VALUE_MISMATCH.value


def _display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (CoerceError, UnitError, RegexError)):
        return v.original
    return str(v)


class DiskEngine(CompareEngine):
    def compare(self, left: DataSource, right: DataSource, task: TaskConfig) -> CompareResult:
        started = time.perf_counter()
        con = duckdb.connect()   # reserved for future SQL JOIN optimization
        try:
            key_cols = [key_canonical_name(k) for k in task.match.keys]
            field_cols = [field_canonical_name(f) for f in task.compare.fields]

            left_df, left_missing = self._normalize_all(left, task, "left")
            right_df, right_missing = self._normalize_all(right, task, "right")

            left_total = len(left_df)
            right_total = len(right_df)

            # v0.8: 双侧同 field 缺 → 硬失败
            both_missing = left_missing & right_missing
            if both_missing:
                raise ConfigError(
                    f"compare fields not found in either source: {sorted(both_missing)}",
                    path="compare.fields",
                    suggestion=(
                        f"available left={list(left_df.columns)}, "
                        f"available right={list(right_df.columns)}"
                    ),
                )

            for label, df in (("left", left_df), ("right", right_df)):
                dupes = df[df.duplicated(subset=key_cols, keep=False)]
                if not dupes.empty:
                    keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                    raise ValueError(f"duplicate keys in {label} side: {keys_display}")

            merged = left_df.merge(
                right_df, on=key_cols, how="outer", indicator=True,
                suffixes=("__left", "__right"),
            )
            both = merged[merged["_merge"] == "both"]
            left_only_mask = merged["_merge"] == "left_only"
            right_only_mask = merged["_merge"] == "right_only"

            diff_records: list[dict] = []
            errors: list[FieldError] = []
            identical_mask = pd.Series(True, index=both.index)
            summary_missing_count = 0

            for f in task.compare.fields:
                canonical = field_canonical_name(f)
                # v0.8: 单侧缺 → 追加一条汇总记录，跳过 per-row
                if canonical in left_missing:
                    diff_records.append(_build_field_missing_record(
                        field_canonical=canonical, side_missing="left",
                        key_cols=key_cols, other_side_row_count=right_total,
                    ))
                    summary_missing_count += 1
                    continue
                if canonical in right_missing:
                    diff_records.append(_build_field_missing_record(
                        field_canonical=canonical, side_missing="right",
                        key_cols=key_cols, other_side_row_count=left_total,
                    ))
                    summary_missing_count += 1
                    continue

                lcol = f"{canonical}__left"
                rcol = f"{canonical}__right"
                for idx, row in both.iterrows():
                    lv, rv = row[lcol], row[rcol]
                    if not _values_equal(lv, rv):
                        identical_mask.at[idx] = False
                        diff_records.append({
                            **{k: row[k] for k in key_cols},
                            "field": canonical,
                            "left_value": _display(lv),
                            "right_value": _display(rv),
                            "diff_type": _classify(lv, rv),
                        })
                    for side_v in (lv, rv):
                        if isinstance(side_v, CoerceError):
                            errors.append(FieldError(
                                row_key={k: str(row[k]) for k in key_cols},
                                field=canonical, kind="type_error", original=side_v.original,
                            ))
                        elif isinstance(side_v, UnitError):
                            errors.append(FieldError(
                                row_key={k: str(row[k]) for k in key_cols},
                                field=canonical, kind="unit_error", original=side_v.original,
                            ))
                        elif isinstance(side_v, RegexError):
                            errors.append(FieldError(
                                row_key={k: str(row[k]) for k in key_cols},
                                field=canonical, kind="regex_error", original=side_v.original,
                            ))

            matched_rows = int(len(both))
            identical_rows = int(identical_mask.sum())
            diff_rows = (matched_rows - identical_rows) + summary_missing_count

            # v0.8: left_only_rows / right_only_rows 补齐缺列，schema 齐整
            left_only_raw = merged[left_only_mask].copy()
            left_only_df = left_only_raw[key_cols].copy()
            for c in field_cols:
                if c in left_missing:
                    left_only_df[c] = "字段不存在"
                else:
                    merged_col = merged_col_name(c, "left", left_missing, right_missing)
                    left_only_df[c] = left_only_raw[merged_col].values

            right_only_raw = merged[right_only_mask].copy()
            right_only_df = right_only_raw[key_cols].copy()
            for c in field_cols:
                if c in right_missing:
                    right_only_df[c] = "字段不存在"
                else:
                    merged_col = merged_col_name(c, "right", left_missing, right_missing)
                    right_only_df[c] = right_only_raw[merged_col].values

            return CompareResult(
                task_name=task.name,
                left_name=left.name, right_name=right.name,
                left_total=left_total, right_total=right_total,
                matched_rows=matched_rows, identical_rows=identical_rows, diff_rows=diff_rows,
                left_only=int(left_only_mask.sum()), right_only=int(right_only_mask.sum()),
                diff_details=pd.DataFrame(diff_records),
                left_only_rows=left_only_df, right_only_rows=right_only_df,
                engine_used="disk", duration_seconds=time.perf_counter() - started,
                errors=errors,
            )
        finally:
            con.close()

    @staticmethod
    def _normalize_all(src: DataSource, task: TaskConfig, side: str) -> tuple[pd.DataFrame, frozenset[str]]:
        """Concatenate all chunks' normalized DataFrames + return the (chunk-invariant)
        missing_field_canonicals. Missing set is derived from task config and thus
        identical across chunks."""
        dfs: list[pd.DataFrame] = []
        missing: frozenset[str] = frozenset()
        for chunk in src.read():
            side_result = normalize_side(chunk, task.match.keys, task.compare, side=side)
            dfs.append(side_result.df)
            missing = side_result.missing_field_canonicals
        if not dfs:
            return pd.DataFrame(), missing
        return pd.concat(dfs, ignore_index=True), missing
