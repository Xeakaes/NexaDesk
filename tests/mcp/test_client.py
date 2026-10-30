import json
import os
import sys
import threading
import time

import pytest

from core.agent.cancellation import CancellationToken
from core.mcp.client import MCPClient, MCPServerConfig, MCPClientError


def _config(scenario: str = "ok", *args: str, **overrides) -> MCPServerConfig:
    base = {
        "command": [sys.executable, "-m", "tests.mcp.fake_server", scenario, *args],
        "request_timeout_s": 3.0,
    }
    base.update(overrides)
    return MCPServerConfig(**base)


def test_start_and_list_tools(tmp_path):
    client = MCPClient(_config())
    try:
        client.start()
        names = {t["name"] for t in client.list_tools()}
        assert names == {"echo", "get_lap", "echo_env", "write_setup"}
        echo = next(t for t in client.list_tools() if t["name"] == "echo")
        assert echo["inputSchema"]["required"] == ["text"]
    finally:
        client.close()


def test_double_start_raises_already_started(tmp_path):
    client = MCPClient(_config())
    client.start()
    try:
        with pytest.raises(MCPClientError) as exc:
            client.start()
        assert exc.value.code == "already_started"
    finally:
        client.close()


def test_list_tools_before_start_raises_not_started():
    client = MCPClient(_config())
    with pytest.raises(MCPClientError) as exc:
        client.list_tools()
    assert exc.value.code == "not_started"


def test_start_with_missing_binary_raises_spawn_failed():
    client = MCPClient(MCPServerConfig(command=["no-such-binary-xyz"]))
    with pytest.raises(MCPClientError) as exc:
        client.start()
    assert exc.value.code == "spawn_failed"


def test_crash_during_initialize_raises_server_crashed():
    client = MCPClient(_config(scenario="crash_on_init", request_timeout_s=2.0))
    with pytest.raises(MCPClientError) as exc:
        client.start()
    assert exc.value.code == "server_crashed"


def test_close_terminates_process(tmp_path):
    pid_file = tmp_path / "fake.pid"
    client = MCPClient(_config(env={"FAKE_MCP_PID": str(pid_file)}))
    client.start()
    pid = int(pid_file.read_text())
    client.close()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_close_is_idempotent(tmp_path):
    client = MCPClient(_config())
    client.start()
    client.close()
    client.close()  # second close must not raise


def test_context_manager_closes(tmp_path):
    pid_file = tmp_path / "fake.pid"
    with MCPClient(_config(env={"FAKE_MCP_PID": str(pid_file)})) as client:
        client.start()
        pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_from_dict_parses_all_fields():
    cfg = MCPServerConfig.from_dict({
        "command": ["python", "-m", "srv"],
        "env": {"A": "1"},
        "cwd": "/tmp",
        "request_timeout_s": 5.0,
        "prefix": "mcp_",
    })
    assert cfg.command == ["python", "-m", "srv"]
    assert cfg.env == {"A": "1"}
    assert cfg.cwd == "/tmp"
    assert cfg.request_timeout_s == 5.0
    assert cfg.prefix == "mcp_"


@pytest.mark.parametrize("bad", [{}, {"command": []}, {"command": "python"}, {"command": [1, 2]}])
def test_from_dict_rejects_missing_or_empty_command(bad):
    with pytest.raises(ValueError):
        MCPServerConfig.from_dict(bad)


def test_call_tool_happy_path(tmp_path):
    client = MCPClient(_config())
    client.start()
    try:
        payload = client.call_tool("echo", {"text": "merhaba"})
        assert payload["isError"] is False
        assert json.loads(payload["content"][0]["text"]) == {"text": "merhaba"}
    finally:
        client.close()


def test_env_passthrough(tmp_path):
    client = MCPClient(_config(env={"FAKE_MCP_TOKEN": "abc"}))
    client.start()
    try:
        payload = client.call_tool("echo_env", {"name": "FAKE_MCP_TOKEN"})
        assert json.loads(payload["content"][0]["text"]) == {"value": "abc"}
    finally:
        client.close()


def test_unknown_tool_raises_not_found(tmp_path):
    client = MCPClient(_config())
    client.start()
    try:
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("nope", {})
        assert exc.value.code == "not_found"
    finally:
        client.close()


def test_call_timeout_raises_timeout(tmp_path):
    state = tmp_path / "state"
    client = MCPClient(_config(
        "delay", "5",
        env={"FAKE_MCP_STATE": str(state)},
        request_timeout_s=0.3,
    ))
    client.start()
    try:
        start = time.monotonic()
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {})
        assert exc.value.code == "timeout"
        assert time.monotonic() - start < 2.0
    finally:
        client.close()


def test_client_usable_after_timeout(tmp_path):
    state = tmp_path / "state"
    client = MCPClient(_config(
        "delay", "1",
        env={"FAKE_MCP_STATE": str(state)},
        request_timeout_s=0.2,
    ))
    client.start()
    try:
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {})
        assert exc.value.code == "timeout"
        time.sleep(1.1)  # late response arrives and must be dropped silently
        payload = client.call_tool("get_lap", {})
        assert json.loads(payload["content"][0]["text"])["lap"] == 1
    finally:
        client.close()


def test_cancel_interrupts_call(tmp_path):
    state = tmp_path / "state"
    client = MCPClient(_config("delay", "5", env={"FAKE_MCP_STATE": str(state)}))
    client.start()
    try:
        token = CancellationToken()
        threading.Timer(0.1, token.cancel).start()
        start = time.monotonic()
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {}, cancel=token)
        assert exc.value.code == "cancelled"
        assert time.monotonic() - start < 2.0
    finally:
        client.close()


def test_error_result_returns_payload(tmp_path):
    client = MCPClient(_config("error_result"))
    client.start()
    try:
        payload = client.call_tool("write_setup", {"name": "race"})
        assert payload["isError"] is True
        assert "refused" in payload["content"][0]["text"]
    finally:
        client.close()


def test_crash_during_call_raises_server_crashed(tmp_path):
    client = MCPClient(_config("crash_on_call"))
    client.start()
    try:
        start = time.monotonic()
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {})
        assert exc.value.code == "server_crashed"
        assert time.monotonic() - start < 2.0
    finally:
        client.close()


def test_reconnect_after_crash(tmp_path):
    pid_file = tmp_path / "fake.pid"
    state = tmp_path / "state"
    client = MCPClient(_config(
        "flaky",
        env={"FAKE_MCP_PID": str(pid_file), "FAKE_MCP_STATE": str(state)},
    ))
    client.start()
    first_pid = int(pid_file.read_text())
    try:
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {})
        assert exc.value.code == "server_crashed"
        payload = client.call_tool("get_lap", {})  # auto-reconnect heals the call
        assert json.loads(payload["content"][0]["text"])["lap"] == 1
        second_pid = int(pid_file.read_text())
        assert second_pid != first_pid
        client.close()
        with pytest.raises(ProcessLookupError):
            os.kill(second_pid, 0)
    finally:
        client.close()


def test_invalid_json_response_raises_protocol(tmp_path):
    pid_file = tmp_path / "fake.pid"
    client = MCPClient(_config("invalid_json", env={"FAKE_MCP_PID": str(pid_file)}))
    client.start()
    pid = int(pid_file.read_text())
    try:
        start = time.monotonic()
        with pytest.raises(MCPClientError) as exc:
            client.call_tool("get_lap", {})
        assert exc.value.code == "protocol"
        assert time.monotonic() - start < 2.0
        client.close()
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        client.close()
