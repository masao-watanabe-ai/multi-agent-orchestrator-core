"""
nodes/action/action.py
-----------------------
Action node: creates a Task for the specified worker and returns it to the
engine.  The engine is responsible for dispatching the Task and suspending
the ExecutionInstance.

Config keys
-----------
worker : str  (required)
    Identifier of the worker/agent that should handle this task.
payload : dict  (optional, default {})
    Arbitrary data forwarded to the worker inside ``Task.payload``.

Example DSL::

    - id: summarise
      type: action
      worker: summariser-agent
      payload:
        max_tokens: 256
      next: review
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from dsl.compiler import NodeDefinition
from runtime.models import Task


def run(node: NodeDefinition, instance_id: str) -> Task:
    """Build a :class:`~runtime.models.Task` from an action node's config.

    Parameters
    ----------
    node:
        The compiled action :class:`~dsl.compiler.NodeDefinition`.
    instance_id:
        The ``instance_id`` of the owning :class:`~runtime.models.ExecutionInstance`.

    Returns
    -------
    Task
        Ready to be handed to a dispatcher.

    Raises
    ------
    ValueError
        If ``node.config`` does not contain a ``"worker"`` key.
    """
    worker: str | None = node.config.get("worker")
    if not worker:
        raise ValueError(
            f"Action node {node.id!r} requires 'worker' in config"
        )

    # Merge worker identifier into payload so dispatchers can route by it.
    extra: dict[str, Any] = dict(node.config.get("payload", {}))
    payload: dict[str, Any] = {"worker": worker, **extra}

    return Task(
        task_id=str(uuid.uuid4()),
        node_id=node.id,
        instance_id=instance_id,
        created_at=datetime.now(tz=timezone.utc),
        payload=payload,
    )
