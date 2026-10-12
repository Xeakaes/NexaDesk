"""Configuration loading for the desktop assistant core."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

DEFAULT_AGENT_SETTINGS = {
    "max_tool_calls": 10,
    "tool_timeout_s": 30,
    "model_timeout_s": 60,
}


class ConfigError(Exception):
    """Raised when configuration or secrets cannot be loaded or are unsafe."""


def load_settings(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load settings from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"settings root must be an object: {path}")
    agent = data.setdefault("agent", {})
    for key, value in DEFAULT_AGENT_SETTINGS.items():
        agent.setdefault(key, value)
    return data


def load_secrets(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load secrets from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"secrets root must be an object: {path}")
    return data


def ensure_secrets_mode(path: Path) -> None:
    if os.name != "posix":
        # Windows has no POSIX mode bits (every file reports 0o666);
        # protection there comes from NTFS ACLs, not chmod.
        return
    mode = stat.S_IMODE(Path(path).stat().st_mode)
    if mode != 0o600:
        raise ConfigError(f"secrets file {path} must have mode 0600, got {oct(mode)}")


def save_settings(path: Path, data: dict) -> None:
    """Atomically write settings JSON (tmp + os.replace)."""
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
