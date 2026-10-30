"""Newline-delimited JSON-RPC framing shared by the MCP client transport.

One message per line, compact JSON, UTF-8 — the stdio framing assetto-mcp's
supervisor and the official MCP SDK both speak. Nothing else about the
protocol lives here.
"""

from __future__ import annotations

import json


class ProtocolError(Exception):
    """A line from the server could not be parsed as a JSON-RPC message."""


def encode(obj: dict) -> bytes:
    """Serialize one message as a newline-terminated UTF-8 line."""
    return json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict:
    """Parse one line; raise ProtocolError for invalid JSON or non-object input."""
    try:
        obj = json.loads(line.decode("utf-8").rstrip("\n"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(str(exc)) from exc
    if not isinstance(obj, dict):
        raise ProtocolError(f"expected JSON object, got {type(obj).__name__}")
    return obj
