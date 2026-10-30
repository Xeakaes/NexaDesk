from core.agent.config import AgentConfig
from core.agent.runtime import AgentRuntime
from core.events import EventBus
from core.session.store import SessionStore
from core.tools.registry import PermissionPolicy, ToolRegistry
from tests.fakes import FakeProvider


def _runtime() -> AgentRuntime:
    return AgentRuntime(
        FakeProvider([]),
        ToolRegistry(),
        PermissionPolicy({"*": "allow"}),
        EventBus(),
        SessionStore(),
        AgentConfig(),
    )


def test_close_runs_hooks_in_order_and_never_raises():
    rt = _runtime()
    order: list[str] = []
    rt.on_close(lambda: order.append("first"))

    def boom():
        order.append("boom")
        raise RuntimeError("hook exploded")

    rt.on_close(boom)
    rt.close()  # teardown must not propagate a hook failure
    assert order == ["first", "boom"]
