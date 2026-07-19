"""In-memory pandas-based comparison engine."""
from __future__ import annotations
import time
from typing import Any
import pandas as pd
from datacompare.config.models import TaskConfig
from datacompare.sources.base import DataSource
from datacompare.normalize.pipeline import normalize_side
from datacompare.normalize.types import CoerceError
from datacompare.normalize.units import UnitError
from .base import CompareEngine
from .result import CompareResult, DiffType, FieldError
from datacompare.normalize.columns import field_canonical_name


def _values_equal(l: Any, r: Any) -> bool:
    if l is None and r is None:
        return True
    if l is None or r is None:
        return False
    if isinstance(l, (CoerceError, UnitError)) or isinstance(r, (CoerceError, UnitError)):
        return False
    return l == r


def _classify(l: Any, r: Any) -> str:
    if l is None or r is None:
        return DiffType.NULL_MISMATCH.value
    if isinstance(l, CoerceError) or isinstance(r, CoerceError):
        return DiffType.TYPE_ERROR.value
    if isinstance(l, UnitError) or isinstance(r, UnitError):
        return DiffType.UNIT_ERROR.value
    return DiffType.VALUE_MISMATCH.value


def _display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, CoerceError):
        return v.original
    if isinstance(v, UnitError):
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

        key_cols = [k.right for k in task.match.keys]
        field_cols = [field_canonical_name(f) for f in task.compare.fields]

        ldf = normalize_side(left_raw, task.match.keys, task.compare, side="left")
        rdf = normalize_side(right_raw, task.match.keys, task.compare, side="right")

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

        # field-level diffs
        diff_records: list[dict] = []
        errors: list[FieldError] = []
        identical_mask = pd.Series(True, index=both.index)

        for f in task.compare.fields:
            canonical = field_canonical_name(f)
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
                if isinstance(lv, (CoerceError, UnitError)):
                    kind = "type_error" if isinstance(lv, CoerceError) else "unit_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=lv.original,
                    ))
                if isinstance(rv, (CoerceError, UnitError)):
                    kind = "type_error" if isinstance(rv, CoerceError) else "unit_error"
                    errors.append(FieldError(
                        row_key={k: str(row[k]) for k in key_cols},
                        field=canonical, kind=kind, original=rv.original,
                    ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        diff_rows = matched_rows - identical_rows

        # build left_only / right_only DataFrames (use left-suffix / right-suffix cols)
        left_only_df = merged[left_only_mask][key_cols + [f"{c}__left" for c in field_cols]]
        left_only_df = left_only_df.rename(columns={f"{c}__left": c for c in field_cols})
        right_only_df = merged[right_only_mask][key_cols + [f"{c}__right" for c in field_cols]]
        right_only_df = right_only_df.rename(columns={f"{c}__right": c for c in field_cols})

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
