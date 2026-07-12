"""JSON reporter with truncation for large detail sets."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from datacompare.engine.result import CompareResult
from .base import Reporter


def _df_records(df: pd.DataFrame, limit: int) -> tuple[list[dict], bool]:
    if len(df) <= limit:
        return df.to_dict(orient="records"), False
    return df.head(limit).to_dict(orient="records"), True


class JSONReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        limit = self.config.get("truncate_details_over", 10_000)
        diff_records, t1 = _df_records(result.diff_details, limit)
        left_records, t2 = _df_records(result.left_only_rows, limit)
        right_records, t3 = _df_records(result.right_only_rows, limit)

        payload = {
            "task": result.task_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "left": {"name": result.left_name, "total": result.left_total},
            "right": {"name": result.right_name, "total": result.right_total},
            "summary": {
                "matched": result.matched_rows,
                "identical": result.identical_rows,
                "diff": result.diff_rows,
                "left_only": result.left_only,
                "right_only": result.right_only,
                "match_rate": result.match_rate(),
            },
            "diff_details": diff_records,
            "left_only": left_records,
            "right_only": right_records,
            "errors": [
                {"row_key": e.row_key, "field": e.field, "kind": e.kind, "original": e.original}
                for e in result.errors
            ],
            "engine": result.engine_used,
            "duration_seconds": result.duration_seconds,
            "truncated": t1 or t2 or t3,
        }
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        return out
