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
        ProviderResponse(text="neutral", tool_calls=[]),  # F1 classifier call
    ])
    rt, _ = _runtime(provider, tool)
    rt.start_task("s1", "echo")
    assert tool.calls == [{"x": "?"}]
    assert len(provider.calls) == 3
    assert "invalid_arguments" in provider.calls[1].messages[-1].content


def test_unknown_tool_name():
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="ghost", arguments={})]),
        ProviderResponse(text="yok.", tool_calls=[]),
    ])
    rt, _ = _runtime(provider, FakeTool("real"))
    rt.start_task("s1", "hoot")
    assert "unknown_tool" in provider.calls[1].messages[-1].content


def test_missing_required_argument_returns_invalid_arguments():
    # B27: schema-required fields must be checked before invoke, so the model
    # gets a fixable error instead of a raw TypeError from inside the tool.
    tool = FakeTool("read")
    tool.input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    provider = FakeProvider([
        ProviderResponse(
            text=None,
            tool_calls=[ToolCall(id="c1", name="read", arguments={"dir": "/tmp"})],
        ),
        ProviderResponse(text="ok", tool_calls=[]),
    ])
    rt, _ = _runtime(provider, tool)
    rt.start_task("s1", "read the file")
    assert tool.calls == []
    content = provider.calls[1].messages[-1].content
    assert "invalid_arguments" in content
    assert "path" in content


def test_missing_required_argument_skips_confirmation_prompt():
    # Validating after the ASK prompt would make the user approve a call that
    # is guaranteed to fail; the check must run first.
    tool = FakeTool("read")
    tool.input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    provider = FakeProvider([
        ProviderResponse(
            text=None, tool_calls=[ToolCall(id="c1", name="read", arguments={})]
        ),
        ProviderResponse(text="ok", tool_calls=[]),
    ])
    rt, events = _runtime(provider, tool, policy=PermissionPolicy({"*": "ask"}))
    reqs = []

    def resolver(e):
        # Watchdog: keeps the buggy (prompt-first) path from hanging the test.
        reqs.append(e)
        rt.resolve_confirmation(e.task_id, e.payload["confirm_id"], True)

    events.subscribe("confirmation_requested", resolver)
    rt.start_task("s1", "read the file")
    assert reqs == []
    assert tool.calls == []


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


def test_tool_pool_saturation_fails_fast_with_distinct_code():
    # B14: future.cancel() cannot stop a running tool thread. Once every
    # pool worker is stuck on a hung tool, the next call must fail fast
    # with a distinct "pool_saturated" code instead of silently waiting
    # out the wall clock on a future that can never start.
    import time as _time

    from core.agent.config import AgentConfig

    hang = FakeTool("hang", ignore_cancel=True, sleep_s=1.5)
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[
            ToolCall(id=f"c{i}", name="hang", arguments={}) for i in range(5)
        ]),
        ProviderResponse(text="done", tool_calls=[]),
    ])
    reg = ToolRegistry()
    reg.register(hang)
    from core.events import EventBus as _Bus
    from core.session.store import SessionStore as _SS

    rt = AgentRuntime(
        provider, reg, PermissionPolicy({"*": "allow"}),
        _Bus(), _SS(), AgentConfig(tool_timeout_s=0.15, max_tool_calls=10),
    )
    seen = []
    rt._events.subscribe("*", seen.append)
    t0 = _time.perf_counter()
    tid = rt.begin_task("s1", "go")
    rt.run_task(tid)
    elapsed = _time.perf_counter() - t0
    tool_events = [e for e in seen if e.name == "tool_finished"]
    # 4 hung calls burn the 4 workers; the 5th must not wait a full timeout.
    saturated = [
        e for e in tool_events
        if e.payload.get("error_code") == "pool_saturated"
        or "saturated" in (e.payload.get("summary") or "")
    ]
    assert saturated, (
        "expected a pool_saturated tool_finished, got: "
        + repr([(e.payload.get("ok"), e.payload.get("summary")) for e in tool_events])
    )
    # Fail-fast: the saturated call must not burn the full tool_timeout again.
    assert elapsed < 0.15 * 5 + 0.45


def test_tool_call_ids_unique_and_nonempty_across_turns():
    # B36: providers may collide (ollama_0) or send empty ids; the runtime
    # must guarantee unique non-empty ids before they hit session history.
    tool = FakeTool("echo")
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[
            ToolCall(id="dup", name="echo", arguments={}),
            ToolCall(id="", name="echo", arguments={}),
        ]),
        ProviderResponse(text=None, tool_calls=[ToolCall(id="dup", name="echo", arguments={})]),
        ProviderResponse(text="ok", tool_calls=[]),
        ProviderResponse(text="neutral", tool_calls=[]),  # F1 classifier call
    ])
    rt, _ = _runtime(provider, tool)
    rt.start_task("s1", "echo twice")
    tool_ids = [m.tool_call_id for m in rt._session.messages("s1") if m.role == "tool"]
    assert len(tool_ids) == 3
    assert all(tool_ids)
    assert len(set(tool_ids)) == 3
    # assistant tool_calls must carry the same rewritten ids
    asst_ids = [
        c.id for m in rt._session.messages("s1") if m.role == "assistant" and m.tool_calls
        for c in m.tool_calls
    ]
    assert asst_ids == tool_ids
