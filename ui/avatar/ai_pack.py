"""AI emotion-set pack orchestration for F2.

The configured image model produces one identity-preserving still per pack
state (fixed English prompts — no user-editable prompt text anywhere), and
the existing transform pipeline completes the animated work set. Providers
without image models never reach this module; the AI-less pack builder in
Settings stays available as the fallback.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from ui.avatar.pack import PackError, build_pack_from_state_images

IDENTITY_BLOCK = (
    "Recreate this exact character from the photo — same face, hair, colors, "
    "outfit, and art style. Do not redesign, do not add or remove elements. "
    "Neutral flat background. Character centered, full upper body visible."
)

EMOTION_PROMPTS: dict[str, str] = {
    "idle": "Calm and neutral, relaxed expression.",
    "thinking": "Pensive, looking slightly upward as if thinking.",
    "working": "Focused and busy, determined expression.",
    "speaking": "Cheerful and talkative, mid-conversation expression.",
    "error": "Surprised or alarmed, wide-eyed reaction.",
}


class AiPackCancelled(Exception):
    """User cancelled the AI pack build."""


def emotion_prompt(state: str) -> str:
    """Full prompt for one pack state: identity block + emotion clause."""
    return f"{IDENTITY_BLOCK}\n\n{EMOTION_PROMPTS[state]}"


def build_ai_pack(
    photo: Path,
    out_dir: Path,
    name: str,
    generate,
    *,
    progress=None,
    cancelled=None,
) -> Path:
    """Generate one still per state, then build the animated pack.

    ``generate(state, prompt) -> bytes`` is injected (the ImageGenClient
    closure lives on the UI side). ``progress(state, index, total)`` runs
    before each generation; ``cancelled() -> bool`` is polled before each
    one. Any failure or cancellation leaves no pack directory behind.
    """
    states = tuple(EMOTION_PROMPTS)
    total = len(states)
    # Fail fast on collision: never touch a directory this run did not create.
    if out_dir.exists():
        raise PackError(f"exists: {out_dir}")
    state_images: dict[str, Image.Image] = {}
    for index, state in enumerate(states, start=1):
        if cancelled is not None and cancelled():
            _cleanup(out_dir)
            raise AiPackCancelled()
        if progress is not None:
            progress(state, index, total)
        try:
            raw = generate(state, emotion_prompt(state))
            img = Image.open(io.BytesIO(raw))
            img.load()
        except AiPackCancelled:
            _cleanup(out_dir)
            raise
        except PackError:
            raise
        except Exception:
            _cleanup(out_dir)
            raise
        state_images[state] = img
    try:
        return build_pack_from_state_images(state_images, out_dir, name)
    except Exception:
        _cleanup(out_dir)
        raise


def _cleanup(out_dir: Path) -> None:
    """Best-effort removal of a partially built pack directory."""
    import shutil

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
