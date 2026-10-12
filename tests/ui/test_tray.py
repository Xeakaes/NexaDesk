from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from ui.gui.main_window import ChatWindow
from ui.history import HistoryStore
from ui.tray import TrayController, close_to_tray_enabled


def _app():
    return QApplication.instance() or QApplication([])


def test_close_to_tray_enabled_reads_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{}")
    assert close_to_tray_enabled(p) is True
    p.write_text('{"tray": {"close_to_tray": false}}')
    assert close_to_tray_enabled(p) is False


def test_tray_menu_actions_emit_signals():
    app = _app()
    tray = TrayController()
    seen = []
    tray.open_chat.connect(lambda: seen.append("chat"))
    tray.open_avatar.connect(lambda: seen.append("avatar"))
    tray.open_settings.connect(lambda: seen.append("settings"))
    tray.quit_requested.connect(lambda: seen.append("quit"))
    tray._act_chat.trigger()
    tray._act_avatar.trigger()
    tray._act_settings.trigger()
    tray._act_quit.trigger()
    assert seen == ["chat", "avatar", "settings", "quit"]
    tray.deleteLater()


class FakeTrayObj:
    def __init__(self):
        self.shown = []
        self.visible = False

    def show_message(self, title, body):
        self.shown.append((title, body))

    def show(self):
        self.visible = True


def _win(tmp_path):
    app = _app()
    store = HistoryStore(tmp_path / "h.db")
    settings = tmp_path / "settings.json"
    if not settings.exists():
        settings.write_text("{}")
    win = ChatWindow(history=store, settings_path=settings)
    return app, win, settings


def test_close_to_tray_hides_window(tmp_path):
    import json

    app, win, settings = _win(tmp_path)
    settings.write_text(json.dumps({"tray": {"close_to_tray": True}}))
    tray = FakeTrayObj()
    win._tray = tray
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted() is False
    assert win.isHidden()
    win.close()


def test_close_quits_when_tray_disabled(tmp_path):
    import json

    app, win, settings = _win(tmp_path)
    settings.write_text(json.dumps({"tray": {"close_to_tray": False}}))
    win._tray = FakeTrayObj()
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted() is True
    win.close()


def test_force_quit_bypasses_close_to_tray(tmp_path):
    import json

    app, win, settings = _win(tmp_path)
    settings.write_text(json.dumps({"tray": {"close_to_tray": True}}))
    win._tray = FakeTrayObj()
    win._quitting = True
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted() is True
    win.close()


def test_tray_open_chat_shows_hidden_window(tmp_path):
    app, win, settings = _win(tmp_path)
    win.hide()
    win._show_main_window()
    assert not win.isHidden()
    win.close()


def test_notifier_uses_show_message_duck_type():
    from ui.notifications import Notifier

    tray = FakeTrayObj()
    Notifier(tray=tray).notify("t", "b")
    assert tray.shown == [("t", "b")]
