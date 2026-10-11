"""JSON-lines timing telemetry for diagnosing agent slowness.

One JSON object per line in ``config_dir()/logs/agent.log`` (rotated, 2x1MB).
Two events matter for the rate-limit investigation:

- ``model_request``  — every provider HTTP attempt: duration, status, wait,
  Retry-After, the provider's x-ratelimit-* headers, token usage.
- ``task_summary``   — one line per agent task: total duration, model call
  count, per-tool timings, outcome.

Telemetry must never break the agent: every write is best-effort. Disable
with ``NEXADESK_TELEMETRY=off``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.paths import config_dir

_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 2
_OFF_VALUES = {"0", "off", "false", "no"}


def _log_file() -> Path:
    return config_dir() / "logs" / "agent.log"


def _disabled() -> bool:
    return os.environ.get("NEXADESK_TELEMETRY", "").strip().lower() in _OFF_VALUES


_loggers: dict[str, object] = {}


def _logger_for(path: Path):
    """Rotating file logger keyed by path; None when the dir is unwritable."""
    key = str(path)
    if key in _loggers:
        return _loggers[key]
    try:
        import logging
        from logging.handlers import RotatingFileHandler

        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(f"nexadesk.telemetry.{key}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            logger.addHandler(handler)
        _loggers[key] = logger
        return logger
    except Exception:  # noqa: BLE001 — unwritable dir must never crash the agent
        _loggers[key] = None  # don't retry a broken path on every call
        return None


def log_event(event: str, **fields) -> None:
    """Append one JSON line; never raises."""
    if _disabled():
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
    }
    record.update(fields)
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — unserializable field, skip the line
        return
    logger = _logger_for(_log_file())
    if logger is None:
        return
    try:
        logger.info(line)
    except Exception:  # noqa: BLE001, S110 — best-effort by design
        pass
