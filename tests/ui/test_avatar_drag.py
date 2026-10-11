"""Avatar drag: the chat bubble must track the avatar while it is dragged."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from core.paths import assets_dir
from ui.avatar.window import AvatarWindow


def _base_avatar_dir() -> Path:
    return assets_dir() / "avatars" / "base"


def _mouse(event_type, pos, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(pos[0], pos[1]),
        QPointF(pos[0], pos[1]),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_drag_move_emits_drag_moved():
    app = QApplication.instance() or QApplication([])
    av = AvatarWindow(_base_avatar_dir())
    spy = QSignalSpy(av.drag_moved)
    av.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            (10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    av.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            (80, 90),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    av.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            (80, 90),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert spy.count() == 1
    av.close()


def test_move_without_drag_does_not_emit():
    app = QApplication.instance() or QApplication([])
    av = AvatarWindow(_base_avatar_dir())
    spy = QSignalSpy(av.drag_moved)
    av.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            (80, 90),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert spy.count() == 0
    av.close()


def test_bubble_tracks_avatar_during_drag(tmp_path, monkeypatch):
    from tests.ui.test_avatar_app import _make_app

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.avatar.move(500, 400)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.pos() == QPoint(500 - 340, 400 - 80)
    # Clamped to the screen: never a negative position.
    ui.avatar.move(-500, -500)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.pos() == QPoint(0, 0)
    ui.close()
