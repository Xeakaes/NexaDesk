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
        self._base_icon = icon if icon is not None and not icon.isNull() else None
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

    def set_agent_state(self, state: str) -> None:
        """Reflect the agent run in the tray icon (B88).

        busy → greyscale, error → red-dot overlay, anything else → base.
        A null base icon is a no-op (headless / no app icon set).
        """
        if self._base_icon is None:
            return
        if state == "idle":
            self._tray.setIcon(self._base_icon)
            return
        pixmap = self._base_icon.pixmap(64, 64)
        if pixmap.isNull():
            return
        if state == "busy":
            from PySide6.QtGui import QColor, QImage

            img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            for y in range(img.height()):
                for x in range(img.width()):
                    c = QColor(img.pixel(x, y))
                    if c.alpha() == 0:
                        continue
                    g = (c.red() + c.green() + c.blue()) // 3
                    img.setPixelColor(x, y, QColor(g, g, g, c.alpha()))
            from PySide6.QtGui import QIcon, QPixmap

            self._tray.setIcon(QIcon(QPixmap.fromImage(img)))
        elif state == "error":
            from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

            out = QPixmap(pixmap)
            painter = QPainter(out)
            painter.setBrush(QColor(220, 38, 38))
            painter.setPen(QColor(255, 255, 255))
            r = max(4, out.width() // 4)
            painter.drawEllipse(out.width() - r, 0, r, r)
            painter.end()
            self._tray.setIcon(QIcon(out))
        else:
            self._tray.setIcon(self._base_icon)

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
