"""
trace/collector.py
------------------
InMemoryTraceCollector — event sink that indexes events by ``instance_id``.

Unlike the flat :class:`~trace.emitter.TraceEmitter`, the collector allows
efficient per-instance lookups and type-based filtering, making it the
preferred choice for tests and multi-instance scenarios.
"""
from __future__ import annotations

from trace.model import TraceEvent


class InMemoryTraceCollector:
    """Collects trace events grouped by ``instance_id``.

    Implements the :class:`~trace.emitter.TraceEmitterProtocol` duck-type
    interface (has ``emit()``) so it can be passed directly to the engine.

    Usage::

        collector = InMemoryTraceCollector()
        instance = start(flow, context, emitter=collector)
        events = collector.list_events(instance.instance_id)
        boundary_hits = collector.by_type("boundary.triggered", instance.instance_id)

    Attributes
    ----------
    _events:
        Flat ordered list of all received events across all instances.
    """

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    # ------------------------------------------------------------------
    # Emitter interface
    # ------------------------------------------------------------------

    def emit(self, event: TraceEvent) -> None:
        """Append *event* to the collection."""
        self._events.append(event)

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def list_events(self, instance_id: str | None = None) -> list[TraceEvent]:
        """Return events in insertion order.

        Parameters
        ----------
        instance_id:
            When provided, only events whose ``instance_id`` matches are
            returned.  When ``None``, all events across all instances are
            returned.
        """
        if instance_id is None:
            return list(self._events)
        return [e for e in self._events if e.instance_id == instance_id]

    def by_type(
        self,
        event_type: str,
        instance_id: str | None = None,
    ) -> list[TraceEvent]:
        """Return events filtered by *event_type* (and optionally by *instance_id*).

        Parameters
        ----------
        event_type:
            Exact event type string to match, e.g. ``"node.succeeded"``.
        instance_id:
            Optional additional filter.
        """
        return [
            e for e in self.list_events(instance_id)
            if e.event_type == event_type
        ]

    def event_types(self, instance_id: str | None = None) -> list[str]:
        """Return the ordered list of event type strings for quick assertions."""
        return [e.event_type for e in self.list_events(instance_id)]

    def __len__(self) -> int:
        return len(self._events)
