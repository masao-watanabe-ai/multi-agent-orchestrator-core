"""
trace/model.py
--------------
Minimal TraceEvent dataclass for recording engine execution events.

Each event captures the instance it belongs to, the node that triggered it
(or ``None`` for flow-level events), a string ``event_type``, a UTC timestamp,
and an open ``payload`` dict for type-specific metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TraceEvent:
    """A single structured event emitted during workflow execution.

    Attributes
    ----------
    instance_id:
        The :class:`~runtime.models.ExecutionInstance` this event belongs to.
    node_id:
        The node that triggered this event, or ``None`` for flow-level events
        (e.g. ``"flow.started"``, ``"flow.succeeded"``).
    event_type:
        Dot-namespaced event name, e.g. ``"node.started"``,
        ``"action.dispatched"``, ``"boundary.triggered"``.
    timestamp:
        UTC datetime when the event was created.
    payload:
        Arbitrary metadata specific to the event type.
    """

    instance_id: str
    node_id: str | None
    event_type: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)
