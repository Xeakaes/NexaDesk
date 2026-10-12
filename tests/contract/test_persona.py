from core.agent.config import AgentConfig
from core.agent.runtime import AgentRuntime
from core.events import EventBus
from core.providers.base import ProviderResponse, ToolCall
from core.session.store import SessionStore
from core.tools.registry import PermissionPolicy, ToolRegistry
from tests.fakes import FakeProvider


def _runtime(provider, config=None):
    rt = AgentRuntime(
        provider,
        ToolRegistry(),
        PermissionPolicy({"*": "allow"}),
        EventBus(),
        SessionStore(),
        config or AgentConfig(),
    )
    return rt


def test_persona_prepends_system_message():
    provider = FakeProvider([ProviderResponse(text="ok", tool_calls=[])])
    rt = _runtime(provider, AgentConfig(persona="Sen kısaltan bir asistansın."))
    rt.start_task("s1", "selam")
    first = provider.calls[0].messages[0]
    assert first.role == "system"
    assert first.content == "Sen kısaltan bir asistansın."
    assert provider.calls[0].messages[1].role == "user"


def test_empty_persona_sends_no_system_message():
    provider = FakeProvider([ProviderResponse(text="ok", tool_calls=[])])
    rt = _runtime(provider)
    rt.start_task("s1", "selam")
    assert provider.calls[0].messages[0].role == "user"


def test_set_persona_applies_to_next_task_without_restart():
    # F1: each final reply is followed by one classifier call (scripted here
    # as "neutral"), so two tasks consume four provider responses.
    provider = FakeProvider([
        ProviderResponse(text="ok", tool_calls=[]),
        ProviderResponse(text="neutral", tool_calls=[]),
        ProviderResponse(text="ok", tool_calls=[]),
        ProviderResponse(text="neutral", tool_calls=[]),
    ])
    rt = _runtime(provider)
    rt.start_task("s1", "bir")
    assert provider.calls[0].messages[0].role == "user"
    rt.set_persona("Her cevabın sonuna yıldız koy.")
    rt.start_task("s2", "iki")
    assert provider.calls[2].messages[0].role == "system"
    assert provider.calls[2].messages[0].content == "Her cevabın sonuna yıldız koy."


def test_persona_present_on_followup_model_calls_in_same_task():
    from core.tools.base import ToolResult
    from tests.fakes import FakeTool

    tool_provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[
            ToolCall(id="c1", name="echo", arguments={"x": 1})
        ]),
        ProviderResponse(text="bitti", tool_calls=[]),
    ])
    tool = FakeTool("echo", [ToolResult(ok=True, data={"v": 1})])
    reg = ToolRegistry()
    reg.register(tool)
    rt = AgentRuntime(
        tool_provider, reg, PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(persona="P"),
    )
    rt.start_task("s1", "çalış")
    assert tool_provider.calls[1].messages[0].role == "system"
    assert tool_provider.calls[1].messages[0].content == "P"
