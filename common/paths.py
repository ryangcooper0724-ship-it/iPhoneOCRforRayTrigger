"""PyInstaller onefile実行時/ソース実行時のパス解決を一元化する共通ヘルパー。

main.py・ui/main_window.py・sensor/ydci_driver.pyにそれぞれ個別に書かれていた
sys.frozen判定ロジックをここに集約する。
"""

import os
import sys


def resolve_base_dir(caller_file: str, levels_up: int = 0) -> str:
    """config.json・Ydci.dll・csv/など、exe本体と同じ場所に置く外部ファイルの基準フォルダ。

    PyInstaller onefile実行時は__file__が一時展開フォルダ（_MEI*）を指すため使えない。
    その場合はexe本体のフォルダ（sys.executableの場所）を返す。
    ソース実行時はcaller_file（呼び出し元の__file__）からlevels_up階層分上に遡った
    フォルダを返す（例: projectroot/ui/main_window.pyから呼ぶ場合はlevels_up=1）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    base = os.path.dirname(os.path.abspath(caller_file))
    for _ in range(levels_up):
        base = os.path.dirname(base)
    return base


def resolve_bundled_resource_dir(caller_file: str, levels_up: int = 0) -> str:
    """PyInstallerの--add-dataで同梱した読み取り専用リソース（アイコン等）の基準フォルダ。

    onefile展開時はsys._MEIPASS（一時展開フォルダ）配下にリソースが置かれるため、
    resolve_base_dir()とは異なりexe本体のフォルダではなくこちらを返す。
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", resolve_base_dir(caller_file, levels_up))
    base = os.path.dirname(os.path.abspath(caller_file))
    for _ in range(levels_up):
        base = os.path.dirname(base)
    return base
