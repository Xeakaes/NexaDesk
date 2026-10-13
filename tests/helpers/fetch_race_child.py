"""Subprocess child for the B61 fetch-race stress test.

Hammers SettingsWindow.load() (which replaces both model-fetch workers)
every 10 ms while forcing gc.collect() every 50 ms. A segfault kills this
process with a non-zero exit code — the parent test asserts returncode == 0.
"""

import gc
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core.providers as providers  # noqa: E402


class FakeProvider:
    """Fast local catalog; no network in CI."""

    def list_models(self):
        return [f"m-{i}" for i in range(200)]


providers.create_provider = lambda s, sec: FakeProvider()


def main() -> int:
    from ui.settings import SettingsWindow

    tmp = Path(tempfile.mkdtemp())
    (tmp / "settings.json").write_text(
        json.dumps({"provider": {"type": "groq", "model": "m-0"}})
    )
    (tmp / "secrets.json").write_text(json.dumps({"groq_api_key": "x"}))
    app = QApplication(sys.argv)
    win = SettingsWindow(tmp / "settings.json", tmp / "secrets.json", tmp / "ui.json")
    win.show()
    win.load()
    # Replace both workers every 10 ms while the threads are still in flight.
    churn = QTimer()
    churn.setInterval(10)
    churn.timeout.connect(win.load)
    churn.start()
    gc_timer = QTimer()
    gc_timer.setInterval(50)
    gc_timer.timeout.connect(gc.collect)
    gc_timer.start()

    def _shutdown():
        churn.stop()
        gc_timer.stop()
        win.close()  # closeEvent joins in-flight workers
        app.quit()

    QTimer.singleShot(1500, _shutdown)
    app.exec()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
