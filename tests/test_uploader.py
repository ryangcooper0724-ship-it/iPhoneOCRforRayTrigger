"""sheets/uploader.pyの振る舞いを保証する番犬テスト。

FORMAT_RUN_SLOTS/BIB_COLを共通モジュールへ移す配線変更の前後で、
write_to_sheetが「同じセルに同じ値を書く」ことを保証する。
実際のGoogle Sheets APIは呼ばず、gspreadのインターフェースだけ真似たフェイクを使う。
"""

import pytest

from sheets.uploader import write_result, write_to_sheet, FORMAT_RUN_SLOTS, BIB_COL


class FakeCell:
    def __init__(self, row):
        self.row = row


class FakeWorksheet:
    def __init__(self, title, row_count=50):
        self.title = title
        self.row_count = row_count
        self._cells: dict[tuple[int, int], str] = {}
        self.updates: list[tuple[int, int, object]] = []

    def find(self, value, in_column):
        for (row, col), v in self._cells.items():
            if col == in_column and v == value:
                return FakeCell(row)
        return None

    def col_values(self, col):
        max_row = max([row for (row, c) in self._cells if c == col], default=0)
        return [self._cells.get((r, col), "") for r in range(1, max_row + 1)]

    def cell(self, row, col):
        class _V:
            def __init__(self, value):
                self.value = value
        return _V(self._cells.get((row, col), ""))

    def update_cell(self, row, col, value):
        self._cells[(row, col)] = value
        self.updates.append((row, col, value))


class FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = {w.title: w for w in worksheets}

    def worksheet(self, title):
        return self._worksheets[title]


class FakeClient:
    def __init__(self, spreadsheet):
        self._spreadsheet = spreadsheet

    def open_by_key(self, spreadsheet_id):
        return self._spreadsheet


def make_client_with_bib_registered(sheet_title="タイム表", bib=12, bib_row=2):
    ws = FakeWorksheet(sheet_title)
    ws._cells[(bib_row, BIB_COL)] = str(bib)
    return FakeClient(FakeSpreadsheet([ws])), ws


def test_write_to_sheet_writes_first_open_slot_for_format1():
    client, ws = make_client_with_bib_registered()
    write_to_sheet(client, "sheet-id", 12, 73.123, pt_count=1, datsurin_count=0, format="format1")

    run_col, pt_col, ds_col = FORMAT_RUN_SLOTS["format1"][0]
    assert ws._cells[(2, run_col)] == pytest.approx(73.123 / 86400)
    assert ws._cells[(2, pt_col)] == 1
    assert ws._cells[(2, ds_col)] == ""


def test_write_to_sheet_second_call_fills_next_slot():
    client, ws = make_client_with_bib_registered()
    write_to_sheet(client, "sheet-id", 12, 73.123, format="format1")
    write_to_sheet(client, "sheet-id", 12, 60.0, format="format1")

    slot0 = FORMAT_RUN_SLOTS["format1"][0]
    slot1 = FORMAT_RUN_SLOTS["format1"][1]
    assert ws._cells[(2, slot0[0])] == pytest.approx(73.123 / 86400)
    assert ws._cells[(2, slot1[0])] == pytest.approx(60.0 / 86400)


def test_write_to_sheet_explicit_slot_index_overwrites():
    client, ws = make_client_with_bib_registered()
    write_to_sheet(client, "sheet-id", 12, 73.123, format="format1", slot_index=1)

    slot1 = FORMAT_RUN_SLOTS["format1"][1]
    assert ws._cells[(2, slot1[0])] == pytest.approx(73.123 / 86400)
    slot0 = FORMAT_RUN_SLOTS["format1"][0]
    assert (2, slot0[0]) not in ws._cells


def test_write_to_sheet_registers_new_bib_row():
    ws = FakeWorksheet("タイム表")
    client = FakeClient(FakeSpreadsheet([ws]))
    write_to_sheet(client, "sheet-id", 99, 50.0, format="format1")

    assert ws._cells[(1, BIB_COL)] == 99  # 1行目（ヘッダー無し前提）に新規登録


def test_write_to_sheet_dnf_writes_string_and_clears_counts():
    from common.time_format import DNF_SECONDS
    client, ws = make_client_with_bib_registered()
    write_to_sheet(client, "sheet-id", 12, DNF_SECONDS, pt_count=2, format="format1")

    run_col, pt_col, ds_col = FORMAT_RUN_SLOTS["format1"][0]
    assert ws._cells[(2, run_col)] == "DNF"
    assert ws._cells[(2, pt_col)] == ""
    assert ws._cells[(2, ds_col)] == ""


def test_write_result_returns_false_on_exception():
    client, ws = make_client_with_bib_registered()
    ok, message = write_result(client, "sheet-id", 12, 73.123, format="format1", slot_index=99)
    assert ok is False
    assert "超えています" in message


def test_write_result_returns_true_on_success():
    client, ws = make_client_with_bib_registered()
    ok, message = write_result(client, "sheet-id", 12, 73.123, format="format1")
    assert ok is True
