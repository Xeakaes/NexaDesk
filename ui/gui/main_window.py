"""GUI main window: sidebar, chat transcript, history browser (spec §4, §5)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QKeyEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.history import HistoryStore, default_db_path
from ui.i18n import i18n
from ui.paths import SETTINGS_PATH, SECRETS_PATH
from ui.prefs import UiPrefs, load_prefs, save_prefs
from ui.theme import qss


class _Input(QPlainTextEdit):
    returnPressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            == Qt.KeyboardModifier.NoModifier
        ):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)


class _UiSignals(QObject):
    assistant = Signal(str)
    tool = Signal(str, str, bool)
    finished = Signal()
    error = Signal(str, str)  # message, session_id
    cancelled = Signal(str)  # session_id


def _build_delete_dialog(parent, title: str) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(i18n.t("sessions.delete"))
    lay = QVBoxLayout(dlg)
    msg = QLabel(i18n.t("sessions.delete_confirm", title=title), dlg)
    msg.setWordWrap(True)
    lay.addWidget(msg)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No,
        dlg,
    )
    yes = buttons.button(QDialogButtonBox.StandardButton.Yes)
    yes.setText(i18n.t("sessions.delete"))
    yes.setObjectName("danger")
    no = buttons.button(QDialogButtonBox.StandardButton.No)
    no.setText(i18n.t("sessions.delete_cancel"))
    no.setObjectName("outline")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    return dlg


def confirm_delete_session(parent, title: str) -> bool:
    dlg = _build_delete_dialog(parent, title)
    return dlg.exec() == QDialog.DialogCode.Accepted


class ChatWindow(QMainWindow):
    def __init__(
        self,
        runtime=None,
        bus=None,
        history: HistoryStore | None = None,
        ui_json_path: Path | None = None,
        settings_path: Path | None = None,
        secrets_path: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("main")
        self.resize(880, 600)
        self._runtime = runtime
        self._history = history or HistoryStore(default_db_path())
        self._ui_json_path = ui_json_path or default_ui_json()
        self._settings_path = settings_path or SETTINGS_PATH
        self._secrets_path = secrets_path or SECRETS_PATH
        self._session_id: str | None = None
        self._active_task_session: str | None = None
        self._messages: list[dict] = []
        self._busy = False
        self._sidebar_expanded = True
        self._notifier = None
        self._quitting = False
        self._tray = None

        # --- sidebar ---
        self._new_chat_btn = QPushButton(self)
        self._new_chat_btn.setObjectName("new_chat")
        self._new_chat_btn.clicked.connect(self.new_chat)
        self._sessions_header = QLabel(self)
        self._sessions_header.setObjectName("sessions_header")
        self._sessions = QListWidget(self)
        self._sessions.itemClicked.connect(self._on_session_click)
        self._theme_btn = QPushButton(self)
        self._theme_btn.clicked.connect(self._toggle_theme)
        self._settings_btn = QPushButton(self)
        self._settings_btn.clicked.connect(self._open_settings)
        self._switch_avatar_btn = QPushButton(self)
        self._switch_avatar_btn.clicked.connect(self._switch_to_avatar)
        self._collapse_btn = QPushButton(self)
        self._collapse_btn.clicked.connect(self._toggle_sidebar)

        side_layout = QVBoxLayout()
        side_layout.addWidget(self._new_chat_btn)
        side_layout.addWidget(self._sessions_header)
        side_layout.addWidget(self._sessions, 1)
        side_layout.addWidget(self._theme_btn)
        side_layout.addWidget(self._settings_btn)
        side_layout.addWidget(self._switch_avatar_btn)
        side_layout.addWidget(self._collapse_btn)
        self._side_inner = QFrame(self)
        self._side_inner.setObjectName("sidebar")
        self._side_inner.setLayout(side_layout)
        self._side_inner.setFixedWidth(260)

        # --- chat ---
        self._empty_state = QFrame(self)
        self._empty_state.setObjectName("empty_state")
        empty_lay = QVBoxLayout(self._empty_state)
        self._empty_title = QLabel(self._empty_state)
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint = QLabel(self._empty_state)
        self._empty_hint.setObjectName("muted")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(self._empty_title)
        empty_lay.addWidget(self._empty_hint)
        self._msg_area = QWidget()
        self._msg_area.setObjectName("msg_area")
        self._msg_layout = QVBoxLayout(self._msg_area)
        self._msg_layout.addWidget(self._empty_state)
        self._msg_layout.addStretch(1)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("chat")
        self._scroll.setWidget(self._msg_area)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._activity = QLabel("", self)
        self._activity.setObjectName("muted")
        self._chat_input = _Input(self)
        self._chat_input.setObjectName("chat_input")
        self._chat_input.setFixedHeight(80)
        self._chat_input.returnPressed.connect(self._send)
        self._send_btn = QPushButton(self)
        self._send_btn.clicked.connect(self._send)
        self._cancel_btn = QPushButton(self)
        self._cancel_btn.setObjectName("outline")
        self._cancel_btn.clicked.connect(self._cancel)
        self._attach_plus = QPushButton("+", self)
        self._attach_plus.setObjectName("attach_plus")
        self._attach_plus.setToolTip(i18n.t("chat.attach"))
        self._attach_plus.setFixedSize(28, 28)
        self._attach_plus.clicked.connect(self._pick_attachments)
        self._pending_attachments: list = []
        self._chip_bar = QWidget(self)
        self._chip_bar.hide()
        self._chip_layout = QHBoxLayout(self._chip_bar)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.addStretch(1)

        self._input_row = QWidget(self)
        self._input_row.setObjectName("input_row")
        input_l = QHBoxLayout(self._input_row)
        input_l.setContentsMargins(6, 0, 0, 0)
        input_l.setSpacing(6)
        input_l.addWidget(self._attach_plus)
        input_l.addWidget(self._chat_input, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self._input_row, 1)
        bottom.addWidget(self._send_btn)
        bottom.addWidget(self._cancel_btn)

        self._update_tag: str | None = None
        self._update_banner = QFrame(self)
        self._update_banner.setObjectName("update_banner")
        self._update_banner.hide()
        banner_l = QHBoxLayout(self._update_banner)
        banner_l.setContentsMargins(10, 4, 10, 4)
        self._update_label = QLabel(self._update_banner)
        self._update_download_btn = QPushButton(self._update_banner)
        self._update_download_btn.clicked.connect(self._open_update_page)
        self._update_dismiss_btn = QPushButton(self._update_banner)
        self._update_dismiss_btn.setObjectName("outline")
        self._update_dismiss_btn.clicked.connect(self._update_banner.hide)
        banner_l.addWidget(self._update_label, 1)
        banner_l.addWidget(self._update_download_btn)
        banner_l.addWidget(self._update_dismiss_btn)

        right = QVBoxLayout()
        right.addWidget(self._update_banner)
        right.addWidget(self._scroll, 1)
        right.addWidget(self._activity)
        right.addWidget(self._chip_bar)
        right.addLayout(bottom)
        right_w = QWidget(self)
        right_w.setLayout(right)

        central = QWidget(self)
        central_l = QHBoxLayout(central)
        central_l.setContentsMargins(0, 0, 0, 0)
        central_l.setSpacing(0)
        central_l.addWidget(self._side_inner)
        central_l.addWidget(right_w, 1)
        self.setCentralWidget(central)

        self._signals = _UiSignals()
        self._signals.assistant.connect(self._on_assistant)
        self._signals.tool.connect(self._on_tool)
        self._signals.finished.connect(self._on_finished)
        self._signals.error.connect(self._on_error)
        self._signals.cancelled.connect(self._on_cancelled)

        self._bridge = None
        if bus is not None:
            from ui.bridge import QtBridge

            self._bridge = QtBridge(bus)
            self._bridge.sig.connect(self._on_event)

        from ui.i18n import language_bridge

        language_bridge.changed.connect(self.retranslate)

        self._sessions.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._sessions.customContextMenuRequested.connect(self._on_session_menu)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self._sessions,
            activated=self._on_session_menu_keyboard,
            context=Qt.ShortcutContext.WidgetShortcut,
        )

        self.retranslate()
        self._history.purge_empty_sessions()
        self.new_chat()
        QTimer.singleShot(2000, self._schedule_update_check)
        self._setup_tray()

    # --- i18n / theme ---

    def retranslate(self) -> None:
        t = i18n.t
        self.setWindowTitle(t("app.title"))
        self._new_chat_btn.setText(t("sidebar.new_chat"))
        self._sessions_header.setText(t("sidebar.sessions"))
        self._theme_btn.setText(t("sidebar.theme"))
        self._settings_btn.setText(t("sidebar.settings"))
        self._switch_avatar_btn.setText(t("sidebar.switch_avatar"))
        if self._sidebar_expanded:
            self._collapse_btn.setText("»")
            self._collapse_btn.setToolTip(t("sidebar.collapse"))
        else:
            self._collapse_btn.setText("☰")
            self._collapse_btn.setToolTip(t("sidebar.expand"))
        self._chat_input.setPlaceholderText(t("chat.input_placeholder"))
        self._send_btn.setText(t("chat.send"))
        self._cancel_btn.setText(t("chat.cancel"))
        self._attach_plus.setToolTip(t("chat.attach"))
        self._empty_title.setText(t("chat.empty_title"))
        self._empty_hint.setText(t("chat.empty_hint"))
        self._update_download_btn.setText(t("update.download"))
        self._update_dismiss_btn.setText(t("update.dismiss"))
        self._refresh_update_banner_text()
        if self._tray is not None:
            self._tray.retranslate()

    # --- update check ---

    def _schedule_update_check(self) -> None:
        from core.paths import bundled_version
        from ui.update import schedule_update_check

        schedule_update_check(
            self._settings_path, bundled_version(), self._show_update_banner
        )

    def _show_update_banner(self, tag: str) -> None:
        self._update_tag = tag
        self._refresh_update_banner_text()
        self._update_banner.show()

    def _refresh_update_banner_text(self) -> None:
        tag = self._update_tag or ""
        self._update_label.setText(i18n.t("update.banner", tag=tag))

    def _open_update_page(self) -> None:
        from ui.update import RELEASES_URL

        QDesktopServices.openUrl(QUrl(RELEASES_URL))

    # --- system tray ---

    def _setup_tray(self) -> None:
        from ui.tray import TrayController

        controller = TrayController(self)
        if not controller.is_available():
            controller.deleteLater()
            return
        self._tray = controller
        controller.open_chat.connect(self._show_main_window)
        controller.open_avatar.connect(self._switch_to_avatar)
        controller.open_settings.connect(self._open_settings)
        controller.quit_requested.connect(self._force_quit)
        controller.show()

    def _show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _force_quit(self) -> None:
        self._quitting = True
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt naming
        from ui.tray import close_to_tray_enabled

        if (
            not self._quitting
            and self._tray is not None
            and close_to_tray_enabled(self._settings_path)
        ):
            event.ignore()
            self.hide()
            return
        event.accept()

    def _toggle_theme(self) -> None:
        prefs = load_prefs(self._ui_json_path)
        new = "light" if prefs.theme == "dark" else "dark"
        save_prefs(self._ui_json_path, UiPrefs(mode=prefs.mode, theme=new, lang=prefs.lang))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss(new))

    def _toggle_sidebar(self) -> None:
        # B71: the collapsed 48px rail cannot hold a text label or the
        # sessions header — glyphs only, header hidden with the rest.
        widgets = (
            self._sessions_header,
            self._new_chat_btn,
            self._sessions,
            self._theme_btn,
            self._settings_btn,
            self._switch_avatar_btn,
        )
        if self._sidebar_expanded:
            self._side_inner.setFixedWidth(48)
            for w in widgets:
                w.hide()
            self._sidebar_expanded = False
            self._collapse_btn.setText("☰")  # expand
            self._collapse_btn.setToolTip(i18n.t("sidebar.expand"))
        else:
            self._side_inner.setFixedWidth(260)
            for w in widgets:
                w.show()
            self._sidebar_expanded = True
            self._collapse_btn.setText("»")  # collapse
            self._collapse_btn.setToolTip(i18n.t("sidebar.collapse"))

    def _switch_to_avatar(self) -> None:
        prefs = load_prefs(self._ui_json_path)
        save_prefs(self._ui_json_path, UiPrefs(mode="avatar", theme=prefs.theme, lang=prefs.lang))
        self._restart()

    def _restart(self) -> None:
        import os
        import sys

        from ui.prefs import restart_argv

        argv = restart_argv()
        os.execv(sys.executable, argv)

    def _open_settings(self) -> None:
        from ui.settings import SettingsWindow

        if getattr(self, "_settings_win", None) is None:
            self._settings_win = SettingsWindow(
                self._settings_path,
                self._secrets_path,
                self._ui_json_path,
            )
            self._settings_win.saved.connect(self._on_settings_saved)
        self._settings_win.load()
        self._settings_win.show()
        self._settings_win.raise_()

    def _on_settings_saved(self) -> None:
        """Apply runtime-affecting settings without a restart (persona)."""
        # B42: theme picked in Settings must apply live, not after a restart.
        try:
            prefs = load_prefs(self._ui_json_path)
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(qss(prefs.theme))
        except Exception:
            pass
        if self._runtime is None:
            return
        try:
            from core.config import load_settings

            settings = load_settings(self._settings_path)
        except Exception:
            return
        self._runtime.set_persona(str((settings.get("agent") or {}).get("persona", "")))
        # B29 + B24: rebuild screen-control tools and hot-swap the provider
        # so saved changes reach the live runtime without an app restart.
        # An incomplete save (e.g. missing key) keeps the current provider.
        from ui.setup import apply_screen_control, reload_provider

        apply_screen_control(self._runtime, self._settings_path, self._secrets_path)
        reload_provider(self._runtime, self._settings_path, self._secrets_path)
        # B70: a saved port/host/enabled change must reach the server spawn —
        # otherwise a moved server keeps answering on the old port forever.
        try:
            import sys

            from app_entry.entry import maybe_spawn_server

            maybe_spawn_server(settings)
        except Exception as exc:
            print(f"screen-control spawn skipped: {exc}", file=sys.stderr)

    # --- sessions ---

    def new_chat(self) -> None:
        # Lazy: the session row is created on the first sent message,
        # so closing without typing does not leave an empty session.
        self._session_id = None
        self._clear_messages()
        self._reload_sessions()
        self._chat_input.setFocus()

    def _clear_messages(self) -> None:
        for m in self._messages:
            if m.get("widget") is not None:
                m["widget"].setParent(None)
                m["widget"].deleteLater()
        self._messages.clear()
        self._empty_state.show()

    def _reload_sessions(self) -> None:
        self._sessions.clear()
        for sid, title, _ts in self._history.list_sessions():
            item = QListWidgetItem(title or sid[:8])
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self._sessions.addItem(item)

    def _on_session_click(self, item: QListWidgetItem) -> None:
        sid = item.data(Qt.ItemDataRole.UserRole)
        self._load_session(sid)

    def _on_session_menu(self, pos) -> None:
        item = self._sessions.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._sessions)
        act = menu.addAction(i18n.t("sessions.delete"))
        if menu.exec(self._sessions.mapToGlobal(pos)) == act:
            self._delete_session(item.data(Qt.ItemDataRole.UserRole))

    def _on_session_menu_keyboard(self) -> None:
        item = self._sessions.currentItem()
        if item is None:
            return
        menu = QMenu(self._sessions)
        act = menu.addAction(i18n.t("sessions.delete"))
        center = self._sessions.rect().center()
        if menu.exec(self._sessions.mapToGlobal(center)) == act:
            self._delete_session(item.data(Qt.ItemDataRole.UserRole))

    def _delete_session(self, session_id: str) -> None:
        title = session_id[:8]
        for sid, t, _ts in self._history.list_sessions():
            if sid == session_id:
                title = t or sid[:8]
                break
        if not confirm_delete_session(self, title):
            return
        was_active = session_id == self._session_id
        # B39: cancel the task whenever the DELETED session owns it — even if
        # the user is currently viewing another chat. The was_active+busy
        # branch keeps the legacy behavior when _active_task_session was not
        # tracked (e.g. tests, older flows).
        if self._runtime is not None and (
            self._active_task_session == session_id
            or (was_active and self._busy)
        ):
            self._runtime.cancel_active_task()
            self._active_task_session = None
            self._set_busy(False)
        self._history.delete_session(session_id)
        if was_active:
            self._session_id = None
            self._clear_messages()
            self._chat_input.setFocus()
        self._reload_sessions()

    def _load_session(self, session_id: str, force: bool = False) -> None:
        if not force and session_id == self._session_id:
            return
        self._session_id = session_id
        self._clear_messages()
        seed_pairs: list[tuple[str, str]] = []
        for role, content, tool_name in self._history.messages(session_id):
            self._append(role, content)
            if role in ("user", "assistant"):
                seed_pairs.append((role, content))
        # Give the runtime the text history so the model sees prior turns
        # (B8: without this, a reopened chat had no model-side context).
        if self._runtime is not None and hasattr(self._runtime, "seed_session"):
            self._runtime.seed_session(session_id, seed_pairs)

    # --- chat ---

    def _append(self, role: str, text: str) -> dict:
        self._empty_state.hide()
        name = {
            "user": "msg_user",
            "assistant": "msg_assistant",
            "tool": "msg_tool",
            "error": "msg_error",  # B73
        }.get(role, "msg_assistant")
        frame = QFrame(self)
        frame.setObjectName(name)
        lbl = QLabel(text, frame)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        lay = QHBoxLayout(frame)
        lay.addWidget(lbl)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, frame)
        frame.show()
        entry = {"role": role, "text": text, "objectName": name, "widget": frame}
        self._messages.append(entry)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())
        return entry

    def _send(self) -> None:
        if self._busy:
            return
        text = self._chat_input.toPlainText().strip()
        attachments = list(self._pending_attachments)
        if (not text and not attachments) or self._runtime is None:
            return
        self._chat_input.clear()
        from ui.attachments import build_user_payload

        prompt, images = build_user_payload(text, attachments)
        display = text
        for att in attachments:
            display = f"{display}\n[{i18n.t('chat.attachment')}: {att.name}]".rstrip()
        self._append("user", display or i18n.t("chat.attachment"))
        if self._session_id is None:
            self._session_id = self._history.create_session()
        self._history.append(self._session_id, "user", display or i18n.t("chat.attachment"))
        self._reload_sessions()
        self._set_busy(True)
        self._clear_attachments()
        # snapshot: switching chats mid-task must not rebind the running task
        session_id = self._session_id
        self._active_task_session = session_id
        threading.Thread(
            target=self._run_agent, args=(prompt, images, session_id), daemon=True
        ).start()

    def _run_agent(self, text: str, images: list, session_id: str) -> None:
        try:
            tid = self._runtime.begin_task(session_id, text, images=images or None)
            self._runtime.run_task(tid)
        except Exception as exc:
            self._signals.error.emit(str(exc), session_id)

    def _is_active_task_session(self, session_id: str | None) -> bool:
        # Late events belong to the running task's session, not the chat the
        # user is currently looking at (B9). Fallback keeps the pre-B9 filter
        # for flows that never went through _send (tests, direct calls).
        target = (
            self._active_task_session
            if self._active_task_session is not None
            else self._session_id
        )
        return session_id == target

    # --- attachments ---

    def _pick_attachments(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from ui.attachments import AttachmentError, load_attachment

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            i18n.t("chat.attach"),
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp);;Text (*.txt *.md *.py *.json *.csv *.log);;All (*)",
        )
        rejected = 0  # B74: tell the user, don't drop silently
        for raw in paths:
            try:
                att = load_attachment(Path(raw))
            except (AttachmentError, OSError):
                rejected += 1
                continue
            self._pending_attachments.append(att)
        if rejected:
            self._activity.setText(i18n.t("chat.attach_rejected", count=rejected))
        self._refresh_chips()

    def _clear_attachments(self) -> None:
        self._pending_attachments.clear()
        self._refresh_chips()

    def _refresh_chips(self) -> None:
        while self._chip_layout.count() > 1:  # keep the trailing stretch
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for att in list(self._pending_attachments):
            chip = QPushButton(f"{att.name} ×", self._chip_bar)
            chip.setObjectName("outline")
            chip.clicked.connect(lambda _=False, a=att: self._remove_attachment(a))
            self._chip_layout.insertWidget(self._chip_layout.count() - 1, chip)
        self._chip_bar.setVisible(bool(self._pending_attachments))

    def _remove_attachment(self, att) -> None:
        if att in self._pending_attachments:
            self._pending_attachments.remove(att)
        self._refresh_chips()

    def _on_event(self, event) -> None:
        name = event.name
        payload = event.payload or {}
        if name == "agent_started":
            self._set_busy(True)
        elif name == "tool_started":
            # B33: only draw activity from the chat the user is looking at.
            if event.session_id != self._session_id:
                return
            tool = payload.get("tool_name", "")
            self._signals.tool.emit("tool", i18n.t("chat.tool_started_line", name=tool), True)
            self._activity.setText(i18n.t("chat.activity_running", name=tool))
        elif name == "tool_finished":
            if event.session_id != self._session_id:
                return
            tool = payload.get("tool_name", "")
            ok = bool(payload.get("ok"))
            key = "chat.tool_finished_ok" if ok else "chat.tool_finished_fail"
            line = i18n.t(key, name=tool)
            if not ok:
                # B68: "(Hata)" alone tells the user nothing; carry the
                # runtime's reason into the transcript (truncated for the
                # bubble, full text in the tooltip).
                summary = str(payload.get("summary") or "")
                if summary and summary != "ok":
                    line = f"{line}: {summary[:120]}"
            self._signals.tool.emit("tool", line, True)
            self._activity.setText("")
        elif name == "assistant_message":
            text = payload.get("text", "")
            if text:
                # Persist only for the running task's session; a chat switch
                # must not lose the reply (B9), and a deleted session must not
                # get a late write (FK violation).
                if self._is_active_task_session(event.session_id):
                    self._history.append(event.session_id, "assistant", text)
                if event.session_id == self._session_id:
                    self._signals.assistant.emit(text)
        elif name == "agent_finished":
            if self._is_active_task_session(event.session_id):
                self._active_task_session = None
                self._signals.finished.emit()
        elif name == "agent_error":
            code = payload.get("error_code", "")
            msg = payload.get("message") or code
            if self._is_active_task_session(event.session_id):
                self._active_task_session = None
                self._signals.error.emit(f"({code}): {msg}", event.session_id)
        elif name == "provider_notice":
            if event.session_id != self._session_id:
                return
            if payload.get("code") == "vision_disabled":
                self._signals.tool.emit(
                    "tool", i18n.t("chat.vision_disabled"), True
                )
        elif name == "agent_cancelled":
            if self._is_active_task_session(event.session_id):
                self._active_task_session = None
                self._signals.cancelled.emit(event.session_id)
        elif name == "confirmation_requested":
            self._activity.setText(
                i18n.t("confirmation.pending") + f" {payload.get('tool_name', '?')}"
            )
            from ui.confirmation import ask_confirmation

            approved = ask_confirmation(
                self,
                payload.get("tool_name", "?"),
                payload.get("question", ""),
                payload.get("arguments") or {},
            )
            if self._runtime is not None:
                self._runtime.resolve_confirmation(
                    event.task_id, payload.get("confirm_id", ""), approved
                )
            self._activity.setText("")

    def _on_assistant(self, text: str) -> None:
        # Persistence already happened in _on_event against the task session.
        self._append("assistant", text)

    def _on_tool(self, role: str, text: str, _persist: bool) -> None:
        self._append(role, text)

    def _on_finished(self) -> None:
        self._active_task_session = None
        self._set_busy(False)
        self._activity.setText("")
        self._reload_sessions()
        if not self.isActiveWindow():
            self._maybe_notify(
                i18n.t("notify.task_done_title"), i18n.t("notify.task_done_body")
            )

    def _on_error(self, msg: str, session_id: str | None) -> None:
        self._active_task_session = None
        self._set_busy(False)
        self._activity.setText("")
        line = f"{i18n.t('chat.error_prefix')}: {msg}"
        # B73: role "error" keeps the line out of seed_session (only
        # user/assistant are seeded) — the model must not treat its own
        # failure notice as something it said.
        if session_id is not None:
            self._history.append(session_id, "error", line)
        if session_id == self._session_id:
            self._append("error", line)
        self._reload_sessions()
        # Deliberate: errors notify even when the window is in front
        # (pinned by test_error_notifies_even_when_active) — unlike
        # _on_finished, which only notifies in the background.
        self._maybe_notify(i18n.t("notify.task_error_title"), msg)

    def _maybe_notify(self, title: str, body: str) -> None:
        from ui.notifications import Notifier, notifications_enabled

        if not notifications_enabled(self._settings_path):
            return
        if self._notifier is None:
            # Reuse the tray icon when we own one — one icon per process.
            self._notifier = Notifier(tray=self._tray)
        self._notifier.notify(title, body)

    def _on_cancelled(self, session_id: str | None) -> None:
        self._active_task_session = None
        self._set_busy(False)
        self._activity.setText("")
        line = i18n.t("chat.cancelled")
        # B73: same reasoning as _on_error — a cancel is not model output.
        if session_id is not None:
            self._history.append(session_id, "error", line)
        if session_id == self._session_id:
            self._append("error", line)

    def _cancel(self) -> None:
        if self._runtime is not None:
            self._runtime.cancel_active_task()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._send_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)


def default_ui_json() -> Path:
    from ui.paths import ui_json_path

    return ui_json_path()
