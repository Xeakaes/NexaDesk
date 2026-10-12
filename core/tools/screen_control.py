"""screen-control adapter: consistent Tool wrappers over the ScreenControl SDK.

Transport is the existing Python SDK (HTTP client to the screen-control
server). The agent never sees HTTP details, host, or API key (spec §3.3).
SDK import is lazy — tests inject a fake client via client_factory.
"""

from __future__ import annotations

from typing import Any, Callable

import requests

from core.agent.cancellation import CancellationToken
from core.tools.base import Tool, ToolResult
from core.tools.registry import ToolRegistry


class _ScreenControlTool(Tool):
    def __init__(self, name: str, description: str, input_schema: dict,
                 client_factory: Callable[[], Any]) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self._client_factory = client_factory

    def _run(self, arguments: dict, cancel: CancellationToken, fn) -> ToolResult:
        if cancel.cancelled:
            return ToolResult(ok=False, error="cancelled before call", error_code="cancelled")
        try:
            client = self._client_factory()
            data = fn(client, arguments)
        except requests.Timeout as exc:
            return ToolResult(ok=False, error=str(exc), error_code="timeout")
        except requests.ConnectionError as exc:
            return ToolResult(ok=False, error=str(exc), error_code="server_unreachable")
        except Exception as exc:
            msg = str(exc)
            if "Request failed" in msg or "Max retries" in msg or "Connection" in msg:
                return ToolResult(ok=False, error=msg, error_code="server_unreachable")
            return ToolResult(ok=False, error=msg, error_code="tool_exception")
        if cancel.cancelled:
            return ToolResult(ok=False, error="cancelled during call", error_code="cancelled")
        return ToolResult(ok=True, data=data if isinstance(data, dict) else {"result": data})

    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        raise NotImplementedError


class _ScreenshotTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        def run(client, args):
            import base64
            import io
            import time
            import uuid
            from pathlib import Path

            from core.paths import data_dir

            # Security: never honor a model-supplied path — screenshots only
            # land under our own data dir with a server-generated name.
            shots = data_dir() / "shots"
            shots.mkdir(parents=True, exist_ok=True)
            path = str(shots / f"shot-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.jpg")
            client.screenshot(output=path, hwnd=args.get("hwnd"))
            data = {"path": path}
            # Attach a resized base64 data-URI so vision models can see it.
            try:
                from PIL import Image

                img = Image.open(path)
                img.load()
                img.thumbnail((1280, 1280))
                buf = io.BytesIO()
                try:
                    img.convert("RGB").save(buf, format="JPEG", quality=85)
                    mime = "image/jpeg"
                except Exception:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    mime = "image/png"
                data["image"] = f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"
            except Exception:
                # Vision attach is best-effort; path alone is still useful.
                pass
            return data

        return self._run(arguments, cancel, run)


class _OcrScreenTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        def run(client, args):
            return client.ocr(hwnd=args.get("hwnd"))
        return self._run(arguments, cancel, run)


class _MouseTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        action = arguments.get("action")
        x, y = arguments.get("x"), arguments.get("y")

        def run(client, args):
            if action == "move":
                client.move(int(x), int(y))
            elif action == "click":
                client.click(int(x), int(y))
            elif action == "right_click":
                client.right_click(int(x), int(y))
            elif action == "double_click":
                client.double_click(int(x), int(y))
            elif action == "scroll":
                client.scroll(int(arguments.get("clicks", 0)), x=int(x) if x is not None else None,
                              y=int(y) if y is not None else None)
            else:
                raise ValueError(f"unknown mouse action: {action}")
            return {"action": action, "x": x, "y": y}
        return self._run(arguments, cancel, run)


class _KeyboardTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        action = arguments.get("action")

        def run(client, args):
            if action == "press":
                client.press(arguments["key"])
            elif action == "hotkey":
                keys = arguments.get("keys") or ([arguments["key"]] if arguments.get("key") else [])
                client.hotkey(*keys)
            elif action == "type":
                client.type_text(arguments.get("text", ""))
            elif action == "key_down":
                client.key_down(arguments["key"])
            elif action == "key_up":
                client.key_up(arguments["key"])
            else:
                raise ValueError(f"unknown keyboard action: {action}")
            return {"action": action}
        return self._run(arguments, cancel, run)


class _ListWindowsTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        def run(client, args):
            return {"windows": client.windows()}
        return self._run(arguments, cancel, run)


class _FocusWindowTool(_ScreenControlTool):
    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        def run(client, args):
            client.focus_window(int(args["hwnd"]))
            return {"focused": int(args["hwnd"])}
        return self._run(arguments, cancel, run)


# Every tool this module registers; used to unregister them when Settings
# are re-applied (B29).
SCREEN_CONTROL_TOOL_NAMES = (
    "screenshot",
    "ocr_screen",
    "mouse",
    "keyboard",
    "list_windows",
    "focus_window",
)


def register_screen_control(
    registry: ToolRegistry,
    client_factory: Callable[[], Any],
    timeout_s: float = 30.0,
) -> None:
    del timeout_s  # per-call timeout is enforced by the runtime wall clock + SDK HTTP timeout
    registry.register(_ScreenshotTool(
        "screenshot",
        "Take a screenshot of the desktop and return its file path. "
        "Pass hwnd to capture the monitor showing that window (multi-monitor).",
        {"type": "object",
         "properties": {"hwnd": {"type": ["integer", "null"]}},
         "required": []},
        client_factory,
    ))
    registry.register(_OcrScreenTool(
        "ocr_screen",
        "Read text currently visible on the screen via OCR. "
        "Pass hwnd to read the monitor showing that window (multi-monitor).",
        {"type": "object",
         "properties": {"hwnd": {"type": ["integer", "null"]}},
         "required": []},
        client_factory,
    ))
    registry.register(_MouseTool(
        "mouse",
        "Move, click, right-click, double-click, or scroll the mouse.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["move", "click", "right_click", "double_click", "scroll"]},
                "x": {"type": ["integer", "null"]},
                "y": {"type": ["integer", "null"]},
                "clicks": {"type": "integer"},
            },
            "required": ["action"],
        },
        client_factory,
    ))
    registry.register(_KeyboardTool(
        "keyboard",
        "Press a key, send a hotkey combo, type text, or hold/release a key.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["press", "hotkey", "type", "key_down", "key_up"]},
                "key": {"type": "string"},
                "keys": {"type": "array", "items": {"type": "string"}},
                "text": {"type": "string"},
            },
            "required": ["action"],
        },
        client_factory,
    ))
    registry.register(_ListWindowsTool(
        "list_windows",
        "List open windows with hwnd and title.",
        {"type": "object", "properties": {}, "required": []},
        client_factory,
    ))
    registry.register(_FocusWindowTool(
        "focus_window",
        "Focus a window by hwnd.",
        {
            "type": "object",
            "properties": {"hwnd": {"type": "integer"}},
            "required": ["hwnd"],
        },
        client_factory,
    ))
