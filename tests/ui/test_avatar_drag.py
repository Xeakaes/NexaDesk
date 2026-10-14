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
    ui.bubble.resize(340, 240)
    ui.avatar.move(500, 400)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.pos() == QPoint(500 - 340 - 16, 400 - 80)
    # Clamped to the screen: never a negative position.
    ui.avatar.move(-500, -500)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.pos() == QPoint(0, 0)
    ui.close()


def test_bubble_flips_to_right_when_left_has_no_room(tmp_path, monkeypatch):
    """Near the left screen edge the bubble must move to the avatar's right."""
    from tests.ui.test_avatar_app import _make_app

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.bubble.resize(340, 240)
    ui.avatar.move(100, 300)
    ui.avatar.drag_moved.emit()

    av_right = 100 + ui.avatar.width()
    assert ui.bubble.x() == av_right + 16
    assert ui.bubble.x() >= av_right, "no overlap when flipped right"
    ui.close()


def test_bubble_returns_left_when_room_reappears(tmp_path, monkeypatch):
    """Moving away from the left edge puts the bubble back on the left."""
    from tests.ui.test_avatar_app import _make_app

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.bubble.resize(340, 240)
    ui.avatar.move(100, 300)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.x() > ui.avatar.x(), "starts flipped right"

    ui.avatar.move(700, 300)
    ui.avatar.drag_moved.emit()
    assert ui.bubble.x() == 700 - 340 - 16
    ui.close()


def test_wide_bubble_still_never_overlaps_avatar(tmp_path, monkeypatch):
    """A bubble wider than the old 340px offset must keep a clear gap."""
    from tests.ui.test_avatar_app import _make_app

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    ui.bubble.resize(500, 240)
    ui.avatar.move(800, 300)
    ui.avatar.drag_moved.emit()

    assert ui.bubble.x() + ui.bubble.width() <= ui.avatar.x() - 16
    ui.close()


def test_bubble_repositions_on_resize_and_stays_on_screen(tmp_path, monkeypatch):
    # B83: the bubble grew with the transcript but never re-placed itself,
    # so a tall bubble near the bottom of the screen hung off-screen.
    from PySide6.QtGui import QGuiApplication

    from tests.ui.test_avatar_app import _make_app

    app, ui, rt = _make_app(tmp_path, monkeypatch)
    screen = QGuiApplication.primaryScreen().availableGeometry()
    # resizeEvent only fires on a shown window — matches the real bug path
    # (transcript grows while the bubble is open).
    ui.bubble.show()
    # avatar near the bottom so an 800px-tall bubble would overflow
    ui.avatar.move(500, screen.bottom() - 50)
    ui.avatar.drag_moved.emit()
    ui.bubble.resize(340, 800)  # transcript grows → resizeEvent fires
    bottom = ui.bubble.y() + ui.bubble.height()
    assert bottom <= screen.bottom() + 1, (
        f"bubble hangs off-screen: bottom={bottom} > {screen.bottom()}"
    )
    assert ui.bubble.y() >= screen.top()
    ui.close()
