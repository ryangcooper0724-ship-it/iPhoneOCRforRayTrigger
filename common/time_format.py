"""タイム表示形式の変換ユーティリティ。

内部では常に秒の浮動小数点数で保持する。DNF/MCはセンチネル値で表現し、
Sheets上では文字列"DNF"/"MC"として書き込む。
"""

DNF_SECONDS = 999.999
MC_SECONDS = 999.998

_EPSILON = 0.0001


def seconds_to_display(seconds: float) -> str:
    """73.123 → '1:13.123'。DNF/MCの場合はそのまま"DNF"/"MC"を返す。"""
    if is_dnf(seconds):
        return "DNF"
    if is_mc(seconds):
        return "MC"

    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"


def display_to_seconds(display: str) -> float:
    """'1:13.123' → 73.123。'DNF'/'MC'はそれぞれのセンチネル値に変換する。"""
    text = display.strip()
    if text == "DNF":
        return DNF_SECONDS
    if text == "MC":
        return MC_SECONDS

    minutes_str, _sep, seconds_str = text.partition(":")
    return int(minutes_str) * 60 + float(seconds_str)


def is_dnf(seconds: float) -> bool:
    return abs(seconds - DNF_SECONDS) < _EPSILON


def is_mc(seconds: float) -> bool:
    return abs(seconds - MC_SECONDS) < _EPSILON


def is_valid_time(seconds: float) -> bool:
    """DNF/MCではない、実際に計測されたタイムかどうか。"""
    return not is_dnf(seconds) and not is_mc(seconds)
