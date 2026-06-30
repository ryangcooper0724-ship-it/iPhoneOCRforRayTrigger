"""カメラ・Tesseractが無い開発環境用のモックOCRエンジン。

UIから `set_next_value(bib)` を呼ぶことで、次回以降の読み取り結果を模擬できる。
"""

import threading

import numpy as np

from ocr.engine_base import OcrEngineBase


class MockOcrEngine(OcrEngineBase):
    """外部から注入された値をそのまま返すだけのモックエンジン。

    値が未設定（None）の間はNoneを返す（「ゼッケンがまだ写っていない」状態を模す）。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._next_value: str | None = None

    @property
    def is_mock(self) -> bool:
        return True

    def set_next_value(self, bib_number: str | None) -> None:
        """次回以降の認識結果として返す値を設定する（空文字/Noneでクリア）。"""
        with self._lock:
            self._next_value = bib_number or None

    def recognize(self, frame: np.ndarray | None) -> str | None:
        with self._lock:
            return self._next_value
