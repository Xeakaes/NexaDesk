"""M1 desktop entry: avatar + bubble + settings wired to the M0 agent runtime."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import os

# Bootstrap: allow running as a plain script (python ui/avatar_app.py) where
# sys.path[0] is the ui/ directory, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu

from core.bootstrap import build_runtime
from core.config import load_settings, save_settings
from core.providers.base import ProviderError
from ui.avatar.state_machine import reduce_event
from ui.avatar.window import AvatarWindow
from ui.bridge import QtBridge
from ui.bubble import BubbleWindow
from ui.fonts import load_fonts
from ui.history import HistoryStore, default_db_path
from ui.i18n import i18n
from ui.paths import SECRETS_PATH, SETTINGS_PATH, ui_json_path
from ui.prefs import load_avatar_pos, load_prefs, restart_into, save_avatar_pos
from ui.settings import SettingsWindow
from ui.setup import (
    UnconfiguredProvider,
    apply_screen_control,
    is_missing_key_error,
    reload_provider,
)
from ui.theme import apply_theme

from core.paths import assets_dir

ASSETS = assets_dir() / "avatars"

# Bubble sits up-left of the avatar; the same offset is kept while dragging.
BUBBLE_OFFSET_Y = -80
BUBBLE_GAP = 16


class _UiSignals(QObject):
    finished = Signal(str)
    activity = Signal(str)


class App:
    def __init__(self) -> None:
        self.settings_path = SETTINGS_PATH
        self.secrets_path = SECRETS_PATH
        try:
            self.runtime, self.bus, self.session = build_runtime()
            self._needs_provider_setup = False
        except ProviderError as exc:
            if not is_missing_key_error(exc):
                raise
            # Fresh install: no API key yet. Boot with a placeholder provider
            # and guide the user to Settings instead of dying.
            self.runtime, self.bus, self.session = build_runtime(
                provider=UnconfiguredProvider()
            )
            self._needs_provider_setup = True
        self._settings_cache = load_settings(self.settings_path)
        # Avatar + bubble are Qt.Tool windows; the parentless permission
        # QDialog is the only "normal" window. With Qt's default
        # quitOnLastWindowClosed=True, closing that dialog (Allow/Deny)
        # would quit the whole app — keep the event loop alive; quitting
        # is explicit via the context-menu Quit action.
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
        self._history = HistoryStore(default_db_path())
        self._history.purge_empty_sessions()
        self._sid: str | None = None  # created lazily on first send
        avatar_name = self._settings_cache.get("avatar", "base")
        self.avatar = self._make_avatar(avatar_name)
        self.bubble = BubbleWindow(
            on_send=self._on_send,
            on_cancel=self._on_cancel,
            on_history=self._on_history,
        )
        self.settings_win = SettingsWindow(self.settings_path, self.secrets_path)
        self._ctx_menu: QMenu | None = None  # B22: strong ref, see context_menu
        saved = getattr(self.settings_win, "saved", None)
        if saved is not None:
            saved.connect(self._on_settings_saved)
        self.bridge = QtBridge(self.bus)
        self.signals = _UiSignals()
        self.signals.finished.connect(self._on_finished)
        self.signals.activity.connect(self.bubble.set_tool_activity)
        self.bridge.sig.connect(self._on_event)
        try:
            from app_entry.entry import maybe_spawn_server

            maybe_spawn_server(self._settings_cache)
        except Exception as exc:
            print(f"screen-control spawn skipped: {exc}", file=sys.stderr)
        self._prefs_path = ui_json_path()
        self.avatar.dragging_changed.connect(self._on_avatar_dragging)
        self.avatar.drag_moved.connect(self._on_avatar_drag_moved)
        screen = QApplication.primaryScreen().geometry()
        x, y = self._initial_avatar_pos(screen)
        self.avatar.move(x, y)
        self.avatar.show()
        self._place_bubble()
        if getattr(self, "_pending_avatar_note", ""):
            self.bubble.append_message("tool", self._pending_avatar_note)
        if self._needs_provider_setup:
            # Deferred so the avatar/bubble are mapped and the event loop is
            # running before the modal guidance dialog appears.
            QTimer.singleShot(0, self._guide_provider_setup)

    def _guide_provider_setup(self) -> None:
        box = QMessageBox(None)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(i18n.t("setup.missing_provider.title"))
        box.setText(i18n.t("setup.missing_provider.message"))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self._open_provider_settings()

    def _open_provider_settings(self) -> None:
        if hasattr(self.settings_win, "show_provider_tab"):
            self.settings_win.show_provider_tab()
        else:
            self.settings_win.load()
            self.settings_win.show()
            self.settings_win.raise_()

    def _on_settings_saved(self) -> None:
        # B29 + B24 + B28: screen_control, provider and persona changes must
        # reach the live runtime on every save — not only during first-run
        # setup. Mirrors the main window's handler.
        # B42: theme picked in Settings must apply live, not after a restart.
        try:
            prefs = load_prefs(self._prefs_path)
            app = QApplication.instance()
            if app is not None:
                from ui.theme import qss

                app.setStyleSheet(qss(prefs.theme))
        except Exception:
            pass
        apply_screen_control(self.runtime, self.settings_path, self.secrets_path)
        configured = reload_provider(
            self.runtime, self.settings_path, self.secrets_path
        )
        settings = load_settings(self.settings_path)
        self.runtime.set_persona(str((settings.get("agent") or {}).get("persona", "")))
        if configured and self._needs_provider_setup:
            self._needs_provider_setup = False
            self.bubble.append_message("tool", i18n.t("setup.provider_ready"))

    def _initial_avatar_pos(self, screen) -> tuple[int, int]:
        """Saved position, clamped to the monitor it belongs to (B26).

        ``screen`` is the primary screen's geometry (legacy fallback); a
        position saved on a secondary monitor stays on that monitor.
        """
        saved = load_avatar_pos(self._prefs_path)
        w = self.avatar.width() or 220
        h = self.avatar.height() or 260
        if saved is not None:
            x, y = saved
            target = screen
            for s in QApplication.screens() or []:
                geo = s.geometry()
                if geo.contains(x, y):
                    target = geo
                    break
            x = max(target.x(), min(x, target.x() + target.width() - w))
            y = max(target.y(), min(y, target.y() + target.height() - h))
            return x, y
        return screen.width() - 220, screen.height() - 260

    def _on_avatar_dragging(self, dragging: bool) -> None:
        if dragging:
            self.bubble.setVisible(True)
            self.bubble.set_tool_activity(i18n.t("avatar.dragging"))
        else:
            self.bubble.set_tool_activity("")
            save_avatar_pos(self._prefs_path, self.avatar.x(), self.avatar.y())

    def _place_bubble(self) -> None:
        av_x, av_y = self.avatar.x(), self.avatar.y()
        av_w = self.avatar.width()
        bw = self.bubble.width() or 320
        # Left of the avatar when the bubble fits with a clear gap; near the
        # left screen edge there is no room, so flip to the avatar's right
        # and come back left as soon as the avatar moves away again.
        if av_x - bw - BUBBLE_GAP >= 0:
            bx = av_x - bw - BUBBLE_GAP
        else:
            bx = av_x + av_w + BUBBLE_GAP
        by = max(0, av_y + BUBBLE_OFFSET_Y)
        self.bubble.move(max(0, bx), by)

    def _on_avatar_drag_moved(self) -> None:
        # Keep the bubble glued to the avatar while the user drags it.
        self._place_bubble()

    def _make_avatar(self, name: str) -> AvatarWindow:
        from core.paths import user_avatars_dir

        # User-built packs take precedence; then the bundled asset dir.
        for root in (user_avatars_dir(), ASSETS):
            candidate = root / name
            if candidate.is_dir():
                try:
                    return AvatarWindow(candidate, context_menu_factory=self.context_menu)
                except Exception:
                    continue
        if name != "base":
            self._pending_avatar_note = i18n.t("chat.avatar_fallback", name=name)
            return AvatarWindow(ASSETS / "base", context_menu_factory=self.context_menu)
        raise FileNotFoundError(f"avatar not found: {name}")

    def _on_send(self, text: str, images: list | None = None) -> None:
        self.bubble.append_message("user", text)
        if self._sid is None:
            self._sid = self._history.create_session()
        self._history.append(self._sid, "user", text)
        self.bubble.set_busy(True)
        threading.Thread(
            target=self._run_agent, args=(text, images or None), daemon=True
        ).start()

    def _on_history(self) -> None:
        sessions = [
            (sid, title) for sid, title, _created in self._history.list_sessions()
        ]
        self.bubble.show_session_picker(sessions, self._on_session_chosen)

    def _on_session_chosen(self, sid: str) -> None:
        self._sid = sid
        lines = []
        seed_pairs: list[tuple[str, str]] = []
        for role, content, tool_name in self._history.messages(sid):
            if role == "tool":
                lines.append(f"{tool_name or 'tool'}: {content}")
            else:
                prefix = (
                    i18n.t("chat.user_prefix")
                    if role == "user"
                    else i18n.t("chat.assistant_prefix")
                )
                lines.append(f"{prefix}: {content}")
                if role in ("user", "assistant"):
                    seed_pairs.append((role, content))
        # Rehydrate the model-side context for reopened chats (B8).
        self.session.seed_session(sid, seed_pairs)
        self.bubble.set_transcript("\n".join(lines))

    def _run_agent(self, text: str, images: list | None = None) -> None:
        try:
            tid = self.runtime.begin_task(self._sid, text, images=images)
            self.runtime.run_task(tid)
        except Exception as exc:
            self.signals.finished.emit(f"{i18n.t('chat.error_prefix')}: {exc}")

    def _on_finished(self, final: str) -> None:
        self.bubble.set_busy(False)
        self.bubble.set_tool_activity("")
        if final:
            # B32: _run_agent's exception path emits finished(text); show it.
            self.bubble.append_message("assistant", final)

    def _on_cancel(self) -> None:
        self.runtime.cancel_active_task()

    def _on_event(self, event) -> None:
        new_state = reduce_event(self.avatar.current_state(), event.name)
        self.avatar.set_state(new_state)
        if event.name == "agent_started":
            self.bubble.setVisible(True)
            self.bubble.set_busy(True)
        elif event.name == "tool_started":
            name = event.payload.get("tool_name", "")
            self.signals.activity.emit(i18n.t("chat.activity_running", name=name))
            line = i18n.t("chat.tool_started_line", name=name)
            self.bubble.append_message("tool", line)
            self._history.append(self._sid, "tool", line, tool_name=name)
        elif event.name == "tool_finished":
            self.bubble.set_tool_activity("")
            name = event.payload.get("tool_name", "")
            ok = event.payload.get("ok", "")
            key = "chat.tool_finished_ok" if ok else "chat.tool_finished_fail"
            line = i18n.t(key, name=name)
            if not ok:
                # B68: same as the GUI window — carry the reason.
                summary = str(event.payload.get("summary") or "")
                if summary and summary != "ok":
                    line = f"{line}: {summary[:120]}"
            self.bubble.append_message("tool", line)
            self._history.append(self._sid, "tool", line, tool_name=name)
        elif event.name == "assistant_message":
            text = event.payload.get("text", "")
            if text:
                self.bubble.append_message("assistant", text)
                self._history.append(self._sid, "assistant", text)
        elif event.name == "assistant_emotion":
            # F1: classified reply emotion → avatar axis (unknown → neutral).
            self.avatar.set_emotion(event.payload.get("emotion", "neutral"))
        elif event.name == "agent_finished":
            self._on_finished("")
        elif event.name == "agent_error":
            self._on_finished("")
            self.avatar.set_emotion("neutral")
            msg = event.payload.get("message") or event.payload.get("error_code", "")
            code = event.payload.get("error_code", "")
            if code == "rate_limited":
                msg = i18n.t("chat.error_rate_limited")
            elif code == "unauthorized":
                msg = i18n.t("chat.error_unauthorized")
            line = f"{i18n.t('chat.error_prefix')} ({code}): {msg}"
            self.bubble.append_message("assistant", line)
            self._history.append(self._sid, "assistant", line)
        elif event.name == "agent_cancelled":
            self._on_finished("")
            self.avatar.set_emotion("neutral")
            line = i18n.t("chat.cancelled")
            self.bubble.append_message("assistant", line)
            self._history.append(self._sid, "assistant", line)
        elif event.name == "confirmation_requested":
            self.signals.activity.emit(
                f"▸ {i18n.t('confirmation.pending')}: {event.payload.get('tool_name', '?')}"
            )
            from ui.confirmation import ask_confirmation

            approved = ask_confirmation(
                None,
                event.payload.get("tool_name", "?"),
                event.payload.get("question", ""),
                event.payload.get("arguments") or {},
            )
            self.runtime.resolve_confirmation(
                event.task_id, event.payload.get("confirm_id", ""), approved
            )
            self.signals.activity.emit("")

    def context_menu(self) -> QMenu:
        # B22: keep a strong ref — the menu must never be a temporary that
        # Qt outlives (use-after-free on its actions). App is a QObject, not
        # a QWidget, so unlike tray.py we cannot parent it; same ownership
        # pattern as TrayController._menu.
        menu = QMenu()
        self._ctx_menu = menu
        act_settings = QAction(i18n.t("menu.settings"), menu)
        act_settings.triggered.connect(self._open_settings)
        act_chat = QAction(i18n.t("menu.chat"), menu)
        act_chat.triggered.connect(self.bubble.toggle)
        char_menu = QMenu(i18n.t("menu.avatar"), menu)
        for name in self._avatar_names():
            act = QAction(name, char_menu)
            act.triggered.connect(lambda checked=False, n=name: self._switch_avatar(n))
            char_menu.addAction(act)
        act_switch_gui = QAction(i18n.t("menu.switch_gui"), menu)
        act_switch_gui.triggered.connect(self._switch_to_gui)
        act_quit = QAction(i18n.t("menu.quit"), menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_settings)
        menu.addAction(act_chat)
        menu.addMenu(char_menu)
        menu.addAction(act_switch_gui)
        menu.addSeparator()
        menu.addAction(act_quit)
        return menu

    def _switch_to_gui(self) -> None:
        restart_into(ui_json_path(), "gui")

    def _open_settings(self) -> None:
        self.settings_win.load()
        self.settings_win.show()
        self.settings_win.raise_()

    def _avatar_names(self) -> list[str]:
        # B51: scan BOTH the user-pack dir and bundled assets — user-built
        # packs must appear in the character menu.
        from core.paths import user_avatars_dir

        names: set[str] = set()
        for root in (ASSETS, user_avatars_dir()):
            if root.is_dir():
                names.update(p.name for p in root.iterdir() if p.is_dir())
        return sorted(names)

    def _switch_avatar(self, name: str) -> None:
        settings = load_settings(self.settings_path)
        settings["avatar"] = name
        save_settings(self.settings_path, settings)
        self.bubble.append_message("tool", i18n.t("chat.avatar_selected", name=name))

    def quit(self) -> None:
        self.runtime.close()
        QApplication.quit()

    def close(self) -> None:
        self.runtime.close()


def build_ui() -> App:
    from core.paths import ensure_user_config, window_icon_path

    ensure_user_config()
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtGui import QIcon

    icon_path = window_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))  # B52
    load_fonts(app)
    prefs = load_prefs(ui_json_path())
    i18n.set_language(prefs.lang)
    apply_theme(app, prefs.theme)
    try:
        ui = App()
    except Exception as exc:
        QMessageBox.critical(
            None,
            i18n.t("app.title"),
            f"Agent başlatılamadı:\n{exc}\n\nAyarları config/ altından kontrol edin.",
        )
        raise SystemExit(1) from exc
    app.aboutToQuit.connect(ui.runtime.close)
    app.aboutToQuit.connect(ui._history.close)
    return ui


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from core.config import ConfigError

    from ui.app import show_config_error

    try:
        ui = build_ui()
    except ConfigError as exc:  # B25: corrupt config → dialog, not silent exit
        show_config_error(exc)
        return 1
    ui.bubble.show()
    code = app.exec()
    os._exit(code)  # skip non-daemon ThreadPoolExecutor join on quit-while-busy


if __name__ == "__main__":
    sys.exit(main())
