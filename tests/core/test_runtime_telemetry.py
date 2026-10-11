"""Task-level telemetry: one task_summary line per agent task."""

from __future__ import annotations

import json

from core.agent import telemetry


def _records(log):
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _point_at(tmp_path, monkeypatch):
    log = tmp_path / "agent.log"
    monkeypatch.setenv("NEXADESK_TELEMETRY", "1")
    monkeypatch.setattr(telemetry, "_log_file", lambda: log)
    return log


def _runtime(provider, tool=None):
    from core.agent.config import AgentConfig
    from core.agent.runtime import AgentRuntime
    from core.events import EventBus
    from core.session.store import SessionStore
    from core.tools.registry import PermissionPolicy, ToolRegistry

    reg = ToolRegistry()
    if tool is not None:
        reg.register(tool)
    return AgentRuntime(
        provider, reg, PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )


def test_task_summary_logged_on_success(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    from core.providers.base import ProviderResponse, ToolCall
    from core.tools.base import ToolResult
    from tests.fakes import FakeProvider, FakeTool

    tool = FakeTool("echo", [ToolResult(ok=True, data={"x": 1})])
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={})]),
        ProviderResponse(text="done", tool_calls=[]),
    ])
    rt = _runtime(provider, tool)
    rt.start_task("s1", "merhaba")
    summaries = [r for r in _records(log) if r["event"] == "task_summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["outcome"] == "finished"
    assert s["model_calls"] == 2
    assert s["session_id"] == "s1"
    assert s["duration_ms"] >= 0
    assert [t["name"] for t in s["tools"]] == ["echo"]
    assert s["tools"][0]["ms"] >= 0
    assert s["tools"][0]["ok"] is True


def test_task_summary_logged_on_provider_error(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    from core.providers.base import ProviderError
    from tests.fakes import FakeProvider

    provider = FakeProvider([
        ProviderError("rate limit reached", error_code="rate_limited"),
    ])
    rt = _runtime(provider)
    rt.start_task("s1", "merhaba")
    s = next(r for r in _records(log) if r["event"] == "task_summary")
    assert s["outcome"] == "error"
    assert s["error_code"] == "rate_limited"
    assert s["model_calls"] == 1
    assert s["tools"] == []


def test_task_summary_logged_on_cancel(tmp_path, monkeypatch):
    log = _point_at(tmp_path, monkeypatch)
    from core.providers.base import ProviderResponse
    from tests.fakes import FakeProvider

    provider = FakeProvider([ProviderResponse(text="never delivered", tool_calls=[])])
    rt = _runtime(provider)
    task_id = rt.begin_task("s1", "merhaba")
    rt.cancel_task(task_id)
    rt.run_task(task_id)
    s = next(r for r in _records(log) if r["event"] == "task_summary")
    assert s["outcome"] == "cancelled"
