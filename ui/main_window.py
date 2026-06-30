"""ジムカーナ計測アプリのメイン画面（tkinter）。2台同時出走（枠A/枠B）対応。

GOAL確定回数（1回/2回）切替UIは現在封印中（timer/run_manager.pyのロジック自体は残してある）。
GOALの枠割り当ては「先に出走している方が対象」という固定ルールで、操作者の選択は発生しない。
"""

import math
import os
import queue
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from PIL import Image, ImageTk

from common.paths import resolve_base_dir, resolve_bundled_resource_dir
from ocr.bib_reader import BibReader
from ocr.mock_engine import MockOcrEngine
from sensor.mock_driver import MockDriver
from storage.local_store import LocalStore
from timer.lap_timer import TimerState, format_time, parse_time
from timer.run_manager import RunManager
from version import APP_NAME, APP_VERSION, ORG_NAME

# CSVは全てこのフォルダにまとめる（自動生成分も手動出力分も同じ場所）。
_BASE_DIR = resolve_base_dir(__file__, levels_up=1)
_CSV_DIR = os.path.join(_BASE_DIR, "csv")

# アイコンはPyInstallerの--add-dataで同梱し、onefile展開時はsys._MEIPASS配下から読む。
_ICON_PATH = os.path.join(resolve_bundled_resource_dir(__file__, levels_up=1), "app_icon.ico")

SLOT_LABELS = {"A": "枠A", "B": "枠B"}
HISTORY_COLUMNS = ("bib", "raw_time", "time", "penalty", "recorded_at", "synced")

TIMER_FONT = ("Consolas", 48, "bold")
RAW_TIME_FONT = ("Consolas", 26, "bold")
BIB_FONT = ("", 28, "bold")
LABEL_FONT = ("", 15)
STATE_FONT = ("", 22, "bold")
ENTRY_FONT = ("", 18)
BUTTON_FONT = ("", 14)
# 結果確認パネル（画面下部、横幅に余裕がある）用のPT/脱輪
PENALTY_LABEL_FONT = ("", 30)
PENALTY_BUTTON_FONT = ("", 24, "bold")
# 枠A/B側（画面半分で使う想定、コンパクトに）のPT/脱輪・DNF/リセット/ミスコース
SLOT_PENALTY_LABEL_FONT = ("", 16)
SLOT_PENALTY_BUTTON_FONT = ("", 14, "bold")
SLOT_ACTION_FONT = ("", 13)

PENDING_AUTO_CONFIRM_MS = 10_000  # GOALから（結果確認パネルに表示されてから）この時間で自動確定

OCR_PREVIEW_SIZE = (380, 285)  # カメラ映像プレビューの表示サイズ（幅, 高さ）
OCR_PREVIEW_INTERVAL_MS = 200  # プレビュー更新間隔（_tick()のタイマー精度に影響しないよう別ループで回す）


