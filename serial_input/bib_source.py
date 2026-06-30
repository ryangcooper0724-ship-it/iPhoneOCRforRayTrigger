"""ESP32からUSBシリアル経由で送られてくるゼッケン確定値を受信・保持する。

iPhone（Vision Frameworkでの認識・安定化判定）→ ESP32（Wi-Fi受信→シリアル転送）
→ このモジュール、という経路で1行1JSONの形式で「既に確定済みの」ゼッケン値が
届く。安定化（連続一致判定）は送信元（iPhone）側で完結しているため、ここでは
再デバウンスせず、受信できた最新の有効値をそのまま保持するだけでよい。
"""

import json
import re
import threading
import time

_BIB_PATTERN = re.compile(r"^\d{1,2}$")


def parse_bib_line(line: str) -> str | None:
    """シリアルから届いた1行をパースし、有効なゼッケン値があれば返す。

    壊れたJSON・bibフィールド欠落・桁数不正（1〜2桁の数字以外）は
    すべてNoneを返す（呼び出し側はその行を黙って無視すればよい）。
    """
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    bib = payload.get("bib") if isinstance(payload, dict) else None
    if not isinstance(bib, str):
        return None
    if not _BIB_PATTERN.match(bib):
        return None
    return bib


class SerialBibSource:
    """指定COMポートを監視し、直近に受信した確定済みゼッケン値を保持する。

    BibReader（ocr/bib_reader.py）と同じ get_locked_candidate() / get_locked_frame()
    インターフェースを持たせることで、main.py側の呼び出しコードを共通化できるように
    している（画像は無いのでget_locked_frame()は常にNone）。
    """

    def __init__(self, port: str, baudrate: int = 115200, poll_interval_ms: int = 100):
        self._port = port
        self._baudrate = baudrate
        self._poll_interval = poll_interval_ms / 1000.0

        self._lock = threading.Lock()
        self._locked_candidate: str | None = None
        self._serial = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._close_serial()

    def get_locked_candidate(self) -> str | None:
        """直近に受信した確定済みのゼッケン候補を返す（次の値が届くまで保持）。"""
        with self._lock:
            return self._locked_candidate

    def get_locked_frame(self):
        """互換性のためのメソッド。シリアル経由には画像が無いので常にNone。"""
        return None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._serial is None:
                self._try_open_serial()
                if self._serial is None:
                    time.sleep(self._poll_interval)
                    continue
            self._read_available_lines()
            time.sleep(self._poll_interval)

    def _try_open_serial(self) -> None:
        import serial

        try:
            self._serial = serial.Serial(self._port, self._baudrate, timeout=0)
        except Exception:
            self._serial = None

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def _read_available_lines(self) -> None:
        try:
            while self._serial.in_waiting > 0:
                raw = self._serial.readline()
                line = raw.decode("utf-8", errors="ignore")
                bib = parse_bib_line(line)
                if bib is not None:
                    with self._lock:
                        self._locked_candidate = bib
        except Exception:
            self._close_serial()
