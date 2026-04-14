"""
runtime/resume.py
------------------
Event models for resuming WAITING nodes.

Four event types cover the two node kinds that can suspend:

Action nodes (dispatched to workers)
    TaskCompletedEvent  — task succeeded; result stored in context.
    TaskFailedEvent     — task failed; instance halted.

Human gate nodes (waiting for a human decision)
    HumanApprovedEvent  — approved; execution continues to node.next.
    HumanRejectedEvent  — rejected; instance halted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskCompletedEvent:
    """Signals that the task for a WAITING action node completed successfully.

    Attributes
    ----------
    instance_id:
        Must match the target ``ExecutionInstance.instance_id``.
    node_id:
        The ``id`` of the action node that was suspended.
    payload:
        Result data.  The engine reads ``payload["result"]`` and stores
        it at ``instance.context[node_id]``.
    """

    instance_id: str
    node_id:     str
    payload:     dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskFailedEvent:
    """Signals that the task for a WAITING action node has failed.

    Attributes
    ----------
    instance_id:
        Must match the target ``ExecutionInstance.instance_id``.
    node_id:
        The ``id`` of the action node that was suspended.
    error:
        Human-readable description of the failure reason.
    payload:
        Optional supplementary data (e.g. raw response, stack trace).
    """

    instance_id: str
    node_id:     str
    error:       str
    payload:     dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanApprovedEvent:
    """Signals that a human gate node was approved.

    The engine marks the gate node SUCCEEDED, stores approval metadata at
    ``instance.context[node_id]``, and continues from ``node.next``.

    Attributes
    ----------
    instance_id:
        Must match the target ``ExecutionInstance.instance_id``.
    node_id:
        The ``id`` of the human_gate node that was suspended.
    approver:
        Identifier of the person or system that approved (e.g. username).
    payload:
        Optional supplementary data forwarded to the context entry.
    """

    instance_id: str
    node_id:     str
    approver:    str            = ""
    payload:     dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanRejectedEvent:
    """Signals that a human gate node was rejected.

    The engine marks the gate node FAILED, stores rejection metadata at
    ``instance.context[node_id]``, and halts the instance.

    Attributes
    ----------
    instance_id:
        Must match the target ``ExecutionInstance.instance_id``.
    node_id:
        The ``id`` of the human_gate node that was suspended.
    reason:
        Human-readable explanation of why the gate was rejected.
    approver:
        Identifier of the person or system that rejected.
    payload:
        Optional supplementary data forwarded to the context entry.
    """

    instance_id: str
    node_id:     str
    reason:      str            = ""
    approver:    str            = ""
    payload:     dict[str, Any] = field(default_factory=dict)
