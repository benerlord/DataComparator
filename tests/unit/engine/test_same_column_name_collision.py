"""Regression guard: when left and right have same-named compare fields,
pandas' __left/__right suffixes are internal and the diff report exposes
clean left_value/right_value columns.

Anchored via engine.memory.InMemoryEngine; parity holds for DiskEngine per
tests/engine/test_parity.py.
"""
from pathlib import Path
import pandas as pd
from openpyxl import Workbook

from datacompare.config.models import (
    TaskConfig, ExcelSourceConfig, MatchConfig, KeyMapping,
    CompareConfig, CompareDefaults, FieldRule, OutputConfig,
)
from datacompare.engine.memory import InMemoryEngine
from datacompare.sources.excel import ExcelSource


def _xlsx(path: Path, rows):
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    wb.save(path)


def test_same_column_name_on_both_sides_produces_clean_diff_report(tmp_path):
    """Both sides have ID and amount columns; join key is order_no; ID and
    amount are compare fields on both sides with identical names."""
    _xlsx(tmp_path / "left.xlsx", [
        ["order_no", "ID", "amount"],
        ["ORD1", "100", "1.00"],
        ["ORD2", "200", "2.00"],
        ["ORD3", "300", "3.00"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["order_no", "ID", "amount"],
        ["ORD1", "100", "1.00"],   # identical
        ["ORD2", "999", "2.00"],   # ID differs
        ["ORD3", "300", "3.99"],   # amount differs
    ])

    task = TaskConfig(
        name="collision_test",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(left="order_no", right="order_no")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[
                FieldRule(left="ID", right="ID"),
                FieldRule(left="amount", right="amount",
                          mode="numeric", decimal_places=2),
            ],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    assert result.matched_rows == 3
    assert result.identical_rows == 1
    assert result.diff_rows == 2

    # Diff details must expose clean column names, not pandas __left/__right.
    cols = set(result.diff_details.columns)
    assert "left_value" in cols
    assert "right_value" in cols
    assert "field" in cols
    # No leaked internal suffixes:
    assert not any(c.endswith("__left") or c.endswith("__right") for c in cols)

    # Both same-named fields appear as diffs.
    diff_fields = set(result.diff_details["field"])
    assert diff_fields == {"ID", "amount"}


def test_right_literal_field_end_to_end_via_engine(tmp_path):
    """Regression: `right_literal` must be usable end-to-end through the
    engine (not just normalize_side). Prior to the field_canonical_name
    refactor, engine's `f.right` uses produced None-named columns."""
    _xlsx(tmp_path / "left.xlsx", [
        ["id", "status"],
        ["r1", "active"],
        ["r2", "inactive"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["id"],
        ["r1"],
        ["r2"],
    ])

    task = TaskConfig(
        name="right_literal_e2e",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(left="status", right_literal="active")],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    assert result.matched_rows == 2
    assert result.identical_rows == 1  # r1 (status=active matches literal)
    assert result.diff_rows == 1       # r2 (status=inactive != active)
    diff_fields = set(result.diff_details["field"])
    assert diff_fields == {"status"}   # canonical name from f.left, not None


def test_key_alias_and_field_regex_end_to_end(tmp_path):
    """End-to-end regression: right's 'name' column serves as both join key
    (regex to extract ID suffix, alias=join_id) and compare field (regex to
    extract name prefix). Left has real 'id' and 'name' columns."""
    _xlsx(tmp_path / "left.xlsx", [
        ["id", "name"],
        ["1", "Alice"],
        ["2", "Bob"],
        ["3", "Carol"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["name"],
        ["Alice@@1"],
        ["Bob@@2"],
        ["Different@@3"],
    ])

    task = TaskConfig(
        name="key_alias_field_regex_e2e",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(
            left="id", right="name",
            right_regex=r".*@@(.*)", alias="join_id",
        )]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(
                left="name", right="name",
                right_regex=r"(.*)@@.*",
            )],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    assert result.matched_rows == 3
    assert result.identical_rows == 2
    assert result.diff_rows == 1
    diff_fields = set(result.diff_details["field"])
    assert diff_fields == {"name"}


def test_field_regex_mismatch_reports_as_regex_error(tmp_path):
    """Row 1: left='A', right='A@@X' → regex extract 'A' → identical.
    Row 2: left='B', right='no_at_at' → regex mismatch → RegexError → diff (regex_error).
    """
    _xlsx(tmp_path / "left.xlsx", [
        ["id", "code"],
        ["1", "A"],
        ["2", "B"],
    ])
    _xlsx(tmp_path / "right.xlsx", [
        ["id", "code"],
        ["1", "A@@X"],
        ["2", "no_at_at"],
    ])

    task = TaskConfig(
        name="field_regex_soft_fail_e2e",
        sources={
            "left": ExcelSourceConfig(path=str(tmp_path / "left.xlsx")),
            "right": ExcelSourceConfig(path=str(tmp_path / "right.xlsx")),
        },
        match=MatchConfig(keys=[KeyMapping(left="id", right="id")]),
        compare=CompareConfig(
            defaults=CompareDefaults(),
            fields=[FieldRule(left="code", right="code",
                              right_regex=r"(.*)@@.*")],
        ),
        output=OutputConfig(dir=str(tmp_path / "out"), formats=["json"]),
    )
    left = ExcelSource(task.sources["left"], name="left")
    right = ExcelSource(task.sources["right"], name="right")
    try:
        result = InMemoryEngine().compare(left, right, task)
    finally:
        left.close(); right.close()

    assert result.matched_rows == 2
    assert result.identical_rows == 1
    assert result.diff_rows == 1
    diff_types = set(result.diff_details["diff_type"])
    assert "regex_error" in diff_types
