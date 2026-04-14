"""
state/snapshot.py
------------------
Serialise :class:`~runtime.models.ExecutionInstance` to a plain Python dict
and restore it back.

All datetime values are stored as ISO 8601 strings (with UTC offset) so the
dict can be round-tripped through JSON without data loss.
NodeState enum values are stored as their string ``value`` (e.g. ``"waiting"``).

Limitations
-----------
``NodeExecutionState.output`` and ``ExecutionInstance.context`` may contain
arbitrary Python objects.  :func:`to_dict` preserves them by reference — only
:class:`~state.store.JsonFileStateStore` requires that these values be
JSON-native (``str``, ``int``, ``float``, ``bool``, ``None``, ``list``,
``dict``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from runtime.models import ExecutionInstance, NodeExecutionState, NodeState


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_dict(instance: ExecutionInstance) -> dict[str, Any]:
    """Serialise *instance* to a plain Python dict.

    Parameters
    ----------
    instance:
        The :class:`~runtime.models.ExecutionInstance` to serialise.

    Returns
    -------
    dict
        A dict that can be passed to :func:`from_dict` to restore the
        instance.  For JSON storage, all ``context`` and ``output`` values
        must themselves be JSON-native types.
    """
    return {
        "instance_id": instance.instance_id,
        "workflow_id": instance.workflow_id,
        "created_at":  _dt_to_str(instance.created_at),
        "updated_at":  _dt_to_str(instance.updated_at),
        "status":      instance.status.value,
        "node_states": {
            node_id: _ns_to_dict(ns)
            for node_id, ns in instance.node_states.items()
        },
        "context": instance.context,
    }


def from_dict(data: dict[str, Any]) -> ExecutionInstance:
    """Restore an :class:`~runtime.models.ExecutionInstance` from *data*.

    Parameters
    ----------
    data:
        A dict previously produced by :func:`to_dict`.

    Returns
    -------
    ExecutionInstance
    """
    node_states = {
        node_id: _ns_from_dict(ns_data)
        for node_id, ns_data in data["node_states"].items()
    }
    return ExecutionInstance(
        instance_id=data["instance_id"],
        workflow_id=data["workflow_id"],
        created_at=_str_to_dt(data["created_at"]),
        updated_at=_str_to_dt(data["updated_at"]),
        status=NodeState(data["status"]),
        node_states=node_states,
        context=data.get("context", {}),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ns_to_dict(ns: NodeExecutionState) -> dict[str, Any]:
    return {
        "node_id":     ns.node_id,
        "state":       ns.state.value,
        "started_at":  _dt_to_str(ns.started_at),
        "finished_at": _dt_to_str(ns.finished_at),
        "attempt":     ns.attempt,
        "error":       ns.error,
        "output":      ns.output,
    }


def _ns_from_dict(data: dict[str, Any]) -> NodeExecutionState:
    return NodeExecutionState(
        node_id=    data["node_id"],
        state=      NodeState(data["state"]),
        started_at= _str_to_dt(data.get("started_at")),
        finished_at=_str_to_dt(data.get("finished_at")),
        attempt=    data.get("attempt", 0),
        error=      data.get("error"),
        output=     data.get("output"),
    )


def _dt_to_str(dt: datetime | None) -> str | None:
    """Convert a datetime to an ISO 8601 string, or ``None`` if *dt* is None."""
    return None if dt is None else dt.isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    """Parse an ISO 8601 string back to datetime, or return ``None``."""
    return None if s is None else datetime.fromisoformat(s)
