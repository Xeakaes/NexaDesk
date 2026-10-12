"""Simple observer event bus (pure Python, no Qt).

Every event carries session_id and task_id so multi-session use will not
mix events later (spec §3.4). UI bridges these to Qt signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.agent.telemetry import log_event

EVENT_NAMES = (
    "agent_started",
    "assistant_message",
    "assistant_emotion",
    "tool_started",
    "tool_finished",
    "confirmation_requested",
    "agent_error",
    "agent_finished",
    "agent_cancelled",
    "provider_notice",
)


@dataclass(frozen=True)
class Event:
    name: str
    session_id: str
    task_id: str
    payload: dict


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Event], None]]] = {}

    def subscribe(self, name: str, cb: Callable[[Event], None]) -> None:
        self._subs.setdefault(name, []).append(cb)

    def unsubscribe(self, name: str, cb: Callable[[Event], None]) -> None:
        subs = self._subs.get(name)
        if not subs:
            return
        try:
            subs.remove(cb)
        except ValueError:
            pass

    def publish(self, name: str, session_id: str, task_id: str, payload: dict) -> None:
        event = Event(name, session_id, task_id, payload)
        targets = list(self._subs.get(name, ()))
        targets.extend(self._subs.get("*", ()))
        for cb in targets:
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001 — one bad subscriber must not kill the bus
                log_event(
                    "subscriber_error",
                    event_name=name,
                    callback=getattr(cb, "__qualname__", repr(cb)),
                    error=repr(exc),
                )
