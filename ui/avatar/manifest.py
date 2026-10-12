"""Pure-Python loader for avatar manifest.json (spec §4.1).

v1 manifests carry a top-level ``states`` object and load as a single
neutral emotion. v2 manifests carry ``emotions`` mapping each of
``REQUIRED_EMOTIONS`` to a full state set (F1 emotion axis).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED_STATES = ("idle", "thinking", "working", "speaking", "error")
REQUIRED_EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class StateAnim:
    frames: tuple[str, ...]
    fps: float
    loop: bool


@dataclass(frozen=True)
class Manifest:
    emotions: dict[str, dict[str, StateAnim]]

    @property
    def states(self) -> dict[str, StateAnim]:
        return self.emotions["neutral"]


def _parse_states(states: dict, base: Path) -> dict[str, StateAnim]:
    out: dict[str, StateAnim] = {}
    for name in REQUIRED_STATES:
        if name not in states:
            raise ManifestError(f"missing state: {name}")
        raw = states[name]
        frames = raw.get("frames") or []
        if not frames:
            raise ManifestError(f"state {name}: frames must be non-empty")
        fps = raw.get("fps", 0)
        try:
            fps = float(fps)
        except (TypeError, ValueError):
            fps = 0.0
        if fps <= 0:
            raise ManifestError(f"state {name}: fps must be > 0")
        out[name] = StateAnim(
            frames=tuple(str(base / f) for f in frames),
            fps=fps,
            loop=bool(raw.get("loop", True)),
        )
    return out


def _validate_files(manifest: Manifest) -> None:
    """Raise ManifestError when any listed frame file is missing (B46)."""
    for emotion, states in manifest.emotions.items():
        for state, anim in states.items():
            for frame in anim.frames:
                if not Path(frame).is_file():
                    raise ManifestError(
                        f"missing frame: {emotion}/{state}: {frame}"
                    )


def load_manifest(path: Path, validate_files: bool = False) -> Manifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    base = path.parent
    emotions_raw = data.get("emotions")
    if emotions_raw is None:
        states = data.get("states")
        if not isinstance(states, dict):
            raise ManifestError("manifest must contain a 'states' object")
        manifest = Manifest(emotions={"neutral": _parse_states(states, base)})
    else:
        if not isinstance(emotions_raw, dict):
            raise ManifestError("manifest 'emotions' must be an object")
        for name in REQUIRED_EMOTIONS:
            if name not in emotions_raw:
                raise ManifestError(f"missing emotion: {name}")
        for name in emotions_raw:
            if name not in REQUIRED_EMOTIONS:
                raise ManifestError(f"unknown emotion: {name}")
        emotions = {
            name: _parse_states(emotions_raw[name], base)
            for name in REQUIRED_EMOTIONS
        }
        manifest = Manifest(emotions=emotions)
    if validate_files:
        _validate_files(manifest)
    return manifest
