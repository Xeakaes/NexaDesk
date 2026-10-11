"""Shared test fixtures.

Telemetry writes a JSON-lines timing log to the real config dir by default
(that is the point — the packaged app must log without configuration). Tests
must never touch the user's log, so it is off globally and re-enabled
explicitly by the telemetry tests that need it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _telemetry_off(monkeypatch):
    monkeypatch.setenv("NEXADESK_TELEMETRY", "off")
