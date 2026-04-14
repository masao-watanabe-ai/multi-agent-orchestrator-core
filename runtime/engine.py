"""
runtime/engine.py
-----------------
Minimal synchronous RuntimeEngine for condition / decision / action workflows.

Supported node types
--------------------
condition   — evaluate an expression and branch
decision    — write values to context and advance
action      — create a Task, dispatch it, and suspend the instance (WAITING)
human_gate  — suspend for human approval; resumed via HumanApprovedEvent /
              HumanRejectedEvent
boundary    — expression-based branching (same logic as condition, distinct
              semantic)

All other types raise :class:`UnsupportedNodeTypeError`.

Public API
----------
start(flow, context, *, dispatcher, emitter)            -> ExecutionInstance
resume(flow, instance, event, *, dispatcher, emitter)   -> ExecutionInstance

Trace events emitted
--------------------
flow.started        — instance created, execution about to begin
flow.succeeded      — all nodes completed inline
flow.waiting        — an action/human_gate suspended the instance
flow.failed         — an exception or failure event halted the instance
flow.resumed        — resume() called on a WAITING instance
node.started        — a node began executing
node.succeeded      — a node completed successfully
node.waiting        — action/human_gate node suspended (WAITING state)
node.failed         — a node raised or received a failure event
action.dispatched   — a Task was dispatched by an action node
boundary.triggered  — a boundary node evaluated (payload: next_id)
human_gate.approved — a HumanApprovedEvent was processed
human_gate.rejected — a HumanRejectedEvent was processed
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Union

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import DispatcherProtocol
from nodes.action import action as action_node
from nodes.decision import boundary as boundary_node
from nodes.decision import condition as condition_node
from nodes.decision import decision as decision_node
from nodes.decision import human_gate as human_gate_node
from runtime.models import ExecutionInstance, NodeExecutionState, NodeState
from runtime.resume import (
    HumanApprovedEvent,
    HumanRejectedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
)
from trace.emitter import TraceEmitterProtocol
from trace.model import TraceEvent

# Internal sentinel: returned by _execute_node when a node was dispatched
# or suspended and the instance should stop the execution loop.
_WAIT = object()

# Union type for all accepted resume events
ResumeEvent = Union[TaskCompletedEvent, TaskFailedEvent, HumanApprovedEvent, HumanRejectedEvent]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UnsupportedNodeTypeError(NotImplementedError):
    """Raised when the engine encounters a node type it cannot handle.

    Attributes
    ----------
    node_type:
        The unsupported type string (e.g. ``"human_gate"``).
    node_id:
        The id of the node that triggered the error.
    """

    def __init__(self, node_type: str, node_id: str) -> None:
        super().__init__(
            f"Node type {node_type!r} is not supported by this engine "
            f"(node_id={node_id!r}).  "
            "Supported types: action, boundary, condition, decision, human_gate."
        )
        self.node_type = node_type
        self.node_id = node_id


class InstanceMismatchError(ValueError):
    """Raised when a resume event's instance_id does not match the instance.

    Attributes
    ----------
    event_instance_id:
        The ``instance_id`` carried by the event.
    instance_id:
        The ``instance_id`` of the target ``ExecutionInstance``.
    """

    def __init__(self, event_instance_id: str, instance_id: str) -> None:
        super().__init__(
            f"Event instance_id {event_instance_id!r} does not match "
            f"ExecutionInstance.instance_id {instance_id!r}."
        )
        self.event_instance_id = event_instance_id
        self.instance_id = instance_id


class NodeNotWaitingError(ValueError):
    """Raised when resume targets a node that is not in WAITING state.

    Attributes
    ----------
    node_id:
        The id of the node that was targeted.
    actual_state:
        The node's current :class:`~runtime.models.NodeState`.
    """

    def __init__(self, node_id: str, actual_state: NodeState) -> None:
        super().__init__(
            f"Node {node_id!r} is not in WAITING state "
            f"(current state: {actual_state!r})."
        )
        self.node_id = node_id
        self.actual_state = actual_state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(
    flow: FlowDefinition,
    context: dict[str, Any] | None = None,
    *,
    dispatcher: DispatcherProtocol | None = None,
    emitter: TraceEmitterProtocol | None = None,
) -> ExecutionInstance:
    """Create and synchronously execute a new workflow instance.

    Traverses *flow* starting from ``flow.start_node``.  ``condition`` and
    ``decision`` nodes execute inline.  When an ``action`` node is reached,
    a :class:`~runtime.models.Task` is dispatched and the instance is
    returned immediately with ``status = NodeState.WAITING``.

    Parameters
    ----------
    flow:
        Compiled :class:`~dsl.compiler.FlowDefinition` to execute.
    context:
        Initial execution context.  A shallow copy is stored on the
        instance so the caller's dict is not mutated.  Defaults to ``{}``.
    dispatcher:
        Required when the flow contains ``action`` nodes.  Receives the
        generated :class:`~runtime.models.Task`.
    emitter:
        Optional trace sink.  When provided, structured
        :class:`~trace.model.TraceEvent` objects are emitted at each major
        execution step.

    Returns
    -------
    ExecutionInstance
        ``status`` is one of:

        * ``NodeState.SUCCEEDED`` — all nodes completed inline.
        * ``NodeState.WAITING``   — an action node was dispatched.
        * ``NodeState.FAILED``    — an exception escaped a node handler.

    Raises
    ------
    UnsupportedNodeTypeError
        If a node with an unsupported ``type`` is encountered.
    ValueError
        If an ``action`` node is reached but *dispatcher* is ``None``.
    """
    now = datetime.now(tz=timezone.utc)
    instance = ExecutionInstance(
        instance_id=str(uuid.uuid4()),
        workflow_id=flow.flow_id,
        created_at=now,
        updated_at=now,
        status=NodeState.RUNNING,
        context=dict(context) if context else {},
    )
    _emit(emitter, instance.instance_id, None, "flow.started", {"workflow_id": flow.flow_id})
    return _run_loop(flow, instance, flow.start_node, dispatcher, emitter)


def resume(
    flow: FlowDefinition,
    instance: ExecutionInstance,
    event: ResumeEvent,
    *,
    dispatcher: DispatcherProtocol | None = None,
    emitter: TraceEmitterProtocol | None = None,
) -> ExecutionInstance:
    """Resume a WAITING ``ExecutionInstance`` using an external task event.

    Validates the event, updates the suspended node's state, and continues
    execution from ``node.next``.

    Parameters
    ----------
    flow:
        The same :class:`~dsl.compiler.FlowDefinition` used to create
        *instance*.
    instance:
        The WAITING :class:`~runtime.models.ExecutionInstance` to resume.
        Mutated in-place.
    event:
        A :class:`~runtime.resume.TaskCompletedEvent` or
        :class:`~runtime.resume.TaskFailedEvent`.
    dispatcher:
        Required when further ``action`` nodes follow the resumed node.
    emitter:
        Optional trace sink.  Receives ``flow.resumed`` and subsequent
        events for this resume pass.

    Returns
    -------
    ExecutionInstance
        The same *instance*, updated.  ``status`` is one of:

        * ``NodeState.SUCCEEDED`` — execution completed.
        * ``NodeState.WAITING``   — another action node was dispatched.
        * ``NodeState.FAILED``    — the event reported failure, or an
          exception escaped during resumed execution.

    Raises
    ------
    InstanceMismatchError
        If ``event.instance_id != instance.instance_id``.
    NodeNotWaitingError
        If the targeted node is not currently in ``WAITING`` state.
    """
    # --- validation --------------------------------------------------------
    if event.instance_id != instance.instance_id:
        raise InstanceMismatchError(event.instance_id, instance.instance_id)

    ns = instance.node_states.get(event.node_id)
    actual_state = ns.state if ns is not None else NodeState.PENDING
    if actual_state != NodeState.WAITING:
        raise NodeNotWaitingError(event.node_id, actual_state)

    node = flow.nodes_by_id[event.node_id]

    _emit(emitter, instance.instance_id, event.node_id, "flow.resumed",
          {"event_type": type(event).__name__})

    # --- failure events: halt the instance --------------------------------
    if isinstance(event, TaskFailedEvent):
        _finish_node_state(ns, NodeState.FAILED, error=event.error)  # type: ignore[arg-type]
        _emit(emitter, instance.instance_id, event.node_id, "node.failed",
              {"error": event.error})
        _emit(emitter, instance.instance_id, None, "flow.failed")
        instance.status = NodeState.FAILED
        instance.updated_at = datetime.now(tz=timezone.utc)
        return instance

    if isinstance(event, HumanRejectedEvent):
        _finish_node_state(
            ns,  # type: ignore[arg-type]
            NodeState.FAILED,
            error=event.reason or "rejected by human",
        )
        instance.context[event.node_id] = {
            "approved": False,
            "reason": event.reason,
            "approver": event.approver,
        }
        _emit(emitter, instance.instance_id, event.node_id, "human_gate.rejected",
              {"reason": event.reason, "approver": event.approver})
        _emit(emitter, instance.instance_id, None, "flow.failed")
        instance.status = NodeState.FAILED
        instance.updated_at = datetime.now(tz=timezone.utc)
        return instance

    # --- success events: advance to node.next -----------------------------
    _finish_node_state(ns, NodeState.SUCCEEDED)  # type: ignore[arg-type]

    if isinstance(event, HumanApprovedEvent):
        instance.context[event.node_id] = {
            "approved": True,
            "approver": event.approver,
        }
        _emit(emitter, instance.instance_id, event.node_id, "human_gate.approved",
              {"approver": event.approver})
    else:
        # TaskCompletedEvent: store payload["result"] under node_id
        instance.context[event.node_id] = event.payload.get("result")

    # Continue execution from node.next (None → flow ends here).
    return _run_loop(flow, instance, node.next, dispatcher, emitter)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_loop(
    flow: FlowDefinition,
    instance: ExecutionInstance,
    start_id: str | None,
    dispatcher: DispatcherProtocol | None,
    emitter: TraceEmitterProtocol | None = None,
) -> ExecutionInstance:
    """Execute nodes from *start_id*, updating *instance* in-place.

    Shared by :func:`start` and :func:`resume`.
    """
    current_id = start_id
    instance.status = NodeState.RUNNING

    try:
        while current_id is not None:
            node = flow.nodes_by_id[current_id]
            result = _execute_node(node, instance, dispatcher, emitter)
            if result is _WAIT:
                _emit(emitter, instance.instance_id, None, "flow.waiting")
                instance.status = NodeState.WAITING
                instance.updated_at = datetime.now(tz=timezone.utc)
                return instance
            current_id = result  # type: ignore[assignment]

        _emit(emitter, instance.instance_id, None, "flow.succeeded")
        instance.status = NodeState.SUCCEEDED

    except Exception:
        _emit(emitter, instance.instance_id, None, "flow.failed")
        instance.status = NodeState.FAILED
        instance.updated_at = datetime.now(tz=timezone.utc)
        raise

    instance.updated_at = datetime.now(tz=timezone.utc)
    return instance


def _execute_node(
    node: NodeDefinition,
    instance: ExecutionInstance,
    dispatcher: DispatcherProtocol | None,
    emitter: TraceEmitterProtocol | None = None,
) -> str | None | object:
    """Run a single node and update ``instance.node_states``.

    Returns the next node id, ``None`` (end of flow), or the ``_WAIT``
    sentinel when the instance should suspend.
    """
    ns = _start_node_state(node.id, instance)
    _emit(emitter, instance.instance_id, node.id, "node.started", {"node_type": node.type})

    try:
        if node.type == "action":
            if dispatcher is None:
                raise ValueError(
                    f"Action node {node.id!r} requires a dispatcher. "
                    "Pass dispatcher= to engine.start() or engine.resume()."
                )
            task = action_node.run(node, instance.instance_id)
            dispatcher.dispatch(task)
            _emit(emitter, instance.instance_id, node.id, "action.dispatched",
                  {"task_id": task.task_id, "worker": task.payload.get("worker")})
            _finish_node_state(ns, NodeState.WAITING)
            _emit(emitter, instance.instance_id, node.id, "node.waiting")
            return _WAIT

        if node.type == "human_gate":
            human_gate_node.run(node)
            _finish_node_state(ns, NodeState.WAITING)
            _emit(emitter, instance.instance_id, node.id, "node.waiting")
            return _WAIT

        next_id = _dispatch(node, instance.context)

        if node.type == "boundary":
            _emit(emitter, instance.instance_id, node.id, "boundary.triggered",
                  {"next_id": next_id})

        _finish_node_state(ns, NodeState.SUCCEEDED)
        _emit(emitter, instance.instance_id, node.id, "node.succeeded")
        return next_id

    except Exception as exc:
        _finish_node_state(ns, NodeState.FAILED, error=str(exc))
        _emit(emitter, instance.instance_id, node.id, "node.failed", {"error": str(exc)})
        raise


def _dispatch(node: NodeDefinition, context: dict[str, Any]) -> str | None:
    """Route synchronous nodes to their handlers."""
    if node.type == "boundary":
        return boundary_node.run(node, context)
    if node.type == "condition":
        return condition_node.run(node, context)
    if node.type == "decision":
        return decision_node.run(node, context)
    raise UnsupportedNodeTypeError(node.type, node.id)


def _start_node_state(
    node_id: str, instance: ExecutionInstance
) -> NodeExecutionState:
    ns = NodeExecutionState(
        node_id=node_id,
        state=NodeState.RUNNING,
        started_at=datetime.now(tz=timezone.utc),
        attempt=1,
    )
    instance.node_states[node_id] = ns
    return ns


def _finish_node_state(
    ns: NodeExecutionState,
    state: NodeState,
    *,
    error: str | None = None,
) -> None:
    ns.state = state
    ns.finished_at = datetime.now(tz=timezone.utc)
    ns.error = error


def _emit(
    emitter: TraceEmitterProtocol | None,
    instance_id: str,
    node_id: str | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Fire a trace event if *emitter* is not ``None``."""
    if emitter is None:
        return
    emitter.emit(TraceEvent(
        instance_id=instance_id,
        node_id=node_id,
        event_type=event_type,
        timestamp=datetime.now(tz=timezone.utc),
        payload=payload or {},
    ))
