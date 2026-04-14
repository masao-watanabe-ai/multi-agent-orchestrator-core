"""
trace/ledger_adapter.py
------------------------
Converts :class:`~trace.model.TraceEvent` objects to plain ledger record
dicts suitable for audit logs, external sinks, or JSON serialisation.

The ledger record format uses ISO 8601 strings for timestamps and copies the
``payload`` dict so the caller's mutations do not affect the original event.
"""
from __future__ import annotations

from typing import Any

from trace.model import TraceEvent


def to_ledger_record(event: TraceEvent) -> dict[str, Any]:
    """Convert *event* to a ledger record dict.

    Parameters
    ----------
    event:
        The :class:`~trace.model.TraceEvent` to convert.

    Returns
    -------
    dict
        Keys:

        ``instance_id``
            Instance the event belongs to.
        ``node_id``
            Node that triggered the event, or ``None`` for flow-level events.
        ``event_type``
            Dot-namespaced event name string.
        ``timestamp``
            ISO 8601 string (with UTC offset) of when the event occurred.
        ``payload``
            Shallow copy of the event's metadata dict.
    """
    return {
        "instance_id": event.instance_id,
        "node_id":     event.node_id,
        "event_type":  event.event_type,
        "timestamp":   event.timestamp.isoformat(),
        "payload":     dict(event.payload),
    }
