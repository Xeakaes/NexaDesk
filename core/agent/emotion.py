"""Classify an assistant reply into one avatar emotion (F1).

Best-effort and side-effect free: any failure (provider error, empty text,
cancellation) resolves to "neutral" so the avatar can always render.
"""

from __future__ import annotations

from core.agent.cancellation import CancellationToken
from core.providers.base import ChatMessage, ModelProvider

EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised")

_SYSTEM_PROMPT = (
    "Classify the assistant reply into exactly one word: "
    "neutral, happy, sad, angry, or surprised. "
    "Answer with that single word only."
)


def classify_emotion(
    provider: ModelProvider, text: str, cancel: CancellationToken
) -> str:
    """Return one of EMOTIONS; never raises."""
    if cancel.cancelled:
        return "neutral"
    if not text or not text.strip():
        return "neutral"
    try:
        response = provider.complete(
            [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=text),
            ],
            [],
            cancel,
        )
    except Exception:
        return "neutral"
    if cancel.cancelled:
        return "neutral"
    if not response.text:
        return "neutral"
    for token in response.text.strip().split():
        word = token.strip(".,!?:;\"'()[]{}").lower()
        if word in EMOTIONS:
            return word
    return "neutral"
