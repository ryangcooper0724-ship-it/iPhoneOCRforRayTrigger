"""exe実行時/ソース実行時のベースディレクトリ解決ロジックの番犬テスト。

main.py / ui/main_window.py / sensor/ydci_driver.pyの3箇所に重複している
sys.frozen判定ロジックをcommon/paths.pyへ集約する予定だが、各モジュールが
「sys.frozen=Trueならsys.executableの場所、Falseならソースファイル基準」という
同じ結論に達することを保証する。
"""

import importlib
import os
import sys


def test_main_base_dir_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "RayTrigger.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    import main
    importlib.reload(main)
    try:
        assert main.BASE_DIR == str(tmp_path)
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        importlib.reload(main)


def test_main_base_dir_uses_source_dir_when_not_frozen():
    import main
    importlib.reload(main)
    assert main.BASE_DIR == os.path.dirname(os.path.abspath(main.__file__))


def test_ui_main_window_csv_dir_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "RayTrigger.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    from ui import main_window
    importlib.reload(main_window)
    try:
        assert main_window._CSV_DIR == os.path.join(str(tmp_path), "csv")
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        importlib.reload(main_window)


def test_ydci_default_dll_path_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "RayTrigger.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    from sensor.ydci_driver import YdciDriver
    assert YdciDriver._default_dll_path() == os.path.join(str(tmp_path), "Ydci.dll")
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_ydci_default_dll_path_uses_project_root_when_not_frozen():
    import sensor.ydci_driver as mod
    expected_root = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
    assert mod.YdciDriver._default_dll_path() == os.path.join(expected_root, "Ydci.dll")
