"""AI emotion-set pack orchestration (F2): fixed prompts + cleanup."""

import base64
import io

import pytest
from PIL import Image

from ui.avatar.ai_pack import (
    AiPackCancelled,
    EMOTION_PROMPTS,
    IDENTITY_BLOCK,
    build_ai_pack,
    emotion_prompt,
)
from ui.avatar.manifest import REQUIRED_STATES


@pytest.fixture(autouse=True)
def _telemetry_off(monkeypatch):
    monkeypatch.setenv("NEXADESK_TELEMETRY", "off")


def _png_bytes(color=(40, 40, 40, 255)):
    # Background-colored canvas with a contrasting center blob, so the
    # background-strip pipeline keeps a character-like component.
    buf = io.BytesIO()
    img = Image.new("RGBA", (64, 64), (250, 250, 250, 255))
    for y in range(20, 44):
        for x in range(20, 44):
            img.putpixel((x, y), color)
    img.save(buf, "PNG")
    return buf.getvalue()


def test_prompt_contract():
    assert set(EMOTION_PROMPTS) == set(REQUIRED_STATES)
    assert all(EMOTION_PROMPTS[s].strip() for s in REQUIRED_STATES)
    assert emotion_prompt("idle").startswith(IDENTITY_BLOCK)
    with pytest.raises(KeyError):
        emotion_prompt("bogus")


def test_build_ai_pack_generates_five_and_builds(tmp_path):
    calls = []
    progress = []

    def generate(state, prompt):
        calls.append((state, prompt))
        return _png_bytes()

    out = tmp_path / "pack"
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    result = build_ai_pack(
        photo, out, "My Avatar", generate,
        progress=lambda s, i, n: progress.append((s, i, n)),
    )

    assert result == out
    assert [c[0] for c in calls] == ["idle", "thinking", "working", "speaking", "error"]
    assert progress == [
        ("idle", 1, 5), ("thinking", 2, 5), ("working", 3, 5),
        ("speaking", 4, 5), ("error", 5, 5),
    ]
    assert (out / "manifest.json").is_file()


def test_build_ai_pack_cleans_up_on_cancel(tmp_path):
    calls = {"n": 0}

    def generate(state, prompt):
        calls["n"] += 1
        return _png_bytes()

    out = tmp_path / "pack"
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    with pytest.raises(AiPackCancelled):
        build_ai_pack(
            photo, out, "pack", generate,
            cancelled=lambda: calls["n"] >= 2,
        )

    assert not out.exists()


def test_build_ai_pack_cleans_up_on_generator_failure(tmp_path):
    def generate(state, prompt):
        if state == "working":
            raise RuntimeError("rate limited")
        return _png_bytes()

    out = tmp_path / "pack"
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    with pytest.raises(RuntimeError, match="rate limited"):
        build_ai_pack(photo, out, "pack", generate)

    assert not out.exists()
