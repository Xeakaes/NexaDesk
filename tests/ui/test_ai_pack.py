"""AI emotion-still pack orchestration (F1): emotion prompts + cleanup."""

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
from ui.avatar.manifest import REQUIRED_EMOTIONS


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
    assert set(EMOTION_PROMPTS) == set(REQUIRED_EMOTIONS)
    assert all(EMOTION_PROMPTS[s].strip() for s in REQUIRED_EMOTIONS)
    assert emotion_prompt("happy").startswith(IDENTITY_BLOCK)
    with pytest.raises(KeyError):
        emotion_prompt("bogus")


def test_build_ai_pack_generates_five_emotions_and_builds_v2(tmp_path):
    calls = []
    progress = []

    def generate(emotion, prompt):
        calls.append((emotion, prompt))
        return _png_bytes()

    out = tmp_path / "pack"
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    result = build_ai_pack(
        photo, out, "My Avatar", generate,
        progress=lambda s, i, n: progress.append((s, i, n)),
    )

    assert result == out
    assert [c[0] for c in calls] == list(REQUIRED_EMOTIONS)
    assert progress == [
        ("neutral", 1, 5), ("happy", 2, 5), ("sad", 3, 5),
        ("angry", 4, 5), ("surprised", 5, 5),
    ]
    import json

    manifest = json.loads((out / "manifest.json").read_text())
    assert "emotions" in manifest
    assert set(manifest["emotions"]) == set(REQUIRED_EMOTIONS)


def test_build_ai_pack_cleans_up_on_cancel(tmp_path):
    calls = {"n": 0}

    def generate(emotion, prompt):
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
    def generate(emotion, prompt):
        if emotion == "sad":
            raise RuntimeError("rate limited")
        return _png_bytes()

    out = tmp_path / "pack"
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    with pytest.raises(RuntimeError, match="rate limited"):
        build_ai_pack(photo, out, "pack", generate)

    assert not out.exists()


def test_build_ai_pack_never_deletes_preexisting_dir(tmp_path):
    # Review Critical #1: an out_dir that already exists (user's pack) must
    # fail fast and stay untouched — no cleanup, no wasted generations.
    from ui.avatar.pack import PackError

    out = tmp_path / "pack"
    out.mkdir()
    marker = out / "manifest.json"
    marker.write_text("{}")
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())

    calls = []

    def generate(emotion, prompt):
        calls.append(emotion)
        return _png_bytes()

    with pytest.raises(PackError):
        build_ai_pack(photo, out, "pack", generate)

    assert calls == []
    assert marker.exists()


def test_pack_workers_hand_results_via_queue_not_signals(tmp_path):
    # Backlog 2 / B61 parity: cross-thread signal emits from pack workers
    # are the same segfault class the model-fetch workers had — results must
    # ride a SimpleQueue drained on the UI thread.
    import threading
    from pathlib import Path

    from PIL import Image

    from ui.settings import _AiPackWorker, _PackBuildWorker

    src = tmp_path / "photo.png"
    # solid fills get wiped by background removal; use a noisy image that
    # survives the pipeline
    import random

    random.seed(0)
    img = Image.new("RGB", (64, 64))
    img.putdata(
        [(random.randint(40, 220), random.randint(40, 220), random.randint(40, 220))
         for _ in range(64 * 64)]
    )
    img.save(src)
    out = tmp_path / "packs" / "p1"

    w = _PackBuildWorker(Path(src), out, "p1")
    assert not hasattr(w, "signals") or w.signals is None, (
        "pack worker must not emit cross-thread signals"
    )
    assert hasattr(w, "take"), "pack worker must expose take() for UI drain"
    w.start()
    assert w.wait(5000), "pack worker did not finish"
    assert w.done
    item = w.take()
    assert item[0] == "succeeded", item

    # AI worker: same contract, plus a progress queue drained on the UI thread.
    import io

    def _png_bytes() -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    class FakeClient:
        def generate(self, model, prompt, photo=None):
            return _png_bytes()

    ai_out = tmp_path / "packs" / "p2"
    aw = _AiPackWorker(Path(src), ai_out, "p2", "m", FakeClient())
    assert not hasattr(aw, "signals") or aw.signals is None
    assert hasattr(aw, "take"), "AI worker must expose take() for UI drain"
    aw.start()
    assert aw.wait(10000), "AI worker did not finish"
    assert aw.done
    # drain until terminal
    terminal = None
    while True:
        item = aw.take()
        if item[0] in ("succeeded", "failed", "cancelled"):
            terminal = item
            break
    assert terminal[0] == "succeeded", terminal
