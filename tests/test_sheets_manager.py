"""sheets/manager.pyのうち、ネットワーク・Tkinterに依存しない部分の番犬テスト。

manager.py内のTkinterダイアログ部分（_prompt_format_choice/start_session）はUI層へ
切り出す予定だが、Session/セッションファイルの読み書き・build_clientの異常系は
そのまま挙動を保証する。
"""

import pytest

from sheets.manager import Session, build_client, load_session, save_session


def test_session_to_dict_from_dict_roundtrip():
    session = Session(
        event_name="テスト大会", date="2026-06-29", spreadsheet_id="abc123",
        spreadsheet_url="https://example.com/abc123", csv_path="/tmp/foo.csv",
        created_at="2026-06-29T10:00:00", format="format2", sheet_csv_path="/tmp/foo_sheet.csv",
    )
    restored = Session.from_dict(session.to_dict())
    assert restored == session


def test_save_and_load_session_roundtrip(tmp_path):
    session_path = str(tmp_path / "session.json")
    session = Session(
        event_name="テスト大会", date="2026-06-29", spreadsheet_id="abc123",
        spreadsheet_url="https://example.com/abc123", csv_path="/tmp/foo.csv",
        created_at="2026-06-29T10:00:00",
    )
    save_session(session, session_path)
    loaded = load_session(session_path)
    assert loaded == session


def test_load_session_missing_file_returns_none(tmp_path):
    assert load_session(str(tmp_path / "missing.json")) is None


def test_load_session_corrupted_file_returns_none(tmp_path):
    session_path = tmp_path / "session.json"
    session_path.write_text("{not valid json", encoding="utf-8")
    assert load_session(str(session_path)) is None


def test_build_client_raises_when_credentials_missing(tmp_path):
    config = {"credentials_path": "credentials.json"}
    with pytest.raises(FileNotFoundError):
        build_client(config, str(tmp_path))
