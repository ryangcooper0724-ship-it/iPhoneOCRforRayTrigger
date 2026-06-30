"""カメラ＋OCRエンジンを束ね、「停止中に安定して読み取れた値」を保持・提供する。

スタート待機中は車が停止しているため、同じ認識結果が連続するはずである。
これを利用し、STARTセンサー検知の瞬間（発進直後でブレやすい）の生の値ではなく、
停止中に確定済みの値（ロック値）を main.py 側に渡す。ロック値は次の車の認識結果が
新たに安定するまで保持され続ける（前の値を上書きしない）。
"""

import threading
import time

from ocr.camera_capture import CameraCapture
from ocr.engine_base import OcrEngineBase


class BibReader:
    def __init__(
        self,
        engine: OcrEngineBase,
        camera: CameraCapture | None,
        poll_interval_ms: int = 250,
        confirm_count: int = 3,
        min_confidence: float = 60.0,
    ):
        self._engine = engine
        self._camera = camera
        self._poll_interval = poll_interval_ms / 1000.0
        self._confirm_count = max(1, confirm_count)
        self._min_confidence = min_confidence

        self._lock = threading.Lock()
        self._locked_candidate: str | None = None
        self._locked_frame = None
        self._last_raw_value: str | None = None
        self._streak_count = 0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._camera is not None:
            self._camera.start()
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
        if self._camera is not None:
            self._camera.stop()

    def get_locked_candidate(self) -> str | None:
        """直近で停止中に確定した（次の車の確定まで保持される）ゼッケン候補を返す。"""
        with self._lock:
            return self._locked_candidate

    def get_locked_frame(self):
        """ロック確定が起きた瞬間のカメラフレームを返す（誤読確認用、次の車の確定まで保持）。"""
        with self._lock:
            return self._locked_frame

    def get_preview_frame(self):
        """画面に表示するための直近カメラフレームを返す（カメラ未接続/モック時はNone）。"""
        if self._camera is None:
            return None
        return self._camera.get_latest_frame()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            frame = self._camera.get_latest_frame() if self._camera is not None else None
            raw_value, confidence = self._engine.recognize_with_confidence(frame)
            self._observe(raw_value, confidence, frame)
            time.sleep(self._poll_interval)

    def _observe(self, raw_value: str | None, confidence: float = 100.0, frame=None) -> None:
        """生の認識値を1件処理する。同じ値がconfirm_count回連続したらロック値を更新する。

        信頼度（confidence）がmin_confidence未満の読み取りは「読めなかった」（None）として
        扱い、連続カウントを途切れさせる（低信頼度の誤読でロックが汚染されるのを防ぐ）。
        ロックが新たに確定した瞬間のframeも一緒に記録する（誤読確認用のスナップショット）。
        """
        with self._lock:
            if raw_value is not None and confidence < self._min_confidence:
                raw_value = None

            if raw_value is None or raw_value != self._last_raw_value:
                self._last_raw_value = raw_value
                self._streak_count = 1 if raw_value is not None else 0
                return

            self._streak_count += 1
            if self._streak_count >= self._confirm_count and raw_value != self._locked_candidate:
                self._locked_candidate = raw_value
                self._locked_frame = frame.copy() if hasattr(frame, "copy") else frame
