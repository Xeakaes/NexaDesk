"""EventBus → Qt signal bridge (thread-safe queued delivery to the GUI thread)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.events import Event, EventBus


class QtBridge(QObject):
    sig = Signal(object)

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._bus = bus
        bus.subscribe("*", self._on_event)

    def _on_event(self, event: Event) -> None:
        self.sig.emit(event)

    def close(self) -> None:
        """Backlog 3: stop delivery — late events from a dying runtime must
        not touch deleted widgets."""
        if self._bus is not None:
            self._bus.unsubscribe("*", self._on_event)
            self._bus = None
            try:
                self.sig.disconnect()
            except RuntimeError:
                pass  # no connections left
