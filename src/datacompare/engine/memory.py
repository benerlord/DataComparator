"""In-memory pandas-based comparison engine."""
from __future__ import annotations
import time
from typing import Any
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
from ._field_missing import _build_field_missing_record
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


class InMemoryEngine(CompareEngine):
    def compare(
        self, left: DataSource, right: DataSource, task: TaskConfig,
    ) -> CompareResult:
        started = time.perf_counter()
        left_raw = pd.concat(list(left.read()), ignore_index=True)
        right_raw = pd.concat(list(right.read()), ignore_index=True)

        left_total = len(left_raw)
        right_total = len(right_raw)

        key_cols = [key_canonical_name(k) for k in task.match.keys]
        field_cols = [field_canonical_name(f) for f in task.compare.fields]

        left_side = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        right_side = normalize_side(right_raw, task.match.keys, task.compare, side="right")
        ldf = left_side.df
        rdf = right_side.df

        # v0.8: 双侧同 field 缺 → 硬失败
        both_missing = left_side.missing_field_canonicals & right_side.missing_field_canonicals
        if both_missing:
            raise ConfigError(
                f"compare fields not found in either source: {sorted(both_missing)}",
                path="compare.fields",
                suggestion=(
                    f"available left={list(left_raw.columns)}, "
                    f"available right={list(right_raw.columns)}"
                ),
            )

        # duplicate key check
        for label, df in (("left", ldf), ("right", rdf)):
            dupes = df[df.duplicated(subset=key_cols, keep=False)]
            if not dupes.empty:
                keys_display = dupes[key_cols].drop_duplicates().head(10).to_dict(orient="records")
                raise ValueError(f"duplicate keys in {label} side: {keys_display}")

        merged = ldf.merge(
            rdf, on=key_cols, how="outer", indicator=True,
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
            if canonical in left_side.missing_field_canonicals:
                diff_records.append(_build_field_missing_record(
                    field_canonical=canonical, side_missing="left",
                    key_cols=key_cols, other_side_row_count=right_total,
                ))
                summary_missing_count += 1
                continue
            if canonical in right_side.missing_field_canonicals:
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
                if isinstance(lv, (CoerceError, UnitError, RegexError)):
                    if isinstance(lv, CoerceError):
                        kind = "type_error"
                    elif isinstance(lv, UnitError):
                        kind = "unit_error"
                    else:
                        kind = "regex_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=lv.original,
                    ))
                if isinstance(rv, (CoerceError, UnitError, RegexError)):
                    if isinstance(rv, CoerceError):
                        kind = "type_error"
                    elif isinstance(rv, UnitError):
                        kind = "unit_error"
                    else:
                        kind = "regex_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=rv.original,
                    ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        # v0.8: 汇总记录也计入 diff_rows；identical_rows 只受 per-row 影响
        diff_rows = (matched_rows - identical_rows) + summary_missing_count

        # v0.8: left_only_rows / right_only_rows 补齐缺列，schema 齐整
        # pandas outer-join 只在两侧都有同名列时才加后缀；单侧列保留原名。
        # 单侧存在列的 merged 列名规则：
        #   col exists on both sides  → {c}__left / {c}__right
        #   col exists only on left   → bare {c}  (from left side)
        #   col exists only on right  → bare {c}  (from right side)

        def _merged_col_name(canonical: str, side: str) -> str:
            on_left = canonical not in left_side.missing_field_canonicals
            on_right = canonical not in right_side.missing_field_canonicals
            if on_left and on_right:
                return f"{canonical}__{side}"
            # single-side: pandas kept the bare name
            return canonical

        left_only_raw = merged[left_only_mask].copy()
        left_only_df = left_only_raw[key_cols].copy()
        for c in field_cols:
            if c in left_side.missing_field_canonicals:
                left_only_df[c] = "字段不存在"
            else:
                merged_col = _merged_col_name(c, "left")
                left_only_df[c] = left_only_raw[merged_col].values

        right_only_raw = merged[right_only_mask].copy()
        right_only_df = right_only_raw[key_cols].copy()
        for c in field_cols:
            if c in right_side.missing_field_canonicals:
                right_only_df[c] = "字段不存在"
            else:
                merged_col = _merged_col_name(c, "right")
                right_only_df[c] = right_only_raw[merged_col].values

        diff_df = pd.DataFrame(diff_records)

        return CompareResult(
            task_name=task.name,
            left_name=left.name,
            right_name=right.name,
            left_total=left_total,
            right_total=right_total,
            matched_rows=matched_rows,
            identical_rows=identical_rows,
            diff_rows=diff_rows,
            left_only=int(left_only_mask.sum()),
            right_only=int(right_only_mask.sum()),
            diff_details=diff_df,
            left_only_rows=left_only_df,
            right_only_rows=right_only_df,
            engine_used="memory",
            duration_seconds=time.perf_counter() - started,
            errors=errors,
        )
