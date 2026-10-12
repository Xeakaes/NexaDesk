import pytest
import requests
from core.agent.cancellation import CancellationToken
from core.tools.base import ToolResult
from core.tools.registry import ToolRegistry
from core.tools.screen_control import register_screen_control


class FakeClient:
    def __init__(self, exc=None, screenshot_path="/tmp/shot.png", ocr_text="merhaba", windows=None):
        self.exc = exc
        self.screenshot_path = screenshot_path
        self.ocr_text = ocr_text
        self._windows_list = windows or [{"hwnd": 1, "title": "Terminal"}]
        self.calls = []

    def _maybe_raise(self):
        if self.exc:
            raise self.exc

    def screenshot(self, output=None, monitor=1, region=None):
        self.calls.append(("screenshot", output))
        self._maybe_raise()
        return b"jpegbytes"

    def ocr(self, region=None):
        self.calls.append(("ocr", region))
        self._maybe_raise()
        return {"text": self.ocr_text}

    def move(self, x, y):
        self.calls.append(("move", x, y))
        self._maybe_raise()

    def click(self, x, y, button="left", clicks=1):
        self.calls.append(("click", x, y, button, clicks))
        self._maybe_raise()

    def press(self, key):
        self.calls.append(("press", key))
        self._maybe_raise()

    def type_text(self, text, interval=0.03):
        self.calls.append(("type_text", text))
        self._maybe_raise()

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))
        self._maybe_raise()

    def windows(self):
        self.calls.append(("windows",))
        self._maybe_raise()
        return self._windows_list

    def focus_window(self, hwnd):
        self.calls.append(("focus_window", hwnd))
        self._maybe_raise()


def _registry(client, timeout_s=30.0):
    reg = ToolRegistry()
    register_screen_control(reg, lambda: client, timeout_s=timeout_s)
    return reg


def test_screenshot_calls_sdk_and_returns_path():
    client = FakeClient()
    reg = _registry(client)
    r = reg.get("screenshot").execute({}, CancellationToken())
    assert r.ok and r.data["path"].endswith(".jpg")
    assert client.calls[0][0] == "screenshot"


def test_screenshot_ignores_model_supplied_path(monkeypatch, tmp_path):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    client = FakeClient()
    reg = _registry(client)
    r = reg.get("screenshot").execute({"path": "/etc/nexadesk-evil.jpg"}, CancellationToken())
    assert r.ok
    out = client.calls[0][1]
    assert out.startswith(str(tmp_path / "shots"))
    assert "evil" not in out
    assert r.data["path"] == out


def test_screenshot_uses_unique_names_per_call(monkeypatch, tmp_path):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    client = FakeClient()
    reg = _registry(client)
    reg.get("screenshot").execute({}, CancellationToken())
    reg.get("screenshot").execute({}, CancellationToken())
    outs = [c[1] for c in client.calls if c[0] == "screenshot"]
    assert len(outs) == 2 and outs[0] != outs[1]


def test_mouse_validates_action_and_forwards():
    client = FakeClient()
    reg = _registry(client)
    r = reg.get("mouse").execute({"action": "move", "x": 10, "y": 20}, CancellationToken())
    assert r.ok
    assert ("move", 10, 20) in client.calls
    r2 = reg.get("mouse").execute({"action": "click", "x": 1, "y": 2}, CancellationToken())
    assert r2.ok
    assert any(c[0] == "click" for c in client.calls)


def test_timeout_sets_error_code():
    client = FakeClient(exc=requests.Timeout("slow"))
    reg = _registry(client)
    r = reg.get("screenshot").execute({}, CancellationToken())
    assert not r.ok and r.error_code == "timeout"


def test_connection_error_sets_server_unreachable():
    client = FakeClient(exc=requests.ConnectionError("down"))
    reg = _registry(client)
    r = reg.get("list_windows").execute({}, CancellationToken())
    assert not r.ok and r.error_code == "server_unreachable"


def test_cancelled_before_call_does_not_touch_client():
    client = FakeClient()
    reg = _registry(client)
    token = CancellationToken()
    token.cancel()
    r = reg.get("screenshot").execute({}, token)
    assert not r.ok and r.error_code == "cancelled"
    assert client.calls == []


def test_registered_names_match_spec():
    reg = _registry(FakeClient())
    assert set(reg.names()) == {
        "screenshot", "ocr_screen", "mouse", "keyboard", "list_windows", "focus_window"
    }
