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
        self.seeds = []

    def begin_task(self, sid, text, images=None):
        from ui.gui.main_window import _UiSignals  # noqa: F401

        self._win._signals.assistant.emit("merhaba")
        self._win._signals.finished.emit()
        return "tid"

    def run_task(self, tid):
        pass

    def cancel_active_task(self):
        pass

    def seed_session(self, sid, pairs):
        self.seeds.append((sid, pairs))


class SilentRuntime:
    """Runtime that starts a task but never finishes it (for mid-task scenarios)."""

    def __init__(self, win):
        self._win = win
        self.started = []

    def begin_task(self, sid, text, images=None):
        self.started.append((sid, text))
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


def test_load_session_seeds_runtime_context(tmp_path):
    # B8: opening a session must hand the runtime its text history so the
    # model sees prior turns, not just the new message.
    app, win = _make_window(tmp_path)
    win._runtime = FakeRuntime(win)
    sid = win._history.create_session("sohbet")
    win._history.append(sid, "user", "eski soru")
    win._history.append(sid, "assistant", "eski cevap")
    win._history.append(sid, "tool", "ekran alındı", tool_name="screenshot")
    win._load_session(sid, force=True)
    assert win._runtime.seeds == [
        (sid, [("user", "eski soru"), ("assistant", "eski cevap")])
    ]
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
        def begin_task(self, sid, text, images=None):
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


def test_switching_chat_mid_task_does_not_busy_lock(tmp_path):
    """B9: a background task finishing must release the busy state even when
    the user has switched to another chat."""
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = SilentRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sid_a = win._session_id
    assert win._busy is True
    win.new_chat()  # user switches away mid-task
    ev = SimpleNamespace(
        name="agent_finished", session_id=sid_a, task_id="t1", payload={}
    )
    win._on_event(ev)
    assert win._busy is False
    assert win._send_btn.isEnabled()
    win.hide()


def test_late_assistant_reply_lands_in_task_session(tmp_path):
    """B9: the reply of a background task must be persisted to its own session
    and must not leak into the currently visible chat."""
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = SilentRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sid_a = win._session_id
    win.new_chat()
    ev = SimpleNamespace(
        name="assistant_message",
        session_id=sid_a,
        task_id="t1",
        payload={"text": "gorev yaniti"},
    )
    win._on_event(ev)
    assert ("assistant", "gorev yaniti", None) in win._history.messages(sid_a)
    assert all(m["text"] != "gorev yaniti" for m in win._messages)
    win.hide()


def test_error_after_new_chat_does_not_integrity_error(tmp_path):
    """B35: the error path must persist to the task's session, never to a
    None session id (sqlite FK violation)."""
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = SilentRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sid_a = win._session_id
    win.new_chat()  # _session_id is None now
    ev = SimpleNamespace(
        name="agent_error",
        session_id=sid_a,
        task_id="t1",
        payload={"error_code": "provider_error", "message": "patlak"},
    )
    win._on_event(ev)  # must not raise sqlite3.IntegrityError
    assert win._busy is False
    assert any("patlak" in m[1] for m in win._history.messages(sid_a))
    win.hide()


def test_cancelled_after_switch_persists_to_task_session(tmp_path):
    """B9: a cancel that lands while another chat is visible still records the
    cancelled marker in the task's own session and releases busy."""
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = SilentRuntime(win)
    win._chat_input.setPlainText("selam")
    win._send()
    sid_a = win._session_id
    win.new_chat()
    ev = SimpleNamespace(
        name="agent_cancelled", session_id=sid_a, task_id="t1", payload={}
    )
    win._on_event(ev)
    assert win._busy is False
    assert any("iptal" in m[1].lower() for m in win._history.messages(sid_a))
    win.hide()


def test_on_settings_saved_applies_screen_control(tmp_path):
    # B29: saving Settings must rebuild screen_control tools on the live
    # runtime — the registry starts empty here (disabled at startup).
    import json

    from PySide6.QtWidgets import QApplication

    from core.agent.config import AgentConfig
    from core.agent.runtime import AgentRuntime
    from core.events import EventBus
    from core.session.store import SessionStore
    from core.tools.registry import PermissionPolicy, ToolRegistry
    from tests.fakes import FakeProvider
    from ui.gui.main_window import ChatWindow

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "screen_control": {"enabled": True, "host": "127.0.0.1", "port": 8745},
        "agent": {"persona": "x"},
    }))
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({}))
    rt = AgentRuntime(
        FakeProvider([]), ToolRegistry(), PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )
    win = ChatWindow(
        runtime=rt, history=HistoryStore(tmp_path / "h.db"),
        settings_path=settings, secrets_path=secrets,
    )
    win._on_settings_saved()
    assert rt.registry.get("screenshot") is not None
    win.hide()


