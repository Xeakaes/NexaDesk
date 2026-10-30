import contextlib
import json
import os
import sys

import pytest

from core.agent.cancellation import CancellationToken
from core.mcp.client import MCPClient, MCPServerConfig, MCPClientError
from core.mcp.mapping import MCPToolAdapter, register_mcp_tools
from core.tools.registry import ToolRegistry, missing_required_args


def _config(scenario: str = "ok", *args: str, **overrides) -> MCPServerConfig:
    base = {
        "command": [sys.executable, "-m", "tests.mcp.fake_server", scenario, *args],
        "request_timeout_s": 3.0,
    }
    base.update(overrides)
    return MCPServerConfig(**base)


@contextlib.contextmanager
def registered(*configs: MCPServerConfig):
    registry = ToolRegistry()
    clients = register_mcp_tools(registry, list(configs))
    try:
        yield registry
    finally:
        for client in clients:
            client.close()


def test_schema_fields_verbatim_in_registry(tmp_path):
    with registered(_config(prefix="mcp_")) as registry:
        entry = next(s for s in registry.schemas() if s["name"] == "mcp_echo")
        assert entry["description"] == "Echo text back"
        assert entry["input_schema"] == {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }


def test_missing_required_args_works_on_mcp_schema(tmp_path):
    with registered(_config(prefix="mcp_")) as registry:
        entry = next(s for s in registry.schemas() if s["name"] == "mcp_echo")
        assert missing_required_args(entry["input_schema"], {}) == ["text"]


def test_execute_happy_path(tmp_path):
    with registered(_config()) as registry:
        result = registry.get("echo").execute(
            {"text": "merhaba"}, CancellationToken()
        )
        assert result.ok is True
        assert result.data == {"text": "merhaba"}


def test_execute_get_lap_parses_json(tmp_path):
    with registered(_config()) as registry:
        result = registry.get("get_lap").execute({}, CancellationToken())
        assert result.ok is True
        assert result.data == {"lap": 1, "time_s": 82.4, "sectors": [27.1, 27.5, 27.8]}


def test_execute_empty_content_maps_to_empty_data(tmp_path):
    with registered(_config("empty")) as registry:
        result = registry.get("echo").execute(
            {"text": "x"}, CancellationToken()
        )
        assert result.ok is True
        assert result.data == {}


def test_is_error_maps_to_tool_error(tmp_path):
    with registered(_config("error_result")) as registry:
        result = registry.get("write_setup").execute(
            {"name": "race"}, CancellationToken()
        )
        assert result.ok is False
        assert "refused" in result.error
        assert result.error_code == "tool_error"


def test_invalid_json_maps_to_mcp_error(tmp_path):
    with registered(_config("invalid_json")) as registry:
        result = registry.get("get_lap").execute({}, CancellationToken())
        assert result.ok is False
        assert result.error_code == "mcp_error"


def test_client_crash_maps_to_server_unreachable(tmp_path):
    with registered(_config("crash_on_call")) as registry:
        result = registry.get("get_lap").execute({}, CancellationToken())
        assert result.ok is False
        assert result.error_code == "server_unreachable"


def test_timeout_maps_to_timeout(tmp_path):
    state = tmp_path / "state"
    with registered(_config(
        "delay", "5",
        env={"FAKE_MCP_STATE": str(state)},
        request_timeout_s=0.3,
    )) as registry:
        result = registry.get("get_lap").execute({}, CancellationToken())
        assert result.ok is False
        assert result.error_code == "timeout"


def test_cancel_maps_to_cancelled(tmp_path):
    with registered(_config()) as registry:
        token = CancellationToken()
        token.cancel()
        result = registry.get("echo").execute({"text": "x"}, token)
        assert result.ok is False
        assert result.error_code == "cancelled"


def test_description_fallback_when_server_omits(tmp_path):
    client = MCPClient(_config())
    adapter = MCPToolAdapter(client, "bare", "mcp_bare", "", {})
    assert adapter.description == "MCP tool bare"
    client.close()


def test_register_failure_closes_started_clients(tmp_path):
    pid_file = tmp_path / "fake.pid"
    registry = ToolRegistry()
    configs = [
        _config(env={"FAKE_MCP_PID": str(pid_file)}),
        MCPServerConfig(command=["no-such-binary-xyz"]),
    ]
    with pytest.raises(MCPClientError) as exc:
        register_mcp_tools(registry, configs)
    assert exc.value.code == "spawn_failed"
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_register_failure_closes_hung_handshake_client(tmp_path):
    pid_file = tmp_path / "hang.pid"
    registry = ToolRegistry()
    configs = [
        _config(),
        _config("hang_on_init", env={"FAKE_MCP_PID": str(pid_file)},
                request_timeout_s=0.5),
    ]
    with pytest.raises(MCPClientError) as exc:
        register_mcp_tools(registry, configs)
    assert exc.value.code == "timeout"
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_handshake_failure_includes_server_stderr(tmp_path):
    client = MCPClient(_config("die_on_init"))
    with pytest.raises(MCPClientError) as exc:
        client.start()
    assert exc.value.code == "server_crashed"
    assert "missing dependency 'libx'" in exc.value.message
    client.close()


def test_unknown_tool_jsonrpc_error_maps_to_mcp_error(tmp_path):
    client = MCPClient(_config())
    client.start()
    try:
        adapter = MCPToolAdapter(client, "nope", "mcp_nope", "", {})
        result = adapter.execute({}, CancellationToken())
    finally:
        client.close()
    assert result.ok is False
    assert result.error_code == "mcp_error"
