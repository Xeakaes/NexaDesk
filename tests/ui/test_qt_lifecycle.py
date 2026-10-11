"""Regression tests for Qt object lifetime across test threads.

See tests/ui/conftest.py for the dangling-QBasicTimer root cause these pin.
"""

import threading


def test_drain_destroys_leftover_chat_window_on_main_thread(
    tmp_path, qt_garbage_drain
):
    """Leftover cyclic UI wrappers must be destroyed by the main-thread drain.

    A Qt widget wrapper stays alive as long as any reference cycle keeps it
    (parent/child links, held widget references), so it can only be freed by
    the cyclic GC - which may run on any thread. If collection happens on a
    worker thread, QBasicTimer entries stay registered against the wrong
    dispatcher and a later main-thread processEvents() segfaults. The
    autouse conftest fixture drains garbage on the main thread after every
    UI test - this pins that contract.
    """
    from PySide6.QtWidgets import QApplication

    from ui.gui.main_window import ChatWindow
    from ui.history import HistoryStore

    app = QApplication.instance() or QApplication([])
    win = ChatWindow(history=HistoryStore(tmp_path / "history.db"))
    destroyed_on = []
    win.destroyed.connect(lambda *_: destroyed_on.append(threading.current_thread()))
    # _append auto-scrolls via the vertical QScrollBar, which arms a
    # QBasicTimer on the main dispatcher - the exact dangling-timer trigger.
    win._append("assistant", "x" * 200)
    win._append("assistant", "y" * 200)
    # Emulate the reference cycles Qt wrappers form in real apps (the last
    # reference is often dropped by a worker thread, which is what used to
    # destroy the widget tree on the wrong thread).
    win._cycle = win

    del win
    assert not destroyed_on, "wrappers must survive the refcount drop via cycles"

    qt_garbage_drain()

    assert destroyed_on, "the drain must destroy leftover UI wrappers"
    assert destroyed_on[0] is threading.main_thread()
