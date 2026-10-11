"""Avatar-mode session history: history picker in the bubble (backlog #3)."""

from __future__ import annotations

from tests.ui.test_avatar_app import _make_app


def _seed_sessions(ui):
    sid1 = ui._history.create_session()
    ui._history.append(sid1, "user", "ilk soru")
    ui._history.append(sid1, "assistant", "ilk cevap")
    sid2 = ui._history.create_session()
    ui._history.append(sid2, "user", "ikinci soru")
    return sid1, sid2


def test_history_button_lists_session_titles(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    _seed_sessions(ui)

    assert ui.bubble._history_btn.isEnabled()
    ui._on_history()

    picker = ui.bubble._session_picker
    titles = {picker.item(i).text() for i in range(picker.count())}
    assert titles == {"ilk soru", "ikinci soru"}
    ui.close()


def test_picking_session_loads_transcript_and_switches(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    sid1, sid2 = _seed_sessions(ui)
    ui._history.append(sid1, "tool", "ekran alintisi alindi", tool_name="screenshot")

    ui._on_session_chosen(sid1)

    assert ui._sid == sid1
    transcript = ui.bubble._transcript.toPlainText()
    assert "ilk soru" in transcript
    assert "ilk cevap" in transcript
    assert "screenshot: ekran alintisi alindi" in transcript
    ui.close()


def test_picker_click_switches_session(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    sid1, sid2 = _seed_sessions(ui)

    ui._on_history()
    picker = ui.bubble._session_picker
    from PySide6.QtCore import Qt

    for i in range(picker.count()):
        if picker.item(i).data(Qt.ItemDataRole.UserRole) == sid2:
            picker.itemClicked.emit(picker.item(i))
            break
    else:
        raise AssertionError("session item not found in picker")

    assert ui._sid == sid2
    assert not picker.isVisible()
    ui.close()


def test_send_after_picking_continues_picked_session(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    sid1, sid2 = _seed_sessions(ui)

    ui._on_session_chosen(sid1)
    ui._on_send("devam mesaji")

    assert ui._sid == sid1
    assert len(ui._history.list_sessions()) == 2, "must not create a new session"
    assert ("user", "devam mesaji", None) in ui._history.messages(sid1)
    ui.close()


def test_history_disabled_while_busy(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.bubble.set_busy(True)
    assert not ui.bubble._history_btn.isEnabled()
    ui.bubble.set_busy(False)
    assert ui.bubble._history_btn.isEnabled()
    ui.close()


def test_history_picker_empty_when_no_sessions(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._on_history()
    assert ui.bubble._session_picker.count() == 0
    ui.close()
