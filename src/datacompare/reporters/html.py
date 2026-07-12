"""HTML reporter using Jinja2 template."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from datacompare.engine.result import CompareResult
from .base import Reporter

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _df_to_html(df: pd.DataFrame, max_rows: int = 500) -> str:
    if df.empty:
        return "<p><em>(无)</em></p>"
    return df.head(max_rows).to_html(index=False, escape=True)


class HTMLReporter(Reporter):
    def render(self, result: CompareResult) -> Path:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("html_report.jinja2")
        html = template.render(
            result=result,
            include_charts=self.config.get("include_charts", True),
            diff_html=_df_to_html(result.diff_details),
            left_only_html=_df_to_html(result.left_only_rows),
            right_only_html=_df_to_html(result.right_only_rows),
        )
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out = self.output_dir / "report.html"
        out.write_text(html, encoding="utf-8")
        return out
