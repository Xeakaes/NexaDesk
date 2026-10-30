"""Deterministic MCP stdio server for CI tests.

Run as ``python -m tests.mcp.fake_server [scenario]``; scenario defaults to
``ok``. Test infrastructure only — pytest must not collect it (no test_
prefix). Scenarios beyond ok/crash_on_init are added by later tasks.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

LAP = {"lap": 1, "time_s": 82.4, "sectors": [27.1, 27.5, 27.8]}

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "get_lap",
        "description": "A recorded lap",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "echo_env",
        "description": "Read a server environment variable",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "write_setup",
        "description": "Write a car setup file",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def _send(obj: dict) -> None:
    sys.stdout.buffer.write(
        json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


def _text_result(payload: dict, is_error: bool = False) -> dict:
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, separators=(",", ":"))}
        ],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: dict) -> dict:
    if name == "echo":
        return _text_result({"text": arguments.get("text")})
    if name == "get_lap":
        return _text_result(LAP)
    if name == "echo_env":
        return _text_result({"value": os.environ.get(arguments.get("name", ""))})
    if name == "write_setup":
        return _text_result({"written": arguments.get("name")})
    raise AssertionError(f"unhandled tool: {name}")


def _claim_first_call(state_file: str | None) -> bool:
    """True the first time per state file; writes the marker on first claim."""
    if not state_file:
        return True
    path = Path(state_file)
    if path.exists():
        return False
    path.write_text("1")
    return True


def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok"
    delay_s = float(sys.argv[2]) if scenario == "delay" and len(sys.argv) > 2 else 5.0
    state_file = os.environ.get("FAKE_MCP_STATE")
    pid_file = os.environ.get("FAKE_MCP_PID")
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()))
    for raw in sys.stdin.buffer:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            if scenario == "crash_on_init":
                raise SystemExit(1)
            params = msg.get("params") or {}
            _send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion") or "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "fake-mcp", "version": "1.0"},
                },
            })
        elif method and method.startswith("notifications/"):
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            _send({
                "jsonrpc": "2.0",
                "method": "notifications/message",
                "params": {"level": "info", "data": "handling call"},
            })
            if scenario == "crash_on_call":
                raise SystemExit(1)
            if scenario == "invalid_json":
                sys.stdout.buffer.write(b"{this is not json\n")
                sys.stdout.buffer.flush()
                continue
            if scenario == "error_result":
                _send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({"refused": "user denied"}),
                        }],
                        "isError": True,
                    },
                })
                continue
            if scenario == "delay" and _claim_first_call(state_file):
                time.sleep(delay_s)
            if scenario == "flaky" and _claim_first_call(state_file):
                raise SystemExit(1)
            tool_name = params.get("name")
            if tool_name not in {t["name"] for t in TOOLS}:
                _send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}",
                    },
                })
            else:
                _send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _call_tool(tool_name, params.get("arguments") or {}),
                })
        elif msg_id is not None:
            _send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            })


if __name__ == "__main__":
    main()
