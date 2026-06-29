"""common/sheet_schema.py（旧sheets/uploader.py内の定数）の番犬テスト。

値そのものは変えていないが、配線変更後も意図した列構成が保持されていることを保証する。
"""

from common.sheet_schema import (
    BIB_COL,
    FORMAT1_HEADER,
    FORMAT2_HEADER,
    FORMAT3_RUN_COUNT,
    FORMAT_PRACTICE_SLOT,
    FORMAT_RUN_SLOTS,
    FORMAT_SHEET_NAME,
)


def test_bib_col_is_column_b():
    assert BIB_COL == 2


def test_format_run_slots_format1_has_two_runs():
    assert FORMAT_RUN_SLOTS["format1"] == [(7, 8, 9), (10, 11, 12)]


def test_format_run_slots_format3_has_fifteen_runs():
    assert len(FORMAT_RUN_SLOTS["format3"]) == 15
    assert FORMAT_RUN_SLOTS["format3"][0] == (5, 6, 7)


def test_format_practice_slot_only_format2():
    assert FORMAT_PRACTICE_SLOT == {"format2": (7, 8, 9)}


def test_format_sheet_name_defaults():
    assert FORMAT_SHEET_NAME["format1"] == "タイム表"
    assert FORMAT_SHEET_NAME["format3"] == "午前"


def test_format1_header_columns():
    assert FORMAT1_HEADER[:6] == ["順位", "ゼッケン", "氏名", "所属クラブ", "参加車両名", "車両形式"]


def test_format2_header_includes_practice_run():
    assert "練習走行" in FORMAT2_HEADER


def test_format3_run_count():
    assert FORMAT3_RUN_COUNT == 15
