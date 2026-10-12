"""Per-emotion pack building (F1): v2 manifest with 25 variants."""

import json

import pytest
from PIL import Image

from ui.avatar.manifest import REQUIRED_EMOTIONS, REQUIRED_STATES
from ui.avatar.pack import (
    PackError,
    build_pack,
    build_pack_from_emotion_images,
    build_pack_from_state_images,
)


def _solid(color):
    return Image.new("RGBA", (64, 64), color)


def _blob(color):
    """Background-colored canvas with a contrasting center block so the
    background-strip pipeline keeps a character-like component."""
    img = Image.new("RGBA", (64, 64), (250, 250, 250, 255))
    for y in range(20, 44):
        for x in range(20, 44):
            img.putpixel((x, y), color)
    return img


def _emotion_images():
    return {
        "neutral": _blob((255, 0, 0, 255)),
        "happy": _blob((0, 255, 0, 255)),
        "sad": _blob((0, 0, 255, 255)),
        "angry": _blob((255, 255, 0, 255)),
        "surprised": _blob((255, 0, 255, 255)),
    }


def test_requires_all_emotions(tmp_path):
    images = _emotion_images()
    del images["sad"]
    with pytest.raises(PackError, match="missing emotions"):
        build_pack_from_emotion_images(images, tmp_path / "pack", "p")


def test_existing_dir_untouched(tmp_path):
    out = tmp_path / "pack"
    out.mkdir()
    marker = out / "manifest.json"
    marker.write_text("{}")
    with pytest.raises(PackError, match="exists"):
        build_pack_from_emotion_images(_emotion_images(), out, "p")
    assert marker.read_text() == "{}"


def test_builds_25_variants_v2_manifest(tmp_path):
    out = tmp_path / "pack"
    result = build_pack_from_emotion_images(_emotion_images(), out, "My Pack")

    assert result == out
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["name"] == "my_pack"
    assert set(manifest["emotions"]) == set(REQUIRED_EMOTIONS)
    total = 0
    for emotion in REQUIRED_EMOTIONS:
        assert set(manifest["emotions"][emotion]) == set(REQUIRED_STATES)
        for state in REQUIRED_STATES:
            frames = manifest["emotions"][emotion][state]["frames"]
            assert frames
            assert all(rel.startswith(f"frames/{emotion}/") for rel in frames)
            for rel in frames:
                assert (out / rel).is_file()
            total += len(frames)
    assert total >= 25


def test_preprocess_off_keeps_colors(tmp_path):
    out = tmp_path / "pack"
    build_pack_from_emotion_images(_emotion_images(), out, "p", preprocess=False)
    manifest = json.loads((out / "manifest.json").read_text())
    happy_first = out / manifest["emotions"]["happy"]["idle"]["frames"][0]
    img = Image.open(happy_first).convert("RGBA")
    assert img.getpixel((img.width // 2, img.height // 2))[:3] == (0, 255, 0)


def test_classic_build_pack_still_emits_v1(tmp_path):
    src = tmp_path / "src.png"
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (10, 10, 200))
    img.save(src)
    out = tmp_path / "pack"
    build_pack(src, out, "classic")
    manifest = json.loads((out / "manifest.json").read_text())
    assert "states" in manifest
    assert "emotions" not in manifest


def test_state_image_builder_still_emits_v1(tmp_path):
    images = {s: _solid((0, 255, 0, 255)) for s in REQUIRED_STATES}
    out = tmp_path / "pack"
    build_pack_from_state_images(images, out, "p", preprocess=False)
    manifest = json.loads((out / "manifest.json").read_text())
    assert "states" in manifest
    assert "emotions" not in manifest
