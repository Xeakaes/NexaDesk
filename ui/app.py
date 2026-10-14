"""Mode dispatcher: first-run chooser + GUI/Avatar launch (spec §6)."""

from __future__ import annotations

import os
import sys

# Bootstrap: allow running as a plain script (python ui/app.py) where
# sys.path[0] is the ui/ directory, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from core.bootstrap import build_runtime
from core.paths import ensure_user_config
from core.providers.base import ProviderError
from ui.chooser import ModeChooser
from ui.fonts import load_fonts
from ui.history import HistoryStore, default_db_path
from ui.i18n import i18n
from ui.paths import SETTINGS_PATH, SECRETS_PATH, ui_json_path
from ui.prefs import UiPrefs, load_prefs, save_prefs
from ui.setup import UnconfiguredProvider, is_missing_key_error, reload_provider
from ui.theme import apply_theme


def _guide_provider_setup(win, runtime) -> None:
    """First-run: explain the missing model, then open Settings on the provider tab."""
    box = QMessageBox(win)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(i18n.t("setup.missing_provider.title"))
    box.setText(i18n.t("setup.missing_provider.message"))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()
    win._open_settings()
    sw = getattr(win, "_settings_win", None)
    if sw is None:
        return
    if hasattr(sw, "show_provider_tab"):
        sw.show_provider_tab()
    saved = getattr(sw, "saved", None)
    if saved is not None:
        saved.connect(
            lambda: reload_provider(runtime, SETTINGS_PATH, SECRETS_PATH)
        )


def show_config_error(exc: Exception) -> None:
    """Surface a ConfigError as a dialog (B25) — never a silent exit."""
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(i18n.t("setup.config_error.title"))
    box.setText(i18n.t("setup.config_error.message").format(error=exc))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _build_runtime_or_none():
    """(runtime, bus, session, needs_setup), or None after showing a dialog.

    B25: a corrupt settings/secrets file makes build_runtime raise ConfigError;
    on a frozen GUI build that would be a silent exit with no window.
    """
    from core.config import ConfigError

    try:
        try:
            runtime, bus, _session = build_runtime()
            needs_setup = False
        except ProviderError as exc:
            if not is_missing_key_error(exc):
                raise
            # Fresh install: no API key yet. Boot with a placeholder provider
            # and guide the user to Settings instead of dying.
            runtime, bus, _session = build_runtime(provider=UnconfiguredProvider())
            needs_setup = True
    except ConfigError as exc:
        show_config_error(exc)
        return None
    except ProviderError as exc:
        # B67: any provider failure that is not a missing key (unknown type,
        # broken URL) must surface as a dialog — not kill the GUI silently.
        show_config_error(exc)
        return None
    return runtime, bus, _session, needs_setup


def main() -> int:
    ensure_user_config()
    app = QApplication.instance() or QApplication(sys.argv)
    from core.paths import window_icon_path
    from PySide6.QtGui import QIcon

    icon_path = window_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))  # B52
    load_fonts(app)
    ui_json = ui_json_path()
    prefs = load_prefs(ui_json)
    i18n.set_language(prefs.lang)
    apply_theme(app, prefs.theme)
    mode = prefs.mode
    if mode is None:
        chooser = ModeChooser()
        if not chooser.exec() or not chooser.chosen:
            os._exit(0)
        mode = chooser.chosen
        save_prefs(ui_json, UiPrefs(mode=mode, theme=prefs.theme, lang=prefs.lang))
    if mode == "gui":
        from ui.gui.main_window import ChatWindow

        built = _build_runtime_or_none()
        if built is None:
            return 1
        runtime, bus, _session, needs_setup = built
        history = HistoryStore(default_db_path())
        win = ChatWindow(
            runtime=runtime,
            bus=bus,
            history=history,
            ui_json_path=ui_json,
            settings_path=SETTINGS_PATH,
            secrets_path=SECRETS_PATH,
        )
        try:
            from app_entry.entry import maybe_spawn_server
            from core.config import load_settings

            maybe_spawn_server(load_settings(SETTINGS_PATH))
        except Exception as exc:
            print(f"screen-control spawn skipped: {exc}", file=sys.stderr)
        app.aboutToQuit.connect(runtime.close)
        app.aboutToQuit.connect(history.close)
        win.show()
        if os.environ.get("NEXADESK_DEBUG_OPEN_SETTINGS") == "1":
            QTimer.singleShot(1200, win._open_settings)
        if needs_setup:
            QTimer.singleShot(0, lambda: _guide_provider_setup(win, runtime))
        code = app.exec()
        os._exit(code)
    else:
        from ui.avatar_app import main as avatar_main

        code = avatar_main()
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
