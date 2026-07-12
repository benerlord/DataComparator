import pytest
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from datacompare.sources.excel import ExcelSource
from datacompare.config.models import ExcelSourceConfig, SheetSelector

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "excel"


@pytest.fixture(scope="module", autouse=True)
def _make_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    # simple.xlsx: single sheet, header row 1
    wb = Workbook()
    ws = wb.active
    ws.append(["order_id", "amount", "region"])
    ws.append(["A001", "100.50", "North"])
    ws.append(["A002", "200.00", "South"])
    wb.save(FIXTURES / "simple.xlsx")
    # multi_sheet.xlsx: two sheets with same header
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "North"
    ws1.append(["order_id", "amount"])
    ws1.append(["A001", "100"])
    ws2 = wb.create_sheet("South")
    ws2.append(["order_id", "amount"])
    ws2.append(["B001", "200"])
    ws2.append(["B002", "300"])
    wb.save(FIXTURES / "multi_sheet.xlsx")
    # header_row2.xlsx: title in row 1, headers in row 2
    wb = Workbook()
    ws = wb.active
    ws.append(["Report", None])
    ws.append(["order_id", "amount"])
    ws.append(["X1", "50"])
    wb.save(FIXTURES / "header_row2.xlsx")
    yield


def test_columns_from_first_sheet():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    assert src.columns() == ["order_id", "amount", "region"]
    src.close()


def test_estimated_rows():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    assert src.estimated_rows() == 2
    src.close()


def test_read_returns_strings():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "simple.xlsx"))
    src = ExcelSource(cfg)
    chunks = list(src.read())
    assert len(chunks) == 1
    df = chunks[0]
    assert df.iloc[0]["order_id"] == "A001"
    assert df.iloc[0]["amount"] == "100.50"
    assert all(df.dtypes == "object")
    src.close()


def test_multi_sheet_by_name_concat():
    cfg = ExcelSourceConfig(
        path=str(FIXTURES / "multi_sheet.xlsx"),
        sheets=[SheetSelector(name="North"), SheetSelector(name="South")],
    )
    src = ExcelSource(cfg)
    df = pd.concat(src.read())
    assert len(df) == 3
    assert "__sheet__" in df.columns
    assert set(df["__sheet__"].unique()) == {"North", "South"}
    src.close()


def test_header_row_configurable():
    cfg = ExcelSourceConfig(path=str(FIXTURES / "header_row2.xlsx"), header_row=2)
    src = ExcelSource(cfg)
    assert src.columns() == ["order_id", "amount"]
    df = pd.concat(src.read())
    assert df.iloc[0]["order_id"] == "X1"
    src.close()


def test_multi_sheet_header_mismatch_raises(tmp_path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "A"
    ws1.append(["id", "amount"])
    ws1.append(["1", "100"])
    ws2 = wb.create_sheet("B")
    ws2.append(["id", "value"])   # mismatched header
    ws2.append(["2", "200"])
    p = tmp_path / "mismatch.xlsx"
    wb.save(p)
    cfg = ExcelSourceConfig(
        path=str(p),
        sheets=[SheetSelector(name="A"), SheetSelector(name="B")],
    )
    src = ExcelSource(cfg)
    with pytest.raises(Exception, match="header"):
        src.columns()
    src.close()
