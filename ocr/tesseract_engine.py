"""Tesseract（pytesseract）＋OpenCVによるゼッケン認識エンジン（デフォルト実装）。"""

import re

import numpy as np

from ocr.engine_base import OcrEngineBase

_BIB_PATTERN = re.compile(r"^\d{1,2}$")
_PSM_MODES = (7, 8)  # 7: 単一行として扱う, 8: 単一単語として扱う


class TesseractOcrEngine(OcrEngineBase):
    """2桁の数字（ゼッケン番号）のみを認識対象とするOCRエンジン。

    複数の前処理パターン（Otsu二値化／適応的二値化）× 複数のpsmモードで認識を試み、
    image_to_dataの信頼度（conf）が最も高い候補を採用する。固定カメラの照明ムラや
    距離によるボケに対する頑健性を上げるための工夫。

    Tesseract本体がシステムにインストールされている必要がある（pip install pytesseractは
    Pythonバインディングのみで本体は別途必要）。tesseract_cmd_pathで本体の場所を指定する。
    """

    def __init__(self, tesseract_cmd_path: str | None = None):
        import pytesseract

        if tesseract_cmd_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd_path
        self._pytesseract = pytesseract

    def recognize(self, frame: np.ndarray | None) -> str | None:
        value, _confidence = self.recognize_with_confidence(frame)
        return value

    def recognize_with_confidence(self, frame: np.ndarray | None) -> tuple[str | None, float]:
        if frame is None:
            return None, 0.0

        best_value: str | None = None
        best_conf = 0.0
        for variant in self._preprocess_variants(frame):
            for psm in _PSM_MODES:
                value, conf = self._recognize_variant(variant, psm)
                if value is not None and conf > best_conf:
                    best_value, best_conf = value, conf
        return best_value, best_conf

    def _recognize_variant(self, image: np.ndarray, psm: int) -> tuple[str | None, float]:
        from pytesseract import Output

        data = self._pytesseract.image_to_data(
            image,
            config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
            output_type=Output.DICT,
        )
        best: tuple[str, float] | None = None
        for text, conf in zip(data["text"], data["conf"]):
            candidate = text.strip()
            if not _BIB_PATTERN.match(candidate):
                continue
            try:
                conf_value = float(conf)
            except ValueError:
                continue
            if conf_value < 0:
                continue
            if best is None or conf_value > best[1]:
                best = (candidate, conf_value)
        return best if best is not None else (None, 0.0)

    def _preprocess_variants(self, frame: np.ndarray) -> list[np.ndarray]:
        """グレースケール化→コントラスト強調→ノイズ除去→拡大した上で、
        二値化パターン違い（Otsu固定閾値／適応的二値化）の2枚を候補として返す。

        適応的二値化は照明ムラに強く、Otsuは均一な照明下で安定しやすいため、
        どちらが良い結果を出すかは設置環境次第。両方を候補にして信頼度で選ばせる。
        """
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        denoised = cv2.fastNlMeansDenoising(enhanced, h=10)
        upscaled = cv2.resize(denoised, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

        otsu = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        adaptive = cv2.adaptiveThreshold(
            upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
        )
        return [otsu, adaptive]
