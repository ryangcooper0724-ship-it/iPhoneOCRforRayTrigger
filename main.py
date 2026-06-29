"""ジムカーナ計測アプリ エントリポイント。"""

import json
import os
import re
import threading
import tkinter as tk
import unicodedata

from common.paths import resolve_base_dir
from common.time_format import DNF_SECONDS, MC_SECONDS
from sensor.mock_driver import MockDriver
from sensor.monitor import SensorMonitor
from sensor.ydci_driver import YdciDriver
from sheets import manager as sheets_manager
from sheets.uploader import write_result
from storage import csv_mirror
from storage.local_store import LocalStore
from timer.lap_timer import parse_time
from timer.run_manager import RunManager
from timer.waiting_list import WaitingList
from ui.main_window import MainWindow
from ui.session_dialogs import prompt_session_start

BASE_DIR = resolve_base_dir(__file__, levels_up=0)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = os.path.join(BASE_DIR, "gymkhana_records.db")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_driver(config: dict):
    """実機ドライバへの接続を試み、失敗したらモックドライバにフォールバックする。"""
    ydci = YdciDriver(
        board_model=config["board_model"],
        board_id_switch=config["board_id_switch"],
    )
    success, message = ydci.connect()
    if success:
        return ydci, message, False

    mock = MockDriver()
    mock_success, mock_message = mock.connect()
    combined_message = f"{message} → {mock_message}"
    return mock, combined_message, True


def build_penalty_text(pt_count: int, datsurin_count: int) -> str:
    """例: PT2脱輪1 のような表記を作る。0件の項目は省略する。"""
    parts = []
    if pt_count:
        parts.append(f"PT{pt_count}")
    if datsurin_count:
        parts.append(f"脱輪{datsurin_count}")
    return "".join(parts)


def parse_penalty_counts(penalty_text: str) -> tuple[int, int]:
    """"PT2脱輪1"のような表記からPT回数・脱輪回数を逆算する（ローカルDBには件数のみ文字列で残るため）。"""
    pt_match = re.search(r"PT(\d+)", penalty_text)
    datsurin_match = re.search(r"脱輪(\d+)", penalty_text)
    pt_count = int(pt_match.group(1)) if pt_match else 0
    datsurin_count = int(datsurin_match.group(1)) if datsurin_match else 0
    return pt_count, datsurin_count


def normalize_bib_number(bib_number: str) -> str:
    """全角で入力されたゼッケン番号（全角数字など）を半角に直す。

    NFKC正規化で全角数字・全角英字を半角に変換する（Sheets側のVLOOKUP・ランキング数式は
    半角の数値文字列を前提にしているため、ここでDB・Sheets・CSVに渡る前に統一する）。
    """
    return unicodedata.normalize("NFKC", bib_number).strip()


