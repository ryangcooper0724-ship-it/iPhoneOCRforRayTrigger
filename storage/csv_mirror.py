"""確定タイムをローカルCSVへ自動で書き出す（Sheetsの代替・バックアップとして常に更新する）。

2種類のCSVを管理する:
  1. 履歴ログCSV: 当日タイム履歴と同じ並び（ゼッケン・生タイム・タイム・ペナルティ・日時）で、
     確定した順（古い順）に1行ずつ追記していくだけのログ。
  2. シート構造ミラーCSV: Google Sheets側の「タイム表」（または午前/午後）と同じ列構成・列順で、
     ゼッケンごとに1行、本数（1本目・2本目…）の枠を更新していく。フォーマット（大会用/阪名戦用/
     練習会用）によって列構成が異なるため、session.formatに応じて切り替える。
     氏名・参加車両名・所属クラブ・順位・ベストなど、エントリーリストやSheets側の数式に依存する
     列はローカルだけでは計算できないため空欄のままにする（ゼッケン・本数・P・D列のみ埋める）。
"""

import csv
import os
import threading

from common.sheet_schema import BIB_COL, FORMAT_RUN_SLOTS
from common.time_format import seconds_to_display
from sheets import template_setup

HISTORY_HEADER = ["ゼッケン", "生タイム", "タイム", "ペナルティ", "日時"]

_history_lock = threading.Lock()
_mirror_lock = threading.Lock()


def append_history_row(
    csv_path: str, bib_number: str, raw_time_display: str, time_display: str,
    penalty_text: str, recorded_at: str,
) -> None:
    """当日タイム履歴と同じ並びで1行追記する（古い順。確定の都度1回だけ呼ぶ）。"""
    with _history_lock:
        is_new = not os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(HISTORY_HEADER)
            writer.writerow([bib_number, raw_time_display, time_display, penalty_text, recorded_at])


def create_history_csv(csv_path: str) -> None:
    """セッション開始時にヘッダーだけのファイルを作る（無ければ）。"""
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(HISTORY_HEADER)


def sheet_mirror_header(format_key: str) -> list[str]:
    """フォーマットに応じた、Sheets側の「タイム表」と同じ列構成のヘッダーを返す。"""
    if format_key == "format2":
        return list(template_setup.FORMAT2_HEADER)
    if format_key == "format3":
        header = ["順位", "ゼッケン", "氏名", "車両形式"]
        for i in range(1, template_setup.FORMAT3_RUN_COUNT + 1):
            header += [f"{i}本目", "P", "D"]
        return header
    return list(template_setup.FORMAT1_HEADER)


def sheet_mirror_path_for(base_path: str, sheet_name: str | None) -> str:
    """午前/午後のように、フォーマット内に複数シートがある場合に別ファイルへ振り分ける。

    sheet_nameがNone（午前/午後の区別が無いフォーマット）ならbase_pathをそのまま返す。
    """
    if not sheet_name:
        return base_path
    root, ext = os.path.splitext(base_path)
    return f"{root}_{sheet_name}{ext}"


def create_sheet_mirror_csv(csv_path: str, format_key: str) -> None:
    """セッション開始時にヘッダーだけのファイルを作る（無ければ）。"""
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(sheet_mirror_header(format_key))


def update_sheet_mirror(
    csv_path: str, format_key: str, bib_number: str, slot_index: int,
    time_value_for_sheet: float | str, pt_count: int, datsurin_count: int,
) -> None:
    """Sheetsへの書き込みと同じタイミングで、ローカルのシート構造ミラーCSVも更新する。

    time_value_for_sheet: write_to_sheetに渡すのと同じ値（秒数、または"DNF"/"MC"センチネル秒数）。
    slot_index: 0始まりで何本目の枠か（Sheets側と同じ計算結果をそのまま渡す）。
    """
    header = sheet_mirror_header(format_key)
    slots = FORMAT_RUN_SLOTS.get(format_key, FORMAT_RUN_SLOTS["format1"])
    if not 0 <= slot_index < len(slots):
        return
    run_col, pt_col, ds_col = slots[slot_index]  # 1始まりの列番号（ヘッダーと同じ並び）

    display_value = seconds_to_display(time_value_for_sheet) if isinstance(time_value_for_sheet, float) else time_value_for_sheet

    with _mirror_lock:
        rows = _read_mirror_rows(csv_path, header)
        row = rows.setdefault(bib_number, [""] * len(header))
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        row[BIB_COL - 1] = bib_number
        row[run_col - 1] = display_value
        row[pt_col - 1] = str(pt_count) if pt_count else ""
        row[ds_col - 1] = str(datsurin_count) if datsurin_count else ""
        rows[bib_number] = row
        _write_mirror_rows(csv_path, header, rows)


def _read_mirror_rows(csv_path: str, header: list[str]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    if not os.path.exists(csv_path):
        return rows
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # ヘッダー行を捨てる
        for r in reader:
            if not r:
                continue
            bib_key = r[BIB_COL - 1] if len(r) >= BIB_COL else ""
            if not bib_key:
                continue
            rows[bib_key] = r
    return rows


def _write_mirror_rows(csv_path: str, header: list[str], rows: dict[str, list[str]]) -> None:
    def sort_key(bib: str):
        return (0, int(bib)) if bib.isdigit() else (1, bib)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for bib in sorted(rows, key=sort_key):
            writer.writerow(rows[bib])
