from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.gui.main_window import ChatWindow
from ui.history import HistoryStore


def _win(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = HistoryStore(tmp_path / "h.db")
    win = ChatWindow(history=store)
    return app, win


def test_banner_hidden_by_default(tmp_path):
    app, win = _win(tmp_path)
    assert win._update_banner.isHidden()
    win.close()


def test_show_update_banner_displays_tag(tmp_path):
    app, win = _win(tmp_path)
    win._show_update_banner("v9.9.9")
    assert not win._update_banner.isHidden()
    assert "v9.9.9" in win._update_label.text()
    win.close()


def test_download_button_opens_release_page(tmp_path, monkeypatch):
    app, win = _win(tmp_path)
    opened = []
    from PySide6.QtGui import QDesktopServices

    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(str(url))
    )
    win._show_update_banner("v9.9.9")
    win._update_download_btn.click()
    assert opened and "github.com/Xeakaes/NexaDesk/releases" in opened[0]
    win.close()


def test_dismiss_hides_banner(tmp_path):
    app, win = _win(tmp_path)
    win._show_update_banner("v9.9.9")
    win._update_dismiss_btn.click()
    assert win._update_banner.isHidden()
    win.close()


def test_update_enabled_reads_settings(tmp_path):
    from ui.update import update_check_enabled

    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}")
    assert update_check_enabled(settings_path) is True
    settings_path.write_text('{"updates": {"check_enabled": false}}')
    assert update_check_enabled(settings_path) is False


def test_schedule_update_check_uses_bundled_version(tmp_path, monkeypatch):
    # B10: comparing against core.__version__ ("0.0.0") made every release
    # look newer; the baked _version.txt must win.
    from core import paths as core_paths

    app, win = _win(tmp_path)
    seen = {}

    def fake_schedule(settings_path, current_version, on_newer):
        seen["version"] = current_version

    monkeypatch.setattr("ui.update.schedule_update_check", fake_schedule)
    monkeypatch.delenv("APP_VERSION", raising=False)
    ver_dir = tmp_path / "bundle"
    ver_dir.mkdir()
    (ver_dir / "_version.txt").write_text("0.2.1", encoding="utf-8")
    monkeypatch.setattr(core_paths, "bundle_root", lambda: ver_dir)
    win._schedule_update_check()
    assert seen["version"] == "0.2.1"
    win.close()
