"""serial_input/bib_source.py の番犬テスト。

実シリアルポートには依存せず、parse_bib_line()（1行→ゼッケン値のパース）と
SerialBibSourceの状態保持ロジックを直接検証する。
"""

from serial_input.bib_source import SerialBibSource, parse_bib_line


def test_parse_valid_line():
    assert parse_bib_line('{"bib": "42", "confidence": 87.5, "ts": 1730000000}') == "42"


def test_parse_single_digit_bib():
    assert parse_bib_line('{"bib": "7"}') == "7"


def test_parse_malformed_json_returns_none():
    assert parse_bib_line("not json at all") is None


def test_parse_missing_bib_field_returns_none():
    assert parse_bib_line('{"confidence": 90.0}') is None


def test_parse_non_numeric_bib_returns_none():
    assert parse_bib_line('{"bib": "ab"}') is None


def test_parse_too_many_digits_returns_none():
    assert parse_bib_line('{"bib": "123"}') is None


def test_parse_empty_line_returns_none():
    assert parse_bib_line("") is None
    assert parse_bib_line("   ") is None


def test_locked_candidate_starts_as_none():
    source = SerialBibSource(port="COM_TEST")
    assert source.get_locked_candidate() is None


def test_locked_frame_is_always_none():
    source = SerialBibSource(port="COM_TEST")
    assert source.get_locked_frame() is None


def test_receiving_valid_line_updates_locked_candidate():
    source = SerialBibSource(port="COM_TEST")
    with source._lock:
        source._locked_candidate = parse_bib_line('{"bib": "42"}')
    assert source.get_locked_candidate() == "42"


def test_next_value_overwrites_previous():
    source = SerialBibSource(port="COM_TEST")
    with source._lock:
        source._locked_candidate = parse_bib_line('{"bib": "42"}')
    assert source.get_locked_candidate() == "42"

    with source._lock:
        source._locked_candidate = parse_bib_line('{"bib": "7"}')
    assert source.get_locked_candidate() == "7"
