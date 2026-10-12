"""Desktop notifications via a system tray icon (silently skipped when unavailable)."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon


def notifications_enabled(settings_path: Path) -> bool:
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool((data.get("notifications") or {}).get("enabled", True))


class Notifier:
    """Shows desktop notifications; owns a lazily created tray icon.

    The tray is only used as a notification vehicle here — Feature 1
    extends the same icon with a full tray menu.
    """

    def __init__(self, tray=None) -> None:
        self._tray = tray

    def _ensure_tray(self):
        if self._tray is not None:
            return self._tray
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        icon = app.windowIcon()
        self._tray = QSystemTrayIcon(icon if not icon.isNull() else None)
        self._tray.show()
        return self._tray

    def notify(self, title: str, body: str) -> None:
        tray = self._ensure_tray()
        if tray is None:
            return
        # QSystemTrayIcon uses showMessage; TrayController uses show_message.
        show = getattr(tray, "showMessage", None) or getattr(tray, "show_message", None)
        if show is not None:
            show(title, body)
