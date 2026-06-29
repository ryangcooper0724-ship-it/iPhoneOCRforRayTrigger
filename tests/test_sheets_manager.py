"""sheets/manager.pyのうち、ネットワーク・Tkinterに依存しない部分の番犬テスト。

manager.py内のTkinterダイアログはui/session_dialogs.pyへ切り出し済み。start_session()は
ダイアログ表示をprompt_session_startコールバックへ委譲する形になったため、フェイクの
コールバックを渡すことでTkinterなしにテストできる。
"""

import pytest

from sheets.manager import (
    Session,
    SessionStartCancelled,
    build_client,
    load_session,
    save_session,
    start_session,
)


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


class FakeSpreadsheet:
    def __init__(self):
        self.id = "fake-id"
        self.url = "https://example.com/fake-id"

    def update_title(self, title):
        pass

    def worksheet(self, title):
        import gspread
        raise gspread.exceptions.WorksheetNotFound(title)


class FakeClient:
    """テンプレートIDが設定済みのケース（client.copy()経路）だけをフェイクする。

    テンプレート未設定（client.create() + setup_workbook()）の経路は実際のシート操作
    （add_worksheetなど）を多数行うため、ここではテストしない。
    """

    def copy(self, file_id, title, copy_permissions=True):
        return FakeSpreadsheet()


def test_start_session_reconnects_when_callback_says_yes(tmp_path):
    session_path = tmp_path / "session.json"
    existing = Session(
        event_name="前回大会", date="2026-06-01", spreadsheet_id="abc",
        spreadsheet_url="https://example.com/abc", csv_path="/tmp/foo.csv",
        created_at="2026-06-01T10:00:00",
    )
    save_session(existing, str(session_path))

    def fake_prompt(config, existing_event_name, existing_date):
        assert existing_event_name == "前回大会"
        assert existing_date == "2026-06-01"
        return True, None, None

    session, is_new = start_session({}, str(tmp_path), fake_prompt, client=FakeClient())
    assert session == existing
    assert is_new is False


def test_start_session_creates_new_when_callback_says_no(tmp_path):
    config = {"templates": {"format2": {"template_spreadsheet_id": "tmpl-id"}}}

    def fake_prompt(config, existing_event_name, existing_date):
        assert existing_event_name is None
        assert existing_date is None
        return False, "format2", "新規大会"

    session, is_new = start_session(config, str(tmp_path), fake_prompt, client=FakeClient())
    assert is_new is True
    assert session.event_name == "新規大会"
    assert session.format == "format2"


def test_start_session_raises_when_event_name_missing(tmp_path):
    config = {"templates": {"format1": {"template_spreadsheet_id": "tmpl-id"}}}

    def fake_prompt(config, existing_event_name, existing_date):
        return False, "format1", None

    with pytest.raises(SessionStartCancelled):
        start_session(config, str(tmp_path), fake_prompt, client=FakeClient())
