"""Stdio MCP client: process lifecycle, handshake, tool discovery.

Transport is one subprocess speaking newline-delimited JSON-RPC on its
stdin/stdout (protocol in core.mcp.protocol). A daemon reader thread
correlates responses to requests by id through per-request queues; timeouts,
crashes and malformed lines surface as MCPClientError with a stable ``code``
the mapping layer translates into ToolResult error codes.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from core import __version__
from core.agent.cancellation import CancellationToken
from core.mcp.protocol import ProtocolError, decode, encode

PROTOCOL_VERSION = "2025-06-18"


class MCPClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class MCPServerConfig:
    command: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None
    request_timeout_s: float = 10.0
    prefix: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerConfig":
        command = data.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) for part in command)
        ):
            raise ValueError("mcp server config requires a non-empty 'command' list of strings")
        return cls(
            command=command,
            env=data.get("env"),
            cwd=data.get("cwd"),
            request_timeout_s=float(data.get("request_timeout_s", 10.0)),
            prefix=str(data.get("prefix", "")),
        )


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.protocol_version: str | None = None
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._state = "new"  # new | running | crashed | broken | closed
        self._tools: list[dict] = []
        self._ever_started = False
        self._stderr_chunks: deque[bytes] = deque(maxlen=64)  # ~256 KiB cap
        self._stderr_reader: threading.Thread | None = None

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> None:
        if self._state == "running":
            raise MCPClientError("already_started", "client is already running")
        self._spawn_and_handshake()

    def list_tools(self) -> list[dict]:
        if self._state != "running":
            raise MCPClientError("not_started", f"client state is {self._state!r}")
        return list(self._tools)

    def call_tool(
        self,
        name: str,
        arguments: dict,
        cancel: CancellationToken | None = None,
    ) -> dict:
        """Invoke one MCP tool; returns the raw MCP result payload.

        A dead-but-previously-started client is respawned once before the
        call (auto-reconnect); a failure inside the call itself raises.
        """
        if self._state in ("new", "closed"):
            raise MCPClientError("not_started", f"client state is {self._state!r}")
        if self._state in ("crashed", "broken") and self._ever_started:
            self._spawn_and_handshake()
        if cancel is not None and cancel.cancelled:
            raise MCPClientError("cancelled", f"{name} cancelled before call")
        return self._request(
            "tools/call", {"name": name, "arguments": arguments}, cancel=cancel
        )

    def close(self) -> None:
        if self._state == "closed":
            return
        self._state = "closed"
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass  # kernel will reap it eventually
        self._fail_pending(MCPClientError("server_crashed", "client closed"))
        for thread in (self._reader, self._stderr_reader):
            if thread is not None:
                thread.join(timeout=1.0)

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _spawn_and_handshake(self) -> None:
        self._reap()
        env = None
        if self.config.env:
            env = {**os.environ, **self.config.env}
        self._stderr_chunks.clear()
        try:
            self._proc = subprocess.Popen(
                self.config.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.config.cwd,
                env=env,
            )
        except OSError as exc:
            raise MCPClientError("spawn_failed", str(exc)) from exc
        self._state = "running"
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        stderr_stream = self._proc.stderr
        if stderr_stream is not None:
            self._stderr_reader = threading.Thread(
                target=self._drain_stderr, args=(stderr_stream,), daemon=True
            )
            self._stderr_reader.start()
        try:
            result = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "NexaDesk", "version": __version__},
            })
            self.protocol_version = result.get("protocolVersion")
            self._notify("notifications/initialized")
            self._tools = self._request("tools/list", {}).get("tools", [])
        except MCPClientError as exc:
            raise MCPClientError(
                exc.code, f"{exc.message}{self._stderr_hint()}"
            ) from exc
        self._ever_started = True

    def _reap(self) -> None:
        """Terminate and reap any previous process before a (re)spawn."""
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass  # kernel will reap it eventually
        else:
            proc.wait()  # reap a zombie left by a crash
        # Join the old pipes' threads before a new connection overwrites
        # self._reader, so a straggler cannot mark the fresh connection
        # crashed or fail its pending requests (review finding #3).
        for thread in (self._reader, self._stderr_reader):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._reader = None
        self._stderr_reader = None

    def _drain_stderr(self, stream) -> None:
        """Continuously consume server stderr into a bounded tail.

        Draining is mandatory: an unread PIPE fills (64 KiB) and would block
        the server. Chunks (not lines) bound memory even without newlines.
        """
        try:
            while True:
                chunk = stream.read1(4096)
                if not chunk:
                    break
                self._stderr_chunks.append(chunk)
        except (OSError, ValueError):
            pass

    def _stderr_hint(self) -> str:
        """Tail of server stderr, for handshake failure messages.

        If the server already exited, join the drain thread first so the
        diagnostic emitted just before death is not lost to a scheduling
        race; a still-alive server is not waited for.
        """
        proc = self._proc
        if (
            proc is not None
            and proc.poll() is not None
            and self._stderr_reader is not None
            and self._stderr_reader is not threading.current_thread()
        ):
            self._stderr_reader.join(timeout=0.5)
        if not self._stderr_chunks:
            return ""
        text = b"".join(self._stderr_chunks).decode(errors="replace")[-2000:]
        return f"\nserver stderr tail:\n{text}"

    def _send(self, payload: dict) -> None:
        proc = self._proc
        try:
            proc.stdin.write(encode(payload))
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self._mark_crashed()
            raise MCPClientError("server_crashed", f"write failed: {exc}") from exc

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _request(
        self,
        method: str,
        params: dict | None = None,
        cancel: CancellationToken | None = None,
    ) -> dict:
        if cancel is not None and cancel.cancelled:
            raise MCPClientError("cancelled", f"{method} cancelled before send")
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            waiter: queue.Queue = queue.Queue(maxsize=1)
            self._pending[req_id] = waiter
        try:
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                        "params": params or {}})
        except MCPClientError:
            with self._lock:
                self._pending.pop(req_id, None)
            raise
        deadline = time.monotonic() + self.config.request_timeout_s
        while True:
            if cancel is not None and cancel.cancelled:
                with self._lock:
                    self._pending.pop(req_id, None)
                raise MCPClientError("cancelled", f"{method} cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    self._pending.pop(req_id, None)
                    state = self._state
                if state == "crashed" or (
                    self._proc is not None and self._proc.poll() is not None
                ):
                    raise MCPClientError("server_crashed", f"{method}: server exited")
                if state == "broken":
                    raise MCPClientError("protocol", f"{method}: malformed response")
                raise MCPClientError("timeout", f"{method} timed out") from None
            try:
                reply = waiter.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            break
        if isinstance(reply, MCPClientError):
            raise reply
        if "error" in reply:
            error = reply["error"]
            code = (
                "not_found"
                if isinstance(error, dict) and error.get("code") == -32602
                else "jsonrpc"
            )
            raise MCPClientError(code, json.dumps(error))
        return reply["result"]

    def _read_loop(self) -> None:
        proc = self._proc
        try:
            for raw in iter(proc.stdout.readline, b""):
                try:
                    msg = decode(raw)
                except ProtocolError as exc:
                    self._state = "broken"
                    self._fail_pending(MCPClientError("protocol", str(exc)))
                    return
                if "id" in msg and ("result" in msg or "error" in msg):
                    with self._lock:
                        waiter = self._pending.pop(msg["id"], None)
                    if waiter is not None:
                        waiter.put(msg)
                # notifications (no matching id) are ignored
        except OSError:
            pass
        finally:
            # Only the reader thread currently owned by this client may
            # mutate shared state: a straggler from a replaced connection
            # must not mark the fresh connection crashed or fail its
            # pending requests (review finding #3).
            if threading.current_thread() is self._reader:
                self._mark_crashed()
                self._fail_pending(
                    MCPClientError("server_crashed", "server process ended")
                )

    def _mark_crashed(self) -> None:
        with self._lock:
            if self._state == "running":
                self._state = "crashed"

    def _fail_pending(self, error: MCPClientError) -> None:
        with self._lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            try:
                waiter.put_nowait(error)
            except queue.Full:
                pass
