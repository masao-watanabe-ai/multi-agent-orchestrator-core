"""
state/event_store.py
---------------------
Minimal in-memory store for resume events.

Events are grouped by ``instance_id`` so callers can replay all events
for a given workflow instance.  Any object with an ``instance_id``
attribute is accepted (``TaskCompletedEvent``, ``HumanApprovedEvent``, …).
"""
from __future__ import annotations

from typing import Any


class InMemoryEventStore:
    """Accumulates resume events grouped by ``instance_id``.

    Usage::

        store = InMemoryEventStore()
        store.append(TaskCompletedEvent(instance_id="i1", node_id="a1"))
        events = store.list_events("i1")

    Attributes
    ----------
    _events:
        ``instance_id`` → ordered list of events.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[Any]] = {}

    def append(self, event: Any) -> None:
        """Add *event* to the store.

        Parameters
        ----------
        event:
            Any object with an ``instance_id: str`` attribute.

        Raises
        ------
        AttributeError
            If *event* has no ``instance_id`` attribute.
        """
        instance_id: str = event.instance_id
        self._events.setdefault(instance_id, []).append(event)

    def list_events(self, instance_id: str) -> list[Any]:
        """Return all events recorded for *instance_id* in insertion order.

        Returns an empty list if no events have been appended for the given id.
        """
        return list(self._events.get(instance_id, []))

    def __len__(self) -> int:
        """Total number of events across all instances."""
        return sum(len(evts) for evts in self._events.values())
