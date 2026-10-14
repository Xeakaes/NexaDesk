"""Avatar app tests: P0 (real session, no FK error) + P1 (confirmation resolve)."""

from __future__ import annotations

import threading

import pytest


class FakeBus:
    def subscribe(self, *a, **k):
        pass

    def unsubscribe(self, *a, **k):
        pass


class FakeRuntime:
    def __init__(self):
        self.begin_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[tuple[str, str, bool]] = []
        self._gate: threading.Event | None = None
        self._resume: threading.Event | None = None

    def begin_task(self, sid, text, images=None):
        self.begin_calls.append((sid, text))
        return "tid"

    def run_task(self, tid):
        pass

    def close(self):
        pass

    def resolve_confirmation(self, task_id, confirm_id, approved):
        self.resolve_calls.append((task_id, confirm_id, approved))


def _make_app(tmp_path, monkeypatch, runtime=None):
    from PySide6.QtWidgets import QApplication

    import ui.avatar_app as aa
    from ui.history import HistoryStore

    app = QApplication.instance() or QApplication([])
    rt = runtime or FakeRuntime()
    from core.session.store import SessionStore

    monkeypatch.setattr(
        aa, "build_runtime", lambda: (rt, FakeBus(), SessionStore())
    )
    monkeypatch.setattr(
        aa,
        "load_settings",
        lambda p: {"avatar": "base", "screen_control": {"enabled": False}},
    )
    monkeypatch.setattr(aa, "HistoryStore", lambda p: HistoryStore(tmp_path / "h.db"))
    monkeypatch.setattr(aa, "maybe_spawn_server", lambda s: None, raising=False)

    class FakeSettingsWin:
        def __init__(self, *a, **k):
            pass

        def load(self):
            pass

        def show(self):
            pass

        def raise_(self):
            pass

    monkeypatch.setattr(aa, "SettingsWindow", FakeSettingsWin)
    ui = aa.App()
    return app, ui, rt


def test_avatar_first_message_no_fk_error(tmp_path, monkeypatch):
    """P0: first user message must persist without FOREIGN KEY error."""
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._on_send("merhaba")  # must not raise sqlite3.IntegrityError
    sid = ui._sid
    assert sid, "avatar app must create a session on first send"
    sessions = [s[0] for s in ui._history.list_sessions()]
    assert sid in sessions, "session must exist in history store before messages"
    msgs = ui._history.messages(sid)
    assert msgs and msgs[0] == ("user", "merhaba", None)
    ui.close()


def test_avatar_init_does_not_create_session(tmp_path, monkeypatch):
    """Opening avatar mode must not persist an empty session."""
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    assert ui._sid is None
    assert ui._history.list_sessions() == []
    ui.close()


def test_avatar_begin_task_uses_real_session(tmp_path, monkeypatch):
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._on_send("selam")
    assert rt.begin_calls, "agent thread must start"
    sid, text = rt.begin_calls[0]
    assert sid == ui._sid
    assert text == "selam"
    ui.close()


def test_avatar_confirmation_resolve_approved(tmp_path, monkeypatch):
    """P1 avatar: confirmation_requested must resolve via runtime."""
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "ui.confirmation.ask_confirmation", lambda *a, **k: True, raising=False
    )
    ev = Event(
        "confirmation_requested",
        ui._sid,
        "t1",
        {
            "confirm_id": "c9",
            "tool_name": "screenshot",
            "question": "Run tool screenshot?",
            "arguments": {},
        },
    )
    ui._on_event(ev)
    assert rt.resolve_calls == [("t1", "c9", True)]
    ui.close()


def test_avatar_confirmation_resolve_denied(tmp_path, monkeypatch):
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "ui.confirmation.ask_confirmation", lambda *a, **k: False, raising=False
    )
    ev = Event(
        "confirmation_requested",
        ui._sid,
        "t1",
        {"confirm_id": "c1", "tool_name": "shell", "question": "?", "arguments": {}},
    )
    ui._on_event(ev)
    assert rt.resolve_calls == [("t1", "c1", False)]
    ui.close()


def test_avatar_app_disables_quit_on_last_window_closed(tmp_path, monkeypatch):
    """Regression: the parentless permission QDialog is the only non-Tool
    window in avatar mode — closing it (Allow/Deny) must NOT quit the app."""
    from PySide6.QtWidgets import QApplication

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    assert QApplication.instance().quitOnLastWindowClosed() is False
    ui.close()


def test_avatar_agent_error_unauthorized_shows_i18n_hint(tmp_path, monkeypatch):
    """agent_error with error_code=unauthorized must show the bilingual hint."""
    from core.events import Event
    from ui.i18n import i18n

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._sid = ui._history.create_session()
    ev = Event(
        "agent_error",
        ui._sid,
        "t1",
        {"error_code": "unauthorized", "message": "401 Client Error"},
    )
    ui._on_event(ev)
    assert i18n.t("chat.error_unauthorized") in ui.bubble._transcript.toPlainText()
    ui.close()


def test_context_menu_keeps_strong_ref(tmp_path, monkeypatch):
    # B22: the avatar context menu (settings / chat / switch avatar / quit)
    # must stay owned by the App — a menu freed while its actions can still
    # fire is a use-after-free.
    import gc
    import weakref

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    menu = ui.context_menu()
    ref = weakref.ref(menu)
    del menu
    gc.collect()
    assert ref() is not None, "App must keep the context menu alive"
    assert ui._ctx_menu is ref()


