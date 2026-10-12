"""OpenAI-compatible chat completions provider (API-hosted models)."""

from __future__ import annotations

import json
import random
import time
import uuid
from urllib.parse import urlparse

import requests

from core.agent.cancellation import CancellationToken
from core.agent.telemetry import log_event
from core.providers.base import (
    ChatMessage,
    ModelProvider,
    ProviderError,
    ProviderResponse,
    ToolCall,
)
from core.providers.ollama import _parse_arguments


def to_provider_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s.get("input_schema", {"type": "object"}),
            },
        }
        for s in schemas
    ]


def serialize_messages(
    messages: list[ChatMessage], include_images: bool = True
) -> list[dict]:
    wire: list[dict] = []
    for m in messages:
        if m.images and include_images:
            # Vision: content becomes a list of parts (text + image_url).
            parts: list[dict] = [{"type": "text", "text": m.content or ""}]
            for uri in m.images:
                parts.append({"type": "image_url", "image_url": {"url": uri}})
            item: dict = {"role": m.role, "content": parts}
        else:
            item = {"role": m.role, "content": m.content}
        if m.role == "assistant" and m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.arguments),
                    },
                }
                for c in m.tool_calls
            ]
        if m.role == "tool":
            item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
        wire.append(item)
    return wire


def _looks_like_image_error(text: str) -> bool:
    """Heuristic: did the 400 come from the image parts, not e.g. schema/context?"""
    lowered = text.lower()
    return any(
        key in lowered
        for key in ("image", "vision", "multimodal", "image_url", "base64")
    )


def _looks_like_tool_error(text: str) -> bool:
    """Heuristic: did the 400 reject the tools payload (model has no tool support)?"""
    lowered = text.lower()
    return any(key in lowered for key in ("tool", "function", "tool_call"))


# Hosted providers (Groq above all) answer 429/529 when a burst of tool-calls
# trips the per-minute limits. The retry policy is per provider because the
# budgets differ wildly: Groq free is 30 req/min and 8K tokens/min with a flat
# 2048 tokens per image, so screenshot-carrying agent calls thrash (observed:
# Retry-After ~30s on every call, a task grinding for 210s). Local servers
# never throttle on purpose - a 429 there means something is broken - so they
# get no backoff at all.
_RATE_LIMIT_STATUSES = frozenset({429, 529})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# max_wait_s: cap for a single Retry-After/backoff wait.
# total_budget_s: hard cap on cumulative waiting inside one request chain.
# max_retries: attempts after the first 429/529.
RATE_LIMIT_POLICY: dict[str, dict[str, float]] = {
    # max_wait_s 45 honors real Groq bursts (Retry-After 36-39s) in full:
    # cutting them at 30 only earned a second 429 and a second wait.
    "groq": {"max_wait_s": 45.0, "total_budget_s": 60.0, "max_retries": 3},
    "github": {"max_wait_s": 30.0, "total_budget_s": 90.0, "max_retries": 3},
}
_DEFAULT_RATE_POLICY = {"max_wait_s": 30.0, "total_budget_s": 60.0, "max_retries": 3}
_NO_RATE_POLICY = {"max_wait_s": 0.0, "total_budget_s": 0.0, "max_retries": 0}


