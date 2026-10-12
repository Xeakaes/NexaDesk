"""GUI main window: sidebar, chat transcript, history browser (spec §4, §5)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QKeyEvent, QShortcut
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
from ui.paths import SETTINGS_PATH, SECRETS_PATH, ui_json_path
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
    error = Signal(str)
    cancelled = Signal()


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
        self._messages: list[dict] = []
        self._busy = False
        self._sidebar_expanded = True

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

        bottom = QHBoxLayout()
        bottom.addWidget(self._chat_input, 1)
        bottom.addWidget(self._send_btn)
        bottom.addWidget(self._cancel_btn)

        right = QVBoxLayout()
        right.addWidget(self._scroll, 1)
        right.addWidget(self._activity)
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
            self._collapse_btn.setText(t("sidebar.collapse"))
        else:
            self._collapse_btn.setText(t("sidebar.expand"))
        self._chat_input.setPlaceholderText(t("chat.input_placeholder"))
        self._send_btn.setText(t("chat.send"))
        self._cancel_btn.setText(t("chat.cancel"))
        self._empty_title.setText(t("chat.empty_title"))
        self._empty_hint.setText(t("chat.empty_hint"))

    def _toggle_theme(self) -> None:
        prefs = load_prefs(self._ui_json_path)
        new = "light" if prefs.theme == "dark" else "dark"
        save_prefs(self._ui_json_path, UiPrefs(mode=prefs.mode, theme=new, lang=prefs.lang))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss(new))

    def _toggle_sidebar(self) -> None:
        if self._sidebar_expanded:
            self._side_inner.setFixedWidth(48)
            for w in (
                self._new_chat_btn,
                self._sessions,
                self._theme_btn,
                self._settings_btn,
                self._switch_avatar_btn,
            ):
                w.hide()
            self._sidebar_expanded = False
            self._collapse_btn.setText(i18n.t("sidebar.expand"))
        else:
            self._side_inner.setFixedWidth(260)
            for w in (
                self._new_chat_btn,
                self._sessions,
                self._theme_btn,
                self._settings_btn,
                self._switch_avatar_btn,
            ):
                w.show()
            self._sidebar_expanded = True
            self._collapse_btn.setText(i18n.t("sidebar.collapse"))

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
        if self._runtime is None:
            return
        try:
            from core.config import load_settings

            settings = load_settings(self._settings_path)
        except Exception:
            return
        self._runtime.set_persona(str((settings.get("agent") or {}).get("persona", "")))

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
        if was_active and self._busy and self._runtime is not None:
            self._runtime.cancel_active_task()
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
        for role, content, tool_name in self._history.messages(session_id):
            self._append(role, content)

    # --- chat ---

    def _append(self, role: str, text: str) -> dict:
        self._empty_state.hide()
        name = {"user": "msg_user", "assistant": "msg_assistant", "tool": "msg_tool"}.get(
            role, "msg_assistant"
        )
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
        if not text or self._runtime is None:
            return
        self._chat_input.clear()
        self._append("user", text)
        if self._session_id is None:
            self._session_id = self._history.create_session()
        self._history.append(self._session_id, "user", text)
        self._reload_sessions()
        self._set_busy(True)
        # snapshot: switching chats mid-task must not rebind the running task
        session_id = self._session_id
        threading.Thread(
            target=self._run_agent, args=(text, session_id), daemon=True
        ).start()

    def _run_agent(self, text: str, session_id: str) -> None:
        try:
            tid = self._runtime.begin_task(session_id, text)
            self._runtime.run_task(tid)
        except Exception as exc:
            self._signals.error.emit(str(exc))

    def _on_event(self, event) -> None:
        name = event.name
        payload = event.payload or {}
        if name == "agent_started":
            self._set_busy(True)
        elif name == "tool_started":
            tool = payload.get("tool_name", "")
            self._signals.tool.emit("tool", i18n.t("chat.tool_started_line", name=tool), True)
            self._activity.setText(i18n.t("chat.activity_running", name=tool))
        elif name == "tool_finished":
            tool = payload.get("tool_name", "")
            ok = bool(payload.get("ok"))
            key = "chat.tool_finished_ok" if ok else "chat.tool_finished_fail"
            self._signals.tool.emit("tool", i18n.t(key, name=tool), True)
            self._activity.setText("")
        elif name == "assistant_message":
            text = payload.get("text", "")
            if text and event.session_id == self._session_id:
                self._signals.assistant.emit(text)
        elif name == "agent_finished":
            if event.session_id == self._session_id:
                self._signals.finished.emit()
        elif name == "agent_error":
            code = payload.get("error_code", "")
            msg = payload.get("message") or code
            if event.session_id == self._session_id:
                self._signals.error.emit(f"({code}): {msg}")
        elif name == "provider_notice":
            if payload.get("code") == "vision_disabled":
                self._signals.tool.emit(
                    "tool", i18n.t("chat.vision_disabled"), True
                )
        elif name == "agent_cancelled":
            if event.session_id == self._session_id:
                self._signals.cancelled.emit()
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
        self._append("assistant", text)
        self._history.append(self._session_id, "assistant", text)

    def _on_tool(self, role: str, text: str, _persist: bool) -> None:
        self._append(role, text)

    def _on_finished(self) -> None:
        self._set_busy(False)
        self._activity.setText("")
        self._reload_sessions()

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._activity.setText("")
        line = f"{i18n.t('chat.error_prefix')}: {msg}"
        self._append("assistant", line)
        self._history.append(self._session_id, "assistant", line)
        self._reload_sessions()

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self._activity.setText("")
        self._append("assistant", i18n.t("chat.cancelled"))
        self._history.append(self._session_id, "assistant", i18n.t("chat.cancelled"))

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
