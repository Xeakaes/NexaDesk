import json
import pytest
import requests
from core.agent.cancellation import CancellationToken
from core.providers.base import ChatMessage, ProviderError
from core.providers.openai_compat import OpenAICompatProvider


class FakeResponse:
    def __init__(self, payload, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text else json.dumps(payload)
        self.headers = headers or {}

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


def _payload(content=None, tool_calls=None):
    message = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def test_openai_parses_tool_call_json_string_args():
    wire_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "echo", "arguments": json.dumps({"x": 1})},
    }]
    session = FakeSession(FakeResponse(_payload(tool_calls=wire_calls)))
    p = OpenAICompatProvider("http://api", "key", "model", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.tool_calls[0].id == "call_1"
    assert r.tool_calls[0].name == "echo"
    assert r.tool_calls[0].arguments == {"x": 1}
    assert session.posts[0]["headers"]["Authorization"] == "Bearer key"


def test_openai_parses_content_text():
    session = FakeSession(FakeResponse(_payload(content="Merhaba")))
    p = OpenAICompatProvider("http://api", "key", "model", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.text == "Merhaba" and r.tool_calls == []


def test_openai_http_timeout_maps_error_code():
    session = FakeSession(exc=requests.Timeout("boom"))
    p = OpenAICompatProvider("http://api", "key", "model", timeout_s=9.0, session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "timeout"
    assert session.posts[0]["timeout"] == 9.0


def test_openai_http_error_maps_provider_error():
    session = FakeSession(FakeResponse({}, status_code=500))
    p = OpenAICompatProvider("http://api", "key", "model", session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "provider_error"


class ScriptedSession:
    """Returns each queued response/exc in order and records posts."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.posts = []

    def post(self, url, json=None, timeout=None, headers=None):
        import copy

        self.posts.append({
            "url": url,
            "json": copy.deepcopy(json),
            "timeout": timeout,
            "headers": headers,
        })
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_openai_400_with_images_retries_without_images():
    img_msgs = [ChatMessage(role="user", content="look", images=["data:image/png;base64,AAA"])]
    session = ScriptedSession([
        FakeResponse(
            {"error": "model does not support image input"},
            status_code=400,
            text="model does not support image input",
        ),
        FakeResponse(_payload(content="ok, text only")),
    ])
    p = OpenAICompatProvider("http://api", "key", "text-model", session=session)
    r = p.complete(img_msgs, [], CancellationToken())
    assert r.text == "ok, text only"
    assert len(session.posts) == 2
    # First attempt carried the image...
    assert any(
        isinstance(m.get("content"), list) for m in session.posts[0]["json"]["messages"]
    )
    # ...the retry did not.
    assert all(
        not isinstance(m.get("content"), list) for m in session.posts[1]["json"]["messages"]
    )
    # Vision is disabled for the rest of the session.
    assert p.supports_vision is False


def test_openai_vision_fallback_sets_one_shot_notice():
    img_msgs = [ChatMessage(role="user", content="look", images=["data:image/png;base64,AAA"])]
    session = ScriptedSession([
        FakeResponse({}, status_code=400, text="image_url parts are not supported"),
        FakeResponse(_payload(content="ok")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    p.complete(img_msgs, [], CancellationToken())
    assert p.pop_notice() == {"code": "vision_disabled", "model": "m"}
    assert p.pop_notice() is None


def test_openai_400_with_images_but_non_image_error_does_not_retry():
    img_msgs = [ChatMessage(role="user", content="look", images=["data:image/png;base64,AAA"])]
    session = ScriptedSession([
        FakeResponse(
            {"error": "context length exceeded"},
            status_code=400,
            text="This model's maximum context length is 8192 tokens",
        ),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    with pytest.raises(ProviderError):
        p.complete(img_msgs, [], CancellationToken())
    assert len(session.posts) == 1
    assert p.supports_vision is True
    assert p.pop_notice() is None


def test_openai_400_without_images_still_raises():
    session = ScriptedSession([FakeResponse({}, status_code=400)])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    with pytest.raises(ProviderError):
        p.complete(_msgs(), [], CancellationToken())
    assert len(session.posts) == 1


def test_openai_vision_false_strips_images_from_wire():
    session = ScriptedSession([FakeResponse(_payload(content="ok"))])
    p = OpenAICompatProvider(
        "http://api", "key", "m", session=session, supports_vision=False
    )
    msgs = [ChatMessage(role="user", content="look", images=["data:image/png;base64,AAA"])]
    p.complete(msgs, [], CancellationToken())
    wire = session.posts[0]["json"]["messages"]
    assert all(not isinstance(m.get("content"), list) for m in wire)


def _rate_limited():
    return FakeResponse(
        {"error": {"message": "Too Many Requests"}},
        status_code=429,
        headers={"Retry-After": "0"},
    )


class _RecordingCancel(CancellationToken):
    """Records requested wait durations without actually sleeping."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        return self.cancelled


def test_openai_429_retries_then_succeeds():
    session = ScriptedSession([
        _rate_limited(),
        FakeResponse(_payload(content="recovered")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.text == "recovered"
    assert len(session.posts) == 2


def test_openai_429_exhausts_retries_with_rate_limited_code():
    # 1 initial + 3 retries, all rate-limited, then a clean ProviderError.
    session = ScriptedSession([_rate_limited() for _ in range(4)])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], CancellationToken())
    assert ei.value.error_code == "rate_limited"
    # Not the raw provider URL.
    assert "groq.com" not in ei.value.message
    assert len(session.posts) == 4


def test_openai_429_stops_retrying_when_cancelled():
    session = ScriptedSession([_rate_limited()])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    cancel = CancellationToken()
    cancel.cancel()
    with pytest.raises(ProviderError) as ei:
        p.complete(_msgs(), [], cancel)
    assert ei.value.error_code == "cancelled"
    # Gave up after the first rate-limited response — no backoff loop.
    assert len(session.posts) == 1


def test_openai_529_overloaded_is_also_retried():
    session = ScriptedSession([
        FakeResponse({}, status_code=529, headers={"Retry-After": "0"}),
        FakeResponse(_payload(content="ok")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    r = p.complete(_msgs(), [], CancellationToken())
    assert r.text == "ok"
    assert len(session.posts) == 2


def _telemetry_log(tmp_path, monkeypatch):
    from core.agent import telemetry

    log = tmp_path / "agent.log"
    monkeypatch.setenv("NEXADESK_TELEMETRY", "1")
    monkeypatch.setattr(telemetry, "_log_file", lambda: log)
    return log


def _records(log):
    import json

    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rate_limit_retry_logs_each_attempt(tmp_path, monkeypatch):
    log = _telemetry_log(tmp_path, monkeypatch)
    session = ScriptedSession([
        FakeResponse({}, status_code=429, headers={"Retry-After": "0"}),
        FakeResponse(_payload(content="ok")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    p.complete(_msgs(), [], _RecordingCancel())
    recs = [r for r in _records(log) if r["event"] == "model_request"]
    assert len(recs) == 2
    first, second = recs
    assert first["status"] == 429 and first["attempt"] == 0
    assert first["retry_after_s"] == "0"
    assert first["wait_ms"] == 0  # nothing had been waited before attempt 0
    assert second["status"] == 200 and second["attempt"] == 1
    assert second["wait_ms"] == 0  # Retry-After: 0 honoured — no delay added


def test_backoff_wait_is_recorded_before_next_attempt(tmp_path, monkeypatch):
    log = _telemetry_log(tmp_path, monkeypatch)
    session = ScriptedSession([
        FakeResponse({}, status_code=429),  # no Retry-After -> exponential backoff
        FakeResponse(_payload(content="ok")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    cancel = _RecordingCancel()
    p.complete(_msgs(), [], cancel)
    assert cancel.waits and cancel.waits[0] > 0  # the provider asked us to wait
    second = [r for r in _records(log) if r["event"] == "model_request"][1]
    assert second["wait_ms"] > 0  # ...and that wait is visible in telemetry


def test_pop_stats_counts_calls_and_wait(tmp_path, monkeypatch):
    _telemetry_log(tmp_path, monkeypatch)
    session = ScriptedSession([
        FakeResponse({}, status_code=429, headers={"Retry-After": "0"}),
        FakeResponse(_payload(content="ok")),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    p.complete(_msgs(), [], CancellationToken())
    stats = p.pop_stats()
    assert stats["model_calls"] == 2
    assert stats["total_wait_ms"] >= 0
    assert stats["total_http_ms"] >= 0
    # One-shot, like pop_notice.
    assert p.pop_stats() == {"model_calls": 0, "total_wait_ms": 0.0, "total_http_ms": 0.0}


def test_model_request_logs_usage_and_ratelimit_headers(tmp_path, monkeypatch):
    log = _telemetry_log(tmp_path, monkeypatch)
    payload = _payload(content="hi")
    payload["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    session = ScriptedSession([
        FakeResponse(payload, headers={"x-ratelimit-remaining-requests": "999"}),
    ])
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    p.complete(_msgs(), [], CancellationToken())
    rec = next(r for r in _records(log) if r["event"] == "model_request")
    assert rec["usage"]["total_tokens"] == 15
    assert rec["ratelimit"]["x-ratelimit-remaining-requests"] == "999"


def test_failed_request_logs_attempt(tmp_path, monkeypatch):
    log = _telemetry_log(tmp_path, monkeypatch)
    session = FakeSession(exc=requests.Timeout("slow"))
    p = OpenAICompatProvider("http://api", "key", "m", session=session)
    with pytest.raises(ProviderError):
        p.complete(_msgs(), [], CancellationToken())
    rec = next(r for r in _records(log) if r["event"] == "model_request")
    assert rec["error"] == "Timeout"
    assert rec["status"] is None
