import pandas as pd
from datacompare.reporters.console import ConsoleReporter
from datacompare.engine.result import CompareResult


def test_console_returns_none_and_prints(capsys):
    result = CompareResult(
        task_name="Sales Check", left_name="left.xlsx", right_name="prod.db",
        left_total=100, right_total=100,
        matched_rows=95, identical_rows=90, diff_rows=5,
        left_only=5, right_only=5,
        diff_details=pd.DataFrame(),
        left_only_rows=pd.DataFrame(),
        right_only_rows=pd.DataFrame(),
        engine_used="memory", duration_seconds=1.2, errors=[],
    )
    reporter = ConsoleReporter({}, None)
    assert reporter.render(result) is None
    captured = capsys.readouterr()
    assert "Sales Check" in captured.out
    assert "95" in captured.out or "5" in captured.out
