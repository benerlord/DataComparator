from datacompare.engine._field_missing import _build_field_missing_record


def test_build_record_left_missing():
    record = _build_field_missing_record(
        field_canonical="vmemorys",
        side_missing="left",
        key_cols=["id", "reId"],
        other_side_row_count=10000,
    )
    assert record == {
        "id": "",
        "reId": "",
        "field": "vmemorys",
        "left_value": "字段不存在",
        "right_value": "(右侧 10000 行有值)",
        "diff_type": "field_missing",
    }


def test_build_record_right_missing():
    record = _build_field_missing_record(
        field_canonical="hostname",
        side_missing="right",
        key_cols=["id"],
        other_side_row_count=500,
    )
    assert record == {
        "id": "",
        "field": "hostname",
        "left_value": "(左侧 500 行有值)",
        "right_value": "字段不存在",
        "diff_type": "field_missing",
    }


def test_build_record_no_key_cols():
    record = _build_field_missing_record(
        field_canonical="x",
        side_missing="left",
        key_cols=[],
        other_side_row_count=1,
    )
    assert record == {
        "field": "x",
        "left_value": "字段不存在",
        "right_value": "(右侧 1 行有值)",
        "diff_type": "field_missing",
    }
