import os
import sys

import pytest

from core.mcp.client import MCPClient, MCPServerConfig, MCPClientError


def _config(scenario: str = "ok", **overrides) -> MCPServerConfig:
    base = {
        "command": [sys.executable, "-m", "tests.mcp.fake_server", scenario],
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
