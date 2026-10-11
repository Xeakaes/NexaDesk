from pathlib import Path

from ui.history import HistoryStore


def _make_window(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.gui.main_window import ChatWindow

    app = QApplication.instance() or QApplication([])
    db = tmp_path / "history.db"
    store = HistoryStore(db)
    win = ChatWindow(history=store)
    return app, win


class FakeRuntime:
    def __init__(self, win):
        self._win = win

    def begin_task(self, sid, text):
        from ui.gui.main_window import _UiSignals  # noqa: F401

        self._win._signals.assistant.emit("merhaba")
        self._win._signals.finished.emit()
        return "tid"

    def run_task(self, tid):
        pass

    def cancel_active_task(self):
        pass


def test_sends_and_appends(tmp_path):
    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    assert win._messages[-1]["role"] == "user"
    assert win._messages[-1]["text"] == "selam"
    assert win._messages[-1]["objectName"] == "msg_user"
    # history row persisted
    msgs = win._history.messages(win._session_id)
    assert msgs[0] == ("user", "selam", None)
    win.hide()


def test_enter_sends_shift_enter_newline(tmp_path):
    app, win = _make_window(tmp_path)
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import Qt

    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
    )
    sent = []
    monkey = lambda *a: sent.append(True)
    win._send = monkey
    win._chat_input.keyPressEvent(ev)
    assert sent == [True]
    ev2 = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    win._chat_input.keyPressEvent(ev2)
    assert sent == [True]  # shift+enter did not send
    win.hide()


def test_history_click_loads_session(tmp_path):
    app, win = _make_window(tmp_path)
    sid = win._history.create_session("ilk sohbet")
    win._history.append(sid, "user", "eski mesaj")
    win._reload_sessions()
    win._load_session(sid, force=True)
    assert win._messages[0]["text"] == "eski mesaj"
    win.hide()


def test_sidebar_toggle_width(tmp_path):
    app, win = _make_window(tmp_path)
    assert win._side_inner.width() == 260
    win._toggle_sidebar()
    assert win._side_inner.width() == 48
    win._toggle_sidebar()
    assert win._side_inner.width() == 260
    win.hide()


def test_init_does_not_create_session(tmp_path):
    """Opening the window must not persist an empty session."""
    app, win = _make_window(tmp_path)
    assert win._session_id is None
    assert win._history.list_sessions() == []
    win.hide()


def test_new_chat_does_not_create_session(tmp_path):
    app, win = _make_window(tmp_path)
    win.new_chat()
    assert win._session_id is None
    assert win._history.list_sessions() == []
    win.hide()


def test_first_send_creates_exactly_one_session(tmp_path):
    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sessions = win._history.list_sessions()
    assert len(sessions) == 1
    assert win._session_id == sessions[0][0]
    win.hide()


def test_purge_empty_sessions(tmp_path):
    from ui.history import HistoryStore

    store = HistoryStore(tmp_path / "h.db")
    store.create_session("bos")
    filled = store.create_session("dolu")
    store.append(filled, "user", "merhaba")
    removed = store.purge_empty_sessions()
    assert removed == 1
    assert [s[0] for s in store.list_sessions()] == [filled]
    store.close()


def test_confirmation_requested_resolves_approved(tmp_path, monkeypatch):
    """P1 GUI: confirmation_requested must resolve via runtime with Allow."""
    from core.events import Event

    app, win = _make_window(tmp_path)
    resolved = []

    class RT:
        def resolve_confirmation(self, task_id, confirm_id, approved):
            resolved.append((task_id, confirm_id, approved))

    win._runtime = RT()
    monkeypatch.setattr("ui.confirmation.ask_confirmation", lambda *a, **k: True)
    ev = Event(
        "confirmation_requested",
        win._session_id,
        "t1",
        {
            "confirm_id": "c1",
            "tool_name": "shell",
            "question": "Run tool shell?",
            "arguments": {"cmd": "ls"},
        },
    )
    win._on_event(ev)
    assert resolved == [("t1", "c1", True)]
    win.hide()


def test_confirmation_requested_resolves_denied(tmp_path, monkeypatch):
    from core.events import Event

    app, win = _make_window(tmp_path)
    resolved = []

    class RT:
        def resolve_confirmation(self, task_id, confirm_id, approved):
            resolved.append((task_id, confirm_id, approved))

    win._runtime = RT()
    monkeypatch.setattr("ui.confirmation.ask_confirmation", lambda *a, **k: False)
    ev = Event(
        "confirmation_requested",
        win._session_id,
        "t1",
        {"confirm_id": "c7", "tool_name": "shell", "question": "?", "arguments": {}},
    )
    win._on_event(ev)
    assert resolved == [("t1", "c7", False)]
    win.hide()


def test_send_session_id_snapshotted_at_send_time(tmp_path, monkeypatch):
    """P2: switching chats mid-task must not rebind the running task."""
    import threading as _t

    app, win = _make_window(tmp_path)
    started = []

    class RT:
        def begin_task(self, sid, text):
            started.append(sid)
            return "tid"

        def run_task(self, tid):
            pass

        def cancel_active_task(self):
            pass

    win._runtime = RT()
    created = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            created.append(self)

        def start(self):
            pass  # hold the worker until the test releases it

    monkeypatch.setattr(_t, "Thread", FakeThread)
    # First send creates the session lazily and completes synchronously.
    win._chat_input.setPlainText("ilk")
    win._send()
    created[0]._target(*created[0]._args)
    old_sid = win._session_id
    assert old_sid is not None
    # Second send is held; switch chats before releasing the worker.
    win._busy = False
    win._chat_input.setPlainText("ikinci")
    win._send()
    assert len(created) == 2
    win.new_chat()
    new_sid = win._session_id
    assert new_sid is None or new_sid != old_sid
    created[1]._target(*created[1]._args)
    assert started == [old_sid, old_sid], "task must bind to the session at send time"
    win.hide()


