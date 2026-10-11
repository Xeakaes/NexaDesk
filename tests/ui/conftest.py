"""UI-test lifecycle guards.

Root cause of the historical flaky SIGSEGV guarded against here:

QBasicTimer registers against the *current* thread's event dispatcher, and
QBasicTimer::stop() unregisters from the *current* thread's dispatcher too.
When the Python wrapper for a Qt widget is collected by a worker thread
(CPython's cyclic GC can run in any thread), the widget tree is destroyed
on that thread, the timer is unregistered from the wrong dispatcher, and the
entry stays dangling in the main one. The next QApplication.processEvents()
on the main thread then fires the stale timer and segfaults inside
QCoreApplication::notifyInternal2 (observed as a crash inside
QTimerInfoList::activateTimers during tests/ui/test_settings.py teardown).

Qt widget wrappers form reference cycles of their own (parent/child links,
widgets stored on Python objects), so refcounting alone never frees them -
the cyclic GC does, at an arbitrary later point and on an arbitrary thread.
Draining the collector on the main thread after every UI test guarantees
those wrappers are destroyed here, on the thread that owns them.
"""

from __future__ import annotations

import gc

import pytest


def drain_qt_garbage() -> None:
    """Collect unreachable Qt wrappers and flush deferred deletes.

    Must be called on the main thread.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    gc.collect()
    app = QCoreApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


@pytest.fixture(autouse=True)
def _destroy_ui_on_main_thread():
    yield
    drain_qt_garbage()


@pytest.fixture
def qt_garbage_drain():
    return drain_qt_garbage
