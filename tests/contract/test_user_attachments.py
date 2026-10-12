import base64

import pytest

from core.agent.config import AgentConfig
from core.agent.runtime import AgentRuntime
from core.events import EventBus
from core.providers.base import ProviderResponse
from core.session.store import SessionStore
from core.tools.registry import PermissionPolicy, ToolRegistry
from tests.fakes import FakeProvider


def _runtime(provider):
    return AgentRuntime(
        provider, ToolRegistry(), PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )


def test_begin_task_stores_images_on_user_message():
    provider = FakeProvider([ProviderResponse(text="ok", tool_calls=[])])
    rt = _runtime(provider)
    uri = "data:image/png;base64," + base64.b64encode(b"fake").decode()
    tid = rt.begin_task("s1", "bu ekran görüntüsüne bak", images=[uri])
    rt.run_task(tid)
    first = provider.calls[0].messages[0]
    assert first.role == "user"
    assert first.images == [uri]


def test_begin_task_without_images_unchanged():
    provider = FakeProvider([ProviderResponse(text="ok", tool_calls=[])])
    rt = _runtime(provider)
    tid = rt.begin_task("s1", "selam")
    rt.run_task(tid)
    assert provider.calls[0].messages[0].images is None
