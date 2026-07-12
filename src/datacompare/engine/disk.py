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
from datacompare.sources.base import DataSource
from datacompare.normalize.pipeline import normalize_side
from datacompare.normalize.types import CoerceError
from datacompare.normalize.units import UnitError
from .base import CompareEngine
from .result import CompareResult, DiffType, FieldError


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
    if isinstance(v, (CoerceError, UnitError)):
        return v.original
    return str(v)


class DiskEngine(CompareEngine):
    def compare(self, left: DataSource, right: DataSource, task: TaskConfig) -> CompareResult:
        started = time.perf_counter()
        con = duckdb.connect()   # reserved for future SQL JOIN optimization
        key_cols = [k.right for k in task.match.keys]
        field_cols = [f.right for f in task.compare.fields]

        left_df = self._normalize_all(left, task, "left")
        right_df = self._normalize_all(right, task, "right")

        left_total = len(left_df)
        right_total = len(right_df)

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

        for f in task.compare.fields:
            lcol = f"{f.right}__left"
            rcol = f"{f.right}__right"
            for idx, row in both.iterrows():
                lv, rv = row[lcol], row[rcol]
                if not _values_equal(lv, rv):
                    identical_mask.at[idx] = False
                    diff_records.append({
                        **{k: row[k] for k in key_cols},
                        "field": f.right,
                        "left_value": _display(lv),
                        "right_value": _display(rv),
                        "diff_type": _classify(lv, rv),
                    })
                for side_v in (lv, rv):
                    if isinstance(side_v, CoerceError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=f.right, kind="type_error", original=side_v.original,
                        ))
                    elif isinstance(side_v, UnitError):
                        errors.append(FieldError(
                            row_key={k: str(row[k]) for k in key_cols},
                            field=f.right, kind="unit_error", original=side_v.original,
                        ))

        matched_rows = int(len(both))
        identical_rows = int(identical_mask.sum())
        diff_rows = matched_rows - identical_rows

        left_only_df = merged[left_only_mask][key_cols + [f"{c}__left" for c in field_cols]]
        left_only_df = left_only_df.rename(columns={f"{c}__left": c for c in field_cols})
        right_only_df = merged[right_only_mask][key_cols + [f"{c}__right" for c in field_cols]]
        right_only_df = right_only_df.rename(columns={f"{c}__right": c for c in field_cols})

        con.close()

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

    @staticmethod
    def _normalize_all(src: DataSource, task: TaskConfig, side: str) -> pd.DataFrame:
        chunks = []
        for chunk in src.read():
            chunks.append(normalize_side(chunk, task.match.keys, task.compare, side=side))
        if not chunks:
            return pd.DataFrame()
        return pd.concat(chunks, ignore_index=True)
