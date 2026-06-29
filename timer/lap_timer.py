"""タイマー・GOAL通過カウントの管理。

START検知でタイマー開始。GOALは2回目の通過でタイマー停止・タイム確定。
"""

import time
from dataclasses import dataclass
from enum import Enum, auto


class TimerState(Enum):
    IDLE = auto()       # START待ち
    RUNNING = auto()    # 計測中（GOAL1回目待ち or 2回目待ち）
    FINISHED = auto()   # タイム確定済み


@dataclass
class FinishedResult:
    elapsed_seconds: float
    finished_at: float  # time.time()のタイムスタンプ
    status: str = "OK"  # "OK" または "DNF"


class LapTimer:
    """1回の計測（START〜GOAL通過N回目）のライフサイクルを管理する。

    GOAL通過の確定回数（1回 or 2回）はコースレイアウトによって変わるため、
    goal_count_to_finishでインスタンスごとに設定可能。
    """

    DEFAULT_GOAL_COUNT_TO_FINISH = 1

    def __init__(self, goal_count_to_finish: int = DEFAULT_GOAL_COUNT_TO_FINISH):
        self._state = TimerState.IDLE
        self._start_time: float | None = None
        self._goal_pass_count = 0
        self._result: FinishedResult | None = None
        self._goal_count_to_finish = goal_count_to_finish

    @property
    def state(self) -> TimerState:
        return self._state

    @property
    def goal_pass_count(self) -> int:
        return self._goal_pass_count

    @property
    def goal_count_to_finish(self) -> int:
        return self._goal_count_to_finish

    @goal_count_to_finish.setter
    def goal_count_to_finish(self, value: int) -> None:
        self._goal_count_to_finish = value

    @property
    def result(self) -> FinishedResult | None:
        return self._result

    def on_start_trigger(self) -> bool:
        """STARTセンサー検知時に呼ぶ。新規計測を開始した場合Trueを返す。"""
        if self._state in (TimerState.RUNNING,):
            return False  # 計測中はSTART再検知を無視

        self._state = TimerState.RUNNING
        self._start_time = time.monotonic()
        self._goal_pass_count = 0
        self._result = None
        return True

    def on_goal_trigger(self) -> tuple[bool, int]:
        """GOALセンサー検知時に呼ぶ。

        戻り値: (タイム確定したか, 現在の通過回数)
        """
        if self._state != TimerState.RUNNING:
            return False, self._goal_pass_count

        self._goal_pass_count += 1

        if self._goal_pass_count >= self._goal_count_to_finish:
            elapsed = time.monotonic() - self._start_time
            self._result = FinishedResult(elapsed_seconds=elapsed, finished_at=time.time())
            self._state = TimerState.FINISHED
            return True, self._goal_pass_count

        return False, self._goal_pass_count

    def current_elapsed(self) -> float:
        """計測中の経過時間（秒）。未開始/確定後は0または確定値。"""
        if self._state == TimerState.RUNNING and self._start_time is not None:
            return time.monotonic() - self._start_time
        if self._state == TimerState.FINISHED and self._result is not None:
            return self._result.elapsed_seconds
        return 0.0

    def reset_goal_count(self) -> None:
        """GOAL通過カウントのみリセット（やり直し用）。計測中のみ有効。"""
        if self._state == TimerState.RUNNING:
            self._goal_pass_count = 0

    def mark_dnf(self) -> bool:
        """GOALを待たずDNFとして確定する。RUNNING中のみ有効。確定した場合Trueを返す。"""
        if self._state != TimerState.RUNNING:
            return False

        elapsed = time.monotonic() - self._start_time
        self._result = FinishedResult(elapsed_seconds=elapsed, finished_at=time.time(), status="DNF")
        self._state = TimerState.FINISHED
        return True

    def reset(self) -> None:
        """記録を残さず計測全体をリセットしIDLEに戻す（やり直し用）。"""
        self._state = TimerState.IDLE
        self._start_time = None
        self._goal_pass_count = 0
        self._result = None


def format_time(seconds: float) -> str:
    """秒数を 0:12.345 形式（分:秒.ミリ秒）に整形する。"""
    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"


def parse_time(text: str) -> float:
    """format_time()の逆変換。"M:SS.mmm"形式の文字列を秒数(float)に変換する。"""
    minutes_str, _sep, seconds_str = text.partition(":")
    return int(minutes_str) * 60 + float(seconds_str)
