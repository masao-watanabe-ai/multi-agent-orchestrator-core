"""
execution/event_bus.py
-----------------------
Event bus protocol and a minimal in-memory implementation.

Events are arbitrary objects (``TaskCompletedEvent``, ``TaskFailedEvent``,
…).  ``InMemoryEventBus`` accumulates them in a plain list; a production
implementation would fan-out to subscribers or persist to a stream.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventBusProtocol(Protocol):
    """Structural interface for event buses."""

    def publish(self, event: Any) -> None:
        """Publish *event* to the bus.

        The bus may deliver the event synchronously, enqueue it, or
        persist it — callers make no assumptions about delivery timing.
        """
        ...


class InMemoryEventBus:
    """Accumulates published events in an ordered list.

    Attributes
    ----------
    events:
        Every event passed to :meth:`publish`, in the order received.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        """Append *event* to the internal list."""
        self.events.append(event)
