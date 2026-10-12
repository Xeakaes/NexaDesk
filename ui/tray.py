"""System tray icon with a menu (open chat / avatar / settings, quit)."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ui.i18n import i18n


def close_to_tray_enabled(settings_path: Path) -> bool:
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool((data.get("tray") or {}).get("close_to_tray", True))


class TrayController(QObject):
    """Owns the QSystemTrayIcon and its menu; emits intent signals.

    The same icon doubles as the notification vehicle (Notifier duck-types
    ``show_message``), so only one tray instance exists per process.
    """

    open_chat = Signal()
    open_avatar = Signal()
    open_settings = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        app = QApplication.instance()
        icon = app.windowIcon() if app is not None else None
        self._tray = QSystemTrayIcon(icon if icon is not None and not icon.isNull() else None)
        menu = QMenu()
        self._act_chat = menu.addAction("")
        self._act_avatar = menu.addAction("")
        self._act_settings = menu.addAction("")
        menu.addSeparator()
        self._act_quit = menu.addAction("")
        self._tray.setContextMenu(menu)
        self._menu = menu
        self._act_chat.triggered.connect(self.open_chat)
        self._act_avatar.triggered.connect(self.open_avatar)
        self._act_settings.triggered.connect(self.open_settings)
        self._act_quit.triggered.connect(self.quit_requested)
        self._tray.activated.connect(self._on_activated)
        self.retranslate()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_chat.emit()

    def retranslate(self) -> None:
        t = i18n.t
        self._act_chat.setText(t("tray.chat"))
        self._act_avatar.setText(t("tray.avatar"))
        self._act_settings.setText(t("tray.settings"))
        self._act_quit.setText(t("tray.quit"))

    def show(self) -> None:
        self._tray.show()

    def show_message(self, title: str, body: str) -> None:
        self._tray.showMessage(title, body)

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()
