"""2台同時出走（枠A・枠B）のSTART/GOAL割り当てを管理する。

START: 「空いている枠（IDLEまたは確定済み）」が1つだけならそこへ自動割当。
       両方空いていれば、操作者が事前に選んだ next_start_slot に割当。
GOAL : 「先に出走している（古い）」枠が常にGOAL対象になる
       （例: 1台目出走→2台目出走→1台目GOAL→3台目出走→2台目GOAL...）。
       2枠同時に走行中でも、どちらがGOALかを操作者が選ぶ必要はない。

GOAL確定回数（1回/2回）を枠ごとに変える機能は実装済みだが現在UIからは
封印中（set_goal_count/set_goal_count_allは残してあるので将来復活可能）。
"""

from dataclasses import dataclass

from timer.lap_timer import LapTimer, TimerState

SLOT_IDS = ("A", "B")


@dataclass
class GoalAttributionResult:
    slot_id: str
    finished: bool
    goal_pass_count: int


class RunManager:
    def __init__(self):
        self.lap_timers: dict[str, LapTimer] = {slot: LapTimer() for slot in SLOT_IDS}
        self.bib_numbers: dict[str, str] = {slot: "" for slot in SLOT_IDS}
        self.next_start_slot: str = "A"
        self._start_sequence_counter = 0
        self._start_sequence: dict[str, int] = {}

    def available_slots(self) -> list[str]:
        """新規STARTを割り当てられる枠（IDLE or 確定済み）。"""
        return [
            slot for slot in SLOT_IDS
            if self.lap_timers[slot].state in (TimerState.IDLE, TimerState.FINISHED)
        ]

    def running_slots(self) -> list[str]:
        return [slot for slot in SLOT_IDS if self.lap_timers[slot].state == TimerState.RUNNING]

    def running_order(self, slot_id: str) -> int | None:
        """両枠が同時に走行中のとき、その枠が何番目に出走したか（1=先、2=後）を返す。

        1台のみ走行中、またはslot_idが走行中でない場合はNone（順序を表示する意味がないため）。
        GOAL対象は常に1（先に出走した方）になる。
        """
        running = self.running_slots()
        if slot_id not in running or len(running) < 2:
            return None
        ordered = sorted(running, key=lambda s: self._start_sequence.get(s, 0))
        return ordered.index(slot_id) + 1

    def set_bib(self, slot_id: str, bib_number: str) -> None:
        self.bib_numbers[slot_id] = bib_number

    def set_next_start_slot(self, slot_id: str) -> None:
        self.next_start_slot = slot_id

    def set_goal_count(self, slot_id: str, count: int) -> None:
        """その枠のGOAL確定回数（1回 or 2回）を設定する。コースにより変わる。（現在UIから封印中）"""
        self.lap_timers[slot_id].goal_count_to_finish = count

    def set_goal_count_all(self, count: int) -> None:
        """両枠まとめてGOAL確定回数を設定する。（現在UIから封印中）"""
        for slot in SLOT_IDS:
            self.set_goal_count(slot, count)

    def handle_start_trigger(self) -> str | None:
        """STARTセンサー検知時に呼ぶ。開始した枠IDを返す（開始できなければNone）。"""
        available = self.available_slots()
        if not available:
            return None  # 両枠とも走行中のため新規スタート不可

        if len(available) == 1:
            target = available[0]
        else:
            target = self.next_start_slot if self.next_start_slot in available else available[0]

        self.lap_timers[target].on_start_trigger()
        self._start_sequence_counter += 1
        self._start_sequence[target] = self._start_sequence_counter
        return target

    def handle_goal_trigger(self) -> GoalAttributionResult | None:
        """GOALセンサー検知時に呼ぶ。

        走行中の枠が1つだけならそこが対象。2枠同時に走行中の場合は、
        「先に出走している（古い）」枠が常に対象になる（操作者の判断は不要）。
        """
        running = self.running_slots()
        if not running:
            return None

        if len(running) == 1:
            slot = running[0]
        else:
            slot = min(running, key=lambda s: self._start_sequence.get(s, 0))

        finished, count = self.lap_timers[slot].on_goal_trigger()
        return GoalAttributionResult(slot_id=slot, finished=finished, goal_pass_count=count)

    def reset_slot(self, slot_id: str) -> None:
        """記録を残さずリセットする（やり直し用）。"""
        self.lap_timers[slot_id].reset()

    def mark_dnf(self, slot_id: str) -> bool:
        """DNFとして確定する（GOALを待たずに終了）。確定できればTrue。"""
        return self.lap_timers[slot_id].mark_dnf()

    def reset_goal_count_slot(self, slot_id: str) -> None:
        self.lap_timers[slot_id].reset_goal_count()