def _set_windows_taskbar_icon(root: tk.Tk, icon_path: str) -> None:
    """タスクバーのアイコンを明示的に差し替える。

    tkinterのiconbitmap()はタイトルバーには効くが、Windowsのタスクバーボタンには
    反映されないことがある（Tk既定のアイコンのままになる）ため、Win32 APIで
    ICON_BIG/ICON_SMALLを直接ウィンドウへセットする。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TPGarage.RayTrigger")

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x10
        LR_DEFAULTSIZE = 0x40
        WM_SETICON = 0x80
        ICON_SMALL = 0
        ICON_BIG = 1

        h_small = ctypes.windll.user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )
        h_big = ctypes.windll.user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
        )
        if h_small:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
        if h_big:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
    except Exception:
        pass


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        driver_status: str,
        is_mock: bool,
        run_manager: RunManager,
        sheets_status: str,
        on_reset_slot: Callable[[str], None],
        on_dnf_slot: Callable[[str], None],
        on_reset_goal_count_slot: Callable[[str], None],
        on_next_start_slot_changed: Callable[[str], None],
        on_manual_goal_trigger: Callable[[], None],
        on_waiting_list_changed: Callable[[int, str], None],
        on_confirm_result: Callable[[str, str, float, float, int, int, str], None],
        on_discard_pending: Callable[[str], None],
        local_store: LocalStore,
        on_sync_pending: Callable[[], None],
        on_edit_history_record: Callable[[int, str, str], tuple[bool, str]],
        on_clear_history: Callable[[], int],
        pt_penalty_seconds: float = 2.0,
        datsurin_penalty_seconds: float = 5.0,
        mock_driver: MockDriver | None = None,
        start_channel: int = 0,
        goal_channel: int = 1,
        is_format3: bool = False,
        on_am_pm_changed: Callable[[str], None] | None = None,
        ocr_available: bool = False,
        ocr_mock_engine: MockOcrEngine | None = None,
        ocr_reader: BibReader | None = None,
    ):
        self._root = root
        self._run_manager = run_manager
        self._on_reset_slot = on_reset_slot
        self._on_dnf_slot = on_dnf_slot
        self._on_reset_goal_count_slot = on_reset_goal_count_slot
        self._on_next_start_slot_changed = on_next_start_slot_changed
        self._on_manual_goal_trigger = on_manual_goal_trigger
        self._on_waiting_list_changed = on_waiting_list_changed
        self._on_confirm_result = on_confirm_result
        self._on_discard_pending = on_discard_pending
        self._local_store = local_store
        self._on_sync_pending = on_sync_pending
        self._on_edit_history_record = on_edit_history_record
        self._on_clear_history = on_clear_history
        self._pt_seconds = pt_penalty_seconds
        self._datsurin_seconds = datsurin_penalty_seconds
        self._mock_driver = mock_driver
        self._start_channel = start_channel
        self._goal_channel = goal_channel
        self._is_format3 = is_format3
        self._on_am_pm_changed = on_am_pm_changed
        self._ocr_available = ocr_available
        self._ocr_mock_engine = ocr_mock_engine
        self._ocr_reader = ocr_reader
        self._ocr_preview_photo: ImageTk.PhotoImage | None = None

        self._event_queue: queue.Queue = queue.Queue()
        self._last_bib: dict[str, str] = {"A": "", "B": ""}
        self._bib_vars: dict[str, tk.StringVar] = {}
        self._time_labels: dict[str, ttk.Label] = {}
        self._state_labels: dict[str, ttk.Label] = {}
        self._waiting_vars: list[tk.StringVar] = []
        self._bib_warning_labels: dict[str, ttk.Label] = {}
        self._bib_entries: dict[str, ttk.Entry] = {}
        self._ocr_badge_labels: dict[str, ttk.Label] = {}
        self._ocr_badge_after_ids: dict[str, str] = {}
        self._ocr_frozen_until: float | None = None
        self._slot_pt_vars: dict[str, tk.IntVar] = {}
        self._slot_datsurin_vars: dict[str, tk.IntVar] = {}
        self._slot_mc_vars: dict[str, tk.BooleanVar] = {}

        # 直前にGOAL/DNFした1件の確認待ち状態（main.py側のキューと同期）
        # (slot_id, bib, raw_elapsed, status, pt_count, datsurin_count, mc_flag)
        self._current_pending: tuple[str, str, float, str, int, int, bool] | None = None
        self._current_remaining = 0
        self._pending_after_id: str | None = None
        self._auto_confirm_deadline: float | None = None  # time.monotonic()基準、カウントダウン表示用

        root.title(f"{APP_NAME} - {ORG_NAME} v{APP_VERSION}")
        root.geometry("1100x1000")
        if os.path.exists(_ICON_PATH):
            root.iconbitmap(default=_ICON_PATH)
            _set_windows_taskbar_icon(root, _ICON_PATH)

        style = ttk.Style()
        style.configure("Treeview", font=("", 13), rowheight=30)
        style.configure("Treeview.Heading", font=("", 13, "bold"))
        # 結果確認パネル（画面下部）のPT/脱輪操作部分
        style.configure("Penalty.TButton", font=PENALTY_BUTTON_FONT, padding=(10, 10))
        # 枠A/B側（コンパクト）のPT/脱輪・DNF/リセット/ミスコース
        style.configure("SlotPenalty.TButton", font=SLOT_PENALTY_BUTTON_FONT, padding=(4, 4))
        style.configure("SlotAction.TButton", font=SLOT_ACTION_FONT, padding=(4, 4))
        style.configure("SlotAction.TCheckbutton", font=SLOT_ACTION_FONT)

        self._build_layout(driver_status, is_mock, sheets_status)
        self._schedule_tick()
        if self._ocr_reader is not None:
            self._schedule_ocr_preview()
        self.refresh_history()

    # --- UIスレッドから呼ぶ: 他スレッドからのイベントをキューに積む ---
    def post_event(self, event_name: str, payload=None) -> None:
        self._event_queue.put((event_name, payload))

    def _build_layout(self, driver_status: str, is_mock: bool, sheets_status: str) -> None:
        status_frame = ttk.Frame(self._root, padding=8)
        status_frame.pack(fill="x")

        status_text_frame = ttk.Frame(status_frame)
        status_text_frame.pack(side="left", fill="x", expand=True)

        driver_color = "orange" if is_mock else "green"
        self._driver_status_label = ttk.Label(
            status_text_frame, text=f"センサー: {driver_status}", foreground=driver_color, font=LABEL_FONT
        )
        self._driver_status_label.pack(anchor="w")

        self._sheets_status_label = ttk.Label(status_text_frame, text=f"Sheets: {sheets_status}", font=LABEL_FONT)
        self._sheets_status_label.pack(anchor="w")

        self._ocr_status_label = ttk.Label(status_text_frame, text="OCR: 未使用", font=LABEL_FONT)
        self._ocr_status_label.pack(anchor="w")

        self._ocr_mode_var = tk.BooleanVar(value=self._ocr_available)
        ocr_toggle = ttk.Checkbutton(
            status_text_frame, text="OCR自動読み取りを使う（ONの場合、待機リストは使用しません）",
            variable=self._ocr_mode_var, command=self._on_ocr_mode_toggled,
        )
        ocr_toggle.pack(anchor="w", pady=(2, 0))
        if not self._ocr_available:
            ocr_toggle.config(state="disabled")

        # GOAL結果確認パネルの自動確定トグル・カウントダウン表示（パネル本体から離れた上部に配置）
        auto_confirm_row = ttk.Frame(status_text_frame)
        auto_confirm_row.pack(anchor="w", pady=(2, 0))
        self._auto_confirm_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            auto_confirm_row, text=f"GOAL結果を{PENDING_AUTO_CONFIRM_MS // 1000}秒で自動確定",
            variable=self._auto_confirm_var, command=self._on_auto_confirm_toggled,
        ).pack(side="left")
        self._auto_confirm_countdown_label = ttk.Label(auto_confirm_row, text="", font=LABEL_FONT, foreground="blue")
        self._auto_confirm_countdown_label.pack(side="left", padx=(8, 0))

        # 待機リスト（タイマーより上に配置）: 並んでいる順にゼッケン番号を事前入力しておき、
        # 枠が空くたびに待機1から順に空き枠へ自動で進める。
        # OCR自動読み取りモードがONのときは、次の車のゼッケンはSTART時にOCRから自動入力されるため
        # このパネル自体を隠す（_on_ocr_mode_toggledで切り替える）。
        self._waiting_frame = ttk.LabelFrame(self._root, text="待機リスト（次にスタートする順）", padding=8)
        for i in range(3):
            ttk.Label(self._waiting_frame, text=f"待機{i + 1}:", font=LABEL_FONT).pack(side="left", padx=(8 if i else 0, 2))
            var = tk.StringVar()
            var.trace_add("write", lambda *_args, idx=i: self._on_waiting_list_changed(idx, self._waiting_vars[idx].get()))
            self._waiting_vars.append(var)
            ttk.Entry(self._waiting_frame, textvariable=var, width=8, font=ENTRY_FONT).pack(side="left", padx=2)

        if self._ocr_mode_var.get():
            self._waiting_frame.pack_forget()
        else:
            self._waiting_frame.pack(fill="x", padx=8, pady=8)

        if self._ocr_mock_engine is not None:
            self._build_ocr_mock_panel()

        # 両枠とも空いているときに次のSTARTをどちらに割り当てるかの選択
        start_select_frame = ttk.Frame(self._root, padding=(8, 0))
        start_select_frame.pack(fill="x")
        ttk.Label(
            start_select_frame, text="両枠が空いている場合、次のSTARTを割り当てる枠:", font=LABEL_FONT
        ).pack(side="left")
        self._next_start_var = tk.StringVar(value="A")
        for slot_id, label in SLOT_LABELS.items():
            ttk.Radiobutton(
                start_select_frame, text=label, value=slot_id, variable=self._next_start_var,
                command=lambda: self._on_next_start_slot_changed(self._next_start_var.get()),
            ).pack(side="left", padx=4)

        slots_frame = ttk.Frame(self._root, padding=8)
        slots_frame.pack(fill="x")
        slots_frame.columnconfigure(0, weight=1)
        slots_frame.columnconfigure(1, weight=1)

        # 実機センサーが何らかの理由でGOALを検知できなかった場合の手動発火用ボタン。
        # 枠Bの真上に配置する。
        manual_goal_frame = ttk.Frame(slots_frame)
        manual_goal_frame.grid(row=0, column=1, sticky="e", padx=4)
        ttk.Button(
            manual_goal_frame, text="GOALセンサー", command=self._on_manual_goal_trigger,
        ).pack(side="right")

        for col, slot_id in enumerate(("A", "B")):
            self._build_slot_panel(slots_frame, slot_id, col)

        # 直前にGOALした1件の結果確認（タイマーの下）: PT・脱輪・MC無効を加味して正式確定する
        self._build_result_confirm_panel()

        if is_mock and self._mock_driver is not None:
            mock_frame = ttk.LabelFrame(self._root, text="モック操作（テスト用）", padding=8)
            mock_frame.pack(fill="x", padx=8, pady=8)
            ttk.Button(
                mock_frame, text="STARTセンサー発火",
                command=lambda: self._mock_driver.trigger(self._start_channel),
            ).pack(side="left", padx=4)
            ttk.Button(
                mock_frame, text="GOALセンサー発火",
                command=lambda: self._mock_driver.trigger(self._goal_channel),
            ).pack(side="left", padx=4)

        lower_frame = ttk.Frame(self._root)
        lower_frame.pack(fill="both", expand=True, padx=8, pady=8)
        lower_frame.columnconfigure(0, weight=2)
        lower_frame.columnconfigure(1, weight=1)
        lower_frame.rowconfigure(0, weight=1)

        history_frame = ttk.LabelFrame(lower_frame, text="当日分タイム履歴（新しい順）", padding=8)
        history_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self._history_tree = ttk.Treeview(history_frame, columns=HISTORY_COLUMNS, show="headings", height=8)
        self._history_tree.heading("bib", text="ゼッケン")
        self._history_tree.heading("raw_time", text="生タイム")
        self._history_tree.heading("time", text="タイム")
        self._history_tree.heading("penalty", text="ペナルティ")
        self._history_tree.heading("recorded_at", text="日時")
        self._history_tree.heading("synced", text="Sheets")
        self._history_tree.column("bib", width=70, anchor="center")
        self._history_tree.column("raw_time", width=100, anchor="center")
        self._history_tree.column("time", width=100, anchor="center")
        self._history_tree.column("penalty", width=90, anchor="center")
        self._history_tree.column("recorded_at", width=150, anchor="center")
        self._history_tree.column("synced", width=70, anchor="center")
        self._history_tree.pack(fill="both", expand=True, side="left")
        self._history_tree.bind("<Double-1>", self._on_history_double_click)

        scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self._history_tree.yview)
        scrollbar.pack(fill="y", side="right")
        self._history_tree.configure(yscrollcommand=scrollbar.set)

        ranking_frame = ttk.LabelFrame(lower_frame, text="ランキング（ペナルティ込み・各ゼッケン最速）", padding=8)
        ranking_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        ranking_columns = ("rank", "bib", "time", "attempt")
        self._ranking_tree = ttk.Treeview(ranking_frame, columns=ranking_columns, show="headings", height=8)
        self._ranking_tree.heading("rank", text="順位")
        self._ranking_tree.heading("bib", text="ゼッケン")
        self._ranking_tree.heading("time", text="タイム")
        self._ranking_tree.heading("attempt", text="記録")
        self._ranking_tree.column("rank", width=50, anchor="center")
        self._ranking_tree.column("bib", width=70, anchor="center")
        self._ranking_tree.column("time", width=100, anchor="center")
        self._ranking_tree.column("attempt", width=70, anchor="center")
        self._ranking_tree.pack(fill="both", expand=True, side="left")

        ranking_scrollbar = ttk.Scrollbar(ranking_frame, orient="vertical", command=self._ranking_tree.yview)
        ranking_scrollbar.pack(fill="y", side="right")
        self._ranking_tree.configure(yscrollcommand=ranking_scrollbar.set)

        history_button_frame = ttk.Frame(self._root, padding=8)
        history_button_frame.pack(fill="x")

        ttk.Button(
            history_button_frame, text="CSV出力（当日分）", command=self._export_csv
        ).pack(side="left", padx=4)
        ttk.Button(
            history_button_frame, text="未送信をSheetsに同期", command=self._sync_pending
        ).pack(side="left", padx=4)
        ttk.Button(
            history_button_frame, text="当日履歴を全クリア", command=self._clear_all_history,
        ).pack(side="left", padx=4)

        if self._is_format3:
            self._am_pm_var = tk.StringVar(value="午前")
            am_pm_frame = ttk.Frame(history_button_frame)
            am_pm_frame.pack(side="left", padx=12)
            ttk.Label(am_pm_frame, text="送信先（練習会）:").pack(side="left", padx=(0, 4))
            ttk.Radiobutton(
                am_pm_frame, text="午前", value="午前", variable=self._am_pm_var,
                command=self._on_am_pm_toggled,
            ).pack(side="left")
            ttk.Radiobutton(
                am_pm_frame, text="午後", value="午後", variable=self._am_pm_var,
                command=self._on_am_pm_toggled,
            ).pack(side="left")

    def _on_am_pm_toggled(self) -> None:
        if self._on_am_pm_changed is not None:
            self._on_am_pm_changed(self._am_pm_var.get())

    def _build_ocr_mock_panel(self) -> None:
        """OCRエンジンがモック（実カメラ・Tesseract無し）のときの動作確認用パネル。

        実カメラが無い開発機でも、ここで注入した値が「停止中に安定して読み取れた値」として
        BibReaderにロックされ、START発火時に枠へ反映される（実カメラ運用時の動きを模擬する）。
        """
        frame = ttk.LabelFrame(self._root, text="OCRモック操作（テスト用）", padding=8)
        frame.pack(fill="x", padx=8, pady=8)

        ttk.Label(frame, text="読み取らせるゼッケン（2桁）:", font=LABEL_FONT).pack(side="left")
        ocr_inject_var = tk.StringVar()
        ttk.Entry(frame, textvariable=ocr_inject_var, width=6, font=ENTRY_FONT).pack(side="left", padx=4)

        def inject() -> None:
            self._ocr_mock_engine.set_next_value(ocr_inject_var.get().strip())

        def clear() -> None:
            ocr_inject_var.set("")
            self._ocr_mock_engine.set_next_value(None)

        ttk.Button(frame, text="この値を読み取らせる", command=inject).pack(side="left", padx=4)
        ttk.Button(frame, text="クリア（未読取に戻す）", command=clear).pack(side="left", padx=4)

    def is_ocr_mode_enabled(self) -> bool:
        return self._ocr_available and self._ocr_mode_var.get()

    def _on_ocr_mode_toggled(self) -> None:
        if self._ocr_mode_var.get():
            self._waiting_frame.pack_forget()
        else:
            self._waiting_frame.pack(fill="x", padx=8, pady=8)

    def set_ocr_status(self, text: str) -> None:
        self._ocr_status_label.config(text=f"OCR: {text}")

    def get_slot_penalty_state(self, slot_id: str) -> tuple[int, int, bool]:
        return (
            self._slot_pt_vars[slot_id].get(),
            self._slot_datsurin_vars[slot_id].get(),
            self._slot_mc_vars[slot_id].get(),
        )

    def reset_slot_penalty_state(self, slot_id: str) -> None:
        self._slot_pt_vars[slot_id].set(0)
        self._slot_datsurin_vars[slot_id].set(0)
        self._slot_mc_vars[slot_id].set(False)

    def _adjust_slot_pt(self, slot_id: str, delta: int) -> None:
        var = self._slot_pt_vars[slot_id]
        var.set(max(0, var.get() + delta))

    def _adjust_slot_datsurin(self, slot_id: str, delta: int) -> None:
        var = self._slot_datsurin_vars[slot_id]
        var.set(max(0, var.get() + delta))

    def show_ocr_candidate(self, slot_id: str, bib_number: str, frame=None) -> None:
        """START検知時にOCRのロック済み候補をその枠へ反映し、5秒間「目立つ表示」で通知する。

        光電管ユニット本体がSTART時に音を出すため、ソフトウェア側のブザーは鳴らさない。
        代わりにゼッケン欄の文字色を5秒間緑にし、カメラのライブ映像をその瞬間に確定した
        静止画（frame）に5秒間切り替える（誤読確認用）。確定はブロックしない:
        反映されたゼッケンはそのまま枠の手入力欄に入るので、誤りがあれば操作者がその場で、
        または後のGOAL確認パネルで修正できる。
        """
        self.set_bib_number(slot_id, bib_number)

        bib_entry = self._bib_entries[slot_id]
        bib_entry.config(foreground="green")

        badge = self._ocr_badge_labels[slot_id]
        badge.config(text=f"OCR読み取り: {bib_number}")

        existing_after_id = self._ocr_badge_after_ids.get(slot_id)
        if existing_after_id is not None:
            self._root.after_cancel(existing_after_id)

        def _clear_notification() -> None:
            badge.config(text="")
            bib_entry.config(foreground="black")
            self._ocr_badge_after_ids.pop(slot_id, None)

        self._ocr_badge_after_ids[slot_id] = self._root.after(5000, _clear_notification)

        if frame is not None:
            self._render_frame_to_preview(frame)
            self._ocr_frozen_until = time.monotonic() + 5.0

    def _build_result_confirm_panel(self) -> None:
        # 結果確認パネルの右側を少し空け（当日履歴の下にあるランキング表と同程度の幅）、
        # そこにカメラのライブプレビューを置く（OCR機能が有効なときのみ）。
        confirm_row_frame = ttk.Frame(self._root, padding=8)
        confirm_row_frame.pack(fill="x", padx=8, pady=8)
        confirm_row_frame.columnconfigure(0, weight=1)
        confirm_row_frame.columnconfigure(1, weight=1)

        frame = ttk.LabelFrame(
            confirm_row_frame, text=f"直前のGOAL結果確認（{PENDING_AUTO_CONFIRM_MS // 1000}秒後に自動確定／編集可）", padding=8
        )
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        if self._ocr_reader is not None:
            # _tick()（タイマー表示の100ms更新）とは別の専用ループ（_schedule_ocr_preview）で更新し、
            # 画像処理の負荷がタイマー精度に影響しないようにする。
            preview_frame = ttk.LabelFrame(confirm_row_frame, text="カメラ映像（プレビュー）", padding=4)
            preview_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
            self._ocr_preview_label = ttk.Label(
                preview_frame, text="カメラ映像なし", anchor="center", font=LABEL_FONT,
            )
            self._ocr_preview_label.pack(expand=True)

        self._pending_raw_time_label = ttk.Label(frame, text="生タイム: --", font=RAW_TIME_FONT)
        self._pending_raw_time_label.pack(anchor="w")

        info_row = ttk.Frame(frame)
        info_row.pack(fill="x", pady=(4, 0))
        bib_col = ttk.Frame(info_row)
        bib_col.pack(side="left")
        bib_row = ttk.Frame(bib_col)
        bib_row.pack(anchor="w")
        ttk.Label(bib_row, text="ゼッケン:", font=BIB_FONT).pack(side="left")
        self._pending_bib_var = tk.StringVar(value="--")
        ttk.Entry(bib_row, textvariable=self._pending_bib_var, width=6, font=BIB_FONT).pack(side="left", padx=(6, 0))
        self._pending_bib_warning_label = ttk.Label(bib_col, text="", foreground="red", font=("", 12, "bold"))
        self._pending_bib_warning_label.pack(anchor="w")
        self._pending_bib_var.trace_add("write", lambda *_args: self._update_pending_bib_warning())

        self._pending_time_var = tk.StringVar(value="0:00.000")
        ttk.Entry(info_row, textvariable=self._pending_time_var, width=10, font=TIMER_FONT).pack(side="left", padx=(24, 0))

        self._pending_sub_label = ttk.Label(frame, text="確認待ちのタイムはありません", font=LABEL_FONT)
        self._pending_sub_label.pack(anchor="w")

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=8)

        ttk.Label(controls, text="PT:", font=PENALTY_LABEL_FONT).pack(side="left")
        self._pt_var = tk.IntVar(value=0)
        ttk.Button(
            controls, text="−", width=3, style="Penalty.TButton", command=lambda: self._adjust_pt(-1),
        ).pack(side="left")
        ttk.Label(
            controls, textvariable=self._pt_var, width=3, anchor="center", font=PENALTY_LABEL_FONT,
        ).pack(side="left")
        ttk.Button(
            controls, text="＋", width=3, style="Penalty.TButton", command=lambda: self._adjust_pt(1),
        ).pack(side="left", padx=(0, 24))

        ttk.Label(controls, text="脱輪:", font=PENALTY_LABEL_FONT).pack(side="left")
        self._datsurin_var = tk.IntVar(value=0)
        ttk.Button(
            controls, text="−", width=3, style="Penalty.TButton", command=lambda: self._adjust_datsurin(-1),
        ).pack(side="left")
        ttk.Label(
            controls, textvariable=self._datsurin_var, width=3, anchor="center", font=PENALTY_LABEL_FONT,
        ).pack(side="left")
        ttk.Button(
            controls, text="＋", width=3, style="Penalty.TButton", command=lambda: self._adjust_datsurin(1),
        ).pack(side="left", padx=(0, 24))

        self._mc_invalid_var = tk.BooleanVar(value=False)

        confirm_row = ttk.Frame(frame)
        confirm_row.pack(fill="x", pady=4)

        self._confirm_button = ttk.Button(
            confirm_row, text="確定して記録", style="SlotAction.TButton",
            command=self._confirm_pending_result, state="disabled",
        )
        self._confirm_button.pack(side="left")

        ttk.Checkbutton(
            confirm_row, text="MC", variable=self._mc_invalid_var, style="SlotAction.TCheckbutton",
            command=self._update_pending_preview,
        ).pack(side="left", padx=2)

        self._pending_dnf_button = ttk.Button(
            confirm_row, text="DNF（記録あり）", style="SlotAction.TButton",
            command=self._on_pending_dnf, state="disabled",
        )
        self._pending_dnf_button.pack(side="left", padx=2)

        self._pending_discard_button = ttk.Button(
            confirm_row, text="リセット（記録なし）", style="SlotAction.TButton",
            command=self._on_pending_discard, state="disabled",
        )
        self._pending_discard_button.pack(side="left", padx=2)

    def _update_pending_bib_warning(self) -> None:
        if self._current_pending is not None and not self._pending_bib_var.get().strip():
            self._pending_bib_warning_label.config(text="ゼッケン番号を記入")
        else:
            self._pending_bib_warning_label.config(text="")

    def _adjust_pt(self, delta: int) -> None:
        self._pt_var.set(max(0, self._pt_var.get() + delta))
        self._update_pending_preview()

    def _adjust_datsurin(self, delta: int) -> None:
        self._datsurin_var.set(max(0, self._datsurin_var.get() + delta))
        self._update_pending_preview()

    def _update_pending_preview(self) -> None:
        """PT/脱輪/MC無効の変更を確定後タイム欄に反映する（手動編集は上書きされる）。"""
        if self._current_pending is None:
            self._pending_time_var.set("0:00.000")
            return

        _slot_id, _bib, raw_elapsed, status, _pt, _datsurin, _mc = self._current_pending
        if self._mc_invalid_var.get():
            self._pending_time_var.set("MC")
            return

        if status == "DNF" and self._pt_var.get() == 0 and self._datsurin_var.get() == 0:
            self._pending_time_var.set("DNF")
            return

        pt_bonus = self._pt_var.get() * self._pt_seconds
        datsurin_bonus = self._datsurin_var.get() * self._datsurin_seconds
        final_elapsed = raw_elapsed + pt_bonus + datsurin_bonus
        self._pending_time_var.set(format_time(final_elapsed))

    def _cancel_pending_timer(self) -> None:
        if self._pending_after_id is not None:
            self._root.after_cancel(self._pending_after_id)
            self._pending_after_id = None
        self._auto_confirm_deadline = None

    def _arm_auto_confirm_timer(self) -> None:
        """自動確定タイマーを（再）開始し、カウントダウン表示の基準時刻も合わせて記録する。"""
        self._cancel_pending_timer()
        self._auto_confirm_deadline = time.monotonic() + PENDING_AUTO_CONFIRM_MS / 1000
        self._pending_after_id = self._root.after(PENDING_AUTO_CONFIRM_MS, self._confirm_pending_result)

    def _update_auto_confirm_countdown(self) -> None:
        """画面上部の自動確定カウントダウン表示を更新する（_tick()から毎回呼ぶ）。"""
        if self._auto_confirm_deadline is None:
            self._auto_confirm_countdown_label.config(text="")
            return

        remaining = math.ceil(self._auto_confirm_deadline - time.monotonic())
        if remaining <= 0:
            self._auto_confirm_countdown_label.config(text="")
            return
        self._auto_confirm_countdown_label.config(text=f"残り{remaining}秒")

    def _on_auto_confirm_toggled(self) -> None:
        if self._auto_confirm_var.get():
            if self._current_pending is not None:
                self._arm_auto_confirm_timer()
        else:
            self._cancel_pending_timer()

    def _confirm_pending_result(self) -> None:
        if self._current_pending is None:
            return

        self._cancel_pending_timer()
        slot_id, _orig_bib, raw_elapsed, _orig_status, _pt, _datsurin, _mc = self._current_pending
        bib_number = self._pending_bib_var.get()
        time_text = self._pending_time_var.get().strip()

        if self._mc_invalid_var.get() or time_text == "MC":
            status = "MC"
            final_elapsed = raw_elapsed
        elif time_text == "DNF":
            status = "DNF"
            final_elapsed = raw_elapsed
        else:
            status = "OK"
            try:
                final_elapsed = parse_time(time_text)
            except (ValueError, IndexError):
                final_elapsed = raw_elapsed

        self._on_confirm_result(
            slot_id, bib_number, raw_elapsed, final_elapsed,
            self._pt_var.get(), self._datsurin_var.get(), status,
        )
        # 結果はmain.py側から show_pending / pending_cleared イベントで反映される

    def _refresh_pending_label(self) -> None:
        if self._current_pending is None:
            self._pending_sub_label.config(text="確認待ちのタイムはありません")
            self._pending_raw_time_label.config(text="生タイム: --")
            return

        slot_id, _bib, raw_elapsed, status, _pt, _datsurin, _mc = self._current_pending
        suffix = f"（他に{self._current_remaining}件待ち）" if self._current_remaining else ""
        status_note = "（DNF）" if status == "DNF" else ""
        self._pending_sub_label.config(text=f"{SLOT_LABELS[slot_id]}{status_note}{suffix}")
        self._pending_raw_time_label.config(text=f"生タイム: {format_time(raw_elapsed)}")

    def show_pending_result(
        self, item: tuple[str, str, float, str, int, int, bool], remaining_count: int,
    ) -> None:
        self._cancel_pending_timer()
        self._current_pending = item
        self._current_remaining = remaining_count
        _slot_id, bib_number, _raw_elapsed, _status, pt_count, datsurin_count, mc_flag = item
        self._pending_bib_var.set(bib_number)
        # 枠側で事前入力されていたPT/脱輪/ミスコースがあれば初期値として引き継ぐ（ここでも調整・修正可）
        self._pt_var.set(pt_count)
        self._datsurin_var.set(datsurin_count)
        self._mc_invalid_var.set(mc_flag)
        self._refresh_pending_label()
        self._update_pending_preview()
        self._update_pending_bib_warning()
        self._confirm_button.config(state="normal")
        self._pending_dnf_button.config(state="normal")
        self._pending_discard_button.config(state="normal")
        if self._auto_confirm_var.get():
            self._arm_auto_confirm_timer()

    def update_pending_remaining(self, remaining_count: int) -> None:
        self._current_remaining = remaining_count
        self._refresh_pending_label()

    def clear_pending_result(self) -> None:
        self._cancel_pending_timer()
        self._current_pending = None
        self._current_remaining = 0
        self._pending_bib_var.set("--")
        self._pending_time_var.set("0:00.000")
        self._refresh_pending_label()
        self._update_pending_bib_warning()
        self._confirm_button.config(state="disabled")
        self._pending_dnf_button.config(state="disabled")
        self._pending_discard_button.config(state="disabled")

    def _on_pending_dnf(self) -> None:
        """確認待ちの結果を、生タイムをそのままDNFとして記録する（PT/脱輪の値は使わない）。"""
        if self._current_pending is None:
            return
        slot_id = self._current_pending[0]
        if not messagebox.askyesno(
            "確認", f"{SLOT_LABELS[slot_id]}の確認待ちの結果をDNFとして記録します。よろしいですか？"
        ):
            return
        self._mc_invalid_var.set(False)
        self._pending_time_var.set("DNF")
        self._confirm_pending_result()

    def _on_pending_discard(self) -> None:
        """確認待ちの結果を保存せずに削除する（枠の「リセット（記録なし）」の確認パネル版）。"""
        if self._current_pending is None:
            return
        slot_id = self._current_pending[0]
        if not messagebox.askyesno(
            "確認", f"{SLOT_LABELS[slot_id]}の確認待ちの結果を記録せずに削除します。よろしいですか？"
        ):
            return
        self._cancel_pending_timer()
        self._on_discard_pending(slot_id)
        # 結果はmain.py側から show_pending / pending_cleared イベントで反映される

    def _build_slot_panel(self, parent: ttk.Frame, slot_id: str, col: int) -> None:
        panel = ttk.LabelFrame(parent, text=SLOT_LABELS[slot_id], padding=8)
        panel.grid(row=1, column=col, sticky="nsew", padx=4)

        top_row = ttk.Frame(panel)
        top_row.pack(fill="x")

        bib_entry_frame = ttk.Frame(top_row)
        bib_entry_frame.pack(side="left", anchor="n")
        ttk.Label(bib_entry_frame, text="ゼッケン:", font=BIB_FONT).pack(anchor="w")
        bib_row = ttk.Frame(bib_entry_frame)
        bib_row.pack(anchor="w")
        bib_var = tk.StringVar()
        self._bib_vars[slot_id] = bib_var
        bib_entry = ttk.Entry(bib_row, textvariable=bib_var, width=6, font=BIB_FONT)
        bib_entry.pack(side="left")
        self._bib_entries[slot_id] = bib_entry
        ttk.Button(
            bib_row, text="+1", command=lambda s=slot_id: self._increment_bib(s)
        ).pack(side="left", padx=4)

        bib_warning_label = ttk.Label(bib_entry_frame, text="", foreground="red", font=("", 12, "bold"))
        bib_warning_label.pack(anchor="w")
        self._bib_warning_labels[slot_id] = bib_warning_label
        bib_var.trace_add("write", lambda *_args, s=slot_id: self._update_bib_warning(s))
        self._update_bib_warning(slot_id)

        time_label = ttk.Label(top_row, text="0:00.000", font=TIMER_FONT)
        time_label.pack(side="left", padx=(16, 0))
        self._time_labels[slot_id] = time_label

        ocr_badge_label = ttk.Label(panel, text="", foreground="blue", font=("", 13, "bold"))
        ocr_badge_label.pack(anchor="w")
        self._ocr_badge_labels[slot_id] = ocr_badge_label

        state_label = ttk.Label(panel, text="START待ち", font=STATE_FONT)
        state_label.pack(pady=(8, 0))
        self._state_labels[slot_id] = state_label

        # GOAL通過カウント表示・GOALカウントリセットは現在封印中
        # （timer/lap_timer.py / timer/run_manager.pyのロジック自体は残してある）

        # PT・脱輪・ミスコースの事前入力: 走行中に見えた事実をその場で記録しておき、
        # GOAL確定時に結果確認パネルの初期値として引き渡す（ここではタイムに加算しない）。
        penalty_frame = ttk.Frame(panel)
        penalty_frame.pack(pady=(4, 0))

        pt_var = tk.IntVar(value=0)
        self._slot_pt_vars[slot_id] = pt_var
        ttk.Label(penalty_frame, text="PT:", font=SLOT_PENALTY_LABEL_FONT).pack(side="left")
        ttk.Button(
            penalty_frame, text="−", width=2, style="SlotPenalty.TButton",
            command=lambda s=slot_id: self._adjust_slot_pt(s, -1),
        ).pack(side="left")
        ttk.Label(
            penalty_frame, textvariable=pt_var, width=2, anchor="center", font=SLOT_PENALTY_LABEL_FONT,
        ).pack(side="left")
        ttk.Button(
            penalty_frame, text="＋", width=2, style="SlotPenalty.TButton",
            command=lambda s=slot_id: self._adjust_slot_pt(s, 1),
        ).pack(side="left", padx=(0, 10))

        datsurin_var = tk.IntVar(value=0)
        self._slot_datsurin_vars[slot_id] = datsurin_var
        ttk.Label(penalty_frame, text="脱輪:", font=SLOT_PENALTY_LABEL_FONT).pack(side="left")
        ttk.Button(
            penalty_frame, text="−", width=2, style="SlotPenalty.TButton",
            command=lambda s=slot_id: self._adjust_slot_datsurin(s, -1),
        ).pack(side="left")
        ttk.Label(
            penalty_frame, textvariable=datsurin_var, width=2, anchor="center", font=SLOT_PENALTY_LABEL_FONT,
        ).pack(side="left")
        ttk.Button(
            penalty_frame, text="＋", width=2, style="SlotPenalty.TButton",
            command=lambda s=slot_id: self._adjust_slot_datsurin(s, 1),
        ).pack(side="left")

        # ミスコース・DNF・リセットは1つの行にまとめ、フォント・サイズを揃える
        # （ミスコースはDNFの左隣に配置）。
        button_frame = ttk.Frame(panel)
        button_frame.pack(pady=8)

        mc_var = tk.BooleanVar(value=False)
        self._slot_mc_vars[slot_id] = mc_var
        ttk.Checkbutton(
            button_frame, text="ミスコース", variable=mc_var, style="SlotAction.TCheckbutton",
        ).pack(side="left", padx=2)
        ttk.Button(
            button_frame, text="DNF（記録あり）", style="SlotAction.TButton",
            command=lambda s=slot_id: self._confirm_then(
                self._on_dnf_slot, s, f"{SLOT_LABELS[s]}をDNFとして記録します。よろしいですか？"
            ),
        ).pack(side="left", padx=2)
        ttk.Button(
            button_frame, text="リセット（記録なし）", style="SlotAction.TButton",
            command=lambda s=slot_id: self._confirm_then(
                self._on_reset_slot, s, f"{SLOT_LABELS[s]}を記録を残さずリセットします。よろしいですか？"
            ),
        ).pack(side="left", padx=2)

    def _confirm_then(self, callback: Callable[[str], None], slot_id: str, message: str) -> None:
        if messagebox.askyesno("確認", message):
            callback(slot_id)

    def _update_bib_warning(self, slot_id: str) -> None:
        """ラベルを常時pack済みのまま文字だけ切り替える（pack/forgetだと下の要素がズレるため）。"""
        if self._bib_vars[slot_id].get().strip():
            self._bib_warning_labels[slot_id].config(text="")
        else:
            self._bib_warning_labels[slot_id].config(text="ゼッケン番号を記入")

    def _increment_bib(self, slot_id: str) -> None:
        current = self._bib_vars[slot_id].get()
        last = self._last_bib[slot_id]
        try:
            next_value = int(current) + 1 if current else (int(last) + 1 if last else 1)
        except ValueError:
            next_value = 1
        self._bib_vars[slot_id].set(str(next_value))

    def set_sheets_status(self, text: str) -> None:
        self._sheets_status_label.config(text=f"Sheets: {text}")

    def get_bib_number(self, slot_id: str) -> str:
        return self._bib_vars[slot_id].get()

    def set_bib_number(self, slot_id: str, bib_number: str) -> None:
        self._bib_vars[slot_id].set(bib_number)

    def remember_bib(self, slot_id: str, bib_number: str) -> None:
        self._last_bib[slot_id] = bib_number

    def set_waiting_entry(self, index: int, bib_number: str) -> None:
        """待機リストの表示を更新する（待機リストの自動シフト後にmain.pyから呼ぶ）。"""
        self._waiting_vars[index].set(bib_number)

    def refresh_history(self) -> None:
        for row in self._history_tree.get_children():
            self._history_tree.delete(row)

        # 新しいものが上に来るよう、記録順を反転して挿入する
        # iidに record.id を使い、編集時にどのレコードか即座に特定できるようにする
        for rec in reversed(self._local_store.get_today_records()):
            self._history_tree.insert(
                "",
                "end",
                iid=str(rec.id),
                values=(
                    rec.bib_number,
                    rec.raw_time_display(),
                    rec.time_display(),
                    rec.penalty_text,
                    rec.recorded_at,
                    "○" if rec.synced else "未送信",
                ),
            )

        self.refresh_ranking()

    def refresh_ranking(self) -> None:
        for row in self._ranking_tree.get_children():
            self._ranking_tree.delete(row)

        for rank, bib_number, elapsed_seconds, attempt_number in self._local_store.get_today_ranking():
            self._ranking_tree.insert(
                "",
                "end",
                values=(rank, bib_number, format_time(elapsed_seconds), f"{attempt_number}回目"),
            )

    def _on_history_double_click(self, event: tk.Event) -> None:
        """履歴テーブルのセルをダブルクリックしたら、その場で編集できるようにする。"""
        region = self._history_tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self._history_tree.identify_row(event.y)
        column_id = self._history_tree.identify_column(event.x)
        if not row_id or not column_id:
            return

        col_index = int(column_id.replace("#", "")) - 1
        if col_index < 0 or col_index >= len(HISTORY_COLUMNS):
            return
        col_name = HISTORY_COLUMNS[col_index]

        bbox = self._history_tree.bbox(row_id, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        current_value = self._history_tree.set(row_id, col_name)

        edit_var = tk.StringVar(value=current_value)
        entry = ttk.Entry(self._history_tree, textvariable=edit_var, font=("", 12))
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        entry.select_range(0, "end")

        def commit(_event=None) -> None:
            new_value = edit_var.get()
            entry.destroy()
            if new_value == current_value:
                return
            ok, error_message = self._on_edit_history_record(int(row_id), col_name, new_value)
            if not ok:
                messagebox.showerror("編集エラー", error_message)

        def cancel(_event=None) -> None:
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    def _export_csv(self) -> None:
        os.makedirs(_CSV_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="CSV出力先を選択",
            defaultextension=".csv",
            filetypes=[("CSVファイル", "*.csv")],
            initialdir=_CSV_DIR,
            initialfile="gymkhana_results.csv",
        )
        if not path:
            return

        count = self._local_store.export_today_csv(path)
        messagebox.showinfo("CSV出力", f"{count}件を出力しました\n{path}")

    def _sync_pending(self) -> None:
        self._on_sync_pending()

    def _clear_all_history(self) -> None:
        """当日分タイム履歴をローカルから完全に削除する（取り消せない）。Sheets/CSVは変更しない。"""
        first = messagebox.askyesno(
            "警告: 当日履歴の全クリア",
            "当日分のタイム履歴を全て削除します。\n"
            "この操作は取り消せません（ローカルの記録が消えます。Sheets・CSVは変更されません）。\n\n"
            "本当に削除しますか？",
            icon="warning",
        )
        if not first:
            return

        confirm_text = simpledialog.askstring(
            "最終確認",
            "削除を確定するには「削除」と入力してください。",
        )
        if confirm_text != "削除":
            messagebox.showinfo("キャンセル", "削除は行われませんでした。")
            return

        count = self._on_clear_history()
        messagebox.showinfo("当日履歴の全クリア", f"{count}件を削除しました。")

    def _drain_events(self) -> None:
        while True:
            try:
                event_name, payload = self._event_queue.get_nowait()
            except queue.Empty:
                break

            if event_name == "sheets_status":
                self.set_sheets_status(payload)
            elif event_name == "error":
                for label in self._state_labels.values():
                    label.config(text=f"エラー: {payload}", foreground="red")
            elif event_name == "history_updated":
                self.refresh_history()
            elif event_name == "sync_result":
                messagebox.showinfo("Sheets同期", payload)
            elif event_name == "set_bib":
                slot_id, bib_number = payload
                self.set_bib_number(slot_id, bib_number)
            elif event_name == "waiting_list_updated":
                for idx, value in enumerate(payload):
                    self.set_waiting_entry(idx, value)
            elif event_name == "show_pending":
                item, remaining_count = payload
                self.show_pending_result(item, remaining_count)
            elif event_name == "pending_remaining_updated":
                self.update_pending_remaining(payload)
            elif event_name == "pending_cleared":
                self.clear_pending_result()
            elif event_name == "ocr_candidate":
                slot_id, bib_number, frame = payload
                self.show_ocr_candidate(slot_id, bib_number, frame)

    def _schedule_tick(self) -> None:
        self._tick()
        self._root.after(100, self._schedule_tick)

    def _schedule_ocr_preview(self) -> None:
        self._update_ocr_preview()
        self._root.after(OCR_PREVIEW_INTERVAL_MS, self._schedule_ocr_preview)

    def _update_ocr_preview(self) -> None:
        """カメラの直近フレームを小さく縮小してプレビューラベルへ反映する。

        タイマー精度に関わる_tick()とは別ループで動かす（画像変換のコストを乗せないため）。
        START直後はOCR確定時の静止画を表示中（_ocr_frozen_until）なので、その間はライブ映像の
        更新をスキップする（写真を上書きしない）。
        """
        if self._ocr_frozen_until is not None:
            if time.monotonic() < self._ocr_frozen_until:
                return
            self._ocr_frozen_until = None

        frame = self._ocr_reader.get_preview_frame()
        if frame is None:
            self._ocr_preview_photo = None
            self._ocr_preview_label.config(image="", text="カメラ映像なし")
            return

        self._render_frame_to_preview(frame)

    def _render_frame_to_preview(self, frame) -> None:
        """numpy配列（BGR）のフレームをプレビューラベルに表示する（ライブ更新・静止画表示の両方から使う）。"""
        rgb_frame = frame[:, :, ::-1]
        image = Image.fromarray(rgb_frame).resize(OCR_PREVIEW_SIZE)
        photo = ImageTk.PhotoImage(image=image)
        self._ocr_preview_photo = photo  # 参照を保持しないとGCで表示が消える
        self._ocr_preview_label.config(image=photo, text="")

    def _tick(self) -> None:
        self._drain_events()
        self._update_auto_confirm_countdown()

        for slot_id in ("A", "B"):
            lap_timer = self._run_manager.lap_timers[slot_id]
            elapsed = lap_timer.current_elapsed()
            self._time_labels[slot_id].config(text=format_time(elapsed))

            state = lap_timer.state
            if state == TimerState.IDLE:
                self._state_labels[slot_id].config(text="START待ち", foreground="black")
            elif state == TimerState.RUNNING:
                order = self._run_manager.running_order(slot_id)
                if order == 1:
                    text = "計測中（前）"
                elif order == 2:
                    text = "計測中（後）"
                else:
                    text = "計測中"
                self._state_labels[slot_id].config(text=text, foreground="blue")
            elif state == TimerState.FINISHED:
                if lap_timer.result is not None and lap_timer.result.status == "DNF":
                    self._state_labels[slot_id].config(text="DNF確定", foreground="red")
                else:
                    self._state_labels[slot_id].config(text="タイム確定", foreground="darkgreen")
