"""Startup update check: daily GitHub probe, offline-safe, opt-out via Settings."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Signal

from core.paths import config_dir
from core.update_check import fetch_latest_tag, is_newer, record_check, should_check

RELEASES_URL = "https://github.com/Xeakaes/NexaDesk/releases/latest"


def update_check_enabled(settings_path: Path) -> bool:
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool((data.get("updates") or {}).get("check_enabled", True))


def update_state_path() -> Path:
    return config_dir() / "update_check.json"


class _UpdateSignals(QObject):
    latest = Signal(str)


_update_signals: _UpdateSignals | None = None


def _get_update_signals() -> _UpdateSignals:
    """One shared carrier, created on the UI thread with a Qt parent (B61).

    A per-worker unparented carrier destroyed on the worker thread while its
    queued MetaCall event was still in flight segfaults the app.
    """
    global _update_signals
    if _update_signals is None:
        _update_signals = _UpdateSignals(QCoreApplication.instance())
    return _update_signals


class UpdateCheckWorker:
    """Fetches the latest release tag on a plain background thread.

    B44: the daily-gate record is written only AFTER a successful fetch —
    an offline/failed probe must not burn the 24h slot.
    """

    def __init__(self, current_version: str, session=None, state_path: Path | None = None) -> None:
        self.signals = _get_update_signals()
        self._current = current_version
        self._session = session
        self._state_path = state_path
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        tag = fetch_latest_tag(session=self._session)
        if not tag:
            return  # failed fetch: keep the gate open for the next launch
        if self._state_path is not None:
            record_check(self._state_path)
        if is_newer(tag, self._current):
            self.signals.latest.emit(tag)


def schedule_update_check(settings_path: Path, current_version: str, on_newer) -> None:
    """Start a check if enabled and the daily gate allows; on_newer(tag) on the caller thread."""
    if not update_check_enabled(settings_path):
        return
    state = update_state_path()
    if not should_check(state):
        return
    # B44: do NOT record here — the worker records after a successful fetch.
    worker = UpdateCheckWorker(current_version, state_path=state)
    # The carrier is shared: drop any previous registration of this callback
    # so repeated checks do not stack duplicate slot invocations.
    try:
        worker.signals.latest.disconnect(on_newer)
    except (RuntimeError, TypeError):
        pass
    worker.signals.latest.connect(on_newer)
    # Keep the worker alive until the thread finishes.
    schedule_update_check._last_worker = worker  # type: ignore[attr-defined]
    worker.start()
