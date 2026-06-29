"""テンプレートスプレッドシートをゼロから構築するセットアップスクリプト。

config.jsonの templates.<format>.template_spreadsheet_id が未設定の場合、
manager.create_new_session()がこのモジュールのsetup_workbook()を呼び、
新規スプレッドシートにシート構成を組み立てる。

3つのフォーマットがある:
    format1 (通常大会用): タイム表・リザルト・エントリーリスト
        A 順位 / B ゼッケン / C 氏名 / D 所属クラブ / E 参加車両名 / F 車両形式 /
        G 1本目 / H P / I D / J 2本目 / K P / L D / M ベスト / N トップとの差
    format2 (阪名戦用): format1に「練習走行」を1本目の前に追加
        A 順位 / B ゼッケン / C 氏名 / D 所属クラブ / E 参加車両名 / F 車両形式 /
        G 練習走行 / H P / I D / J 1本目 / K P / L D / M 2本目 / N P / O D /
        P ベスト / Q トップとの差
        （練習走行は順位・ベストの判定に含めない）
    format3 (練習会用): 午前・午後の2シート、それぞれ1本目～15本目
        A 順位 / B ゼッケン / C 氏名 / D 車両形式 / E 1本目 / F P / G D / H 2本目 / ...(15本目まで)

    いずれもPT・脱輪1件あたりの秒数は エントリーリスト!H3 / H4 を参照する
    （大会開始時にconfig.jsonの値で書き込まれる。manager.py参照）。

あらかじめテンプレートを1つ作って毎回コピーする運用にしたい場合は、
このファイルを直接実行してテンプレート用スプレッドシートをセットアップする：
    python -m sheets.template_setup <credentials.jsonのパス> <スプレッドシートID> [format1|format2|format3]
"""

