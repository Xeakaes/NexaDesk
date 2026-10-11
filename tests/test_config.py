import json, os
import pytest
from core.config import load_settings, load_secrets, ensure_secrets_mode, ConfigError

def test_load_settings_reads_json(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"agent": {"max_tool_calls": 5}}))
    assert load_settings(p)["agent"]["max_tool_calls"] == 5

def test_load_secrets_reads_json(tmp_path):
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({"screen_control_api_key": "k"}))
    os.chmod(p, 0o600)
    assert load_secrets(p)["screen_control_api_key"] == "k"

def test_ensure_secrets_mode_rejects_world_readable(tmp_path):
    p = tmp_path / "secrets.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    with pytest.raises(ConfigError):
        ensure_secrets_mode(p)

def test_ensure_secrets_mode_is_noop_on_windows(tmp_path, monkeypatch):
    # Windows has no POSIX mode bits (every file reports 0o666), so the
    # 0600 check must be skipped there or the app cannot start at all.
    p = tmp_path / "secrets.json"
    p.write_text("{}")
    os.chmod(p, 0o666)
    monkeypatch.setattr(os, "name", "nt")
    ensure_secrets_mode(p)

def test_default_settings_values(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({}))
    s = load_settings(p)
    assert s["agent"] == {"max_tool_calls": 10, "tool_timeout_s": 30, "model_timeout_s": 60}
