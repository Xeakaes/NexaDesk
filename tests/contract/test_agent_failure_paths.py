import threading
import time

from core.agent.runtime import AgentRuntime
from core.agent.config import AgentConfig
from core.events import EventBus
from core.providers.base import ProviderResponse, ToolCall
from core.session.store import SessionStore
from core.tools.base import ToolResult
from core.tools.registry import ToolRegistry, PermissionPolicy
from tests.fakes import FakeProvider, FakeTool


def _runtime(provider, tool=None, policy=None, events=None, config=None):
    reg = ToolRegistry()
    if tool:
        reg.register(tool)
    events = events or EventBus()
    rt = AgentRuntime(
        provider, reg, policy or PermissionPolicy({"*": "allow"}),
        events, SessionStore(), config or AgentConfig(),
    )
    return rt, events


def _run_on_thread(rt, session_id, text):
    task_id = rt.begin_task(session_id, text)
    t = threading.Thread(target=rt.run_task, args=(task_id,), daemon=True)
    t.start()
    return task_id, t


def test_cancel_mid_loop():
    provider = FakeProvider(
        [ProviderResponse(text="slow", tool_calls=[])], delay_each_s=0.3
    )
    tool = FakeTool("t")
    rt, events = _runtime(provider, tool)
    seen = []
    events.subscribe("*", seen.append)
    task_id, th = _run_on_thread(rt, "s1", "selam")
    time.sleep(0.05)
    rt.cancel_task(task_id)
    th.join(timeout=2.0)
    names = [e.name for e in seen]
    assert names.count("agent_cancelled") == 1
    assert "agent_finished" not in names
    assert "assistant_message" not in names


def test_cancel_while_confirmation_pending_blocks_late_approval():
    tool = FakeTool("shot")
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="shot", arguments={})]),
        ProviderResponse(text="n", tool_calls=[]),
    ])
    rt, events = _runtime(provider, tool, policy=PermissionPolicy({"*": "ask"}))
    reqs = []
    seen = []
    events.subscribe("*", seen.append)
    events.subscribe("confirmation_requested", reqs.append)
    done = threading.Event()

    def worker():
        rt.start_task("s1", "ekran görüntüsü al")
        done.set()

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    deadline = time.time() + 2.0
    while not reqs and time.time() < deadline:
        time.sleep(0.01)
    assert reqs, "confirmation_requested never published"
    tid = reqs[0].task_id
    cid = reqs[0].payload["confirm_id"]
    rt.cancel_task(tid)
    rt.resolve_confirmation(tid, cid, True)
    done.wait(timeout=2.0)
    assert tool.calls == []
    names = [e.name for e in seen]
    assert "agent_cancelled" in names
    assert "agent_finished" not in names


def test_stale_confirm_id_ignored():
    tool = FakeTool("shot")
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="shot", arguments={})]),
        ProviderResponse(text="ok", tool_calls=[]),
    ])
    rt, events = _runtime(provider, tool, policy=PermissionPolicy({"*": "ask"}))
    reqs = []
    events.subscribe("confirmation_requested", reqs.append)

    def resolver(e):
        rt.resolve_confirmation(e.task_id, "bogus", True)
        rt.resolve_confirmation(e.task_id, e.payload["confirm_id"], True)

    events.subscribe("confirmation_requested", resolver)
    rt.start_task("s1", "shot")
    assert tool.calls == [{}]


def test_double_reply_second_ignored():
    tool = FakeTool("shot")
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="shot", arguments={})]),
        ProviderResponse(text="ok", tool_calls=[]),
    ])
    rt, events = _runtime(provider, tool, policy=PermissionPolicy({"*": "ask"}))

    def resolver(e):
        cid = e.payload["confirm_id"]
        rt.resolve_confirmation(e.task_id, cid, True)
        rt.resolve_confirmation(e.task_id, cid, True)

    events.subscribe("confirmation_requested", resolver)
    rt.start_task("s1", "shot")
    assert tool.calls == [{}]


def test_invalid_arguments_fed_back_then_final():
    tool = FakeTool(
        "echo",
        [ToolResult(ok=False, error="bad args", error_code="invalid_arguments")],
    )
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"x": "?"})]),
        ProviderResponse(text="Anlaşıldım.", tool_calls=[]),
    ])
    rt, _ = _runtime(provider, tool)
    rt.start_task("s1", "echo")
    assert tool.calls == [{"x": "?"}]
    assert len(provider.calls) == 2
    assert "invalid_arguments" in provider.calls[1].messages[-1].content


def test_unknown_tool_name():
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="ghost", arguments={})]),
        ProviderResponse(text="yok.", tool_calls=[]),
    ])
    rt, _ = _runtime(provider, FakeTool("real"))
    rt.start_task("s1", "hoot")
    assert "unknown_tool" in provider.calls[1].messages[-1].content


def test_max_tool_call_limit():
    tool = FakeTool("echo")
    # endless tool calls: FakeTool without results always returns ok
    responses = []
    for i in range(11):
        responses.append(
            ProviderResponse(text=None, tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={})])
        )
    provider = FakeProvider(responses)
    rt, events = _runtime(provider, tool, config=AgentConfig(max_tool_calls=10))
    errs = []
    events.subscribe("agent_error", errs.append)
    rt.start_task("s1", "loop")
    assert len(tool.calls) == 10
    assert errs and errs[0].payload["error_code"] == "max_tool_calls"


def test_provider_without_tools_fails_fast():
    class NoToolsProvider(FakeProvider):
        supports_tools = False

    provider = NoToolsProvider([
        ProviderResponse(text="hi", tool_calls=[]),
    ])
    rt, events = _runtime(provider, FakeTool("t"))
    errs = []
    events.subscribe("agent_error", errs.append)
    rt.start_task("s1", "selam")
    assert errs and errs[0].payload["error_code"] == "unsupported_capability"
    assert len(provider.calls) == 0


def test_cancel_discards_late_tool_result():
    tool = FakeTool("slow", ignore_cancel=True, sleep_s=0.3)
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="slow", arguments={})]),
        ProviderResponse(text="should not happen", tool_calls=[]),
    ])
    rt, events = _runtime(provider, tool)
    seen = []
    events.subscribe("*", seen.append)
    task_id, th = _run_on_thread(rt, "s1", "is")
    deadline = time.time() + 2.0
    while not tool.calls and time.time() < deadline:
        time.sleep(0.01)
    assert tool.calls, "tool never started"
    rt.cancel_task(task_id)
    th.join(timeout=2.0)
    assert not th.is_alive()
    assert len(provider.calls) == 1  # no second model call
    names = [e.name for e in seen]
    assert "agent_cancelled" in names
    assert "agent_finished" not in names


def test_cancel_during_rate_limit_backoff_is_cancelled_not_error():
    # B11: the provider raises ProviderError(error_code="cancelled") when the
    # user cancels during a rate-limit sleep. That must surface as
    # agent_cancelled (normal cancel UX), not agent_error.
    from core.providers.base import ProviderError

    provider = FakeProvider([ProviderError("cancelled", error_code="cancelled")])
    rt, events = _runtime(provider)
    seen = []
    events.subscribe("*", seen.append)
    task_id, th = _run_on_thread(rt, "s1", "selam")
    th.join(timeout=2.0)
    names = [e.name for e in seen]
    assert "agent_cancelled" in names
    assert "agent_error" not in names
    assert "agent_finished" not in names
