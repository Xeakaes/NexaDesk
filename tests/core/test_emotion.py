"""Tests for the reply→emotion classifier (F1)."""

from __future__ import annotations

import pytest

from core.agent.cancellation import CancellationToken
from core.providers.base import ProviderError, ProviderResponse
from tests.fakes import FakeProvider


def _cancelled() -> CancellationToken:
    token = CancellationToken()
    token.cancel()
    return token


def test_emotions_constant():
    from core.agent.emotion import EMOTIONS

    assert EMOTIONS == ("neutral", "happy", "sad", "angry", "surprised")


def test_single_word_happy():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="happy")])
    assert classify_emotion(provider, "Done!", CancellationToken()) == "happy"
    assert len(provider.calls) == 1
    assert provider.calls[0].schemas == []


def test_extracts_word_from_sentence():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="Sure! Here you go: happy")])
    assert classify_emotion(provider, "thanks", CancellationToken()) == "happy"


def test_case_insensitive():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="  HAPPY  \n")])
    assert classify_emotion(provider, "x", CancellationToken()) == "happy"


def test_garbage_falls_back_to_neutral():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="banana-split")])
    assert classify_emotion(provider, "x", CancellationToken()) == "neutral"


def test_none_text_response_falls_back_to_neutral():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text=None)])
    assert classify_emotion(provider, "x", CancellationToken()) == "neutral"


def test_provider_error_falls_back_to_neutral():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderError("boom")])
    assert classify_emotion(provider, "x", CancellationToken()) == "neutral"


def test_cancelled_token_skips_provider_call():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="happy")])
    assert classify_emotion(provider, "x", _cancelled()) == "neutral"
    assert provider.calls == []


def test_provider_receives_system_and_user_messages():
    from core.agent.emotion import classify_emotion

    provider = FakeProvider([ProviderResponse(text="sad")])
    classify_emotion(provider, "I broke it", CancellationToken())
    messages = provider.calls[0].messages
    assert [m.role for m in messages] == ["system", "user"]
    assert messages[1].content == "I broke it"
    assert "sad" in messages[0].content
