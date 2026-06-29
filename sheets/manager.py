"""セッション管理（大会の新規開始・再接続）とスプレッドシート生成。

起動時にsession.jsonを確認し、前回の大会があれば再接続するか操作者に確認する。
新規の場合は大会名を入力してもらい、テンプレートからスプレッドシートをコピーして
（テンプレート未設定ならゼロから構築して）session.jsonに保存する。
"""

import datetime
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Callable

import gspread
from google.oauth2.service_account import Credentials

from sheets import template_setup
from storage import csv_mirror

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ネット不通時に通信がハングし続けないための上限（接続タイムアウト, 読み込みタイムアウト）秒数
REQUEST_TIMEOUT = (10, 20)


class SessionStartCancelled(Exception):
    """操作者が大会名入力などをキャンセルした場合。"""


@dataclass
class Session:
    event_name: str
    date: str
    spreadsheet_id: str
    spreadsheet_url: str
    csv_path: str  # 当日タイム履歴と同じ並びで古い順に追記するログCSV
    created_at: str
    format: str = "format1"
    sheet_csv_path: str = ""  # Sheets「タイム表」（または午前/午後）と同じ列構成のミラーCSV

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Session":
        return Session(**data)


def build_client(config: dict, base_dir: str) -> gspread.Client:
    """サービスアカウント認証でgspreadクライアントを作る。"""
    credentials_path = os.path.join(base_dir, config.get("credentials_path", "credentials.json"))
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"認証ファイルが見つかりません: {credentials_path}")

    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    client.set_timeout(REQUEST_TIMEOUT)
    return client


def load_session(session_path: str) -> Session | None:
    if not os.path.exists(session_path):
        return None
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            return Session.from_dict(json.load(f))
    except (json.JSONDecodeError, TypeError, KeyError):
        return None  # 壊れたsession.jsonは無視して新規扱いにする


def save_session(session: Session, session_path: str) -> None:
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)


def _sanitize_for_filename(text: str) -> str:
    """ファイル名に使えない文字を取り除く。"""
    return re.sub(r'[\\/:*?"<>|]', "", text).strip() or "大会"


def _clear_working_sheet(spreadsheet, format_key: str) -> None:
    """テンプレートを使い回す運用のため、新規大会開始時に前回大会のデータを消す。

    ゼッケン・タイム・PT・脱輪などアプリが書き込む列だけクリアする
    （氏名・車両形式・ベスト・順位などのVLOOKUP/ランキング数式列は消さない）。
    シートが見つからない場合は何もしない。フォーマットごとに列構成が異なるため、
    クリアするシート名・列範囲もフォーマットごとに切り替える。
    """
    if format_key == "format3":
        for sheet_name in ("午前", "午後"):
            try:
                sheet = spreadsheet.worksheet(sheet_name)
                last_col = template_setup._col_letter(4 + template_setup.FORMAT3_RUN_COUNT * 3)
                sheet.batch_clear(["B2:B1000", f"E2:{last_col}1000"])
            except gspread.exceptions.WorksheetNotFound:
                pass
    else:
        clear_range = "G2:L1000" if format_key == "format1" else "G2:O1000"
        try:
            time_table = spreadsheet.worksheet("タイム表")
            time_table.batch_clear(["B2:B1000", clear_range])
        except gspread.exceptions.WorksheetNotFound:
            pass

    try:
        entry_list = spreadsheet.worksheet("エントリーリスト")
        entry_list.batch_clear(["A2:E1000"])
    except gspread.exceptions.WorksheetNotFound:
        pass


def _write_event_info_box(worksheet, event_name: str, date_str: str, config: dict) -> None:
    """エントリーリストのG～H列に「大会名・日付・PT/脱輪の秒数」をラベル+値の小さな表として書く。

    A～E列の参加者入力エリアとは重ならない位置に、背景色・太字・枠線をつけて
    一目で分かるようにする。PT・脱輪の秒数はタイム表の数式（P/Q列）が参照する。
    """
    if worksheet.col_count < 8:
        worksheet.add_cols(8 - worksheet.col_count)

    worksheet.update(
        [
            ["大会名", event_name],
            ["日付", date_str],
            ["PT(秒)", config.get("pt_penalty_seconds", 0)],
            ["脱輪(秒)", config.get("datsurin_penalty_seconds", 0)],
        ],
        "G1:H4",
    )

    worksheet.format("G1:G4", {
        "backgroundColor": {"red": 0.85, "green": 0.91, "blue": 0.98},
        "textFormat": {"bold": True},
        "horizontalAlignment": "CENTER",
    })
    worksheet.format("H1:H4", {
        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
        "textFormat": {"bold": False},
    })
    worksheet.format("G1:H4", {
        "borders": {
            "top": {"style": "SOLID"},
            "bottom": {"style": "SOLID"},
            "left": {"style": "SOLID"},
            "right": {"style": "SOLID"},
        }
    })


