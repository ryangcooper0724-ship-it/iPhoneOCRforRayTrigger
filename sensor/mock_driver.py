"""DLLが無い開発環境用のモックドライバ。

UIから `trigger(channel_no)` を呼ぶことでセンサー遮断を模擬できる。
"""

import threading

from sensor.driver_base import SensorDriverBase


class MockDriver(SensorDriverBase):
    """チャンネルごとの状態をメモリ上で保持するモックドライバ。

    trigger() 呼び出し後、一定時間 (pulse_ms) だけ該当チャンネルを1にする。
    実機の「光電管が遮断されている間は1、通過後0に戻る」動作を模した簡易再現。
    """

    def __init__(self, pulse_ms: int = 150):
        self._pulse_ms = pulse_ms
        self._channel_state: dict[int, int] = {}
        self._lock = threading.Lock()

    @property
    def is_mock(self) -> bool:
        return True

    def connect(self) -> tuple[bool, str]:
        return True, "モックモードで起動しました（実機未接続）"

    def read_channel(self, channel_no: int) -> int:
        with self._lock:
            return self._channel_state.get(channel_no, 0)

    def trigger(self, channel_no: int) -> None:
        """指定チャンネルをpulse_ms間だけ1にする（センサー遮断を模擬）。"""
        with self._lock:
            self._channel_state[channel_no] = 1

        timer = threading.Timer(self._pulse_ms / 1000.0, self._clear, args=(channel_no,))
        timer.daemon = True
        timer.start()

    def _clear(self, channel_no: int) -> None:
        with self._lock:
            self._channel_state[channel_no] = 0

    def close(self) -> None:
        pass
