"""GitHub release update check (offline-safe, at most one request per day)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

REPO = "Xeakaes/NexaDesk"
_LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
_CHECK_INTERVAL_S = 24 * 3600


def parse_version(raw: str) -> tuple[int, ...] | None:
    text = (raw or "").strip().lstrip("vV")
    parts = text.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest_tag: str, current: str) -> bool:
    latest = parse_version(latest_tag)
    base = parse_version(current)
    if latest is None or base is None:
        return False
    # Compare component-wise; "0.2" == "0.2.0".
    length = max(len(latest), len(base))
    latest += (0,) * (length - len(latest))
    base += (0,) * (length - len(base))
    return latest > base


def fetch_latest_tag(
    session: requests.Session | None = None,
    repo: str = REPO,
    timeout: float = 5.0,
) -> str | None:
    """Return the latest release tag, or None on any failure (offline-safe)."""
    sess = session or requests.Session()
    url = _LATEST_URL if repo == REPO else f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = sess.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        tag = (resp.json() or {}).get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except Exception:
        return None


def should_check(state_path: Path, now: float | None = None) -> bool:
    """True at most once every 24h; a corrupt/missing state file counts as never."""
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
        last = float(data.get("last_check", 0))
    except Exception:
        return True
    now = time.time() if now is None else now
    return (now - last) >= _CHECK_INTERVAL_S


def record_check(state_path: Path, now: float | None = None) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_check": time.time() if now is None else now}
    path.write_text(json.dumps(payload), encoding="utf-8")