def test_avatar_pos_clamps_to_secondary_screen(tmp_path, monkeypatch):
    # B26: a position saved on a secondary monitor must stay on that
    # monitor instead of being treated as off-screen and reset to primary.
    from PySide6.QtGui import QGuiApplication

    import ui.avatar_app as aa

    class Geo:
        def __init__(self, x, y, w, h):
            self._x, self._y, self._w, self._h = x, y, w, h

        def x(self):
            return self._x

        def y(self):
            return self._y

        def width(self):
            return self._w

        def height(self):
            return self._h

        def contains(self, px, py):
            return (self._x <= px < self._x + self._w
                    and self._y <= py < self._y + self._h)

    class Screen:
        def __init__(self, geo):
            self._geo = geo

        def geometry(self):
            return self._geo

    primary = Screen(Geo(0, 0, 1920, 1080))
    secondary = Screen(Geo(1920, 0, 2560, 1440))
    monkeypatch.setattr(
        QGuiApplication, "screens", staticmethod(lambda: [primary, secondary])
    )
    monkeypatch.setattr(aa, "load_avatar_pos", lambda p: (2000, 200))
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    x, y = ui._initial_avatar_pos(primary.geometry())
    assert (x, y) == (2000, 200)


def test_avatar_assistant_emotion_sets_emotion(tmp_path, monkeypatch):
    """F1: assistant_emotion must switch the avatar emotion axis."""
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._sid = ui._history.create_session()
    seen = []
    monkeypatch.setattr(ui.avatar, "set_emotion", seen.append)
    ev = Event("assistant_emotion", ui._sid, "t1", {"emotion": "happy"})
    ui._on_event(ev)
    assert seen == ["happy"]
    ui.close()


def test_avatar_unknown_emotion_payload_falls_back(tmp_path, monkeypatch):
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._sid = ui._history.create_session()
    seen = []
    monkeypatch.setattr(ui.avatar, "set_emotion", seen.append)
    ev = Event("assistant_emotion", ui._sid, "t1", {})
    ui._on_event(ev)
    assert seen == ["neutral"]
    ui.close()


def test_avatar_cancelled_resets_emotion(tmp_path, monkeypatch):
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._sid = ui._history.create_session()
    seen = []
    monkeypatch.setattr(ui.avatar, "set_emotion", seen.append)
    ev = Event("agent_cancelled", ui._sid, "t1", {"reason": "cancelled"})
    ui._on_event(ev)
    assert "neutral" in seen
    ui.close()


def test_avatar_error_resets_emotion(tmp_path, monkeypatch):
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._sid = ui._history.create_session()
    seen = []
    monkeypatch.setattr(ui.avatar, "set_emotion", seen.append)
    ev = Event("agent_error", ui._sid, "t1", {"error_code": "boom", "message": "x"})
    ui._on_event(ev)
    assert "neutral" in seen
    ui.close()


def test_avatar_finished_with_final_text_appends_error(tmp_path, monkeypatch):
    # B32: _run_agent's exception path emits finished(text); the text must
    # reach the bubble, not vanish.
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.bubble.setVisible(True)
    ui._on_finished("Hata: patladı")
    lines = ui.bubble._transcript.toPlainText()
    assert "Hata: patladı" in lines
    ui.close()


def test_avatar_names_include_user_dir(tmp_path, monkeypatch):
    # B51: the character menu must list user-built packs too, not only
    # bundled assets.
    app, ui, rt = _make_app(tmp_path, monkeypatch)
    from core import paths as core_paths
    import ui.avatar_app as aa

    user_dir = tmp_path / "user_avatars"
    user_dir.mkdir()
    (user_dir / "mycustom").mkdir()
    assets = tmp_path / "assets_avatars"
    (assets / "base").mkdir(parents=True)
    monkeypatch.setattr(core_paths, "user_avatars_dir", lambda: user_dir)
    monkeypatch.setattr(aa, "ASSETS", assets)
    names = ui._avatar_names()
    assert "mycustom" in names
    assert "base" in names
    ui.close()


def test_avatar_late_events_route_to_task_session(tmp_path, monkeypatch):
    # B72: mirror of the main window's B9 — a late assistant_message must
    # land in the session that started the task, not the one now on screen.
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._on_send("selam")
    task_sid = ui._sid
    other = ui._history.create_session()  # user switches chats mid-task
    ui._sid = other
    ev = Event("assistant_message", task_sid, "t1", {"text": "gec yanit"})
    ui._on_event(ev)
    msgs_a = [m[1] for m in ui._history.messages(task_sid)]
    msgs_b = [m[1] for m in ui._history.messages(other)]
    assert any("gec yanit" in m for m in msgs_a), msgs_a
    assert not any("gec yanit" in m for m in msgs_b), msgs_b
    ui.close()


def test_avatar_late_tool_events_route_to_task_session(tmp_path, monkeypatch):
    from core.events import Event

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui._on_send("selam")
    task_sid = ui._sid
    other = ui._history.create_session()
    ui._sid = other
    ev = Event("tool_finished", task_sid, "t1",
               {"tool_name": "screenshot", "ok": True, "summary": "ok"})
    ui._on_event(ev)
    roles_a = [m[0] for m in ui._history.messages(task_sid)]
    assert "tool" in roles_a, roles_a
    assert [m[0] for m in ui._history.messages(other)] == []
    ui.close()
