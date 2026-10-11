import time

import pytest
from core.agent.cancellation import CancellationToken
from core.providers.base import ChatMessage, ProviderError
from core.providers.github import GitHubCopilotProvider


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code}")


class FakeSession:
    """Routes post/get by URL and records calls."""

    def __init__(self, token_response, chat_responses, models_response=None):
        self.token_response = token_response
        self.chat_responses = list(chat_responses)
        self.models_response = models_response
        self.token_calls = []
        self.chat_calls = []
        self.models_calls = []

    def post(self, url, json=None, timeout=None, headers=None):
        if url.endswith("/copilot_internal/v2/token"):
            self.token_calls.append({"headers": headers})
            return self.token_response
        self.chat_calls.append({"url": url, "json": json, "headers": headers})
        return self.chat_responses.pop(0)

    def get(self, url, timeout=None, headers=None):
        self.models_calls.append({"url": url, "headers": headers})
        return self.models_response


def _msgs():
    return [ChatMessage(role="user", content="hi")]


def _chat_ok(content="ok"):
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def _token(token="copilot-tok", ttl_s=1500):
    return FakeResponse({"token": token, "expires_at": time.time() + ttl_s})


def _provider(session):
    return GitHubCopilotProvider("ghp_pat", "gpt-4o", session=session)


def test_token_exchanged_once_and_reused():
    session = FakeSession(_token(), [_chat_ok(), _chat_ok()])
    p = _provider(session)
    p.complete(_msgs(), [], CancellationToken())
    p.complete(_msgs(), [], CancellationToken())
    assert len(session.token_calls) == 1
    assert session.chat_calls[0]["headers"]["Authorization"] == "Bearer copilot-tok"
    assert session.chat_calls[1]["headers"]["Authorization"] == "Bearer copilot-tok"


def test_chat_headers_include_editor_identity():
    session = FakeSession(_token(), [_chat_ok()])
    p = _provider(session)
    p.complete(_msgs(), [], CancellationToken())
    headers = session.chat_calls[0]["headers"]
    assert headers["Copilot-Integration-Id"] == "vscode-chat"
    assert "Editor-Version" in headers
    assert session.token_calls[0]["headers"]["Authorization"] == "Bearer ghp_pat"


def test_expired_token_is_reexchanged():
    session = FakeSession(
        _token(token="tok-old", ttl_s=10),  # inside the refresh margin
        [_chat_ok(), _chat_ok()],
    )
    # Second exchange returns a fresh token.
    exchanges = [_token(token="tok-old", ttl_s=10), _token(token="tok-new", ttl_s=1500)]
    session.token_responses = exchanges

    def post(url, json=None, timeout=None, headers=None):
        if url.endswith("/copilot_internal/v2/token"):
            session.token_calls.append({"headers": headers})
            return exchanges.pop(0)
        session.chat_calls.append({"url": url, "json": json, "headers": headers})
        return session.chat_responses.pop(0)

    session.post = post
    p = _provider(session)
    p.complete(_msgs(), [], CancellationToken())
    p.complete(_msgs(), [], CancellationToken())
    assert len(session.token_calls) == 2
    assert session.chat_calls[1]["headers"]["Authorization"] == "Bearer tok-new"


def test_token_exchange_failure_raises_missing_api_key():
    session = FakeSession(FakeResponse({}, status_code=403), [_chat_ok()])
    p = _provider(session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "missing_api_key"


def test_list_models_parses_catalog():
    session = FakeSession(
        _token(),
        [],
        models_response=FakeResponse(
            {"data": [{"id": "gpt-4o"}, {"id": "claude-sonnet-4.5"}]}
        ),
    )
    p = _provider(session)
    assert p.list_models() == ["claude-sonnet-4.5", "gpt-4o"]
    assert session.models_calls[0]["headers"]["Copilot-Integration-Id"] == "vscode-chat"


def test_list_models_accepts_bare_list():
    session = FakeSession(
        _token(),
        [],
        models_response=FakeResponse([{"id": "gpt-4o"}, {"id": "o4-mini"}]),
    )
    p = _provider(session)
    assert p.list_models() == ["gpt-4o", "o4-mini"]


def test_list_models_empty_on_http_error():
    session = FakeSession(
        _token(), [], models_response=FakeResponse({}, status_code=401)
    )
    p = _provider(session)
    assert p.list_models() == []
