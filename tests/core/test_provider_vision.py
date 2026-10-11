"""Provider wire-format tests for vision images (Task 2)."""

from __future__ import annotations

from core.providers.base import ChatMessage


def test_openai_compat_serializes_images():
    from core.providers.openai_compatible import serialize_messages

    msgs = [ChatMessage(role="user", content="look", images=["data:image/jpeg;base64,AAA"])]
    wire = serialize_messages(msgs)
    content = wire[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,AAA"


def test_openai_compat_plain_when_no_images():
    from core.providers.openai_compatible import serialize_messages

    msgs = [ChatMessage(role="user", content="hello")]
    wire = serialize_messages(msgs)
    assert wire[0]["content"] == "hello"  # unchanged string form


def test_ollama_serializes_images():
    from core.providers.ollama import serialize_messages

    msgs = [ChatMessage(role="user", content="look", images=["data:image/jpeg;base64,AAA"])]
    wire = serialize_messages(msgs)
    # Ollama expects a raw base64 list (no data: prefix).
    assert wire[0]["images"] == ["AAA"]


def test_ollama_plain_when_no_images():
    from core.providers.ollama import serialize_messages

    msgs = [ChatMessage(role="user", content="hello")]
    wire = serialize_messages(msgs)
    assert wire[0]["content"] == "hello"
    assert "images" not in wire[0]


def test_providers_flag_supports_vision():
    from core.providers.ollama import OllamaProvider
    from core.providers.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider.supports_vision is True
    assert OllamaProvider.supports_vision is True
