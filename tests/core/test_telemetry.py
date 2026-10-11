"""Telemetry: JSON-lines timing log used to diagnose rate-limit slowness."""

from __future__ import annotations

import json

from core.agent import telemetry


def _records(log):
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _point_at(tmp_path, monkeypatch, name="agent.log"):
    log = tmp_path / name
    monkeypatch.setenv("NEXADESK_TELEMETRY", "1")
    monkeypatch.setattr(telemetry, "_log_file", lambda: log)
    return log


def test_log_event_writes_json_line(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    telemetry.log_event("model_request", attempt=0, status=429)
    recs = _records(log)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["event"] == "model_request"
    assert rec["attempt"] == 0 and rec["status"] == 429
    assert "+00:00" in rec["ts"]  # timestamps are UTC


def test_log_event_appends_one_line_per_call(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    telemetry.log_event("a", n=1)
    telemetry.log_event("b", n=2)
    assert [r["event"] for r in _records(log)] == ["a", "b"]


def test_log_event_disabled_via_env(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    monkeypatch.setenv("NEXADESK_TELEMETRY", "off")
    telemetry.log_event("a")
    assert not log.exists()


def test_log_event_never_raises_on_unwritable_path(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("NEXADESK_TELEMETRY", "1")
    monkeypatch.setattr(telemetry, "_log_file", lambda: blocker / "logs" / "agent.log")
    telemetry.log_event("a")  # must not raise


def test_log_event_handles_unserializable_values(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)

    class Weird:
        pass

    telemetry.log_event("a", obj=Weird())  # must not raise
    assert _records(log)[0]["event"] == "a"
