"""計測結果のローカル保存（SQLite）。

Sheets書き込みが失敗してもタイム自体は失わないよう、確定タイムは
必ずローカルDBにも保存する。後で「未送信をSheetsに同期」できる。
"""

import csv
import datetime
import sqlite3
import threading
from dataclasses import dataclass


@dataclass
class Record:
    id: int
    bib_number: str
    elapsed_seconds: float  # ペナルティ反映後の正式タイム（確定タイム）
    recorded_at: str
    synced: bool
    status: str = "OK"  # "OK" / "DNF" / "MC"（MCによるタイム無効）
    penalty_text: str = ""  # 例: "PT2脱輪1"
    raw_elapsed_seconds: float = 0.0  # ペナルティ反映前の生タイム
    target_sheet: str = ""  # 練習会用フォーマットで「午前」/「午後」のどちらに送ったか（他フォーマットは空）

    def time_display(self) -> str:
        if self.status != "OK":
            return self.status
        from timer.lap_timer import format_time
        return format_time(self.elapsed_seconds)

    def raw_time_display(self) -> str:
        from timer.lap_timer import format_time
        return format_time(self.raw_elapsed_seconds)


class LocalStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bib_number TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    recorded_at TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'OK',
                    penalty_text TEXT NOT NULL DEFAULT '',
                    raw_elapsed_seconds REAL NOT NULL DEFAULT 0,
                    target_sheet TEXT NOT NULL DEFAULT ''
                )
                """
            )
            for ddl in (
                "ALTER TABLE records ADD COLUMN status TEXT NOT NULL DEFAULT 'OK'",
                "ALTER TABLE records ADD COLUMN penalty_text TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE records ADD COLUMN raw_elapsed_seconds REAL NOT NULL DEFAULT 0",
                "ALTER TABLE records ADD COLUMN target_sheet TEXT NOT NULL DEFAULT ''",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # 既に列がある（新規DBまたは移行済み）

    def add_record(
        self,
        bib_number: str,
        elapsed_seconds: float,
        status: str = "OK",
        penalty_text: str = "",
        raw_elapsed_seconds: float | None = None,
        target_sheet: str = "",
    ) -> int:
        """確定タイムを1件保存する。生成されたレコードIDを返す。

        raw_elapsed_secondsを省略した場合はelapsed_seconds（ペナルティなし）として扱う。
        target_sheetは練習会用フォーマットでの送信先（「午前」/「午後」）。他フォーマットでは空のまま。
        """
        if raw_elapsed_seconds is None:
            raw_elapsed_seconds = elapsed_seconds

        recorded_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO records "
                "(bib_number, elapsed_seconds, recorded_at, synced, status, penalty_text, raw_elapsed_seconds, target_sheet) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
                (bib_number, elapsed_seconds, recorded_at, status, penalty_text, raw_elapsed_seconds, target_sheet),
            )
            return cur.lastrowid

    def add_dnf_record(self, bib_number: str, elapsed_seconds: float = 0.0) -> int:
        """DNFを1件保存する。生成されたレコードIDを返す。"""
        return self.add_record(bib_number, elapsed_seconds, status="DNF")

    def mark_synced(self, record_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE records SET synced = 1 WHERE id = ?", (record_id,))

    _EDITABLE_COLUMNS = {
        "bib_number", "elapsed_seconds", "raw_elapsed_seconds",
        "status", "penalty_text", "recorded_at", "synced", "target_sheet",
    }

    def update_record(self, record_id: int, **fields) -> None:
        """指定フィールドのみ更新する（履歴の手動編集用）。キーは_EDITABLE_COLUMNSのみ許可。"""
        if not fields:
            return
        invalid = set(fields) - self._EDITABLE_COLUMNS
        if invalid:
            raise ValueError(f"更新できない列です: {invalid}")

        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [record_id]
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE records SET {assignments} WHERE id = ?", values)

    def clear_today_records(self) -> int:
        """当日分の履歴を削除する（新規大会開始時、Sheets側もリセットするのに合わせて呼ぶ）。

        削除した件数を返す。
        """
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM records WHERE recorded_at LIKE ?", (f"{today}%",))
            return cur.rowcount

    def get_record(self, record_id: int) -> "Record | None":
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT id, bib_number, elapsed_seconds, recorded_at, synced, status, penalty_text, raw_elapsed_seconds, target_sheet "
                "FROM records WHERE id = ?",
                (record_id,),
            )
            row = cur.fetchone()
        return self._rows_to_records([row])[0] if row else None

    def _rows_to_records(self, rows) -> list[Record]:
        return [
            Record(
                id=r[0], bib_number=r[1], elapsed_seconds=r[2], recorded_at=r[3],
                synced=bool(r[4]), status=r[5], penalty_text=r[6], raw_elapsed_seconds=r[7],
                target_sheet=r[8] if len(r) > 8 else "",
            )
            for r in rows
        ]

    def get_today_records(self) -> list[Record]:
        """当日分を記録順（古い→新しい）で返す。"""
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT id, bib_number, elapsed_seconds, recorded_at, synced, status, penalty_text, raw_elapsed_seconds, target_sheet "
                "FROM records WHERE recorded_at LIKE ? ORDER BY id",
                (f"{today}%",),
            )
            rows = cur.fetchall()
        return self._rows_to_records(rows)

    def get_unsynced_records(self) -> list[Record]:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT id, bib_number, elapsed_seconds, recorded_at, synced, status, penalty_text, raw_elapsed_seconds, target_sheet "
                "FROM records WHERE synced = 0 ORDER BY id"
            )
            rows = cur.fetchall()
        return self._rows_to_records(rows)

    def get_today_ranking(self) -> list[tuple[int, str, float, int]]:
        """当日分から、ゼッケンごとの最速タイム（status="OK"のみ対象）でランキングを作る。

        戻り値: [(順位, ゼッケン番号, 最速タイム秒, 何回目の記録か), ...] 速い順。
        「何回目」は、そのゼッケンの当日の全記録（OK/DNF/MC含む）を時系列で数えたときの順番。
        """
        records = self.get_today_records()  # id昇順 = 時系列順
        by_bib: dict[str, list[Record]] = {}
        for rec in records:
            by_bib.setdefault(rec.bib_number, []).append(rec)

        entries: list[tuple[float, str, int]] = []  # (最速タイム, ゼッケン, 何回目)
        for bib, recs in by_bib.items():
            ok_with_index = [(i + 1, r) for i, r in enumerate(recs) if r.status == "OK"]
            if not ok_with_index:
                continue
            attempt_number, best_rec = min(ok_with_index, key=lambda pair: pair[1].elapsed_seconds)
            entries.append((best_rec.elapsed_seconds, bib, attempt_number))

        entries.sort(key=lambda e: e[0])
        return [(rank + 1, bib, elapsed, attempt) for rank, (elapsed, bib, attempt) in enumerate(entries)]

    def export_today_csv(self, csv_path: str) -> int:
        """当日分の記録をCSVに出力する（新しい順）。出力した件数を返す。"""
        records = list(reversed(self.get_today_records()))
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["ゼッケン番号", "生タイム", "タイム", "ペナルティ", "日時", "Sheets同期済み"])
            for rec in records:
                writer.writerow(
                    [
                        rec.bib_number, rec.raw_time_display(), rec.time_display(), rec.penalty_text,
                        rec.recorded_at, "○" if rec.synced else "",
                    ]
                )
        return len(records)
