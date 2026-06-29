"""common/time_format.py（旧sheets/formatter.py）の振る舞いを保証する番犬テスト。"""

from common.time_format import (
    DNF_SECONDS,
    MC_SECONDS,
    display_to_seconds,
    is_dnf,
    is_mc,
    is_valid_time,
    seconds_to_display,
)


def test_seconds_to_display_normal_time():
    assert seconds_to_display(73.123) == "1:13.123"


def test_seconds_to_display_dnf():
    assert seconds_to_display(DNF_SECONDS) == "DNF"


def test_seconds_to_display_mc():
    assert seconds_to_display(MC_SECONDS) == "MC"


def test_display_to_seconds_roundtrip():
    assert display_to_seconds("1:13.123") == 73.123


def test_display_to_seconds_dnf_mc():
    assert display_to_seconds("DNF") == DNF_SECONDS
    assert display_to_seconds("MC") == MC_SECONDS


def test_is_valid_time():
    assert is_valid_time(73.123) is True
    assert is_valid_time(DNF_SECONDS) is False
    assert is_valid_time(MC_SECONDS) is False


def test_is_dnf_is_mc():
    assert is_dnf(DNF_SECONDS) is True
    assert is_mc(MC_SECONDS) is True
    assert is_dnf(MC_SECONDS) is False
