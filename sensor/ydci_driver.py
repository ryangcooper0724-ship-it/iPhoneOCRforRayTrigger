"""Y2 Corporation UBシリーズ DIOボード (YDCI.DLL) のラッパー。

公式Python APIドキュメント:
https://www.y2c.co.jp/ub/ub_dio88/python/
"""

import ctypes
import os

from common.paths import resolve_base_dir
from sensor.driver_base import SensorDriverBase

YDCI_RESULT_SUCCESS = 0
YDCI_OPEN_NORMAL = 0


class YdciDriverError(Exception):
    """YDCI.DLL関連のエラー。"""


class YdciDriver(SensorDriverBase):
    """YDCI.DLLをctypes経由で呼び出す実機ドライバ。"""

    def __init__(self, board_model: str, board_id_switch: int, dll_path: str | None = None):
        self._board_model = board_model.encode("ascii")
        self._board_id_switch = board_id_switch
        self._dll_path = dll_path or self._default_dll_path()
        self._ydci = None
        self._board_id = ctypes.c_ushort()

    @staticmethod
    def _default_dll_path() -> str:
        # main.py（exe化時はexe本体）と同じフォルダにYdci.dllを置く前提。
        base_dir = resolve_base_dir(__file__, levels_up=1)
        return os.path.join(base_dir, "Ydci.dll")

    @property
    def is_mock(self) -> bool:
        return False

    def connect(self) -> tuple[bool, str]:
        if not os.path.exists(self._dll_path):
            return False, f"Ydci.dllが見つかりません: {self._dll_path}"

        try:
            self._ydci = ctypes.WinDLL(self._dll_path)
        except OSError as exc:
            return False, f"Ydci.dllの読み込みに失敗しました: {exc}"

        try:
            result = self._ydci.YdciOpen(
                self._board_id_switch,
                self._board_model,
                ctypes.byref(self._board_id),
                YDCI_OPEN_NORMAL,
            )
        except OSError as exc:
            return False, f"YdciOpen呼び出しに失敗しました: {exc}"

        if result != YDCI_RESULT_SUCCESS:
            return False, f"UBボードへの接続に失敗しました (エラーコード: {result})"

        return True, f"UBボードに接続しました (board_id={self._board_id.value})"

    def read_channel(self, channel_no: int) -> int:
        if self._ydci is None:
            raise YdciDriverError("ドライバが接続されていません")

        input_data = ctypes.c_ubyte()
        result = self._ydci.YdciDioInput(
            self._board_id, ctypes.byref(input_data), channel_no, 1
        )
        if result != YDCI_RESULT_SUCCESS:
            raise YdciDriverError(f"YdciDioInputに失敗しました (チャンネル{channel_no}, エラーコード: {result})")

        return 1 if input_data.value else 0

    def close(self) -> None:
        if self._ydci is not None:
            self._ydci.YdciClose(self._board_id)
            self._ydci = None