def create_new_session(
    event_name: str, config: dict, base_dir: str, session_path: str,
    client: gspread.Client | None = None, format_key: str = "format1",
) -> Session:
    """新規の大会を開始する。スプレッドシートとローカルCSVを新規作成し、session.jsonに保存する。"""
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    safe_event_name = _sanitize_for_filename(event_name)
    title = f"ジムカーナ計測_{safe_event_name}_{date_str}"

    if client is None:
        client = build_client(config, base_dir)

    template_id = config.get("templates", {}).get(format_key, {}).get("template_spreadsheet_id", "")
    if template_id:
        try:
            spreadsheet = client.copy(file_id=template_id, title=title, copy_permissions=True)
        except gspread.exceptions.APIError as exc:
            if "storage quota" not in str(exc):
                raise
            # サービスアカウント単体（個人Googleアカウント連携）はDriveの保存容量を
            # 持たないため、新規ファイルの作成・コピーができない。この場合はテンプレートの
            # スプレッドシートをそのまま使い続ける（大会ごとの自動複製は諦める）。
            # 前回大会のデータが残っているので、新規大会開始時に必ずクリアする。
            spreadsheet = client.open_by_key(template_id)
            _clear_working_sheet(spreadsheet, format_key)
    else:
        # テンプレート未設定の場合はゼロから構築する
        spreadsheet = client.create(title)
        template_setup.setup_workbook(spreadsheet, format_key=format_key)

    # ファイル名（大会名・日付）を最新化する。テンプレート使い回し運用では
    # スプレッドシート自体に大会情報が残らないため、Drive上のファイル名で確認できるようにする。
    try:
        spreadsheet.update_title(title)
    except gspread.exceptions.APIError:
        pass  # タイトル変更権限が無くても計測自体は継続する

    # エントリーリストのG～H列に大会名・日付を表っぽい見た目（ラベル+値、背景色・太字・枠線）で書いておく
    try:
        entry_list = spreadsheet.worksheet("エントリーリスト")
        _write_event_info_box(entry_list, event_name, date_str, config)
    except gspread.exceptions.WorksheetNotFound:
        pass

    csv_dir = os.path.join(base_dir, "csv")
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"gymkhana_{safe_event_name}_{date_str}.csv")
    sheet_csv_path = os.path.join(csv_dir, f"gymkhana_{safe_event_name}_{date_str}_sheet.csv")
    csv_mirror.create_history_csv(csv_path)
    if format_key == "format3":
        # 練習会用は午前・午後で別々のシート・別々のミラーCSVになる
        for sheet_name in ("午前", "午後"):
            csv_mirror.create_sheet_mirror_csv(
                csv_mirror.sheet_mirror_path_for(sheet_csv_path, sheet_name), format_key,
            )
    else:
        csv_mirror.create_sheet_mirror_csv(sheet_csv_path, format_key)

    session = Session(
        event_name=event_name,
        date=date_str,
        spreadsheet_id=spreadsheet.id,
        spreadsheet_url=spreadsheet.url,
        csv_path=csv_path,
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        format=format_key,
        sheet_csv_path=sheet_csv_path,
    )
    save_session(session, session_path)
    return session


def start_session(
    config: dict, base_dir: str,
    prompt_session_start: Callable[[dict, str | None, str | None], tuple[bool, str | None, str | None]],
    client: gspread.Client | None = None,
) -> tuple[Session, bool]:
    """アプリ起動時に呼ぶ。session.jsonの有無に応じて再接続/新規をダイアログで確認する。

    ダイアログ表示自体はUI層の責務のため、prompt_session_start（呼び出し側がui.session_dialogs.
    prompt_session_startを渡す想定）に委譲する。新規の場合はフォーマット（templates配下のキー）も
    選んでもらう。
    戻り値: (session, is_new_session)。is_new_sessionは新規大会として開始した場合にTrue
    （呼び出し側はこれを見て、ローカルの当日履歴をリセットするかどうか判断する）。
    """
    session_path = os.path.join(base_dir, "session.json")
    existing = load_session(session_path)

    reconnect, format_key, event_name = prompt_session_start(
        config,
        existing.event_name if existing is not None else None,
        existing.date if existing is not None else None,
    )
    if reconnect:
        return existing, False

    if not event_name or not event_name.strip():
        raise SessionStartCancelled("大会名が入力されなかったため、セッションを開始できません")

    session = create_new_session(
        event_name.strip(), config, base_dir, session_path, client=client, format_key=format_key or "format1",
    )
    return session, True
