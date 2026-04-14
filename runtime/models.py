"""
runtime/models.py
-----------------
Minimum shared data models for Multi-Agent Orchestrator Core v0.1.

These dataclasses / Enums are the single source of truth consumed by
engine, state, and trace layers.  No business logic lives here — only
plain data definitions with type annotations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# NodeState — lifecycle of a single node within an execution
# ---------------------------------------------------------------------------

class NodeState(str, Enum):
    """Lifecycle state of a node.

    Inherits from ``str`` so values can be stored / compared as plain
    strings in JSON payloads, DB columns, and log lines without extra
    serialisation.
    """
    PENDING   = "pending"    # not yet started
    RUNNING   = "running"    # currently executing
    SUCCEEDED = "succeeded"  # completed successfully
    FAILED    = "failed"     # completed with an error
    SKIPPED   = "skipped"    # bypassed (e.g. condition not met)
    WAITING   = "waiting"    # blocked on external event / human gate
    CANCELLED = "cancelled"  # explicitly stopped


# ---------------------------------------------------------------------------
# NodeExecutionState — per-node execution record inside an instance
# ---------------------------------------------------------------------------

@dataclass
class NodeExecutionState:
    """Tracks execution progress for one node within an ExecutionInstance.

    Mutated in-place by the engine as the node transitions through states.
    """
    node_id:     str
    state:       NodeState      = NodeState.PENDING
    started_at:  datetime | None = None
    finished_at: datetime | None = None
    attempt:     int             = 0          # incremented on each retry
    error:       str | None      = None       # last error message
    output:      Any             = None       # arbitrary result payload

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock seconds between start and finish; ``None`` if incomplete."""
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# ExecutionInstance — a running (or completed) workflow instance
# ---------------------------------------------------------------------------

@dataclass
class ExecutionInstance:
    """One concrete run of a workflow graph.

    ``node_states`` is keyed by ``node_id`` for O(1) lookup by engine and
    state layers.
    """
    instance_id:  str
    workflow_id:  str
    created_at:   datetime
    updated_at:   datetime
    status:       NodeState                       = NodeState.PENDING
    node_states:  dict[str, NodeExecutionState]   = field(default_factory=dict)
    context:      dict[str, Any]                  = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Task — unit of work dispatched to an agent / worker
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """Represents a single actionable unit sent to an agent or worker.

    ``payload`` carries node-specific input data; ``priority`` allows the
    dispatcher to order work across the queue.
    """
    task_id:     str
    node_id:     str
    instance_id: str
    created_at:  datetime
    payload:     dict[str, Any] = field(default_factory=dict)
    priority:    int            = 0


# ---------------------------------------------------------------------------
# ResumeEvent — external signal that unblocks a WAITING instance
# ---------------------------------------------------------------------------

@dataclass
class ResumeEvent:
    """Carries an external signal (human approval, timeout, webhook, …) that
    resumes a ``WAITING`` ``ExecutionInstance`` at a specific node.
    """
    event_id:    str
    instance_id: str
    node_id:     str
    arrived_at:  datetime
    payload:     dict[str, Any] = field(default_factory=dict)
    source:      str | None     = None   # e.g. "human-gate", "webhook", "timer"
