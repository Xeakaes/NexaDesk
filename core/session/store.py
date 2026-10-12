"""In-memory session/message store (spec §3.6; SQLite later behind same API)."""

from __future__ import annotations

import uuid

from core.providers.base import ChatMessage, ToolCall


class SessionStore:
    def __init__(self) -> None:
        self._messages: dict[str, list[ChatMessage]] = {}

    def create_session(self) -> str:
        sid = uuid.uuid4().hex
        self._messages[sid] = []
        return sid

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str | None,
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
        images: list[str] | None = None,
    ) -> None:
        self._messages.setdefault(session_id, []).append(
            ChatMessage(
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                name=name,
                tool_calls=tool_calls,
                images=images,
            )
        )

    def messages(self, session_id: str) -> list[ChatMessage]:
        return list(self._messages.get(session_id, ()))

    def seed_session(self, session_id: str, pairs: list[tuple[str, str]]) -> None:
        """Fill an unknown session from persisted (role, text) history pairs.

        Called when the user reopens an old chat (possibly after a restart):
        the in-memory store is empty for that session, so the model would
        otherwise see only the newest message. A session the runtime already
        knows keeps its richer transcript (tool_calls etc.) untouched.
        """
        if session_id in self._messages:
            return
        self._messages[session_id] = [
            ChatMessage(role=role, content=content) for role, content in pairs
        ]

    def trim_images(self, session_id: str, keep: int) -> None:
        """Drop images from all but the most recent `keep` image-bearing messages.

        Base64 data-URIs are large; keeping every screenshot forever leaks
        memory and bloats every subsequent provider request.
        """
        keep = max(keep, 0)
        keepers: list[ChatMessage] = []
        for m in self._messages.get(session_id, ()):
            if m.images:
                keepers.append(m)
        for m in keepers[:-keep] if keep else keepers:
            m.images = None
