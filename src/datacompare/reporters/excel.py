"""Excel reporter using XlsxWriter."""
from __future__ import annotations
from pathlib import Path
import xlsxwriter
from datacompare.engine.result import CompareResult
from .base import Reporter


class ExcelReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.xlsx"
        wb = xlsxwriter.Workbook(str(out))

        title = wb.add_format({"bold": True, "font_size": 14})
        header = wb.add_format({"bold": True, "bg_color": "#f0f4f8", "border": 1})
        diff_fmt = wb.add_format({"bg_color": "#fff9e6"})
        error_fmt = wb.add_format({"bg_color": "#ffe4e4"})

        # Summary
        ws = wb.add_worksheet("摘要")
        ws.write("A1", result.task_name, title)
        rows = [
            ("左侧数据源", result.left_name),
            ("右侧数据源", result.right_name),
            ("引擎", result.engine_used),
            ("耗时 (秒)", round(result.duration_seconds, 2)),
            ("匹配率", round(result.match_rate() * 100, 2)),
            ("完全一致行", result.identical_rows),
            ("字段差异行", result.diff_rows),
            ("左侧独有行", result.left_only),
            ("右侧独有行", result.right_only),
            ("字段错误数", len(result.errors)),
        ]
        for i, (k, v) in enumerate(rows, start=3):
            ws.write(f"A{i}", k, header)
            ws.write(f"B{i}", v)

        # Diff details
        ws = wb.add_worksheet("字段差异")
        cols = list(result.diff_details.columns) or ["(空)"]
        for j, c in enumerate(cols):
            ws.write(0, j, str(c), header)
        for i, row in enumerate(result.diff_details.itertuples(index=False), start=1):
            diff_type = getattr(row, "diff_type", None)
            fmt = None
            if self.config.get("highlight_diff_cells"):
                if diff_type in ("type_error", "unit_error"):
                    fmt = error_fmt
                elif diff_type is not None:
                    fmt = diff_fmt
            for j, val in enumerate(row):
                if fmt:
                    ws.write(i, j, "" if val is None else str(val), fmt)
                else:
                    ws.write(i, j, "" if val is None else str(val))

        # Left-only / Right-only
        for sheet_name, df in [
            ("左侧独有", result.left_only_rows),
            ("右侧独有", result.right_only_rows),
        ]:
            ws = wb.add_worksheet(sheet_name)
            cols = list(df.columns) or ["(空)"]
            for j, c in enumerate(cols):
                ws.write(0, j, str(c), header)
            for i, row in enumerate(df.itertuples(index=False), start=1):
                for j, val in enumerate(row):
                    ws.write(i, j, "" if val is None else str(val))

        wb.close()
        return out
