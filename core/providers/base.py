"""Provider-facing message model and abstract provider (spec §3.1b).

Internal single form; each concrete provider serializes to its own wire
format (Task 6). Assistant messages that requested tools carry `tool_calls`
so the next request can replay call + result history.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from core.agent.cancellation import CancellationToken


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    parse_error: str | None = None


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "tool"
    content: str | None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    images: list[str] | None = None  # data-URIs for vision models


@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ProviderError(Exception):
    def __init__(self, message: str, error_code: str = "provider_error") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ModelProvider(ABC):
    supports_tools: bool = False
    supports_vision: bool = False

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        schemas: list[dict],
        cancel: CancellationToken,
    ) -> ProviderResponse:
        ...

    def list_models(self) -> list[str]:
        """Model ids for the Settings dropdown; [] when unsupported/unavailable."""
        return []