def test_sidebar_has_sessions_header(tmp_path):
    app, win = _make_window(tmp_path)
    assert win._sessions_header.objectName() == "sessions_header"
    assert win._sessions_header.text() == "Geçmiş sohbetler"  # i18n default tr
    win.hide()


def test_empty_state_visible_when_no_messages_then_hides(tmp_path):
    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    assert not win._empty_state.isHidden()
    win._chat_input.setPlainText("selam")
    win._send()
    assert win._empty_state.isHidden()
    win.new_chat()
    assert not win._empty_state.isHidden()
    win.hide()


def test_cancel_button_uses_outline_not_danger(tmp_path):
    app, win = _make_window(tmp_path)
    assert win._cancel_btn.objectName() == "outline"
    win.hide()


def _seed_sessions(win, n=2):
    ids = []
    for i in range(n):
        sid = win._history.create_session()
        win._history.append(sid, "user", f"selam {i}")
        ids.append(sid)
    win._reload_sessions()
    return ids


def test_context_menu_delete_removes_session(tmp_path, monkeypatch):
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    sids = _seed_sessions(win)
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    remaining = [s[0] for s in win._history.list_sessions()]
    assert sids[0] not in remaining
    assert win._sessions.count() == len(remaining)
    win.hide()


def test_cancelled_confirm_keeps_session(tmp_path, monkeypatch):
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    sids = _seed_sessions(win, 1)
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: False)
    win._delete_session(sids[0])
    assert sids[0] in [s[0] for s in win._history.list_sessions()]
    win.hide()


def test_delete_active_session_resets_to_empty(tmp_path, monkeypatch):
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    sids = _seed_sessions(win, 1)
    win._load_session(sids[0])
    assert win._session_id == sids[0]
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    assert win._session_id is None
    assert win._messages == []
    assert not win._empty_state.isHidden()
    win.hide()


def test_delete_active_while_running_cancels_task(tmp_path, monkeypatch):
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    sids = _seed_sessions(win, 1)
    win._load_session(sids[0])
    win._set_busy(True)

    calls = []
    win._runtime = type("R", (), {"cancel_active_task": lambda self: calls.append("cancel")})()
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    assert calls == ["cancel"]
    assert win._session_id is None
    win.hide()


def test_delete_active_while_running_no_late_append(tmp_path, monkeypatch):
    """Late events from a deleted session must not land in a newer one."""
    from types import SimpleNamespace

    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    sids = _seed_sessions(win, 1)
    win._load_session(sids[0])
    win._set_busy(True)
    win._runtime = type("R", (), {"cancel_active_task": lambda self: None})()
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    win._chat_input.setPlainText("yeni mesaj")
    win._send()
    new_sid = win._session_id
    assert new_sid is not None and new_sid != sids[0]
    old_ev = SimpleNamespace(name="assistant_message", session_id=sids[0],
                             task_id="t-old", payload={"text": "eski görev yanıtı"})
    win._on_event(old_ev)
    old_fin = SimpleNamespace(name="agent_cancelled", session_id=sids[0],
                              task_id="t-old", payload={})
    win._on_event(old_fin)
    assert all(m[1] != "eski görev yanıtı" for m in win._history.messages(new_sid))
    assert not any("iptal" in m[1].lower() for m in win._history.messages(new_sid))
    win.hide()


def test_late_events_same_session_still_apply(tmp_path):
    """Control: events matching the current session id are NOT dropped."""
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sid = win._session_id
    ev = SimpleNamespace(name="assistant_message", session_id=sid,
                         task_id="t1", payload={"text": "normal yanıt"})
    win._on_event(ev)
    assert ("assistant", "normal yanıt", None) in win._history.messages(sid)
    win.hide()


def test_send_after_delete_creates_new_session(tmp_path, monkeypatch):
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    sids = _seed_sessions(win, 1)
    win._load_session(sids[0])
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    win._chat_input.setPlainText("yeni mesaj")
    win._send()
    assert win._session_id is not None
    assert win._session_id != sids[0]
    assert ("user", "yeni mesaj", None) in win._history.messages(win._session_id)
    win.hide()


def test_confirm_delete_session_builds_dialog_with_danger_button():
    """The confirm helper builds a dialog with filled-danger delete + outline cancel."""
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from ui.gui.main_window import _build_delete_dialog

    app = QApplication.instance() or QApplication([])
    dlg = _build_delete_dialog(None, "deneme sohbeti")
    buttons = dlg.findChild(QDialogButtonBox)
    assert buttons is not None
    danger = buttons.button(QDialogButtonBox.StandardButton.Yes)
    cancel = buttons.button(QDialogButtonBox.StandardButton.No)
    assert danger is not None and danger.objectName() == "danger"
    assert cancel is not None and cancel.objectName() == "outline"
    dlg.deleteLater()


def test_chat_messages_are_text_selectable(tmp_path):
    """Chat transcript labels must allow mouse/keyboard selection (copy)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    app, win = _make_window(tmp_path)
    win._append("user", "selam dunya")
    win._append("assistant", "merhaba")
    labels = [
        w for w in win._msg_area.findChildren(QLabel) if w.text() in ("selam dunya", "merhaba")
    ]
    assert len(labels) == 2
    for lbl in labels:
        flags = lbl.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
        assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
    win.hide()
