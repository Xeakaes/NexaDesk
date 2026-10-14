"""Chat bubble: transcript, input, tool activity line, cancel (spec §4.2, M2 prompts later)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.i18n import i18n


class BubbleWindow(QFrame):
    def __init__(
        self,
        on_send: Callable[..., None],
        on_cancel: Callable[[], None],
        on_history: Callable[[], None] | None = None,
        on_geometry_change: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("bubble")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setMinimumSize(320, 220)

        self._on_send = on_send
        self._on_cancel = on_cancel
        self._on_history = on_history
        # B83: the transcript can grow the bubble past the screen edge; the
        # host app re-places it on every resize.
        self._on_geometry_change = on_geometry_change
        self._session_picker: QListWidget | None = None

        self._transcript = QPlainTextEdit(self)
        self._transcript.setReadOnly(True)
        # B75: no hard-coded QFont — load_fonts()/the app font already
        # applies; a family override here defeated both.

        self._activity = QLabel("", self)
        self._activity.setWordWrap(True)

        self._input = QLineEdit(self)
        self._input.returnPressed.connect(self._send)

        self._send_btn = QPushButton(self)
        self._send_btn.clicked.connect(self._send)
        self._pending_attachments: list = []
        # Backlog 1: compact + button with chips, matching the chat GUI.
        self._attach_plus = QPushButton("+", self)
        self._attach_plus.setObjectName("attach_plus")
        self._attach_plus.setToolTip(i18n.t("chat.attach"))
        self._attach_plus.setFixedSize(28, 28)
        self._attach_plus.clicked.connect(self._pick_attachments)
        self._chip_bar = QWidget(self)
        self._chip_bar.hide()
        self._chip_layout = QHBoxLayout(self._chip_bar)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.addStretch(1)
        self._history_btn = QPushButton(self)
        if self._on_history is not None:
            self._history_btn.clicked.connect(self._on_history)
        self._cancel_btn = QPushButton(self)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setVisible(False)

        row = QHBoxLayout()
        row.addWidget(self._attach_plus)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_btn)
        row.addWidget(self._history_btn)
        row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._transcript, 1)
        layout.addWidget(self._activity)
        layout.addWidget(self._chip_bar)
        layout.addLayout(row)

        from ui.i18n import language_bridge

        language_bridge.changed.connect(self.retranslate)
        self.retranslate()
        self.set_busy(False)

    def retranslate(self) -> None:
        self._input.setPlaceholderText(i18n.t("chat.input_placeholder"))
        self._send_btn.setText(i18n.t("chat.send"))
        self._attach_plus.setToolTip(i18n.t("chat.attach"))
        self._history_btn.setText(i18n.t("chat.history"))
        self._cancel_btn.setText(i18n.t("chat.cancel"))

    def _pick_attachments(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ui.attachments import AttachmentError, load_attachment

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            i18n.t("chat.attach"),
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp);;Text (*.txt *.md *.py *.json *.csv *.log);;All (*)",
        )
        rejected = 0  # B74
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

    def append_message(self, role: str, text: str) -> None:
        prefix = {
            "user": i18n.t("chat.user_prefix") + ":",
            "assistant": i18n.t("chat.assistant_prefix") + ":",
            "tool": "▸",
        }.get(role, role)
        self._transcript.appendPlainText(f"{prefix} {text}")

    def set_transcript(self, text: str) -> None:
        self._transcript.setPlainText(text)

    def show_session_picker(
        self,
        sessions: list[tuple[str, str]],
        on_pick: Callable[[str], None],
    ) -> None:
        self._close_session_picker()
        picker = QListWidget(self)
        picker.setObjectName("session_picker")
        picker.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        picker.setFixedSize(240, 200)
        for sid, title in sessions:
            item = QListWidgetItem(title or sid[:8], picker)
            item.setData(Qt.ItemDataRole.UserRole, sid)

        def _pick(item: QListWidgetItem) -> None:
            on_pick(item.data(Qt.ItemDataRole.UserRole))
            self._close_session_picker()

        picker.itemClicked.connect(_pick)
        self._session_picker = picker
        picker.move(self.mapToGlobal(QPoint(0, self.height())))
        picker.show()

    def _close_session_picker(self) -> None:
        if self._session_picker is not None:
            self._session_picker.close()
            # B43: schedule deletion so repeated open/close cycles do not
            # accumulate hidden Tool windows until the bubble dies.
            self._session_picker.deleteLater()
            self._session_picker = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # B83: the transcript grows the window; the host must re-place it so
        # it never hangs off the bottom of the screen.
        if self._on_geometry_change is not None:
            self._on_geometry_change()

    def hideEvent(self, event) -> None:
        self._close_session_picker()
        super().hideEvent(event)

    def set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)
        self._history_btn.setEnabled(not busy)
        self._cancel_btn.setVisible(busy)
        self._cancel_btn.setEnabled(busy)

    def set_tool_activity(self, text: str) -> None:
        self._activity.setText(text)

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text and not self._pending_attachments:
            return
        self._input.clear()
        from ui.attachments import build_user_payload

        prompt, images = build_user_payload(text, self._pending_attachments)
        for att in self._pending_attachments:
            if att.kind == "image":
                prompt = f"{prompt}\n[{i18n.t('chat.attachment')}: {att.name}]".rstrip()
        self._pending_attachments.clear()
        self._refresh_chips()
        self._on_send(prompt, images)
