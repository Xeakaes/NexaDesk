"""Ollama chat provider (local models, OpenAI-adjacent but distinct wire format)."""

from __future__ import annotations

import json
import uuid

import requests

from core.agent.cancellation import CancellationToken
from core.providers.base import (
    ChatMessage,
    ModelProvider,
    ProviderError,
    ProviderResponse,
    ToolCall,
)


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


def serialize_messages(messages: list[ChatMessage]) -> list[dict]:
    wire: list[dict] = []
    for m in messages:
        item: dict = {"role": m.role, "content": m.content}
        if m.images:
            # Ollama expects raw base64 strings (no data: prefix).
            b64s = []
            for uri in m.images:
                b64s.append(uri.split(",", 1)[1] if "," in uri else uri)
            item["images"] = b64s
        if m.role == "assistant" and m.tool_calls:
            item["tool_calls"] = [
                {"function": {"name": c.name, "arguments": c.arguments}}
                for c in m.tool_calls
            ]
        if m.role == "tool":
            item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
        wire.append(item)
    return wire


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"invalid tool arguments JSON: {exc}", error_code="invalid_arguments"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError("tool arguments must be an object", error_code="invalid_arguments")
        return parsed
    if raw is None:
        return {}
    raise ProviderError(f"unsupported arguments type: {type(raw)}", error_code="invalid_arguments")


class OllamaProvider(ModelProvider):
    supports_tools = True
    supports_vision = True

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        session: requests.Session | None = None,
        supports_vision: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._session = session or requests.Session()
        self.supports_vision = supports_vision

    def list_models(self) -> list[str]:
        """Local model tags from /api/tags (Settings dropdown)."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/tags", timeout=self.timeout_s
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []
        names = {
            str(m["name"])
            for m in models
            if isinstance(m, dict) and m.get("name")
        }
        return sorted(names)

    def complete(
        self,
        messages: list[ChatMessage],
        schemas: list[dict],
        cancel: CancellationToken,
    ) -> ProviderResponse:
        if not self.supports_vision:
            messages = [
                ChatMessage(
                    role=m.role,
                    content=m.content,
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                    tool_calls=m.tool_calls,
                    images=None,
                )
                for m in messages
            ]
        body: dict = {
            "model": self.model,
            "messages": serialize_messages(messages),
            "stream": False,
        }
        tools = to_provider_tools(schemas)
        if tools:
            body["tools"] = tools
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = self._session.post(
                f"{self.base_url}/api/chat",
                json=body,
                timeout=self.timeout_s,
                headers=headers or None,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.Timeout as exc:
            raise ProviderError(str(exc), error_code="timeout") from exc
        except requests.RequestException as exc:
            raise ProviderError(str(exc), error_code="provider_error") from exc
        try:
            payload = resp.json()
            message = payload["message"]
            if not isinstance(message, dict):
                raise TypeError("message is not an object")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                f"malformed provider response: {exc}", error_code="provider_error"
            ) from exc
        text = message.get("content")
        tool_calls: list[ToolCall] = []
        known_names = {s.get("name") for s in schemas}
        for i, raw in enumerate(message.get("tool_calls") or []):
            fn = raw.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            try:
                arguments = _parse_arguments(raw_args)
                parse_error = None
            except ProviderError as exc:
                arguments = {}
                parse_error = exc.message
            tool_calls.append(
                ToolCall(
                    # B36: index-only ids collide across turns when history
                    # replays; uuid keeps every call unique in the session.
                    id=f"ollama_{uuid.uuid4().hex[:12]}_{i}",
                    name=name,
                    arguments=arguments,
                    parse_error=parse_error,
                )
            )
        if not tool_calls and text and known_names:
            # Some models (e.g. qwen via Ollama) emit the tool call as a JSON
            # object in content instead of the native tool_calls field.
            # Only accept it when the name matches a schema we offered —
            # arbitrary JSON text must stay text (review finding I5).
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    embedded = json.loads(stripped)
                except json.JSONDecodeError:
                    embedded = None
                if (
                    isinstance(embedded, dict)
                    and embedded.get("name") in known_names
                    and "arguments" in embedded
                ):
                    tool_calls.append(
                        ToolCall(
                            id=f"ollama_{uuid.uuid4().hex[:12]}_0",
                            name=embedded["name"],
                            arguments=_parse_arguments(embedded.get("arguments")),
                        )
                    )
                    text = None
        return ProviderResponse(text=text, tool_calls=tool_calls)
