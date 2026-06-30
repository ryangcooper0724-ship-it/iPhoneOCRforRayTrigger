"""固定設置カメラからの継続的なフレーム取得。

sensor/monitor.py のポーリングスレッドと同じ構造：別スレッドで継続的に読み取り、
最新フレームをロック付きで保持する。OCR側の認識ループ（bib_reader.py）が
このフレームを定期的に取り出して使う。
"""

import threading

import numpy as np


class CameraCapture:
    """cv2.VideoCaptureを継続的に読み続け、最新フレームを保持するバックグラウンドスレッド。"""

    def __init__(self, camera_index: int = 0):
        self._camera_index = camera_index
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._capture = None

    def open(self) -> tuple[bool, str]:
        """カメラを開く。失敗した場合は (False, メッセージ) を返す（呼び出し側でフォールバック）。"""
        import cv2

        capture = cv2.VideoCapture(self._camera_index)
        if not capture.isOpened():
            capture.release()
            return False, f"カメラ（index={self._camera_index}）を開けませんでした"
        self._capture = capture
        return True, "カメラに接続しました"

    def start(self) -> None:
        if self._thread is not None or self._capture is None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def get_latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._latest_frame

    def _run(self) -> None:
        while not self._stop_event.is_set():
            ok, frame = self._capture.read()
            if ok:
                with self._lock:
                    self._latest_frame = frame
