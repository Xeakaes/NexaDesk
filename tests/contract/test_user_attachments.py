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


def test_user_images_trimmed_to_max_history():
    # B13: user attachments used to accumulate forever, so every later
    # request resent all prior base64 blobs. Only the newest
    # max_history_images image-bearing messages may keep their images.
    provider = FakeProvider(
        [ProviderResponse(text="ok", tool_calls=[]) for _ in range(3)]
    )
    rt = _runtime(provider)
    uri1 = "data:image/png;base64," + base64.b64encode(b"one").decode()
    uri2 = "data:image/png;base64," + base64.b64encode(b"two").decode()
    tid = rt.begin_task("s1", "ilk ek", images=[uri1])
    rt.run_task(tid)
    tid = rt.begin_task("s1", "ikinci ek", images=[uri2])
    rt.run_task(tid)
    msgs = rt._session.messages("s1")
    with_images = [m for m in msgs if m.images]
    # max_history_images defaults to 1: only the newest survives.
    assert len(with_images) == 1
    assert with_images[0].images == [uri2]
