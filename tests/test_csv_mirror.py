"""storage/csv_mirror.pyの振る舞いを保証する番犬テスト。

storage層がsheets層に依存する配線（FORMAT_RUN_SLOTS/BIB_COLのimport元）を
リファクタリングする予定だが、出力されるCSVの内容自体は変わらないことを保証する。
"""

import csv

from storage import csv_mirror


def test_create_history_csv_writes_header_once(tmp_path):
    path = tmp_path / "history.csv"
    csv_mirror.create_history_csv(str(path))
    csv_mirror.create_history_csv(str(path))  # 2回目は上書きしない

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows == [["ゼッケン", "生タイム", "タイム", "ペナルティ", "日時"]]


def test_append_history_row_appends_in_order(tmp_path):
    path = tmp_path / "history.csv"
    csv_mirror.append_history_row(str(path), "12", "1:03.500", "1:08.500", "PT1", "2026-06-29 10:00:00")
    csv_mirror.append_history_row(str(path), "34", "0:55.000", "0:55.000", "", "2026-06-29 10:05:00")

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["ゼッケン", "生タイム", "タイム", "ペナルティ", "日時"]
    assert rows[1] == ["12", "1:03.500", "1:08.500", "PT1", "2026-06-29 10:00:00"]
    assert rows[2] == ["34", "0:55.000", "0:55.000", "", "2026-06-29 10:05:00"]


def test_sheet_mirror_path_for_no_sheet_name_returns_base():
    assert csv_mirror.sheet_mirror_path_for("foo/bar.csv", None) == "foo/bar.csv"
    assert csv_mirror.sheet_mirror_path_for("foo/bar.csv", "") == "foo/bar.csv"


def test_sheet_mirror_path_for_inserts_suffix():
    assert csv_mirror.sheet_mirror_path_for("foo/bar.csv", "午前") == "foo/bar_午前.csv"


def test_sheet_mirror_header_format1_matches_template():
    from sheets import template_setup
    assert csv_mirror.sheet_mirror_header("format1") == list(template_setup.FORMAT1_HEADER)


def test_sheet_mirror_header_format3_has_run_columns():
    from sheets import template_setup
    header = csv_mirror.sheet_mirror_header("format3")
    assert header[:4] == ["順位", "ゼッケン", "氏名", "車両形式"]
    assert len(header) == 4 + template_setup.FORMAT3_RUN_COUNT * 3
    assert header[4:7] == ["1本目", "P", "D"]


def test_update_sheet_mirror_writes_bib_and_first_slot(tmp_path):
    path = tmp_path / "mirror.csv"
    csv_mirror.create_sheet_mirror_csv(str(path), "format1")
    csv_mirror.update_sheet_mirror(str(path), "format1", "12", 0, 73.123, 1, 0)

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    row = rows[1]
    assert row[header.index("ゼッケン")] == "12"
    # format1の1本目はFORMAT_RUN_SLOTS["format1"][0] == (7, 8, 9) -> 列インデックス6,7,8
    assert row[6] == "1:13.123"
    assert row[7] == "1"
    assert row[8] == ""


def test_update_sheet_mirror_second_call_updates_second_slot(tmp_path):
    path = tmp_path / "mirror.csv"
    csv_mirror.create_sheet_mirror_csv(str(path), "format1")
    csv_mirror.update_sheet_mirror(str(path), "format1", "12", 0, 73.123, 0, 0)
    csv_mirror.update_sheet_mirror(str(path), "format1", "12", 1, 60.0, 0, 1)

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    row = rows[1]
    # format1の2本目はFORMAT_RUN_SLOTS["format1"][1] == (10, 11, 12) -> 列インデックス9,10,11
    assert row[6] == "1:13.123"
    assert row[9] == "1:00.000"
    assert row[11] == "1"


def test_update_sheet_mirror_dnf_string_value(tmp_path):
    path = tmp_path / "mirror.csv"
    csv_mirror.create_sheet_mirror_csv(str(path), "format1")
    csv_mirror.update_sheet_mirror(str(path), "format1", "5", 0, "DNF", 0, 0)

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[1][6] == "DNF"


def test_update_sheet_mirror_out_of_range_slot_is_noop(tmp_path):
    path = tmp_path / "mirror.csv"
    csv_mirror.create_sheet_mirror_csv(str(path), "format1")
    csv_mirror.update_sheet_mirror(str(path), "format1", "5", 99, 1.0, 0, 0)

    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1  # ヘッダーのみ、データ行は追加されない