class PendingResultQueue:
    """GOAL確定後、ペナルティ反映前の「結果確認待ち」を1件ずつ表示するためのFIFOキュー。

    確認中の項目もキューの先頭(items[0])として保持し、確定（pop）されるまで残す。
    enqueueはセンサー監視スレッドから、popは画面ボタン（メインスレッド）から呼ばれるためロックする。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._items: list[tuple[str, str, float, str]] = []  # (slot_id, bib_number, raw_elapsed_seconds, status)

    def enqueue(self, item: tuple[str, str, float, str]) -> tuple[bool, int]:
        """追加する。(これが新たに先頭になったか, 先頭の後ろに何件並んでいるか)を返す。"""
        with self._lock:
            became_current = len(self._items) == 0
            self._items.append(item)
            remaining = len(self._items) - 1
            return became_current, remaining

    def pop_current(self) -> tuple[str, str, float, str] | None:
        """確認済みの先頭を取り除き、新しい先頭（無ければNone）を返す。"""
        with self._lock:
            if self._items:
                self._items.pop(0)
            return self._items[0] if self._items else None

    def remaining_after_current(self) -> int:
        with self._lock:
            return max(0, len(self._items) - 1)


def main() -> None:
    config = load_config()

    driver, driver_status, is_mock = build_driver(config)
    run_manager = RunManager()
    local_store = LocalStore(DB_PATH)
    waiting_list = WaitingList()
    pending_results = PendingResultQueue()

    root = tk.Tk()

    # Sheets連携: サービスアカウントで接続し、大会セッションを開始する
    # （session.jsonがあれば再接続/新規をダイアログで確認、credentials.json/テンプレート未設定なら
    #   ローカル保存のみで動作を継続する）
    sheets_client = None
    session = None

    def connect_sheets() -> str:
        """Sheetsへの接続を試みる。起動時、および起動時の接続が失敗していた場合の
        「未送信を同期」ボタンからの再試行で呼ぶ。成功すればsheets_client/sessionを更新する。
        """
        nonlocal sheets_client, session
        try:
            client = sheets_manager.build_client(config, BASE_DIR)
            new_session, is_new_session = sheets_manager.start_session(
                config, BASE_DIR, prompt_session_start, client=client,
            )
            sheets_client = client
            session = new_session
            message = f"接続済み: {session.event_name}（{session.spreadsheet_url}）"
            if is_new_session:
                # 新規大会開始時はSheets側（テンプレートの使い回し分）もクリアされるので、
                # ローカルの当日履歴も合わせてリセットする（前回大会のデータが残らないように）。
                local_store.clear_today_records()
            return message
        except sheets_manager.SessionStartCancelled:
            return "Sheets連携はスキップされました（大会名未入力）。ローカルのみ記録します"
        except Exception as exc:
            return f"Sheets未接続（ローカルのみ記録します）: {exc}"

    sheets_message = connect_sheets()

    current_am_pm = {"value": "午前"}  # 練習会用フォーマットのみ使う、現在の送信先（午前/午後）

    def handle_am_pm_changed(value: str) -> None:
        current_am_pm["value"] = value

    def _slot_index_for_record(record_id: int, bib_number: str, target_sheet: str) -> int:
        """そのゼッケン・その送信先シート（午前/午後）の当日の記録を記録順（id昇順）に数え、
        record_idが何本目（0始まり）かを返す。

        Sheetsの「1本目/2本目…」の枠は記録順に対応するため、再送信・履歴修正時も
        この本数の枠を直接上書きする（「空いている枠に追記」だと本数がずれる）。
        format3（練習会用）は午前/午後で本数が別々に数えられるよう、target_sheetも一致させて絞り込む。
        """
        records = sorted(
            (
                r for r in local_store.get_today_records()
                if r.bib_number == bib_number and r.target_sheet == target_sheet
            ),
            key=lambda r: r.id,
        )
        for i, rec in enumerate(records):
            if rec.id == record_id:
                return i
        return 0

    def _submit_record_to_sheets(record_id: int, bib_number: str, status: str, elapsed_seconds: float,
                                  raw_elapsed_seconds: float | None, pt_count: int, datsurin_count: int,
                                  target_sheet: str) -> None:
        """確定直後・履歴修正直後の両方から呼ぶ。Sheetsへの送信はバックグラウンドスレッドで行い、
        操作画面をブロックしない（レート制限時の待機リトライ中も操作を継続できるようにする）。

        target_sheet: format3（練習会用）のときの送信先（「午前」/「午後」）。それ以外は空文字。
        """
        if session is None or sheets_client is None:
            window.post_event("sheets_status", "Sheets未接続のためローカルのみ保存しました")
            return

        try:
            bib_int = int(bib_number)
        except ValueError:
            window.post_event(
                "sheets_status", f"Sheets書き込みスキップ（ローカルには保存済み）: ゼッケン番号「{bib_number}」が数値ではありません"
            )
            return

        if status == "DNF":
            time_sec = DNF_SECONDS
        elif status == "MC":
            time_sec = MC_SECONDS
        else:
            # 本数列にはペナルティ込みの最終タイムを直接書く（生タイムは見せない）。
            # PT・脱輪は件数を別列に書く（記録として残すのみで、タイム表の数式側では
            # 二重加算しない）。
            time_sec = elapsed_seconds

        slot_index = _slot_index_for_record(record_id, bib_number, target_sheet)
        sheet_name = target_sheet or None  # format3以外はNone（uploader側のデフォルトシートを使う）

        # Sheetsミラー用のローカルCSV（ゼッケン行ベース、フォーマットごとの列構成）も
        # 同じタイミングで更新する。ローカルファイルなのでSheets送信を待たず即時に行う。
        mirror_csv_path = csv_mirror.sheet_mirror_path_for(session.sheet_csv_path, sheet_name)
        csv_mirror.update_sheet_mirror(
            mirror_csv_path, session.format, bib_number, slot_index, time_sec, pt_count, datsurin_count,
        )

        def worker() -> None:
            ok, message = write_result(
                sheets_client, session.spreadsheet_id, bib_int, time_sec, pt_count, datsurin_count,
                format=session.format, slot_index=slot_index, sheet_name=sheet_name,
            )
            if ok:
                local_store.mark_synced(record_id)
                window.post_event("history_updated")
            window.post_event(
                "sheets_status", message if ok else f"Sheets書き込み失敗（ローカルには保存済み）: {message}"
            )

        threading.Thread(target=worker, daemon=True).start()

    def save_and_upload(
        slot_id: str, bib_number: str, status: str, elapsed_seconds: float,
        penalty_text: str = "", raw_elapsed_seconds: float | None = None,
        pt_count: int = 0, datsurin_count: int = 0,
    ) -> None:
        """確定タイム（OK/DNF/MC）をローカルDBに保存し、Sheetsの「タイム表」へその場で（非同期に）反映する。"""
        bib_number = normalize_bib_number(bib_number)
        window.remember_bib(slot_id, bib_number)

        # 練習会用フォーマットのときだけ、現在のトグル（午前/午後）をこの記録の送信先として固定する。
        target_sheet = current_am_pm["value"] if session is not None and session.format == "format3" else ""

        # 必ずローカルDBに保存してから（失われないように）Sheetsへ送信する
        record_id = local_store.add_record(
            bib_number, elapsed_seconds, status=status, penalty_text=penalty_text,
            raw_elapsed_seconds=raw_elapsed_seconds, target_sheet=target_sheet,
        )
        window.post_event("history_updated")

        # 当日タイム履歴と同じ並び（ゼッケン・生タイム・タイム・ペナルティ・日時）のログCSVに、
        # 確定した順（古い順）で1行追記する。
        if session is not None:
            rec = local_store.get_record(record_id)
            if rec is not None:
                csv_mirror.append_history_row(
                    session.csv_path, rec.bib_number, rec.raw_time_display(), rec.time_display(),
                    rec.penalty_text, rec.recorded_at,
                )

        _submit_record_to_sheets(
            record_id, bib_number, status, elapsed_seconds, raw_elapsed_seconds, pt_count, datsurin_count,
            target_sheet,
        )

    def reset_slot_display(slot_id: str) -> None:
        """枠のタイマーとゼッケン欄を即座にリセットする。

        GOALして結果確認パネルに渡った直後、またはDNF確定直後に呼ぶ。
        このタイミングで待機1のゼッケン番号があればそのまま入れる。無ければ空欄にする。
        """
        run_manager.reset_slot(slot_id)
        next_bib = waiting_list.pop_next()
        if next_bib is not None:
            window.set_bib_number(slot_id, next_bib)
            window.post_event("waiting_list_updated", waiting_list.get_entries())
        else:
            window.set_bib_number(slot_id, "")

    def enqueue_finished_run(slot_id: str, raw_elapsed_seconds: float, status: str = "OK") -> None:
        """GOAL確定（OK）またはDNF確定の直後に呼ぶ。ゼッケンを確定時点でスナップショットしてから、
        結果確認待ちキューに積み、枠は即座にリセットする。
        """
        bib_number = window.get_bib_number(slot_id)
        window.remember_bib(slot_id, bib_number)
        item = (slot_id, bib_number, raw_elapsed_seconds, status)

        became_current, remaining = pending_results.enqueue(item)
        if became_current:
            window.post_event("show_pending", (item, remaining))
        else:
            window.post_event("pending_remaining_updated", remaining)

        reset_slot_display(slot_id)

    def on_reset_slot(slot_id: str) -> None:
        run_manager.reset_slot(slot_id)

    def on_dnf_slot(slot_id: str) -> None:
        """DNFもGOALと同様に結果確認パネルを経由してから記録する（タイム欄は"DNF"表記）。"""
        lap_timer = run_manager.lap_timers[slot_id]
        if run_manager.mark_dnf(slot_id) and lap_timer.result is not None:
            enqueue_finished_run(slot_id, lap_timer.result.elapsed_seconds, status="DNF")

    def on_reset_goal_count_slot(slot_id: str) -> None:
        run_manager.reset_goal_count_slot(slot_id)

    def on_next_start_slot_changed(slot_id: str) -> None:
        run_manager.set_next_start_slot(slot_id)

    # GOAL確定回数（1回/2回）切替UIは封印中。run_manager.set_goal_count_all(count)は
    # 将来復活させる場合に使う（現状はLapTimerのデフォルト2回のまま固定）。

    def on_waiting_list_changed(index: int, bib_number: str) -> None:
        waiting_list.set_entry(index, bib_number)

    def on_confirm_result(
        slot_id: str, bib_number: str, raw_elapsed_seconds: float, final_elapsed_seconds: float,
        pt_count: int, datsurin_count: int, status: str,
    ) -> None:
        """操作者が結果確認パネルで「確定して記録」を押した、または自動確定タイマーが
        満了したときに呼ばれる。final_elapsed_secondsは画面側でPT/脱輪/手動編集を
        反映済みの最終タイムなので、ここでは再計算せずそのまま記録する。
        statusは"OK"/"DNF"/"MC"のいずれか（画面側のタイム欄表示から判定済み）。
        """
        penalty_text = build_penalty_text(pt_count, datsurin_count)
        save_and_upload(
            slot_id, bib_number, status, final_elapsed_seconds, penalty_text, raw_elapsed_seconds,
            pt_count, datsurin_count,
        )

        next_item = pending_results.pop_current()
        if next_item is not None:
            window.post_event("show_pending", (next_item, pending_results.remaining_after_current()))
        else:
            window.post_event("pending_cleared", None)

    def on_edit_history_record(record_id: int, column: str, new_value: str) -> tuple[bool, str]:
        """当日分タイム履歴のセルを直接編集したときに呼ばれる。(成功フラグ, エラーメッセージ)を返す。

        編集した行は内容が変わるため、未送信（synced=0）に戻してSheetsへ即座に再送信する
        （synced列自体を編集した場合はそのまま反映するだけで、Sheetsへは送らない）。
        """
        try:
            if column == "bib":
                local_store.update_record(record_id, bib_number=normalize_bib_number(new_value), synced=0)
            elif column == "raw_time":
                # 生タイムを変えたら、ローカル表示の「タイム」（最終タイム）も既存のPT・脱輪を
                # 反映して再計算する（Sheets側は生タイム＋PT・脱輪を別々に見るので、こちらは表示用）。
                new_raw = parse_time(new_value)
                rec_before = local_store.get_record(record_id)
                pt_count, datsurin_count = parse_penalty_counts(rec_before.penalty_text) if rec_before else (0, 0)
                penalty_seconds = pt_count * config["pt_penalty_seconds"] + datsurin_count * config["datsurin_penalty_seconds"]
                local_store.update_record(
                    record_id, raw_elapsed_seconds=new_raw, elapsed_seconds=new_raw + penalty_seconds, synced=0,
                )
            elif column == "time":
                # Sheets/CSVへは常に「生タイム」を送る（PT・脱輪はSheets側の数式で合算するため）。
                # 「タイム」列を直接書き換えた場合は生タイムも同じ値にし、既存のPT・脱輪は
                # 二重に加算されないようクリアする（=この入力値をそのまま最終タイムとして扱う）。
                stripped = new_value.strip()
                if stripped in ("DNF", "MC"):
                    local_store.update_record(record_id, status=stripped, synced=0)
                else:
                    new_seconds = parse_time(stripped)
                    local_store.update_record(
                        record_id, elapsed_seconds=new_seconds, raw_elapsed_seconds=new_seconds,
                        penalty_text="", status="OK", synced=0,
                    )
            elif column == "penalty":
                # ペナルティを変えたら、ローカル表示の「タイム」（最終タイム）も生タイム＋新しい
                # ペナルティで再計算する。
                rec_before = local_store.get_record(record_id)
                raw_seconds = rec_before.raw_elapsed_seconds if rec_before else 0.0
                pt_count, datsurin_count = parse_penalty_counts(new_value)
                penalty_seconds = pt_count * config["pt_penalty_seconds"] + datsurin_count * config["datsurin_penalty_seconds"]
                local_store.update_record(
                    record_id, penalty_text=new_value, elapsed_seconds=raw_seconds + penalty_seconds, synced=0,
                )
            elif column == "recorded_at":
                local_store.update_record(record_id, recorded_at=new_value, synced=0)
            elif column == "synced":
                local_store.update_record(record_id, synced=1 if new_value.strip() == "○" else 0)
            else:
                return False, f"未対応の列です: {column}"
        except (ValueError, IndexError):
            return False, "値の形式が正しくありません（タイムは M:SS.mmm 形式で入力してください）"

        window.post_event("history_updated")

        if column != "synced":
            rec = local_store.get_record(record_id)
            if rec is not None:
                pt_count, datsurin_count = parse_penalty_counts(rec.penalty_text)
                _submit_record_to_sheets(
                    rec.id, rec.bib_number, rec.status, rec.elapsed_seconds, rec.raw_elapsed_seconds,
                    pt_count, datsurin_count, rec.target_sheet,
                )
        return True, ""

    def sync_pending_records() -> None:
        """「未送信を同期」ボタン。レート制限の待機リトライで時間がかかる場合があるため、
        バックグラウンドスレッドで実行し、画面操作をブロックしない。

        起動時のSheets接続が（ネット不通などで）失敗していた場合は、ここで再接続を試みる。
        一度接続済みであれば、その後の通信はそのつどタイムアウト付きで行われるため、
        途中でネットが切れても未送信のまま残るだけで、ここでの再送信で復旧できる。
        """
        if session is None or sheets_client is None:
            window.post_event("sheets_status", "Sheets未接続のため再接続を試みます…")
            reconnect_message = connect_sheets()
            window.post_event("sheets_status", reconnect_message)
            if session is None or sheets_client is None:
                window.post_event("sync_result", "Sheets未接続のため同期できません")
                return

        pending = local_store.get_unsynced_records()
        if not pending:
            window.post_event("sync_result", "未送信のデータはありません")
            return

        def worker() -> None:
            success_count = 0
            for rec in pending:
                try:
                    bib_int = int(rec.bib_number)
                except ValueError:
                    continue

                pt_count, datsurin_count = parse_penalty_counts(rec.penalty_text)
                if rec.status == "DNF":
                    time_sec = DNF_SECONDS
                elif rec.status == "MC":
                    time_sec = MC_SECONDS
                else:
                    time_sec = rec.raw_elapsed_seconds or rec.elapsed_seconds

                slot_index = _slot_index_for_record(rec.id, rec.bib_number, rec.target_sheet)
                sheet_name = rec.target_sheet or None
                ok, _message = write_result(
                    sheets_client, session.spreadsheet_id, bib_int, time_sec, pt_count, datsurin_count,
                    format=session.format, slot_index=slot_index, sheet_name=sheet_name,
                )
                if ok:
                    local_store.mark_synced(rec.id)
                    success_count += 1
                    mirror_csv_path = csv_mirror.sheet_mirror_path_for(session.sheet_csv_path, sheet_name)
                    csv_mirror.update_sheet_mirror(
                        mirror_csv_path, session.format, rec.bib_number, slot_index, time_sec, pt_count, datsurin_count,
                    )

            window.post_event("history_updated")
            window.post_event(
                "sync_result",
                f"{success_count}/{len(pending)}件をSheetsに同期しました",
            )

        threading.Thread(target=worker, daemon=True).start()

    def handle_goal_trigger() -> None:
        """GOALセンサー検知時（実機・モック）と、手動の「GOALセンサー発火」ボタンの両方から呼ばれる。

        GOAL対象の枠は「先に出走している方」に自動で決まるため、操作者の選択は発生しない。
        1台のみ走行中の場合もそのままその枠が対象になる。
        """
        result = run_manager.handle_goal_trigger()
        if result is not None and result.finished:
            lap_timer = run_manager.lap_timers[result.slot_id]
            if lap_timer.result is not None:
                enqueue_finished_run(result.slot_id, lap_timer.result.elapsed_seconds)

    def on_clear_history() -> int:
        """「当日履歴を全クリア」ボタン用。ローカルの当日履歴のみ削除する（Sheets/CSVは変更しない）。"""
        count = local_store.clear_today_records()
        window.post_event("history_updated")
        return count

    window = MainWindow(
        root=root,
        driver_status=driver_status,
        is_mock=is_mock,
        run_manager=run_manager,
        sheets_status=sheets_message,
        on_reset_slot=on_reset_slot,
        on_dnf_slot=on_dnf_slot,
        on_reset_goal_count_slot=on_reset_goal_count_slot,
        on_next_start_slot_changed=on_next_start_slot_changed,
        on_manual_goal_trigger=handle_goal_trigger,
        on_waiting_list_changed=on_waiting_list_changed,
        on_confirm_result=on_confirm_result,
        local_store=local_store,
        on_sync_pending=sync_pending_records,
        on_edit_history_record=on_edit_history_record,
        on_clear_history=on_clear_history,
        pt_penalty_seconds=config["pt_penalty_seconds"],
        datsurin_penalty_seconds=config["datsurin_penalty_seconds"],
        mock_driver=driver if is_mock else None,
        start_channel=config["start_channel"],
        goal_channel=config["goal_channel"],
        is_format3=session is not None and session.format == "format3",
        on_am_pm_changed=handle_am_pm_changed,
    )

    def handle_start_trigger() -> None:
        run_manager.handle_start_trigger()

    def handle_error(exc: Exception) -> None:
        window.post_event("error", str(exc))

    monitor = SensorMonitor(
        driver=driver,
        start_channel=config["start_channel"],
        goal_channel=config["goal_channel"],
        poll_interval_ms=config["poll_interval_ms"],
        debounce_ms=config["debounce_ms"],
        on_start_trigger=handle_start_trigger,
        on_goal_trigger=handle_goal_trigger,
        on_error=handle_error,
    )
    monitor.start()

    def on_close() -> None:
        monitor.stop()
        driver.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
