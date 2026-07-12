"""CSV reporter: writes separate files per data section."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datacompare.engine.result import CompareResult
from .base import Reporter


class CSVReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        assert self.output_dir is not None
        target = self.output_dir / "csv"
        target.mkdir(parents=True, exist_ok=True)

        result.diff_details.to_csv(target / "diff_details.csv", index=False, encoding="utf-8-sig")
        result.left_only_rows.to_csv(target / "left_only.csv", index=False, encoding="utf-8-sig")
        result.right_only_rows.to_csv(target / "right_only.csv", index=False, encoding="utf-8-sig")

        summary = pd.DataFrame([{
            "task_name": result.task_name,
            "left_total": result.left_total,
            "right_total": result.right_total,
            "matched_rows": result.matched_rows,
            "identical_rows": result.identical_rows,
            "diff_rows": result.diff_rows,
            "left_only": result.left_only,
            "right_only": result.right_only,
            "match_rate": round(result.match_rate(), 4),
            "engine_used": result.engine_used,
            "duration_seconds": round(result.duration_seconds, 3),
            "errors": len(result.errors),
        }])
        summary.to_csv(target / "summary.csv", index=False, encoding="utf-8-sig")
        return target
