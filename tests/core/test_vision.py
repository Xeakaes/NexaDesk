"""Vision plumbing tests: ChatMessage.images, screenshot data-URI, OCR fallback."""

from __future__ import annotations

import base64
import io

from core.providers.base import ChatMessage


def test_chatmessage_images_default_none():
    m = ChatMessage(role="user", content="hi")
    assert m.images is None


def test_chatmessage_images_accepts_list():
    m = ChatMessage(role="user", content="look", images=["data:image/jpeg;base64,AAA"])
    assert m.images == ["data:image/jpeg;base64,AAA"]


def _make_png_bytes(w=8, h=8) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 200, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_screenshot_tool_result_includes_data_uri(tmp_path, monkeypatch):
    from core.agent.cancellation import CancellationToken
    from core.tools.screen_control import _ScreenshotTool

    shot_path = tmp_path / "shot.png"
    png = _make_png_bytes()

    class FakeClient:
        def screenshot(self, output, monitor=None, region=None, hwnd=None):
            with open(output, "wb") as f:
                f.write(png)

    tool = _ScreenshotTool.__new__(_ScreenshotTool)
    # Stub the server round-trip: _run calls the injected fn with a client.
    monkeypatch.setattr(
        tool,
        "_run",
        lambda args, cancel, fn: __import__("core.tools.base", fromlist=["ToolResult"]).ToolResult(
            ok=True, data=fn(FakeClient(), args)
        ),
    )
    result = tool.execute({}, CancellationToken())
    assert result.ok
    assert result.data["path"]
    img = result.data["image"]
    assert img.startswith("data:image/")
    # The base64 payload must decode to a real image.
    b64 = img.split(",", 1)[1]
    assert base64.b64decode(b64)


def test_provider_default_no_vision():
    from core.providers.base import ModelProvider

    class Dummy(ModelProvider):
        def complete(self, messages, schemas, cancel):
            raise NotImplementedError

    assert Dummy().supports_vision is False


def test_session_add_message_accepts_images():
    from core.session.store import SessionStore

    st = SessionStore()
    sid = st.create_session()
    st.add_message(sid, "user", "look", images=["data:image/jpeg;base64,AAA"])
    assert st.messages(sid)[0].images == ["data:image/jpeg;base64,AAA"]


def _screenshot_runtime(provider, tool):
    from core.agent.config import AgentConfig
    from core.agent.runtime import AgentRuntime
    from core.events import EventBus
    from core.session.store import SessionStore
    from core.tools.registry import PermissionPolicy, ToolRegistry

    reg = ToolRegistry()
    reg.register(tool)
    rt = AgentRuntime(
        provider, reg, PermissionPolicy({"*": "allow"}),
        EventBus(), SessionStore(), AgentConfig(),
    )
    return rt


def test_runtime_attaches_image_when_vision_supported():
    from core.providers.base import ProviderResponse, ToolCall
    from core.tools.base import ToolResult
    from tests.fakes import FakeProvider, FakeTool

    img_uri = "data:image/jpeg;base64,QUJD"
    tool = FakeTool("screenshot", [ToolResult(ok=True, data={"path": "/tmp/x.jpg", "image": img_uri})])
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="screenshot", arguments={})]),
        ProviderResponse(text="seen", tool_calls=[]),
    ])
    provider.supports_vision = True
    rt = _screenshot_runtime(provider, tool)
    rt.start_task("s1", "ekran gor")
    # Second call: after tool message there is a user message carrying the image.
    msgs = provider.calls[1].messages
    img_msgs = [m for m in msgs if m.images]
    assert img_msgs, "expected a message with images attached"
    assert img_msgs[-1].images == [img_uri]


def test_runtime_strips_image_without_vision():
    from core.providers.base import ProviderResponse, ToolCall
    from core.tools.base import ToolResult
    from tests.fakes import FakeProvider, FakeTool

    img_uri = "data:image/jpeg;base64,QUJD"
    tool = FakeTool("screenshot", [ToolResult(ok=True, data={"path": "/tmp/x.jpg", "image": img_uri})])
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id="c1", name="screenshot", arguments={})]),
        ProviderResponse(text="ok", tool_calls=[]),
    ])
    provider.supports_vision = False
    rt = _screenshot_runtime(provider, tool)
    rt.start_task("s1", "ekran gor")
    msgs = provider.calls[1].messages
    # No message should carry the image, and the base64 blob must not leak into tool text.
    assert not any(m.images for m in msgs)
    tool_msgs = [m for m in msgs if m.role == "tool"]
    assert img_uri not in (tool_msgs[-1].content or "")


def test_session_trim_images_keeps_most_recent():
    from core.session.store import SessionStore

    st = SessionStore()
    sid = st.create_session()
    for i in range(5):
        st.add_message(sid, "user", f"shot {i}", images=[f"data:image/jpeg;base64,IMG{i}"])
    st.trim_images(sid, keep=2)
    assert [m.images for m in st.messages(sid)] == [
        None, None, None,
        ["data:image/jpeg;base64,IMG3"],
        ["data:image/jpeg;base64,IMG4"],
    ]


def test_session_trim_images_keeps_all_when_under_limit():
    from core.session.store import SessionStore

    st = SessionStore()
    sid = st.create_session()
    st.add_message(sid, "user", "a", images=["data:image/jpeg;base64,A"])
    st.add_message(sid, "user", "b")
    st.add_message(sid, "user", "c", images=["data:image/jpeg;base64,C"])
    st.trim_images(sid, keep=3)
    msgs = st.messages(sid)
    assert msgs[0].images == ["data:image/jpeg;base64,A"]
    assert msgs[1].images is None
    assert msgs[2].images == ["data:image/jpeg;base64,C"]


def test_runtime_keeps_only_last_image():
    """Repeated screenshots must not accumulate: only the most recent
    image survives in the session and in provider payloads."""
    from core.providers.base import ProviderResponse, ToolCall
    from core.tools.base import ToolResult
    from tests.fakes import FakeProvider, FakeTool

    imgs = [f"data:image/jpeg;base64,S{i}" for i in range(4)]
    tool = FakeTool("screenshot", [
        ToolResult(ok=True, data={"path": f"/tmp/{i}.jpg", "image": uri})
        for i, uri in enumerate(imgs)
    ])
    provider = FakeProvider([
        ProviderResponse(text=None, tool_calls=[ToolCall(id=f"c{i}", name="screenshot", arguments={})])
        for i in range(4)
    ] + [ProviderResponse(text="done", tool_calls=[])])
    provider.supports_vision = True
    rt = _screenshot_runtime(provider, tool)
    rt.start_task("s1", "ekran gor")

    # On the final model call only the latest image is attached.
    final = provider.calls[-1].messages
    attached = [m.images for m in final if m.images]
    assert attached == [["data:image/jpeg;base64,S3"]]

    # The store itself no longer holds the superseded base64 blobs.
    stored = rt._session.messages("s1")
    assert [m.images for m in stored if m.role == "user" and m.content == "Image from tool result:"] == [
        None, None, None,
        ["data:image/jpeg;base64,S3"],
    ]
