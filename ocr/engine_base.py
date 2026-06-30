"""OCRエンジンの共通インターフェース定義。"""

from abc import ABC, abstractmethod

import numpy as np


class OcrEngineBase(ABC):
    """ゼッケン認識エンジンが実装すべき共通インターフェース。

    将来Tesseract以外（クラウドOCR等）に差し替える場合は、このインターフェースを
    実装するクラスを追加し、main.pyのbuild_ocr_reader()で選択できるようにする。
    """

    @abstractmethod
    def recognize(self, frame: np.ndarray | None) -> str | None:
        """1フレームから2桁のゼッケン番号を読み取る。読み取れなければNoneを返す。

        frameがNone（カメラ未接続・モック時）の場合は実装側で適宜無視してよい。
        """

    def recognize_with_confidence(self, frame: np.ndarray | None) -> tuple[str | None, float]:
        """ゼッケン番号と信頼度（0-100）のペアを返す。

        デフォルト実装はrecognize()の結果をそのまま流用し、値があれば信頼度100、
        無ければ0として扱う。信頼度を独自に算出できるエンジン（Tesseract等）は
        このメソッドをオーバーライドする。BibReaderはこちらを呼び出す。
        """
        value = self.recognize(frame)
        return value, 100.0 if value else 0.0
