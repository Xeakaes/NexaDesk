import json
from pathlib import Path

import pytest

from ui.avatar.pack import PackError, build_pack, delete_pack, sanitize_pack_name

MIKU = Path("/home/xeakaes/İndirilenler/Miku pixel art!.jpeg")
REQUIRED = {"idle", "thinking", "working", "speaking", "error"}


def test_build_pack_produces_five_states(tmp_path):
    if not MIKU.exists():
        pytest.skip("source image not available")
    out = tmp_path / "miku"
    result = build_pack(MIKU, out, "miku")
    assert result == out
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["states"]) == REQUIRED
    for state in manifest["states"].values():
        for rel in state["frames"]:
            assert (out / rel).exists()


def test_build_pack_existing_dir_raises(tmp_path):
    out = tmp_path / "x"
    out.mkdir()
    with pytest.raises(PackError, match="exists"):
        build_pack(MIKU if MIKU.exists() else tmp_path, out, "x")


def test_build_pack_corrupt_image_raises(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image at all")
    with pytest.raises(PackError):
        build_pack(bad, tmp_path / "out", "badpack")


def test_sanitize_pack_name():
    assert sanitize_pack_name("Miku Pixel Art!") == "miku_pixel_art"
    assert sanitize_pack_name("  Hello--World  ") == "hello_world"
    with pytest.raises(PackError):
        sanitize_pack_name("!!!")


def test_build_pack_predownscales_large_source(tmp_path):
    """A big source image must be pre-scaled to <=512px before the pipeline.

    This keeps the flood-fill background removal fast on large photos.
    """
    from PIL import Image

    src = tmp_path / "big.png"
    # 2000x2000 with a distinct foreground block.
    img = Image.new("RGB", (2000, 2000), (255, 255, 255))
    for x in range(800, 1200):
        for y in range(800, 1200):
            img.putpixel((x, y), (30, 30, 200))
    img.save(src)

    out = tmp_path / "bigpack"
    build_pack(src, out, "bigpack")
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["states"]) == REQUIRED
    # Frames must still be produced and each frame's height is TARGET_H (192).
    frame_path = out / manifest["states"]["idle"]["frames"][0]
    with Image.open(frame_path) as frame:
        assert frame.height == 192


def _make_pack(root: Path, name: str) -> Path:
    pack = root / name
    (pack / "frames").mkdir(parents=True)
    (pack / "manifest.json").write_text(json.dumps({"name": name, "states": {}}))
    return pack


def test_delete_pack_removes_directory(tmp_path):
    pack = _make_pack(tmp_path, "teto")
    delete_pack(tmp_path, "teto")
    assert not pack.exists()


def test_delete_pack_missing_raises(tmp_path):
    with pytest.raises(PackError, match="not found"):
        delete_pack(tmp_path, "ghost")


def test_delete_pack_never_deletes_base(tmp_path):
    base = _make_pack(tmp_path, "base")
    with pytest.raises(PackError, match="built-in"):
        delete_pack(tmp_path, "base")
    assert base.exists()


def test_delete_pack_rejects_non_pack_dir(tmp_path):
    plain = tmp_path / "notapack"
    plain.mkdir()
    with pytest.raises(PackError, match="not a pack"):
        delete_pack(tmp_path, "notapack")
    assert plain.exists()


def test_delete_pack_rejects_path_traversal(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    with pytest.raises(PackError):
        delete_pack(avatars, "../outside")
    with pytest.raises(PackError):
        delete_pack(avatars, "..")
    assert outside.exists()


def test_build_pack_empty_after_background_removal(tmp_path):
    from PIL import Image

    src = tmp_path / "empty.png"
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(src)
    with pytest.raises(PackError, match="empty after background removal"):
        build_pack(src, tmp_path / "emptypack", "emptypack")


def test_build_pack_pipeline_failure_wrapped(tmp_path, monkeypatch):
    import ui.avatar.pack as pack_mod
    from PIL import Image

    src = tmp_path / "ok.png"
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(20, 40):
        for y in range(20, 40):
            img.putpixel((x, y), (10, 10, 200))
    img.save(src)

    def boom(*a, **k):
        raise ValueError("disk on fire")

    monkeypatch.setattr(pack_mod, "crop_pad_resize", boom)
    with pytest.raises(PackError, match="pipeline failed"):
        build_pack(src, tmp_path / "failpack", "failpack")
