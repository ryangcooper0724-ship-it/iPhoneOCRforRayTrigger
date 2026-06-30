"""ocr/bib_reader.py の番犬テスト。

実カメラ・実Tesseractには依存せず、フェイクのエンジン・カメラで
「同じ値がconfirm_count回連続したらロックする」「ロック後は次の安定値まで保持する」
という挙動だけを検証する（BibReaderのバックグラウンドスレッドは使わず、
_observe()を直接呼んで同期的にテストする）。
"""

from ocr.bib_reader import BibReader
from ocr.engine_base import OcrEngineBase


class _FakeEngine(OcrEngineBase):
    def recognize(self, frame):
        return None


def _make_reader(confirm_count: int = 3) -> BibReader:
    return BibReader(_FakeEngine(), camera=None, poll_interval_ms=1, confirm_count=confirm_count)


def test_locked_candidate_starts_as_none():
    reader = _make_reader()
    assert reader.get_locked_candidate() is None


def test_does_not_lock_before_confirm_count_reached():
    reader = _make_reader(confirm_count=3)
    reader._observe("42")
    reader._observe("42")
    assert reader.get_locked_candidate() is None


def test_locks_after_confirm_count_consecutive_matches():
    reader = _make_reader(confirm_count=3)
    reader._observe("42")
    reader._observe("42")
    reader._observe("42")
    assert reader.get_locked_candidate() == "42"


def test_locked_value_holds_through_noisy_readings():
    """発進直後のブレ・空白フレーム等で値が乱れても、ロック済みの値は上書きされない。"""
    reader = _make_reader(confirm_count=3)
    reader._observe("42")
    reader._observe("42")
    reader._observe("42")
    assert reader.get_locked_candidate() == "42"

    reader._observe(None)  # 車が発進してフレームが空白/認識不能になる
    reader._observe("9")  # モーションブラーで別の値が一瞬見える
    assert reader.get_locked_candidate() == "42"


def test_next_car_overwrites_locked_value_once_stable():
    reader = _make_reader(confirm_count=3)
    reader._observe("42")
    reader._observe("42")
    reader._observe("42")
    assert reader.get_locked_candidate() == "42"

    # 次の車が停止し、新しい値が安定して読み取れる
    reader._observe("7")
    reader._observe("7")
    reader._observe("7")
    assert reader.get_locked_candidate() == "7"


def test_broken_streak_resets_confirm_count():
    reader = _make_reader(confirm_count=3)
    reader._observe("42")
    reader._observe("42")
    reader._observe("13")  # 連続が途切れる
    reader._observe("42")
    reader._observe("42")
    assert reader.get_locked_candidate() is None


def test_locked_frame_starts_as_none():
    reader = _make_reader()
    assert reader.get_locked_frame() is None


def test_locked_frame_captured_at_lock_moment():
    reader = _make_reader(confirm_count=3)
    reader._observe("42", frame="frame-1")
    reader._observe("42", frame="frame-2")
    reader._observe("42", frame="frame-3")  # この時点でロックされる
    assert reader.get_locked_candidate() == "42"
    assert reader.get_locked_frame() == "frame-3"


def test_locked_frame_holds_through_noisy_readings():
    reader = _make_reader(confirm_count=3)
    reader._observe("42", frame="frame-1")
    reader._observe("42", frame="frame-2")
    reader._observe("42", frame="frame-3")
    assert reader.get_locked_frame() == "frame-3"

    reader._observe(None, frame=None)
    reader._observe("9", frame="frame-blurry")
    assert reader.get_locked_frame() == "frame-3"


def test_low_confidence_reading_does_not_count_toward_streak():
    """信頼度がmin_confidence未満の読み取りは「読めなかった」扱いになり、連続が途切れる。"""
    reader = BibReader(_FakeEngine(), camera=None, poll_interval_ms=1, confirm_count=3, min_confidence=60.0)
    reader._observe("42", confidence=80.0)
    reader._observe("42", confidence=30.0)  # 低信頼度なのでNone扱い
    reader._observe("42", confidence=80.0)
    reader._observe("42", confidence=80.0)
    assert reader.get_locked_candidate() is None

    reader._observe("42", confidence=80.0)
    assert reader.get_locked_candidate() == "42"


def test_high_confidence_reading_locks_normally():
    reader = BibReader(_FakeEngine(), camera=None, poll_interval_ms=1, confirm_count=3, min_confidence=60.0)
    reader._observe("42", confidence=90.0)
    reader._observe("42", confidence=90.0)
    reader._observe("42", confidence=90.0)
    assert reader.get_locked_candidate() == "42"


def test_locked_frame_overwritten_by_next_car():
    reader = _make_reader(confirm_count=3)
    reader._observe("42", frame="frame-1")
    reader._observe("42", frame="frame-2")
    reader._observe("42", frame="frame-3")
    assert reader.get_locked_frame() == "frame-3"

    reader._observe("7", frame="frame-4")
    reader._observe("7", frame="frame-5")
    reader._observe("7", frame="frame-6")
    assert reader.get_locked_candidate() == "7"
    assert reader.get_locked_frame() == "frame-6"
