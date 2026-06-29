"""START/GOALチャンネルをポーリングし、立ち上がりエッジをコールバックで通知する。"""

import threading
import time
from typing import Callable

from sensor.driver_base import SensorDriverBase


class SensorMonitor:
    """別スレッドでセンサーをポーリングし、0→1の立ち上がりのみ検知する。

    チャタリング除去: 立ち上がり検知後 debounce_ms の間は同チャンネルの
    再トリガーを無視する。
    """

    def __init__(
        self,
        driver: SensorDriverBase,
        start_channel: int,
        goal_channel: int,
        poll_interval_ms: int,
        debounce_ms: int,
        on_start_trigger: Callable[[], None],
        on_goal_trigger: Callable[[], None],
        on_error: Callable[[Exception], None] | None = None,
    ):
        self._driver = driver
        self._start_channel = start_channel
        self._goal_channel = goal_channel
        self._poll_interval = poll_interval_ms / 1000.0
        self._debounce = debounce_ms / 1000.0
        self._on_start_trigger = on_start_trigger
        self._on_goal_trigger = on_goal_trigger
        self._on_error = on_error

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_state = {start_channel: 0, goal_channel: 0}
        self._last_trigger_time = {start_channel: 0.0, goal_channel: 0.0}

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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_channel(self._start_channel, self._on_start_trigger)
                self._poll_channel(self._goal_channel, self._on_goal_trigger)
            except Exception as exc:  # ドライバ読み取り失敗などをUIへ伝える
                if self._on_error is not None:
                    self._on_error(exc)
            time.sleep(self._poll_interval)

    def _poll_channel(self, channel_no: int, on_trigger: Callable[[], None]) -> None:
        value = self._driver.read_channel(channel_no)
        previous = self._last_state[channel_no]
        self._last_state[channel_no] = value

        if previous == 0 and value == 1:
            now = time.monotonic()
            if now - self._last_trigger_time[channel_no] >= self._debounce:
                self._last_trigger_time[channel_no] = now
                on_trigger()
