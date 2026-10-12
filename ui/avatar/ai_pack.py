"""AI emotion-still pack orchestration for F1.

The configured image model produces one identity-preserving still per pack
emotion (fixed English prompts — no user-editable prompt text anywhere), and
the existing transform pipeline expands each still into the five state
animations (25 variants total). Providers without image models never reach
this module; the AI-less pack builder in Settings stays available as the
fallback.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from ui.avatar.pack import PackError, build_pack_from_emotion_images

IDENTITY_BLOCK = (
    "Recreate this exact character from the photo — same face, hair, colors, "
    "outfit, and art style. Do not redesign, do not add or remove elements. "
    "Neutral flat background. Character centered, full upper body visible."
)

EMOTION_PROMPTS: dict[str, str] = {
    "neutral": "Calm and neutral, relaxed expression.",
    "happy": "Happy and cheerful, smiling expression.",
    "sad": "Sad and downcast, melancholic expression.",
    "angry": "Angry and annoyed, frowning expression.",
    "surprised": "Surprised and wide-eyed, startled expression.",
}


class AiPackCancelled(Exception):
    """User cancelled the AI pack build."""


def emotion_prompt(emotion: str) -> str:
    """Full prompt for one pack emotion: identity block + emotion clause."""
    return f"{IDENTITY_BLOCK}\n\n{EMOTION_PROMPTS[emotion]}"


def build_ai_pack(
    photo: Path,
    out_dir: Path,
    name: str,
    generate,
    *,
    progress=None,
    cancelled=None,
) -> Path:
    """Generate one still per emotion, then build the animated v2 pack.

    ``generate(emotion, prompt) -> bytes`` is injected (the ImageGenClient
    closure lives on the UI side). ``progress(emotion, index, total)`` runs
    before each generation; ``cancelled() -> bool`` is polled before each
    one. Any failure or cancellation leaves no pack directory behind.
    """
    emotions = tuple(EMOTION_PROMPTS)
    total = len(emotions)
    # Fail fast on collision: never touch a directory this run did not create.
    if out_dir.exists():
        raise PackError(f"exists: {out_dir}")
    emotion_images: dict[str, Image.Image] = {}
    for index, emotion in enumerate(emotions, start=1):
        if cancelled is not None and cancelled():
            _cleanup(out_dir)
            raise AiPackCancelled()
        if progress is not None:
            progress(emotion, index, total)
        try:
            raw = generate(emotion, emotion_prompt(emotion))
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
        emotion_images[emotion] = img
    try:
        return build_pack_from_emotion_images(emotion_images, out_dir, name)
    except Exception:
        _cleanup(out_dir)
        raise


def _cleanup(out_dir: Path) -> None:
    """Best-effort removal of a partially built pack directory."""
    import shutil

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
