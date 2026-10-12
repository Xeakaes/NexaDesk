import json
import os
from pathlib import Path

from core.agent.runtime import AgentRuntime
from core.bootstrap import build_runtime
from tests.fakes import FakeProvider


def test_build_runtime_wires_everything(tmp_path):
    settings = {
        "provider": {"type": "ollama", "url": "http://127.0.0.1:11434", "model": "m"},
        "screen_control": {"enabled": True, "host": "127.0.0.1", "port": 8745},
        "permissions": {"*": "allow"},
        "agent": {"max_tool_calls": 10, "tool_timeout_s": 30, "model_timeout_s": 60},
    }
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(settings))
    kp = tmp_path / "secrets.json"
    kp.write_text(json.dumps({}))
    os.chmod(kp, 0o600)

    rt, events, session = build_runtime(
        settings_path=sp,
        secrets_path=kp,
        provider=FakeProvider([]),
        client_factory=lambda: object(),
    )
    assert isinstance(rt, AgentRuntime)
    names = set(rt.registry.names())
    assert {"screenshot", "ocr_screen", "mouse", "keyboard", "list_windows", "focus_window"} <= names


def test_build_runtime_loads_persona(tmp_path):
    settings = {
        "provider": {"type": "ollama", "url": "http://x", "model": "m"},
        "screen_control": {"enabled": False},
        "agent": {"persona": "Sen Nexa'sın."},
    }
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(settings))
    kp = tmp_path / "secrets.json"
    kp.write_text(json.dumps({}))
    os.chmod(kp, 0o600)
    rt, _, _ = build_runtime(
        settings_path=sp, secrets_path=kp, provider=FakeProvider([]), client_factory=lambda: object()
    )
    assert rt._config.persona == "Sen Nexa'sın."


def test_build_runtime_respects_screen_control_disabled(tmp_path):
    settings = {
        "provider": {"type": "ollama", "url": "http://x", "model": "m"},
        "screen_control": {"enabled": False},
        "permissions": {"*": "deny"},
    }
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(settings))
    kp = tmp_path / "secrets.json"
    kp.write_text(json.dumps({}))
    os.chmod(kp, 0o600)
    rt, _, _ = build_runtime(
        settings_path=sp, secrets_path=kp, provider=FakeProvider([]), client_factory=lambda: object()
    )
    assert rt.registry.names() == []


def test_live_screen_control_token_reads_data_dir_file(tmp_path, monkeypatch):
    import core.bootstrap as bs

    monkeypatch.setattr(bs, "config_dir", lambda: tmp_path)
    assert bs.live_screen_control_token() is None  # no .token yet
    (tmp_path / ".token").write_text("abc123")
    assert bs.live_screen_control_token() == "abc123"
    (tmp_path / ".token").write_text("   ")  # blank -> None
    assert bs.live_screen_control_token() is None


def test_client_factory_prefers_live_token_over_stale_secrets(tmp_path, monkeypatch):
    """Regression: after a server restart the cached secrets token is stale and
    every tool call 401s. The factory must use the LIVE .token file instead."""
    import core.bootstrap as bs
    import vendor.sc_server.sdk as sdk

    monkeypatch.setattr(bs, "config_dir", lambda: tmp_path)
    (tmp_path / ".token").write_text("LIVE_TOKEN")
    recorded = {}

    class FakeSC:
        def __init__(self, host=None, port=None, api_key=None):
            recorded["api_key"] = api_key

    monkeypatch.setattr(sdk, "ScreenControl", FakeSC)
    factory = bs.default_client_factory({}, {"screen_control_api_key": "STALE_KEY"})
    factory()
    assert recorded["api_key"] == "LIVE_TOKEN"


def test_client_factory_falls_back_to_secrets_without_token_file(tmp_path, monkeypatch):
    import core.bootstrap as bs
    import vendor.sc_server.sdk as sdk

    monkeypatch.setattr(bs, "config_dir", lambda: tmp_path)  # no .token
    recorded = {}

    class FakeSC:
        def __init__(self, host=None, port=None, api_key=None):
            recorded["api_key"] = api_key

    monkeypatch.setattr(sdk, "ScreenControl", FakeSC)
    factory = bs.default_client_factory({}, {"screen_control_api_key": "FROM_SECRETS"})
    factory()
    assert recorded["api_key"] == "FROM_SECRETS"
