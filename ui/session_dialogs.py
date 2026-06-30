"""大会セッション開始時のTkinterダイアログ（再接続確認・フォーマット選択・大会名入力）。

sheets/manager.py（ビジネスロジック層）はTkinterに依存してはならないため、
ダイアログの表示はここに置き、結果だけをコールバックとしてsheets.manager.start_session()へ渡す。
"""

import tkinter as tk
from tkinter import messagebox, simpledialog


def _prompt_format_choice(config: dict, root: tk.Tk) -> str:
    """新規大会開始時に、使用するスプレッドシートのフォーマットを選んでもらう。

    config.jsonのtemplates配下に定義されたフォーマット名をボタンとして表示する。
    """
    templates = config.get("templates", {})
    format_keys = list(templates.keys()) or ["format1"]

    dialog = tk.Toplevel(root)
    dialog.title("フォーマット選択")
    dialog.resizable(False, False)
    tk.Label(dialog, text="使用するスプレッドシートのフォーマットを選んでください", padx=20, pady=10).pack()

    choice = {"value": None}

    def pick(key: str) -> None:
        choice["value"] = key
        dialog.destroy()

    for key in format_keys:
        label = templates.get(key, {}).get("name", key)
        tk.Button(dialog, text=label, width=28, command=lambda k=key: pick(k)).pack(padx=20, pady=5)

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.grab_set()
    dialog.wait_window()
    return choice["value"] or format_keys[0]


def prompt_session_start(
    config: dict, existing_event_name: str | None, existing_date: str | None,
) -> tuple[bool, str | None, str | None]:
    """sheets.manager.start_session()から呼ぶ、大会開始時の一連のダイアログ。

    existing_event_name/existing_dateは前回のsession.jsonの内容（無ければ両方None）。
    既存のTkルートが無い場合は一時的に作成し、終了後に破棄する。

    戻り値: (reconnect, format_key, event_name)
    - 前回の大会に再接続する場合: (True, None, None)
    - 新規大会として開始する場合: (False, format_key, event_name)
      event_nameは入力されなかった/キャンセルされた場合はNone。
    """
    temp_root = None
    if tk._default_root is None:
        temp_root = tk.Tk()
        temp_root.withdraw()
    root = tk._default_root

    try:
        if existing_event_name is not None:
            reconnect = messagebox.askyesno(
                "前回の大会への再接続",
                f"前回の大会「{existing_event_name}」（{existing_date}）に再接続しますか？\n"
                "「いいえ」を選ぶと新規の大会として開始します。",
            )
            if reconnect:
                return True, None, None

            messagebox.showwarning(
                "新規大会として開始",
                "「いいえ」が選択されました。このまま大会名を入力すると新規の大会として開始され、"
                "本日のローカル履歴がクリアされます。\n"
                "続く大会名の入力をキャンセルすれば、何も変更せずに終了できます。",
            )

        format_key = _prompt_format_choice(config, root)
        event_name = simpledialog.askstring("大会名", "大会名を入力してください:")
        return False, format_key, event_name
    finally:
        if temp_root is not None:
            temp_root.destroy()
