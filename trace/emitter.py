"""
trace/emitter.py
-----------------
TraceEmitterProtocol and a concrete TraceEmitter implementation.

TraceEmitterProtocol
    Structural ``@runtime_checkable`` Protocol accepted by the engine.
    Any object that has ``emit(event: TraceEvent) -> None`` satisfies it.

TraceEmitter
    Flat-list implementation.  Stores every event in insertion order and
    exposes ``list_events()`` for inspection.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from trace.model import TraceEvent


@runtime_checkable
class TraceEmitterProtocol(Protocol):
    """Structural interface for trace sinks.

    The runtime engine accepts any object that satisfies this protocol as
    its ``emitter`` argument.
    """

    def emit(self, event: TraceEvent) -> None:
        """Record *event*."""
        ...


class TraceEmitter:
    """Concrete emitter that stores all events in a single flat list.

    Usage::

        emitter = TraceEmitter()
        instance = start(flow, context, emitter=emitter)
        events = emitter.list_events()

    Attributes
    ----------
    _events:
        Ordered list of every :class:`~trace.model.TraceEvent` received.
    """

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        """Append *event* to the internal list."""
        self._events.append(event)

    def list_events(self) -> list[TraceEvent]:
        """Return all events in insertion order (shallow copy)."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