def _rate_limit_delay(resp, attempt: int, cap_s: float) -> float:
    """Seconds to wait before retrying a rate-limited (429/529) response."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(max(float(raw), 0.0), cap_s)
        except ValueError:
            pass
    # Exponential backoff with jitter, capped like Retry-After.
    base = min(2 ** attempt, cap_s)
    return base * (0.5 + random.random())


def _ratelimit_headers(resp) -> dict:
    """Provider rate-limit headers (Groq's x-ratelimit-*) for telemetry."""
    try:
        items = resp.headers.items()
    except Exception:  # noqa: BLE001 — odd header containers still log fine
        return {}
    return {
        k: v
        for k, v in items
        if k.lower().startswith("x-ratelimit-") or k.lower() == "retry-after"
    }


class OpenAICompatibleProvider(ModelProvider):
    supports_tools = True
    supports_vision = True

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        session: requests.Session | None = None,
        supports_vision: bool = True,
        provider_key: str = "openai_compatible",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._session = session or requests.Session()
        self.supports_vision = supports_vision
        self.provider_key = provider_key
        self._notice: dict | None = None
        self._stats: dict = self._empty_stats()

    @staticmethod
    def _empty_stats() -> dict:
        return {"model_calls": 0, "total_wait_ms": 0.0, "total_http_ms": 0.0}

    def pop_notice(self) -> dict | None:
        """One-shot UI notice set by complete() (e.g. vision fallback)."""
        notice, self._notice = self._notice, None
        return notice

    def pop_stats(self) -> dict:
        """One-shot timing counters (model_calls, total_wait_ms, total_http_ms)."""
        stats, self._stats = self._stats, self._empty_stats()
        return stats

    def list_models(self) -> list[str]:
        """Model ids from the provider's /models catalog (Settings dropdown)."""
        try:
            resp = self._session.get(
                f"{self.base_url}/models",
                headers=self._auth_headers(),
                timeout=self.timeout_s,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        ids = {
            str(item["id"])
            for item in items
            if isinstance(item, dict) and item.get("id")
        }
        return sorted(ids)

    def _log_request(
        self,
        *,
        status: int | None,
        attempt: int,
        http_ms: float,
        wait_ms: float,
        resp=None,
        error: str | None = None,
    ) -> None:
        """One telemetry line per HTTP attempt (see core.agent.telemetry)."""
        usage = None
        if resp is not None and status is not None and status < 400:
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001 — non-JSON body just means no usage
                payload = None
            if isinstance(payload, dict):
                usage = payload.get("usage")
        log_event(
            "model_request",
            provider=self.provider_key,
            model=self.model,
            attempt=attempt,
            status=status,
            http_ms=round(http_ms, 1),
            wait_ms=round(wait_ms, 1),
            retry_after_s=(resp.headers.get("Retry-After") if resp is not None else None),
            ratelimit=(_ratelimit_headers(resp) if resp is not None else {}),
            usage=usage,
            error=error,
        )

    def _rate_policy(self) -> dict:
        """Wait budget for this endpoint: none locally, per provider in cloud."""
        host = urlparse(self.base_url).hostname or ""
        if host in _LOOPBACK_HOSTS:
            return _NO_RATE_POLICY
        return RATE_LIMIT_POLICY.get(self.provider_key, _DEFAULT_RATE_POLICY)

    def _post_chat(
        self,
        body: dict,
        headers: dict,
        cancel: CancellationToken,
    ):
        """POST /chat/completions, retrying transient rate limits within budget.

        429/529 responses clear within seconds, so we back off (honouring a
        Retry-After header when present) and retry rather than aborting the
        task with a raw HTTP error. Waiting is bounded by the per-provider
        policy: a single wait is capped, cumulative waits cannot exceed the
        budget (Groq free thrash previously burned 210s per task), and local
        endpoints never wait at all. Retrying stops immediately if the task is
        cancelled, and the final failure surfaces a human message instead of
        the provider URL. Every attempt is timed and logged for telemetry.
        """
        policy = self._rate_policy()
        attempt = 0
        waited_s = 0.0
        pending_wait_ms = 0.0
        while True:
            t0 = time.perf_counter()
            try:
                resp = self._session.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    timeout=self.timeout_s,
                    headers=headers,
                )
            except requests.RequestException as exc:
                http_ms = (time.perf_counter() - t0) * 1000.0
                self._stats["model_calls"] += 1
                self._stats["total_http_ms"] += http_ms
                self._log_request(
                    status=None, attempt=attempt, http_ms=http_ms,
                    wait_ms=pending_wait_ms, error=type(exc).__name__,
                )
                raise
            http_ms = (time.perf_counter() - t0) * 1000.0
            self._stats["model_calls"] += 1
            self._stats["total_http_ms"] += http_ms
            self._log_request(
                status=resp.status_code, attempt=attempt, http_ms=http_ms,
                wait_ms=pending_wait_ms, resp=resp,
            )
            pending_wait_ms = 0.0
            if resp.status_code in _RATE_LIMIT_STATUSES:
                if attempt >= int(policy["max_retries"]):
                    raise ProviderError(
                        "rate limit reached (429); please wait a moment and retry",
                        error_code="rate_limited",
                    )
                cap = float(policy["max_wait_s"])
                delay = min(_rate_limit_delay(resp, attempt, cap), cap)
                if waited_s + delay > float(policy["total_budget_s"]):
                    # Another wait would exceed the budget (e.g. Groq's
                    # Retry-After ~30s thrash): fail honestly instead of
                    # grinding for minutes.
                    raise ProviderError(
                        "rate limit reached (429); please wait a moment and retry",
                        error_code="rate_limited",
                    )
                # cancel.wait() doubles as a cancel-aware sleep.
                if cancel.wait(delay):
                    raise ProviderError("cancelled", error_code="cancelled")
                waited_s += delay
                pending_wait_ms = delay * 1000.0
                self._stats["total_wait_ms"] += pending_wait_ms
                attempt += 1
                continue
            return resp

    def _auth_headers(self) -> dict:
        """Per-request auth headers; subclasses may add/refresh tokens."""
        return {"Authorization": f"Bearer {self.api_key}"}

    def complete(
        self,
        messages: list[ChatMessage],
        schemas: list[dict],
        cancel: CancellationToken,
    ) -> ProviderResponse:
        body: dict = {
            "model": self.model,
            "messages": self._serialize(messages),
        }
        tools = to_provider_tools(schemas)
        if tools:
            body["tools"] = tools
        headers = self._auth_headers()
        try:
            resp = self._post_chat(body, headers, cancel)
            if (
                resp.status_code == 400
                and self.supports_vision
                and any(m.images for m in messages)
                and _looks_like_image_error(resp.text)
            ):
                # Text-only models reject image_url parts with a 400 mentioning
                # images. Retry once without images and disable vision for the
                # session. Other 400s (context length, bad tool schema) must
                # surface unchanged.
                self.supports_vision = False
                self._notice = {"code": "vision_disabled", "model": self.model}
                body["messages"] = self._serialize(messages, include_images=False)
                resp = self._post_chat(body, headers, cancel)
            if resp.status_code in (401, 403):
                # raise_for_status() would bury a bad key under a generic
                # HTTPError; surface it as a distinct, actionable code.
                raise ProviderError(
                    f"provider rejected the API key (HTTP {resp.status_code});"
                    " check the key in Settings",
                    error_code="unauthorized",
                )
            if resp.status_code == 400 and tools and _looks_like_tool_error(resp.text):
                # B37: a tool-less model rejects the tools payload with a 400
                # naming tools/functions. Keep the real provider message and a
                # distinct code so the UI can say "model has no tool support"
                # instead of a generic HTTP failure.
                raise ProviderError(
                    f"model does not support tool calling: {resp.text}",
                    error_code="unsupported_capability",
                )
            resp.raise_for_status()
            payload = resp.json()
        except requests.Timeout as exc:
            raise ProviderError(str(exc), error_code="timeout") from exc
        except requests.RequestException as exc:
            raise ProviderError(str(exc), error_code="provider_error") from exc
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("malformed provider response", error_code="provider_error") from exc
        tool_calls: list[ToolCall] = []
        for i, raw in enumerate(message.get("tool_calls") or []):
            fn = raw.get("function") or {}
            tool_calls.append(
                ToolCall(
                    # B36: some endpoints omit ids; empty ids break the
                    # tool-call/tool-result pairing in history replay.
                    id=raw.get("id") or f"call_{uuid.uuid4().hex[:12]}_{i}",
                    name=fn.get("name", ""),
                    arguments=_parse_arguments(fn.get("arguments")),
                )
            )
        return ProviderResponse(text=message.get("content"), tool_calls=tool_calls)

    def _serialize(
        self, messages: list[ChatMessage], include_images: bool | None = None
    ) -> list[dict]:
        if include_images is None:
            include_images = self.supports_vision
        return serialize_messages(messages, include_images=include_images)
