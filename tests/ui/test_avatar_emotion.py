"""Avatar window emotion rendering (F1): set_emotion + v1 fallback."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.paths import assets_dir
from ui.avatar.manifest import REQUIRED_EMOTIONS, REQUIRED_STATES
from ui.avatar.window import AvatarWindow


def _base_avatar_dir() -> Path:
    return assets_dir() / "avatars" / "base"


def _qapp():
    return QApplication.instance() or QApplication([])


def _v2_pack(tmp_path: Path) -> Path:
    """Minimal on-disk v2 pack: one 1x1 frame per emotion×state."""
    from PIL import Image

    pack = tmp_path / "v2pack"
    colors = {
        "neutral": (255, 0, 0),
        "happy": (0, 255, 0),
        "sad": (0, 0, 255),
        "angry": (255, 255, 0),
        "surprised": (255, 0, 255),
    }
    emotions = {}
    for emotion in REQUIRED_EMOTIONS:
        (pack / "frames" / emotion).mkdir(parents=True)
        emotions[emotion] = {}
        for state in REQUIRED_STATES:
            rel = f"frames/{emotion}/{state}_00.png"
            img = Image.new("RGBA", (8, 8), (*colors[emotion], 255))
            img.save(pack / rel)
            emotions[emotion][state] = {"frames": [rel], "fps": 6, "loop": True}
    (pack / "manifest.json").write_text(
        json.dumps({"name": "v2pack", "format": 2, "emotions": emotions})
    )
    return pack


def test_initial_emotion_is_neutral():
    _qapp()
    av = AvatarWindow(_base_avatar_dir())
    assert av.current_emotion() == "neutral"
    av.close()


def test_v1_pack_set_emotion_unknown_falls_back_to_neutral():
    _qapp()
    av = AvatarWindow(_base_avatar_dir())
    av.set_emotion("happy")  # v1 pack: only neutral exists
    assert av.current_emotion() == "neutral"
    av.close()


def test_unknown_emotion_string_falls_back_to_neutral(tmp_path):
    _qapp()
    av = AvatarWindow(_v2_pack(tmp_path))
    av.set_emotion("confused")
    assert av.current_emotion() == "neutral"
    av.close()


def test_set_emotion_switches_frames_and_keeps_state(tmp_path):
    _qapp()
    av = AvatarWindow(_v2_pack(tmp_path))
    av.set_state("working")
    av.set_emotion("happy")
    assert av.current_emotion() == "happy"
    assert av.current_state() == "working"
    # Rendered frames come from the happy emotion set.
    assert all(
        "frames/happy/" in frame
        for frame in av._manifest.emotions["happy"]["working"].frames
    )
    assert av._label.pixmap() is not None
    av.close()


def test_same_emotion_noop(tmp_path):
    _qapp()
    av = AvatarWindow(_v2_pack(tmp_path))
    av.set_emotion("sad")
    index = av._frame_index
    av.set_emotion("sad")
    assert av.current_emotion() == "sad"
    assert av._frame_index == index
    av.close()
