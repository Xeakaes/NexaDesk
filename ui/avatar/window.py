"""Frameless transparent avatar window driven by manifest animations (spec §4.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from ui.avatar.manifest import StateAnim, load_manifest
from ui.avatar.state_machine import AvatarState

DISPLAY_H = 160
SPINNER_STATES = {"thinking", "working"}
SPINNER_FPS = 12


def error_timeout_ms() -> int:
    return 3000


def load_spinner_frames(avatar_dir: Path) -> list[str]:
    spinner_dir = avatar_dir / "spinner"
    if not spinner_dir.is_dir():
        return []
    return sorted(str(p) for p in spinner_dir.glob("spin_*.png"))


class AvatarWindow(QWidget):
    """Frameless avatar; left-drag moves it around the desktop.

    dragging_changed emits True on drag start and False on drop so the host
    app can show a status line and persist the new position.
    """

    dragging_changed = Signal(bool)
    drag_moved = Signal()  # emitted on every move while dragging

    def __init__(
        self,
        avatar_dir: Path,
        parent: QWidget | None = None,
        context_menu_factory: Callable[[], QMenu] | None = None,
    ) -> None:
        super().__init__(parent)
        self._context_menu_factory = context_menu_factory
        self._active_menu: QMenu | None = None  # B22: strong ref while open
        self._avatar_dir = avatar_dir
        self._states: dict[str, StateAnim] = load_manifest(avatar_dir / "manifest.json")
        self._spinner_frames = load_spinner_frames(avatar_dir)
        self._state: AvatarState = "idle"
        self._frame_index = 0
        self._spinner_index = 0
        self._drag_offset = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._label = QLabel(self)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._spinner = QLabel(self)
        self._spinner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._spinner.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(max(1, int(1000 / SPINNER_FPS)))
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.timeout.connect(lambda: self.set_state("idle"))

        self._render_frame()
        self._start_timer()

    def current_state(self) -> AvatarState:
        return self._state

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self._context_menu_factory is not None:
            menu = self._context_menu_factory()
            self._active_menu = menu
            menu.exec(event.globalPos())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self.dragging_changed.emit(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.drag_moved.emit()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_offset is not None
        ):
            self._drag_offset = None
            self.dragging_changed.emit(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_state(self, state: AvatarState) -> None:
        if state == self._state and state != "error":
            return
        self._state = state
        self._frame_index = 0
        self._start_timer()
        self._render_frame()
        self._update_spinner()
        if state == "error":
            self._error_timer.start(error_timeout_ms())
        else:
            self._error_timer.stop()

    def _start_timer(self) -> None:
        anim = self._states[self._state]
        interval = max(1, int(1000 / anim.fps))
        self._timer.setInterval(interval)
        self._timer.start()

    def _advance(self) -> None:
        anim = self._states[self._state]
        if self._frame_index >= len(anim.frames) - 1:
            if anim.loop:
                self._frame_index = 0
            else:
                self._timer.stop()
                return
        else:
            self._frame_index += 1
        self._render_frame()

    def _advance_spinner(self) -> None:
        if not self._spinner_frames:
            return
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_frames)
        self._show_spinner_frame()

    def _show_spinner_frame(self) -> None:
        pix = QPixmap(self._spinner_frames[self._spinner_index])
        if pix.isNull():
            return
        scaled = pix.scaledToHeight(
            36, Qt.TransformationMode.FastTransformation
        )
        self._spinner.setPixmap(scaled)
        # top-right of the character
        self._spinner.move(self.width() - scaled.width() - 4, 2)
        self._spinner.setVisible(True)
        self._spinner.raise_()

    def _update_spinner(self) -> None:
        active = self._state in SPINNER_STATES and bool(self._spinner_frames)
        if active:
            self._spinner_index = 0
            self._show_spinner_frame()
            self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
            self._spinner.setVisible(False)

    def _render_frame(self) -> None:
        anim = self._states[self._state]
        path = anim.frames[self._frame_index]
        pix = QPixmap(path)
        if pix.isNull():
            self._label.setText("[!]")
            return
        scaled = pix.scaledToHeight(
            DISPLAY_H, Qt.TransformationMode.FastTransformation
        )
        self._label.setPixmap(scaled)
        self.resize(scaled.width(), scaled.height())
        if self._spinner.isVisible():
            self._show_spinner_frame()
