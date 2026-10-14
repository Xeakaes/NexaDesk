"""Per-state pack building (F2): distinct base images per emotion state."""

import json

import pytest
from PIL import Image

from ui.avatar.manifest import REQUIRED_STATES
from ui.avatar.pack import PackError, build_pack_from_state_images


def _solid(color):
    return Image.new("RGBA", (64, 64), color)


def test_build_pack_from_state_images_requires_all_states(tmp_path):
    images = {s: _solid((0, 255, 0, 255)) for s in REQUIRED_STATES if s != "error"}
    with pytest.raises(PackError):
        build_pack_from_state_images(images, tmp_path / "pack", "p")


def test_build_pack_from_state_images_writes_distinct_states(tmp_path):
    images = {
        "idle": _solid((255, 0, 0, 255)),
        "thinking": _solid((0, 0, 255, 255)),
        "working": _solid((0, 255, 0, 255)),
        "speaking": _solid((255, 255, 0, 255)),
        "error": _solid((0, 255, 255, 255)),
    }
    out = tmp_path / "pack"
    result = build_pack_from_state_images(images, out, "my pack", preprocess=False)

    assert result == out
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["states"]) == set(REQUIRED_STATES)
    assert manifest["name"] == "my_pack"
    for state in REQUIRED_STATES:
        frames = manifest["states"][state]["frames"]
        assert frames
        for rel in frames:
            assert (out / rel).is_file()

    idle = Image.open(out / manifest["states"]["idle"]["frames"][0]).convert("RGBA")
    thinking = Image.open(out / manifest["states"]["thinking"]["frames"][0]).convert("RGBA")
    assert idle.getpixel((idle.width // 2, idle.height // 2))[:3] == (255, 0, 0)
    assert thinking.getpixel((thinking.width // 2, thinking.height // 2))[:3] == (0, 0, 255)


def test_base_frames_have_no_exact_duplicates():
    # B-ek: the bundled base pack shipped 9 byte-identical PNG twins —
    # dead weight in every artifact.
    import hashlib

    from core.paths import assets_dir

    frames = sorted((assets_dir() / "avatars" / "base" / "frames").glob("*.png"))
    assert frames, "base pack must ship frames"
    by_hash: dict[str, list] = {}
    for p in frames:
        h = hashlib.md5(p.read_bytes()).hexdigest()
        by_hash.setdefault(h, []).append(p.name)
    dupes = {h: names for h, names in by_hash.items() if len(names) > 1}
    assert not dupes, f"duplicate frame files: {dupes}"
