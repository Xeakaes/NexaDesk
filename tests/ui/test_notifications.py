from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.gui.main_window import ChatWindow
from ui.history import HistoryStore
from ui.notifications import Notifier, notifications_enabled


def _win(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "h.db")
    settings = tmp_path / "settings.json"
    if not settings.exists():
        settings.write_text("{}")
    win = ChatWindow(history=store, settings_path=settings)
    win._session_id = store.create_session("t")
    return app, win


def test_notifications_enabled_defaults_on(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{}")
    assert notifications_enabled(p) is True
    p.write_text('{"notifications": {"enabled": false}}')
    assert notifications_enabled(p) is False


class FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, title, body, *a, **k):
        self.messages.append((title, body))


def test_notifier_sends_through_tray():
    tray = FakeTray()
    n = Notifier(tray=tray)
    n.notify("Başlık", "Gövde")
    assert tray.messages == [("Başlık", "Gövde")]


def test_finished_notifies_when_window_inactive(tmp_path):
    app, win = _win(tmp_path)
    fake = FakeTray()
    win._notifier = Notifier(tray=fake)
    win.isActiveWindow = lambda: False
    win._on_finished()
    assert len(fake.messages) == 1
    win.close()


def test_finished_skips_notification_when_active(tmp_path):
    app, win = _win(tmp_path)
    fake = FakeTray()
    win._notifier = Notifier(tray=fake)
    win.isActiveWindow = lambda: True
    win._on_finished()
    assert fake.messages == []
    win.close()


def test_error_notifies_even_when_active(tmp_path):
    # Errors matter even with the window in front.
    app, win = _win(tmp_path)
    fake = FakeTray()
    win._notifier = Notifier(tray=fake)
    win.isActiveWindow = lambda: True
    win._on_error("boom", None)
    assert len(fake.messages) == 1
    win.close()


def test_notifications_respect_disable_toggle(tmp_path):
    import json

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"notifications": {"enabled": False}}))
    store = HistoryStore(tmp_path / "h.db")
    win = ChatWindow(history=store, settings_path=settings)
    fake = FakeTray()
    win._notifier = Notifier(tray=fake)
    win.isActiveWindow = lambda: False
    win._session_id = store.create_session("t")
    win._on_finished()
    win._on_error("boom", win._session_id)
    assert fake.messages == []
    win.close()
