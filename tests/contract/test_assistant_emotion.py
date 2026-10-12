"""assistant_emotion event: LLM reply classification wired into the runtime (F1)."""

from core.agent.config import AgentConfig
from core.agent.runtime import AgentRuntime
from core.events import EventBus
from core.providers.base import ProviderError, ProviderResponse
from core.session.store import SessionStore
from core.tools.registry import PermissionPolicy, ToolRegistry
from tests.fakes import FakeProvider


def _runtime(provider):
    events = EventBus()
    rt = AgentRuntime(
        provider, ToolRegistry(), PermissionPolicy({"*": "allow"}),
        events, SessionStore(), AgentConfig(),
    )
    return rt, events


def test_final_reply_publishes_happy_emotion():
    provider = FakeProvider([
        ProviderResponse(text="Great job!", tool_calls=[]),
        ProviderResponse(text="happy", tool_calls=[]),
    ])
    rt, events = _runtime(provider)
    seen = []
    events.subscribe("*", seen.append)
    rt.start_task("s1", "selam")
    names = [e.name for e in seen]
    emotion = next(e for e in seen if e.name == "assistant_emotion")
    assert emotion.payload["emotion"] == "happy"
    # Ordering: emotion arrives after the message, before finished.
    assert names.index("assistant_message") < names.index("assistant_emotion")
    assert names.index("assistant_emotion") < names.index("agent_finished")


def test_classifier_error_publishes_neutral():
    provider = FakeProvider([
        ProviderResponse(text="whatever", tool_calls=[]),
        ProviderError("boom"),
    ])
    rt, events = _runtime(provider)
    seen = []
    events.subscribe("assistant_emotion", seen.append)
    rt.start_task("s1", "selam")
    assert seen[0].payload["emotion"] == "neutral"


def test_empty_reply_skips_classifier_call():
    provider = FakeProvider([
        ProviderResponse(text="", tool_calls=[]),
    ])
    rt, events = _runtime(provider)
    seen = []
    events.subscribe("assistant_emotion", seen.append)
    rt.start_task("s1", "selam")
    assert seen[0].payload["emotion"] == "neutral"
    assert len(provider.calls) == 1  # classifier must not fire on empty text


def test_cancelled_task_publishes_no_emotion():
    import threading
    import time

    provider = FakeProvider(
        [ProviderResponse(text="slow", tool_calls=[])], delay_each_s=0.3
    )
    rt, events = _runtime(provider)
    seen = []
    events.subscribe("*", seen.append)
    task_id = rt.begin_task("s1", "selam")
    th = threading.Thread(target=rt.run_task, args=(task_id,), daemon=True)
    th.start()
    time.sleep(0.05)
    rt.cancel_task(task_id)
    th.join(timeout=2.0)
    names = [e.name for e in seen]
    assert "assistant_emotion" not in names
    assert "agent_cancelled" in names
