"""Frozen-aware path resolution for config/data/assets (spec packaging §1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", repo_root()))
    return repo_root()


def bundled_version() -> str:
    """Best-known running version: APP_VERSION env, baked _version.txt, core.

    The release build writes the real version into _version.txt; comparing
    against core.__version__ alone would always report "0.0.0" (B10).
    """
    import os as _os

    env = _os.environ.get("APP_VERSION", "").strip()
    if env:
        return env
    p = bundle_root() / "_version.txt"
    if p.exists():
        v = p.read_text(encoding="utf-8").strip()
        if v:
            return v
    from core import __version__

    return __version__


def config_dir() -> Path:
    if is_frozen():
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", str(Path.home()))) / "NexaDesk"
        else:
            base = Path.home() / ".config" / "NexaDesk"
        return base
    return repo_root() / "config"


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "NexaDesk"
    else:
        base = Path.home() / ".local" / "share" / "NexaDesk"
    base.mkdir(parents=True, exist_ok=True)
    return base


def assets_dir() -> Path:
    return bundle_root() / "assets"


def user_avatars_dir() -> Path:
    """Writable directory for user-built avatar packs (survives updates)."""
    d = config_dir() / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _legacy_config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "desktop-assistant"
    return Path.home() / ".config" / "desktop-assistant"


def _legacy_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "desktop-assistant"
    return Path.home() / ".local" / "share" / "desktop-assistant"


def _move_missing(src: Path, dst: Path) -> None:
    """Move entries from src into dst without overwriting anything in dst."""
    import shutil

    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if target.exists():
            continue
        try:
            item.rename(target)
        except OSError:
            shutil.move(str(item), str(target))


def migrate_legacy_dirs() -> None:
    """One-time migration from the pre-rename desktop-assistant directories.

    Old installs kept config in ~/.config/desktop-assistant and data
    (history.db, …) in ~/.local/share/desktop-assistant (Windows: one
    %APPDATA%\\desktop-assistant folder). Move anything the new NexaDesk
    directories do not have yet, then remove the emptied legacy dirs.
    """
    pairs = (
        (_legacy_config_dir(), config_dir()),
        (_legacy_data_dir(), data_dir()),
    )
    for old, new in pairs:
        if not old.is_dir() or old.resolve() == new.resolve():
            continue
        _move_missing(old, new)
        try:
            old.rmdir()  # only succeeds when fully migrated
        except OSError:
            pass


def create_empty_secrets(path: Path) -> None:
    """Create an empty secrets file with 0600 perms (never overwrite).

    Uses O_EXCL + restrictive mode at creation so the file is never
    world-readable, not even for the instant between creation and a
    follow-up chmod (the old write_text + chmod pattern had that window).
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, b"{}")
    finally:
        os.close(fd)


def ensure_user_config() -> None:
    """Seed config_dir() with defaults on first frozen launch."""
    import json

    migrate_legacy_dirs()
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    settings = cfg / "settings.json"
    if not settings.exists():
        template = bundle_root() / "config_template" / "settings.json"
        if template.exists():
            settings.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            settings.write_text(
                json.dumps(
                    {
                        "avatar": "base",
                        "language": "tr",
                        "theme": "dark",
                        "screen_control": {"enabled": True, "host": "127.0.0.1", "port": 8745},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    create_empty_secrets(cfg / "secrets.json")
