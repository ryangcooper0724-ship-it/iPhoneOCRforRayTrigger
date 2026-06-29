"""タイム書き込み: Sheetsの「タイム表」（または午前/午後）へリアルタイムに書き込む。

ローカルCSVへの自動書き出しはstorage/csv_mirror.pyが担当する（main.py側で
local_storeへの保存と合わせて呼ぶ）。このモジュールはSheets側の書き込みのみ。
"""

import threading
from typing import Callable

import gspread

from sheets.formatter import is_dnf, is_mc

BIB_COL = 2  # B列: ゼッケン（全フォーマット共通）

# フォーマットごとの (タイム列, P列, D列) の並び（1始まり）。template_setup.pyの列構成と対応している。
# 「通常の本数」として扱う列のみ。format2の練習走行は別途FORMAT_PRACTICE_SLOTで扱う。
FORMAT_RUN_SLOTS: dict[str, list[tuple[int, int, int]]] = {
    "format1": [(7, 8, 9), (10, 11, 12)],
    "format2": [(10, 11, 12), (13, 14, 15)],
    "format3": [(5 + 3 * i, 6 + 3 * i, 7 + 3 * i) for i in range(15)],
}
FORMAT_PRACTICE_SLOT: dict[str, tuple[int, int, int]] = {
    "format2": (7, 8, 9),
}
FORMAT_SHEET_NAME: dict[str, str] = {
    "format1": "タイム表",
    "format2": "タイム表",
    "format3": "午前",  # format3は午前/午後の2シートあり。write_result()のsheet_nameで上書きする
}

_SECONDS_PER_DAY = 86400

_sheet_lock = threading.Lock()


def _write_to_sheet_safe(
    client: gspread.Client, spreadsheet_id: str, bib: int, time_sec: float,
    on_error: Callable[[str], None] | None, pt_count: int = 0, datsurin_count: int = 0,
    format: str = "format1", run_type: str = "normal", sheet_name: str | None = None,
    slot_index: int | None = None,
) -> None:
    try:
        write_to_sheet(
            client, spreadsheet_id, bib, time_sec, pt_count, datsurin_count, format, run_type, sheet_name, slot_index,
        )
    except Exception as exc:
        if on_error is not None:
            on_error(str(exc))


def write_result(
    client: gspread.Client, spreadsheet_id: str, bib: int, time_sec: float,
    pt_count: int = 0, datsurin_count: int = 0,
    format: str = "format1", run_type: str = "normal", sheet_name: str | None = None,
    slot_index: int | None = None,
) -> tuple[bool, str]:
    """write_to_sheetを同期・例外なしで呼ぶラッパー。(成功フラグ, メッセージ)を返す。

    確定操作の直後にその場でSheetsへ反映したい（リアルタイム更新したい）場合に使う。
    format: "format1"(通常大会用)/"format2"(阪名戦用)/"format3"(練習会用)。session.formatを渡す。
    run_type: "normal"（1本目・2本目…）または "practice"（format2の練習走行）。
    sheet_name: format3で「午前」「午後」のどちらに書くか指定する（省略時は「午前」）。
    slot_index: 0始まりで何本目の枠に書くかを明示する（そのゼッケンの当日の記録順）。
        Noneの場合は「まだ空いている最初の枠」に書く（新規記録時のデフォルト動作）。
        再送信・履歴修正の反映では、本数がずれないよう必ず指定すること。
    """
    try:
        write_to_sheet(
            client, spreadsheet_id, bib, time_sec, pt_count, datsurin_count, format, run_type, sheet_name, slot_index,
        )
    except Exception as exc:
        return False, str(exc)
    return True, "Sheetsに書き込みました"


def _find_or_register_bib_row(worksheet: gspread.Worksheet, bib: int) -> int:
    """ゼッケンに対応する行番号を返す。見つからなければ、未使用の最初の行にゼッケンを登録して作る。

    操作者が大会前にエントリーリスト・タイム表へゼッケンを入力し忘れていても、
    計測した瞬間に自動で行が追加され、同期が失敗し続けることを防ぐ。
    """
    cell = worksheet.find(str(bib), in_column=BIB_COL)
    if cell is not None:
        return cell.row

    bib_values = worksheet.col_values(BIB_COL)  # ヘッダー含む
    next_row = len(bib_values) + 1
    if next_row > worksheet.row_count:
        raise ValueError(f"ゼッケン{bib}を登録する空き行がありません（{worksheet.title}の行数を増やしてください）")
    worksheet.update_cell(next_row, BIB_COL, bib)
    return next_row


def write_to_sheet(
    client: gspread.Client, spreadsheet_id: str, bib: int, time_sec: float,
    pt_count: int = 0, datsurin_count: int = 0,
    format: str = "format1", run_type: str = "normal", sheet_name: str | None = None,
    slot_index: int | None = None,
) -> None:
    """ゼッケンに対応する行を探し、本数の枠（タイム・P・D列）に書き込む。

    slot_indexを指定した場合はその枠（0始まり）に直接書き込む（上書き）。
    指定しない場合はまだ記録の無い最初の枠を探して書く（新規記録時のデフォルト）。

    タイム欄には「ペナルティ込みの最終タイム」を書く（PT・脱輪は件数の記録として別列に書くのみ）。
    Sheets上で時刻形式（1:03.505など）として見せるため、秒数を1日=86400秒の比率に変換して書き込む。
    DNF/MCの場合はタイム欄に文字列を書き、PT・脱輪欄には書かない。

    失敗時は例外を投げる（呼び出し側で捕捉すること。write_result()なら例外を投げない）。
    """
    if run_type == "practice":
        practice_slot = FORMAT_PRACTICE_SLOT.get(format)
        if practice_slot is None:
            raise ValueError(f"フォーマット「{format}」には練習走行欄がありません")
        slots = [practice_slot]
    else:
        slots = FORMAT_RUN_SLOTS.get(format, FORMAT_RUN_SLOTS["format1"])

    target_sheet = sheet_name or FORMAT_SHEET_NAME.get(format, "タイム表")

    if is_dnf(time_sec):
        run_value = "DNF"
        write_counts = False
    elif is_mc(time_sec):
        run_value = "MC"
        write_counts = False
    else:
        run_value = time_sec / _SECONDS_PER_DAY
        write_counts = True

    with _sheet_lock:
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(target_sheet)

        row = _find_or_register_bib_row(worksheet, bib)

        if slot_index is not None:
            if not 0 <= slot_index < len(slots):
                raise ValueError(f"本数の枠（{len(slots)}本）を超えています: slot_index={slot_index}")
            target = slots[slot_index]
        else:
            target = None
            for run_col, pt_col, datsurin_col in slots:
                if not worksheet.cell(row, run_col).value:
                    target = (run_col, pt_col, datsurin_col)
                    break
            if target is None:
                raise ValueError(f"ゼッケン{bib}は記録できる本数の枠がすべて埋まっています")

        run_col, pt_col, datsurin_col = target
        worksheet.update_cell(row, run_col, run_value)
        # 上書き時、件数が0になった（取り消された）場合も反映できるよう、PT/脱輪は常に書く
        if write_counts:
            worksheet.update_cell(row, pt_col, pt_count or "")
            worksheet.update_cell(row, datsurin_col, datsurin_count or "")
        else:
            worksheet.update_cell(row, pt_col, "")
            worksheet.update_cell(row, datsurin_col, "")
