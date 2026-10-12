from pathlib import Path

import pytest

from ui.avatar.manifest import (
    REQUIRED_EMOTIONS,
    REQUIRED_STATES,
    ManifestError,
    load_manifest,
)

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "avatars" / "base"


def _state(fps: float = 6.0) -> dict:
    return {"frames": ["f.png"], "fps": fps, "loop": True}


def _states() -> dict:
    return {name: _state() for name in REQUIRED_STATES}


def _v1_manifest(states: dict) -> str:
    import json

    return json.dumps({"name": "x", "states": states})


def _v2_manifest(emotions: dict) -> str:
    import json

    return json.dumps({"name": "x", "format": 2, "emotions": emotions})


def _v2_full() -> dict:
    return {emotion: _states() for emotion in REQUIRED_EMOTIONS}


def test_real_manifest_loads():
    manifest = load_manifest(ASSETS / "manifest.json")
    assert set(manifest.states) == set(REQUIRED_STATES)
    assert all(s.frames and s.fps > 0 for s in manifest.states.values())
    assert all(
        (ASSETS / f).exists() for s in manifest.states.values() for f in s.frames
    )
    assert set(manifest.emotions) == {"neutral"}


def test_v1_wraps_as_neutral(tmp_path):
    (tmp_path / "manifest.json").write_text(_v1_manifest(_states()))
    manifest = load_manifest(tmp_path / "manifest.json")
    assert set(manifest.emotions) == {"neutral"}
    assert manifest.states == manifest.emotions["neutral"]
    assert set(manifest.states) == set(REQUIRED_STATES)


def test_v2_full_pack_loads(tmp_path):
    (tmp_path / "manifest.json").write_text(_v2_manifest(_v2_full()))
    manifest = load_manifest(tmp_path / "manifest.json")
    assert set(manifest.emotions) == set(REQUIRED_EMOTIONS)
    for emotion_states in manifest.emotions.values():
        assert set(emotion_states) == set(REQUIRED_STATES)
    assert manifest.states == manifest.emotions["neutral"]


def test_v2_missing_emotion_raises(tmp_path):
    emotions = _v2_full()
    del emotions["surprised"]
    (tmp_path / "manifest.json").write_text(_v2_manifest(emotions))
    with pytest.raises(ManifestError, match="missing emotion"):
        load_manifest(tmp_path / "manifest.json")


def test_v2_unknown_emotion_key_raises(tmp_path):
    emotions = _v2_full()
    emotions["confused"] = _states()
    (tmp_path / "manifest.json").write_text(_v2_manifest(emotions))
    with pytest.raises(ManifestError, match="unknown emotion"):
        load_manifest(tmp_path / "manifest.json")


def test_v2_missing_state_in_emotion_raises(tmp_path):
    emotions = _v2_full()
    del emotions["happy"]["working"]
    (tmp_path / "manifest.json").write_text(_v2_manifest(emotions))
    with pytest.raises(ManifestError, match="missing state"):
        load_manifest(tmp_path / "manifest.json")


def test_manifest_missing_state_raises(tmp_path):
    (tmp_path / "manifest.json").write_text(_v1_manifest({}))
    with pytest.raises(ManifestError, match="missing state"):
        load_manifest(tmp_path / "manifest.json")


def test_manifest_empty_frames_raises(tmp_path):
    states = _states()
    states["idle"] = {"frames": [], "fps": 6, "loop": True}
    (tmp_path / "manifest.json").write_text(_v1_manifest(states))
    with pytest.raises(ManifestError, match="frames"):
        load_manifest(tmp_path / "manifest.json")


def test_manifest_bad_fps_raises(tmp_path):
    states = _states()
    states["idle"] = _state(fps=0)
    (tmp_path / "manifest.json").write_text(_v1_manifest(states))
    with pytest.raises(ManifestError, match="fps"):
        load_manifest(tmp_path / "manifest.json")


def test_emotions_constant():
    assert REQUIRED_EMOTIONS == (
        "neutral",
        "happy",
        "sad",
        "angry",
        "surprised",
    )
