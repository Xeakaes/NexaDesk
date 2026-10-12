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

@pytest.mark.skipif(os.name == "nt", reason="no POSIX mode bits on Windows; ensure_secrets_mode is a no-op there")
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

def test_save_settings_is_atomic(tmp_path):
    # Write must go through tmp + os.replace so a crash mid-write cannot
    # leave a truncated/corrupt settings.json behind.
    from core.config import save_settings
    p = tmp_path / "settings.json"
    save_settings(p, {"avatar": "teto"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"avatar": "teto"}
    assert not list(tmp_path.glob("*.tmp"))

def test_save_settings_preserves_other_keys(tmp_path):
    from core.config import save_settings
    p = tmp_path / "settings.json"
    save_settings(p, {"provider": {"type": "groq"}, "avatar": "base"})
    data = load_settings(p)
    save_settings(p, {**data, "avatar": "teto"})
    data2 = load_settings(p)
    assert data2["provider"]["type"] == "groq"
    assert data2["avatar"] == "teto"

@pytest.mark.skipif(os.name == "nt", reason="no POSIX mode bits on Windows; ensure_secrets_mode is a no-op there")
def test_ensure_secrets_mode_error_suggests_chmod_with_full_path(tmp_path):
    # B59: the dialog must give the actionable fix with the real path —
    # "fix the file" alone leads users to delete their API keys.
    p = tmp_path / "secrets.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    with pytest.raises(ConfigError) as ei:
        ensure_secrets_mode(p)
    msg = str(ei.value)
    assert "chmod 600" in msg
    assert str(p) in msg
