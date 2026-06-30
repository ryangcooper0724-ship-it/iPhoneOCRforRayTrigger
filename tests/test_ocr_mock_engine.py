"""ocr/mock_engine.py の番犬テスト。"""

from ocr.mock_engine import MockOcrEngine


def test_returns_none_when_no_value_injected():
    engine = MockOcrEngine()
    assert engine.recognize(None) is None


def test_returns_injected_value_repeatedly():
    engine = MockOcrEngine()
    engine.set_next_value("42")
    assert engine.recognize(None) == "42"
    assert engine.recognize(None) == "42"


def test_clearing_with_none_resets_to_none():
    engine = MockOcrEngine()
    engine.set_next_value("42")
    engine.set_next_value(None)
    assert engine.recognize(None) is None


def test_clearing_with_empty_string_resets_to_none():
    engine = MockOcrEngine()
    engine.set_next_value("42")
    engine.set_next_value("")
    assert engine.recognize(None) is None
