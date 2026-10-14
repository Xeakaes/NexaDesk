"""B82: avatar state debounce + frame cache."""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.paths import assets_dir
from ui.avatar.window import AvatarWindow


def _base() -> Path:
    return assets_dir() / "avatars" / "base"


def _app():
    return QApplication.instance() or QApplication([])


def test_state_change_is_debounced(tmp_path):
    # B82: a burst of events (thinking→working in the same tick) used to
    # thrash the animation; each state must dwell at least 200 ms.
    app = _app()
    av = AvatarWindow(_base())
    av.set_state("thinking")
    assert av.current_state() == "thinking"
    av.set_state("working")  # immediately after — must be deferred
    assert av.current_state() == "thinking", "working must wait out the dwell"
    # let the dwell timer fire
    from PySide6.QtCore import QCoreApplication, QTimer

    deadline = av._dwell_timer.interval() + 50
    QTimer.singleShot(deadline, QCoreApplication.quit)
    app.exec()
    assert av.current_state() == "working"
    av.close()
    av.deleteLater()


def test_frame_path_is_cached():
    # B82: _render_frame re-read the pixmap from disk on every tick; cache
    # by path so animation frames are decoded once.
    app = _app()
    av = AvatarWindow(_base())
    calls = []
    real_pixmap = __import__("ui.avatar.window", fromlist=["QPixmap"]).QPixmap

    class CountingPixmap(real_pixmap):
        def __init__(self, path=""):
            if path:
                calls.append(str(path))
            super().__init__(path)

    import ui.avatar.window as winmod

    winmod.QPixmap = CountingPixmap
    try:
        av.set_state("thinking")
        first = len(calls)
        # force a re-render of the same first frame
        av._frame_index = 0
        av._render_frame()
        assert len(calls) == first, (
            f"second render must hit the cache, not re-read ({calls})"
        )
    finally:
        winmod.QPixmap = real_pixmap
    av.close()
    av.deleteLater()
