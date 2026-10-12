import json
import pytest
import requests
from core.agent.cancellation import CancellationToken
from core.providers.base import ChatMessage, ProviderError
from core.providers.ollama import OllamaProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.posts = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.posts.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        if self.exc:
            raise self.exc
        return self.response


def _msgs():
    return [ChatMessage(role="user", content="hi")]


def test_ollama_parses_tool_call_dict_args():
    payload = {
        "message": {"tool_calls": [{"function": {"name": "echo", "arguments": {"x": 1}}}]},
        "done": True,
    }
    session = FakeSession(FakeResponse(payload))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.tool_calls[0].name == "echo"
    assert r.tool_calls[0].arguments == {"x": 1}
    assert r.tool_calls[0].id.startswith("ollama_")


def test_ollama_parses_tool_call_json_string_args():
    payload = {
        "message": {"tool_calls": [{"function": {"name": "echo", "arguments": '{"x": 1}'}}]},
        "done": True,
    }
    session = FakeSession(FakeResponse(payload))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.tool_calls[0].arguments == {"x": 1}


def test_ollama_parses_tool_call_embedded_in_content():
    # qwen-style: tool call JSON in content, no tool_calls field
    payload = {
        "message": {
            "role": "assistant",
            "content": '{"name": "screenshot", "arguments": {}}',
        },
        "done": True,
    }
    session = FakeSession(FakeResponse(payload))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    schemas = [{"name": "screenshot", "description": "d", "input_schema": {"type": "object"}}]
    r = p.complete(_msgs(), schemas, CancellationToken())
    assert r.tool_calls[0].name == "screenshot"
    assert r.tool_calls[0].arguments == {}
    assert r.text is None


def test_ollama_malformed_response_shape_maps_provider_error():
    session = FakeSession(FakeResponse({"message": "not-an-object"}))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "provider_error"


def test_ollama_native_invalid_json_sets_parse_error():
    payload = {
        "message": {"tool_calls": [{"function": {"name": "echo", "arguments": "{bad"}}]},
        "done": True,
    }
    session = FakeSession(FakeResponse(payload))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.tool_calls[0].parse_error is not None
    assert r.tool_calls[0].arguments == {}


def test_ollama_http_timeout_maps_error_code():
    session = FakeSession(exc=requests.Timeout("boom"))
    p = OllamaProvider("http://127.0.0.1:11434", "m", timeout_s=7.0, session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "timeout"
    assert session.posts[0]["timeout"] == 7.0


def test_ollama_http_error_maps_provider_error():
    session = FakeSession(FakeResponse({}, status_code=500))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "provider_error"


def test_ollama_list_models_parses_tags():
    class S:
        def get(self, url, timeout=None, headers=None):
            self.url = url
            return FakeResponse(
                {"models": [{"name": "llama3:8b"}, {"name": "qwen:4b"}]}
            )

    s = S()
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=s)
    assert p.list_models() == ["llama3:8b", "qwen:4b"]
    assert s.url == "http://127.0.0.1:11434/api/tags"


def test_ollama_tool_call_ids_unique_across_calls():
    # B36: "ollama_{i}" collides across turns (history replays duplicate ids).
    payload = {
        "message": {"tool_calls": [{"function": {"name": "echo", "arguments": {}}}]},
        "done": True,
    }
    session = FakeSession(FakeResponse(payload))
    p = OllamaProvider("http://127.0.0.1:11434", "m", session=session)
    r1 = p.complete(_msgs(), [], CancellationToken())
    r2 = p.complete(_msgs(), [], CancellationToken())
    assert r1.tool_calls[0].id != r2.tool_calls[0].id
    assert r1.tool_calls[0].id