def test_on_settings_saved_swaps_provider(tmp_path):
    # B24: a provider/model change saved in Settings must reach the live
    # runtime — restarting the app to switch models is the bug.
    import json

    from PySide6.QtWidgets import QApplication

    from core.agent.config import AgentConfig
    from core.agent.runtime import AgentRuntime
    from core.events import EventBus
    from core.session.store import SessionStore
    from core.tools.registry import PermissionPolicy, ToolRegistry
    from tests.fakes import FakeProvider
    from ui.gui.main_window import ChatWindow

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "provider": {"type": "groq", "model": "m1"},
        "agent": {"persona": "x"},
    }))
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({"groq_api_key": "gsk_test"}))
    rt = AgentRuntime(
        FakeProvider([]), ToolRegistry(), PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )
    win = ChatWindow(
        runtime=rt, history=HistoryStore(tmp_path / "h.db"),
        settings_path=settings, secrets_path=secrets,
    )
    win._on_settings_saved()
    assert not isinstance(rt._provider, FakeProvider)
    assert rt._provider.provider_key == "groq"
    assert rt._provider.model == "m1"
    win.hide()


def test_tool_events_from_other_session_do_not_leak(tmp_path):
    # B33: tool_started/tool_finished/provider_notice from a background
    # session must not draw lines into the currently open chat.
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._session_id = "s-mine"
    before = len(win._messages)
    win._on_event(SimpleNamespace(
        name="tool_started", session_id="s-other", task_id="t",
        payload={"tool_name": "screenshot"},
    ))
    win._on_event(SimpleNamespace(
        name="tool_finished", session_id="s-other", task_id="t",
        payload={"tool_name": "screenshot", "ok": True},
    ))
    win._on_event(SimpleNamespace(
        name="provider_notice", session_id="s-other", task_id="t",
        payload={"code": "vision_disabled"},
    ))
    assert len(win._messages) == before
    # same-session events still draw
    win._on_event(SimpleNamespace(
        name="tool_started", session_id="s-mine", task_id="t",
        payload={"tool_name": "screenshot"},
    ))
    assert len(win._messages) == before + 1
    win.hide()


def test_delete_background_session_with_running_task_cancels(tmp_path, monkeypatch):
    # B39: deleting the session whose task is running — even while another
    # chat is displayed — must cancel that task and free the busy state.
    import ui.gui.main_window as mw

    app, win = _make_window(tmp_path)
    sids = _seed_sessions(win, 2)
    win._load_session(sids[1])  # display second session
    win._active_task_session = sids[0]
    win._set_busy(True)
    calls = []
    win._runtime = type("R", (), {"cancel_active_task": lambda self: calls.append("cancel")})()
    monkeypatch.setattr(mw, "confirm_delete_session", lambda parent, title: True)
    win._delete_session(sids[0])
    assert calls == ["cancel"]
    assert win._active_task_session is None
    assert not win._busy
    # displayed session untouched
    assert win._session_id == sids[1]
    win.hide()


def test_settings_saved_reapplies_theme(tmp_path):
    # B42: theme picked in Settings must apply live, not after a restart.
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from ui.gui.main_window import ChatWindow
    from ui.history import HistoryStore
    from ui.prefs import THEMES, UiPrefs, load_prefs, save_prefs

    app = QApplication.instance() or QApplication([])
    ui_json = tmp_path / "ui.json"
    store = HistoryStore(tmp_path / "h.db")
    win = ChatWindow(history=store, ui_json_path=ui_json)
    cur = load_prefs(ui_json).theme
    new = "light" if cur == "dark" else "dark"
    save_prefs(ui_json, UiPrefs(mode="gui", theme=new, lang=load_prefs(ui_json).lang))
    qss_before = app.styleSheet()
    win._on_settings_saved()
    assert app.styleSheet() != qss_before or app.styleSheet()  # reapplied at least
    from ui.theme import qss as build_qss

    assert app.styleSheet() == build_qss(new)
    win.hide()


def test_session_picker_closed_widget_is_scheduled_for_deletion(tmp_path):
    # B43: repeatedly opening/closing the picker must not leak widgets.
    from PySide6.QtWidgets import QApplication

    from ui.bubble import BubbleWindow

    app = QApplication.instance() or QApplication([])
    b = BubbleWindow(on_send=lambda text: None, on_cancel=lambda: None)
    b.show_session_picker([("s1", "chat")], lambda sid: None)
    picker = b._session_picker
    assert picker is not None
    b._close_session_picker()
    assert b._session_picker is None
    assert picker.isHidden()
    b.show_session_picker([("s1", "chat")], lambda sid: None)  # reopen works
    assert b._session_picker is not None
    b._close_session_picker()
    b.setParent(None)
    b.deleteLater()
    app.processEvents()