import sys
import time
from functools import wraps

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _with_retry(func, max_retries: int = 6, delay_seconds: int = 20):
    """429（レート制限）エラー時に待って自動再試行するラッパー。

    テンプレート構築は1シートあたり数十回のAPI呼び出しを連続で行うため、
    Sheets APIの書き込みレート制限（分あたり）にすぐ達してしまう。
    429以外の例外はそのまま投げる。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except gspread.exceptions.APIError as exc:
                is_rate_limit = "429" in str(exc) or "Quota exceeded" in str(exc)
                if not is_rate_limit or attempt == max_retries - 1:
                    raise
                time.sleep(delay_seconds)
    return wrapper


# gspreadの書き込み系メソッドをレート制限リトライ付きに差し替える（プロセス全体・1回だけ）。
# テンプレート構築だけでなく、本番計測中のリアルタイム書き込み（uploader.py）にも効く。
for _cls, _methods in (
    (gspread.Worksheet, ["format", "batch_format", "update", "update_cell", "update_title",
                          "freeze", "resize", "batch_clear", "find", "cell"]),
    (gspread.Spreadsheet, ["batch_update", "add_worksheet"]),
):
    for _name in _methods:
        _original = getattr(_cls, _name)
        if not getattr(_original, "_retry_wrapped", False):
            _wrapped = _with_retry(_original)
            _wrapped._retry_wrapped = True
            setattr(_cls, _name, _wrapped)

FORMAT1_HEADER = [
    "順位", "ゼッケン", "氏名", "所属クラブ", "参加車両名", "車両形式",
    "1本目", "P", "D", "2本目", "P", "D", "ベスト", "トップとの差",
]
FORMAT2_HEADER = [
    "順位", "ゼッケン", "氏名", "所属クラブ", "参加車両名", "車両形式",
    "練習走行", "P", "D", "1本目", "P", "D", "2本目", "P", "D", "ベスト", "トップとの差",
]
ENTRY_LIST_HEADER = ["ゼッケン", "氏名", "車種", "参加車両名", "所属クラブ"]

DEFAULT_ENTRY_ROWS = 60
FORMAT3_RUN_COUNT = 15

# PT・脱輪1件あたりの秒数を読むエントリーリスト上のセル
PT_SECONDS_CELL = "エントリーリスト!$H$3"
DATSURIN_SECONDS_CELL = "エントリーリスト!$H$4"


def setup_workbook(
    spreadsheet: gspread.Spreadsheet, format_key: str = "format1", entry_rows: int = DEFAULT_ENTRY_ROWS,
) -> None:
    """フォーマットに応じてシート構成を組み立てる。"""
    if format_key == "format2":
        _setup_workbook_format2(spreadsheet, entry_rows)
    elif format_key == "format3":
        _setup_workbook_format3(spreadsheet, entry_rows)
    else:
        _setup_workbook_format1(spreadsheet, entry_rows)


def _setup_workbook_format1(spreadsheet: gspread.Spreadsheet, entry_rows: int) -> None:
    """通常大会用: タイム表・リザルト・エントリーリストの3シートを構築する。

    タイム表の数式が「エントリーリスト」シートを参照するため、
    エントリーリストを先に作ってから他のシートを構築する
    （先にタイム表の数式を書くと、参照先がまだ存在せず#REF!になる）。
    """
    entry_sheet = spreadsheet.add_worksheet(title="エントリーリスト", rows=entry_rows + 1, cols=5)
    _setup_entry_list(entry_sheet)

    time_table = spreadsheet.sheet1
    time_table.update_title("タイム表")
    _setup_time_table_v1(time_table, entry_rows, FORMAT1_HEADER, practice=False)

    result_sheet = spreadsheet.add_worksheet(title="リザルト", rows=entry_rows + 1, cols=len(FORMAT1_HEADER))
    _setup_result_sheet_v1(result_sheet, entry_rows, FORMAT1_HEADER, practice=False)

    spreadsheet.reorder_worksheets([time_table, result_sheet, entry_sheet])


def _setup_workbook_format2(spreadsheet: gspread.Spreadsheet, entry_rows: int) -> None:
    """阪名戦用: format1に「練習走行」列を1本目の前に追加した3シートを構築する。

    練習走行は記録のみで、順位・ベストの判定には含めない。
    エントリーリストを先に作る理由はformat1と同じ（#REF!回避）。
    """
    entry_sheet = spreadsheet.add_worksheet(title="エントリーリスト", rows=entry_rows + 1, cols=5)
    _setup_entry_list(entry_sheet)

    time_table = spreadsheet.sheet1
    time_table.update_title("タイム表")
    _setup_time_table_v1(time_table, entry_rows, FORMAT2_HEADER, practice=True)

    result_sheet = spreadsheet.add_worksheet(title="リザルト", rows=entry_rows + 1, cols=len(FORMAT2_HEADER))
    _setup_result_sheet_v1(result_sheet, entry_rows, FORMAT2_HEADER, practice=True)

    spreadsheet.reorder_worksheets([time_table, result_sheet, entry_sheet])


def _setup_workbook_format3(spreadsheet: gspread.Spreadsheet, entry_rows: int) -> None:
    """練習会用: 午前・午後の2シート（各1本目～15本目）＋エントリーリストを構築する。

    エントリーリストを先に作る理由はformat1と同じ（#REF!回避）。
    """
    entry_sheet = spreadsheet.add_worksheet(title="エントリーリスト", rows=entry_rows + 1, cols=5)
    _setup_entry_list(entry_sheet)

    am_sheet = spreadsheet.sheet1
    am_sheet.update_title("午前")
    _setup_practice_meet_sheet(am_sheet, entry_rows)

    pm_sheet = spreadsheet.add_worksheet(title="午後", rows=entry_rows + 1, cols=4 + FORMAT3_RUN_COUNT * 3)
    _setup_practice_meet_sheet(pm_sheet, entry_rows)

    spreadsheet.reorder_worksheets([am_sheet, pm_sheet, entry_sheet])


# ---------------------------------------------------------------------------
# format1 / format2 共通（練習走行の有無だけ異なる）
# ---------------------------------------------------------------------------

def _setup_time_table_v1(sheet: gspread.Worksheet, entry_rows: int, header: list[str], practice: bool) -> None:
    """A-?列が見える表（最後の3列は隠し列＝ランキング計算用の数値キー）。"""
    last_row = entry_rows + 1
    visible_cols = len(header)
    sheet.resize(rows=last_row, cols=visible_cols + 3)

    last_letter = _col_letter(visible_cols)
    sheet.update([header], f"A1:{last_letter}1")
    _style_header(sheet, f"A1:{last_letter}1")
    sheet.freeze(rows=1)

    # 列位置（1始まり）: 練習走行ありなら G/H/I=練習走行/P/D, J/K/L=1本目/P/D, M/N/O=2本目/P/D
    #                    練習走行なしなら G/H/I=1本目/P/D, J/K/L=2本目/P/D
    run1_col = 10 if practice else 7
    run2_col = 13 if practice else 10
    eff1_col, eff2_col, best_col = visible_cols + 1, visible_cols + 2, visible_cols + 3

    eff1_letter, eff2_letter, best_letter = _col_letter(eff1_col), _col_letter(eff2_col), _col_letter(best_col)
    run1_letter, pt1_letter, ds1_letter = _col_letter(run1_col), _col_letter(run1_col + 1), _col_letter(run1_col + 2)
    run2_letter, pt2_letter, ds2_letter = _col_letter(run2_col), _col_letter(run2_col + 1), _col_letter(run2_col + 2)
    best_disp_letter = _col_letter(visible_cols - 1)  # ベスト列（末尾から2列目）
    gap_letter = _col_letter(visible_cols)  # トップとの差（最終列）

    c_f, d_f, e_f, f_f = [], [], [], []
    a_f, best_f, gap_f = [], [], []
    eff1_f, eff2_f, best_hidden_f = [], [], []

    for row in range(2, last_row + 1):
        c_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,2,FALSE),"")'])
        d_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,5,FALSE),"")'])
        e_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,4,FALSE),"")'])
        f_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,3,FALSE),"")'])

        # 本数列にはすでにペナルティ込みの最終タイムが入っているため（main.py参照）、
        # P・D列の秒数を重ねて加算しない（評価値への変換のみ行う）。P・D列は記録として残す。
        eff1_f.append([
            f'=IF({run1_letter}{row}="DNF",999.999,IF({run1_letter}{row}="MC",999.998,'
            f'IF({run1_letter}{row}="",9999,{run1_letter}{row}*86400)))'
        ])
        eff2_f.append([
            f'=IF({run2_letter}{row}="DNF",999.999,IF({run2_letter}{row}="MC",999.998,'
            f'IF({run2_letter}{row}="",9999,{run2_letter}{row}*86400)))'
        ])
        best_hidden_f.append([f"=MIN({eff1_letter}{row},{eff2_letter}{row})"])

        best_f.append([
            f'=IF(AND({run1_letter}{row}="",{run2_letter}{row}=""),"",'
            f'IF({best_letter}{row}=9999,"",'
            f'IF({best_letter}{row}=999.999,"DNF",'
            f'IF({best_letter}{row}=999.998,"MC",'
            f'TEXT(INT({best_letter}{row}/60),"0")&":"&TEXT(MOD({best_letter}{row},60),"00.000")))))'
        ])
        a_f.append([f'=IF({best_letter}{row}=9999,"",RANK({best_letter}{row},${best_letter}$2:${best_letter}${last_row},1))'])
        gap_f.append([
            f'=IF({best_letter}{row}>=900,"",'
            f'IF({best_letter}{row}=MINIFS(${best_letter}$2:${best_letter}${last_row},${best_letter}$2:${best_letter}${last_row},"<900"),"",'
            f'TEXT({best_letter}{row}-MINIFS(${best_letter}$2:${best_letter}${last_row},${best_letter}$2:${best_letter}${last_row},"<900"),"+0.000")))'
        ])

    sheet.update(a_f, f"A2:A{last_row}", value_input_option="USER_ENTERED")
    sheet.update(c_f, f"C2:C{last_row}", value_input_option="USER_ENTERED")
    sheet.update(d_f, f"D2:D{last_row}", value_input_option="USER_ENTERED")
    sheet.update(e_f, f"E2:E{last_row}", value_input_option="USER_ENTERED")
    sheet.update(f_f, f"F2:F{last_row}", value_input_option="USER_ENTERED")
    sheet.update(best_f, f"{best_disp_letter}2:{best_disp_letter}{last_row}", value_input_option="USER_ENTERED")
    sheet.update(gap_f, f"{gap_letter}2:{gap_letter}{last_row}", value_input_option="USER_ENTERED")
    sheet.update(best_hidden_f, f"{best_letter}2:{best_letter}{last_row}", value_input_option="USER_ENTERED")
    sheet.update(eff1_f, f"{eff1_letter}2:{eff1_letter}{last_row}", value_input_option="USER_ENTERED")
    sheet.update(eff2_f, f"{eff2_letter}2:{eff2_letter}{last_row}", value_input_option="USER_ENTERED")

    run_pd_cols = [run1_col, run1_col + 1, run1_col + 2, run2_col, run2_col + 1, run2_col + 2]
    if practice:
        run_pd_cols = [7, 8, 9] + run_pd_cols
    _apply_time_table_layout(
        sheet, last_row, visible_cols, run_pd_cols, hide_start=eff1_col - 1, hide_end=best_col,
    )


def _apply_time_table_layout(
    sheet: gspread.Worksheet, last_row: int, visible_cols: int, run_pd_cols: list[int],
    hide_start: int, hide_end: int,
) -> None:
    """列幅・表示形式・配置・枠線・縞模様・隠し列をまとめて設定する（タイム表・リザルト共通）。

    過去のレイアウト変更で隠したまま忘れられた列が残っていることがあるため、
    まず全列を表示状態に戻してから、必要な列だけ改めて隠す。
    run_pd_cols: [run1, P1, D1, run2, P2, D2, (練習走行ありなら先頭に practice, P, D も)]の1始まり列番号。
    """
    _unhide_all_columns(sheet)

    _set_column_width(sheet, column_index=0, width_px=45)   # A列(順位)
    _set_column_width(sheet, column_index=1, width_px=45)   # B列(ゼッケン)
    _set_column_width(sheet, column_index=4, width_px=160)  # E列(参加車両名)
    for i, col in enumerate(run_pd_cols):
        is_run_col = (i % 3 == 0)
        if not is_run_col:
            _set_column_width(sheet, column_index=col - 1, width_px=24)  # P・D列は1文字分

    if hide_end > hide_start:
        _hide_columns(sheet, start_index=hide_start, end_index=hide_end)

    last_letter = _col_letter(visible_cols)
    sheet.format(f"A2:B{last_row}", {"horizontalAlignment": "CENTER"})
    sheet.format(f"G2:{last_letter}{last_row}", {"horizontalAlignment": "CENTER"})

    # 1本目・2本目（・練習走行）: アプリは「日数」として書き込む（86400秒=1日）ので、
    # 時間形式で見た目だけ "1:03.505" にする。P・D列は件数（整数）。
    for i in range(0, len(run_pd_cols), 3):
        run_col, pt_col, ds_col = run_pd_cols[i], run_pd_cols[i + 1], run_pd_cols[i + 2]
        run_letter = _col_letter(run_col)
        pt_letter, ds_letter = _col_letter(pt_col), _col_letter(ds_col)
        sheet.format(f"{run_letter}2:{run_letter}{last_row}", {"numberFormat": {"type": "TIME", "pattern": "m:ss.000"}})
        sheet.format(f"{pt_letter}2:{ds_letter}{last_row}", {"numberFormat": {"type": "NUMBER", "pattern": "0"}})

    _apply_borders(sheet, f"A1:{last_letter}{last_row}")
    _apply_banding(sheet, f"A2:{last_letter}{last_row}")


def _setup_result_sheet_v1(sheet: gspread.Worksheet, entry_rows: int, header: list[str], practice: bool) -> None:
    """タイム表をベストタイム昇順に並べ替えるだけ（数式のみ・手入力禁止）。"""
    last_row = entry_rows + 1
    visible_cols = len(header)
    last_letter = _col_letter(visible_cols)
    best_col_in_source = visible_cols + 3  # タイム表側の「best」隠し列（ソートキー）

    sheet.update([header], f"A1:{last_letter}1")
    _style_header(sheet, f"A1:{last_letter}1")
    sheet.freeze(rows=1)

    src_best_letter = _col_letter(best_col_in_source)
    sort_formula = f"=SORT(タイム表!B2:{last_letter}{last_row}, タイム表!{src_best_letter}2:{src_best_letter}{last_row}, TRUE)"
    sheet.update([[sort_formula]], "B2", value_input_option="USER_ENTERED")

    rank_formula = f'=ARRAYFORMULA(IF(B2:B{last_row}="","",ROW(B2:B{last_row})-1))'
    sheet.update([[rank_formula]], "A2", value_input_option="USER_ENTERED")

    run1_col = 10 if practice else 7
    run2_col = 13 if practice else 10
    run_pd_cols = [run1_col, run1_col + 1, run1_col + 2, run2_col, run2_col + 1, run2_col + 2]
    if practice:
        run_pd_cols = [7, 8, 9] + run_pd_cols

    _apply_time_table_layout(sheet, last_row, visible_cols, run_pd_cols, hide_start=0, hide_end=0)


# ---------------------------------------------------------------------------
# format3（練習会用: 午前・午後、1本目～15本目）
# ---------------------------------------------------------------------------

def _setup_practice_meet_sheet(sheet: gspread.Worksheet, entry_rows: int, run_count: int = FORMAT3_RUN_COUNT) -> None:
    """順位 / ゼッケン / 氏名 / 車両形式 / (1本目 P D) x run_count の表を作る。

    末尾に各本のタイム評価値（隠し列、run_count個）＋ベスト（隠し列）を追加し、
    全本数のうち一番速いものを順位判定に使う。
    """
    last_row = entry_rows + 1
    fixed_cols = 4  # 順位・ゼッケン・氏名・車両形式
    visible_cols = fixed_cols + run_count * 3
    hidden_cols = run_count + 1  # 各本の評価値 + ベスト
    total_cols = visible_cols + hidden_cols
    sheet.resize(rows=last_row, cols=total_cols)

    header = ["順位", "ゼッケン", "氏名", "車両形式"]
    for i in range(1, run_count + 1):
        header += [f"{i}本目", "P", "D"]
    last_letter = _col_letter(visible_cols)
    sheet.update([header], f"A1:{last_letter}1")
    _style_header(sheet, f"A1:{last_letter}1")
    sheet.freeze(rows=1)

    eff_cols = [visible_cols + 1 + i for i in range(run_count)]
    best_col = visible_cols + hidden_cols
    best_letter = _col_letter(best_col)
    eff_letters = [_col_letter(c) for c in eff_cols]

    c_f, d_f, a_f, rank_disp_f = [], [], [], []
    eff_f_by_run = [[] for _ in range(run_count)]
    best_f = []

    for row in range(2, last_row + 1):
        c_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,2,FALSE),"")'])
        d_f.append([f'=IFERROR(VLOOKUP(B{row},エントリーリスト!$A:$E,3,FALSE),"")'])

        for i in range(run_count):
            run_col = fixed_cols + 1 + i * 3
            pt_col, ds_col = run_col + 1, run_col + 2
            run_letter, pt_letter, ds_letter = _col_letter(run_col), _col_letter(pt_col), _col_letter(ds_col)
            # 練習会用（format3）は本数列にすでにペナルティ込みの最終タイムが入っているため
            # （main.py参照）、P・D列の秒数を重ねて加算しない（ここでは順位判定用の評価値に
            # 変換するだけ）。P・D列はあくまで何回PT・脱輪があったかの記録として残す。
            eff_f_by_run[i].append([
                f'=IF({run_letter}{row}="DNF",999.999,IF({run_letter}{row}="MC",999.998,'
                f'IF({run_letter}{row}="",9999,{run_letter}{row}*86400)))'
            ])

        first_eff_letter, last_eff_letter = eff_letters[0], eff_letters[-1]
        best_f.append([f"=MIN({first_eff_letter}{row}:{last_eff_letter}{row})"])
        a_f.append([f'=IF({best_letter}{row}=9999,"",RANK({best_letter}{row},${best_letter}$2:${best_letter}${last_row},1))'])

    sheet.update(a_f, f"A2:A{last_row}", value_input_option="USER_ENTERED")
    sheet.update(c_f, f"C2:C{last_row}", value_input_option="USER_ENTERED")
    sheet.update(d_f, f"D2:D{last_row}", value_input_option="USER_ENTERED")
    for i in range(run_count):
        letter = eff_letters[i]
        sheet.update(eff_f_by_run[i], f"{letter}2:{letter}{last_row}", value_input_option="USER_ENTERED")
    sheet.update(best_f, f"{best_letter}2:{best_letter}{last_row}", value_input_option="USER_ENTERED")

    _unhide_all_columns(sheet)
    # 過去のビルドで列幅が残っていても上書きされるよう、常に明示的に設定する
    # （氏名・車両形式・各本のタイム列はデフォルト幅、P/D列だけ1文字分に狭くする）。
    _set_column_width(sheet, column_index=0, width_px=45)   # 順位
    _set_column_width(sheet, column_index=1, width_px=45)   # ゼッケン
    _set_column_width(sheet, column_index=2, width_px=100)  # 氏名
    _set_column_width(sheet, column_index=3, width_px=100)  # 車両形式
    for i in range(run_count):
        run_col = fixed_cols + 1 + i * 3
        sheet.format(
            f"{_col_letter(run_col)}2:{_col_letter(run_col)}{last_row}",
            {"numberFormat": {"type": "TIME", "pattern": "m:ss.000"}},
        )
        sheet.format(
            f"{_col_letter(run_col + 1)}2:{_col_letter(run_col + 2)}{last_row}",
            {"numberFormat": {"type": "NUMBER", "pattern": "0"}},
        )
        _set_column_width(sheet, column_index=run_col - 1, width_px=100)  # 本数のタイム列
        _set_column_width(sheet, column_index=run_col, width_px=24)       # P列
        _set_column_width(sheet, column_index=run_col + 1, width_px=24)   # D列
    _hide_columns(sheet, start_index=visible_cols, end_index=total_cols)

    sheet.format(f"A2:B{last_row}", {"horizontalAlignment": "CENTER"})
    sheet.format(f"E2:{last_letter}{last_row}", {"horizontalAlignment": "CENTER"})
    _apply_borders(sheet, f"A1:{last_letter}{last_row}")
    _apply_banding(sheet, f"A2:{last_letter}{last_row}")


def _setup_entry_list(sheet: gspread.Worksheet) -> None:
    """事前に手入力するシート（フォーマット共通）。アプリ・数式からは読むだけ。

    G1:H2には大会名・日付、G3:H4にはPT・脱輪1件あたりの秒数（config.jsonの値）が
    大会開始時に書き込まれる（manager.py参照）。
    """
    sheet.update([ENTRY_LIST_HEADER], "A1:E1")
    _style_header(sheet, "A1:E1")
    sheet.freeze(rows=1)
    sheet.format("A2:A61", {"horizontalAlignment": "CENTER"})
    _apply_borders(sheet, "A1:E61")
    _apply_banding(sheet, "A2:E61")


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------

def _col_letter(col: int) -> str:
    """1始まりの列番号をA1表記の列文字に変換する（1→A, 27→AA）。"""
    letters = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _style_header(sheet: gspread.Worksheet, a1_range: str) -> None:
    """ヘッダー行を濃い色の背景・白文字・太字・中央揃えにする。"""
    sheet.format(a1_range, {
        "backgroundColor": {"red": 0.16, "green": 0.30, "blue": 0.48},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
    })


def _apply_borders(sheet: gspread.Worksheet, a1_range: str) -> None:
    """範囲全体に薄い格子線を付ける。"""
    sheet.format(a1_range, {
        "borders": {
            "top": {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
            "bottom": {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
            "left": {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
            "right": {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
        }
    })


def _clear_bandings(sheet: gspread.Worksheet) -> None:
    """このシートに既に設定されている縞模様（バンディング）を全て削除する。

    同じ範囲に重ねて追加しようとするとAPIエラーになるため、再構築時は必ず先に呼ぶ。
    """
    meta = sheet.spreadsheet.fetch_sheet_metadata()
    for sheet_meta in meta.get("sheets", []):
        if sheet_meta["properties"]["sheetId"] != sheet.id:
            continue
        bandings = sheet_meta.get("bandedRanges", [])
        if not bandings:
            return
        requests = [{"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}} for b in bandings]
        sheet.spreadsheet.batch_update({"requests": requests})
        return


def _apply_banding(sheet: gspread.Worksheet, a1_range: str) -> None:
    """データ行に1行おきの縞模様（バンディング）を付ける。

    headerColorを指定すると範囲の先頭行が強制的にヘッダー扱いになり、
    本来の縞模様の先頭と重なって2行連続で同じ色になってしまうため、
    headerColorは指定しない（範囲には既にヘッダー行を含めていない）。
    """
    _clear_bandings(sheet)
    grid_range = gspread.utils.a1_range_to_grid_range(a1_range, sheet.id)
    sheet.spreadsheet.batch_update({
        "requests": [{
            "addBanding": {
                "bandedRange": {
                    "range": grid_range,
                    "rowProperties": {
                        "firstBandColor": {"red": 1, "green": 1, "blue": 1},
                        "secondBandColor": {"red": 0.95, "green": 0.97, "blue": 1.0},
                    },
                }
            }
        }]
    })


def _set_column_width(sheet: gspread.Worksheet, column_index: int, width_px: int) -> None:
    sheet.spreadsheet.batch_update({
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet.id,
                    "dimension": "COLUMNS",
                    "startIndex": column_index,
                    "endIndex": column_index + 1,
                },
                "properties": {"pixelSize": width_px},
                "fields": "pixelSize",
            }
        }]
    })


def _unhide_all_columns(sheet: gspread.Worksheet) -> None:
    """シート全体の列の非表示フラグを解除する（過去のレイアウトの隠し列が残らないように）。"""
    sheet.spreadsheet.batch_update({
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet.id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": sheet.col_count,
                },
                "properties": {"hiddenByUser": False},
                "fields": "hiddenByUser",
            }
        }]
    })


def _hide_columns(sheet: gspread.Worksheet, start_index: int, end_index: int) -> None:
    sheet.spreadsheet.batch_update({
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet.id,
                    "dimension": "COLUMNS",
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        }]
    })


def main() -> None:
    if len(sys.argv) < 3:
        print("使い方: python -m sheets.template_setup <credentials.jsonのパス> <スプレッドシートID> [format1|format2|format3]")
        sys.exit(1)

    credentials_path, spreadsheet_id = sys.argv[1], sys.argv[2]
    format_key = sys.argv[3] if len(sys.argv) > 3 else "format1"
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    setup_workbook(spreadsheet, format_key=format_key)
    print(f"セットアップ完了（{format_key}）: {spreadsheet.url}")


if __name__ == "__main__":
    main()