def test_tool_failure_shows_summary_in_transcript(tmp_path):
    # B68: "(Hata)" alone told the user nothing; the runtime payload carries
    # the reason (summary/error_code) and it must reach the transcript line.
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = SilentRuntime(win)
    win._chat_input.setPlainText("is")
    win._send()
    sid = win._session_id
    ev = SimpleNamespace(
        name="tool_finished",
        session_id=sid,
        task_id="t1",
        payload={
            "tool_name": "screenshot",
            "ok": False,
            "summary": "server_unreachable: no reply on 8745",
            "error_code": "server_unreachable",
        },
    )
    win._on_event(ev)
    tool_lines = [m["text"] for m in win._messages if m["role"] == "tool"]
    assert any("server_unreachable" in line for line in tool_lines), tool_lines
    win.hide()


def test_on_settings_saved_respawns_screen_control_server(tmp_path, monkeypatch):
    # B70: a saved port change must reach maybe_spawn_server — otherwise a
    # moved server keeps answering on the old port forever.
    import json

    from PySide6.QtWidgets import QApplication

    from core.agent.config import AgentConfig
    from core.agent.runtime import AgentRuntime
    from core.events import EventBus
    from core.session.store import SessionStore
    from core.tools.registry import PermissionPolicy, ToolRegistry
    from tests.fakes import FakeProvider
    from ui.gui.main_window import ChatWindow

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "screen_control": {"enabled": True, "host": "127.0.0.1", "port": 9001},
        "agent": {"persona": "x"},
    }))
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({}))
    rt = AgentRuntime(
        FakeProvider([]), ToolRegistry(), PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )
    win = ChatWindow(
        runtime=rt, history=HistoryStore(tmp_path / "h.db"),
        settings_path=settings, secrets_path=secrets,
    )
    calls = []
    import app_entry.entry as entry_mod

    monkeypatch.setattr(entry_mod, "maybe_spawn_server", lambda s: calls.append(s))
    win._on_settings_saved()
    assert calls, "save must trigger maybe_spawn_server"
    assert calls[0]["screen_control"]["port"] == 9001
    win.hide()


def test_collapse_sidebar_hides_header_and_shows_glyph(tmp_path):
    # B71: collapsed sidebar left the "Oturumlar" header visible and kept the
    # long "Genişlet" label, which overflows the 48px rail. Glyphs instead.
    app, win = _make_window(tmp_path)
    win.show()
    assert win._sidebar_expanded
    win._toggle_sidebar()
    assert not win._sidebar_expanded
    assert win._sessions_header.isHidden()
    assert win._collapse_btn.text() == "☰"
    assert win._collapse_btn.width() <= 48
    win._toggle_sidebar()  # expand again
    assert win._sidebar_expanded
    assert not win._sessions_header.isHidden()
    assert win._collapse_btn.text() == "»"
    win.hide()


def test_retranslate_keeps_collapse_glyph_when_collapsed(tmp_path):
    # B71: retranslate() used to overwrite the glyph with the long label.
    app, win = _make_window(tmp_path)
    win._toggle_sidebar()  # collapse
    win.retranslate()
    assert win._collapse_btn.text() == "☰"
    win.hide()


def test_error_line_persists_with_error_role_and_stays_out_of_seed(tmp_path):
    # B73: error/cancel lines were stored as "assistant", so the next
    # seed_session fed them back to the model as if the assistant said them.
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)

    class RT:
        def seed_session(self, sid, pairs):
            self.seeded = pairs

        def cancel_active_task(self):
            pass

    win._runtime = RT()
    win._chat_input.setPlainText("is")
    # need a real session: use _send path but avoid threading by faking busy
    from tests.ui.test_chat import FakeRuntime  # noqa: F401 — reuse if present

    win._runtime = type("F", (), {
        "begin_task": lambda self, sid, text, images=None: "t",
        "run_task": lambda self, tid: None,
        "cancel_active_task": lambda self: None,
        "seed_session": lambda self, sid, pairs: setattr(self, "seeded", pairs),
    })()
    win._send()
    sid = win._session_id
    ev = SimpleNamespace(name="agent_error", session_id=sid, task_id="t1",
                         payload={"error_code": "provider_error", "message": "patlak"})
    win._on_event(ev)
    roles = [m[0] for m in win._history.messages(sid)]
    assert "error" in roles, roles
    # switching away and back must NOT seed the error line to the model
    win.new_chat()
    win._load_session(sid)
    assert all("patlak" not in str(p[1]) for p in win._runtime.seeded)
    win.hide()


def test_cancel_line_persists_with_error_role(tmp_path):
    from types import SimpleNamespace

    app, win = _make_window(tmp_path)
    win._runtime = type("F", (), {
        "begin_task": lambda self, sid, text, images=None: "t",
        "run_task": lambda self, tid: None,
        "cancel_active_task": lambda self: None,
        "seed_session": lambda self, sid, pairs: None,
    })()
    win._chat_input.setPlainText("is")
    win._send()
    sid = win._session_id
    ev = SimpleNamespace(name="agent_cancelled", session_id=sid, task_id="t1", payload={})
    win._on_event(ev)
    roles = [m[0] for m in win._history.messages(sid)]
    assert "error" in roles, roles
    win.hide()
