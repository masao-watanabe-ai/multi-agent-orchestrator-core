"""
examples/async_action/run.py
-----------------------------
Demonstrates the action -> WAITING -> resume pattern.

Flow:

    prepare (decision)
        -> classify (action: worker="text_classifier")
            -> record (decision)

1. start()  — runs 'prepare', reaches 'classify', dispatches a Task, returns WAITING.
2. A simulated worker inspects the dispatched task and produces a result.
3. resume() with TaskCompletedEvent — continues from 'record', returns SUCCEEDED.

A second run shows the TaskFailedEvent path, which halts the instance immediately.

Run from the project root:
    python examples/async_action/run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dsl.compiler import compile_dsl
from dsl.validator import validate
from execution.dispatcher import InMemoryDispatcher
from runtime.engine import resume, start
from runtime.models import NodeState
from runtime.resume import TaskCompletedEvent, TaskFailedEvent
from trace.collector import InMemoryTraceCollector

# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------

DSL = {
    "flow_id": "text_classification",
    "start_node": "prepare",
    "nodes": [
        {
            "id":   "prepare",
            "type": "decision",
            "next": "classify",
            "set":  {"text": "urgent: server is down"},
        },
        {
            "id":     "classify",
            "type":   "action",
            "next":   "record",
            "worker": "text_classifier",
        },
        {
            "id":   "record",
            "type": "decision",
            "set":  {"logged": True},
        },
    ],
}

validate(DSL)
flow = compile_dsl(DSL)

# ---------------------------------------------------------------------------
# Helper: simulate a worker processing a dispatched task
# ---------------------------------------------------------------------------

def simulate_worker(dispatcher: InMemoryDispatcher) -> dict:
    """Return a fixed classification result for the most recently dispatched task.

    In a real system the worker would receive the task via a queue, perform
    actual inference, and publish a TaskCompletedEvent.  Here we return a
    hard-coded result to keep the example self-contained.
    """
    task = dispatcher.tasks[-1]
    _ = task  # real worker would read task.payload for inputs
    return {"label": "urgent", "confidence": 0.97}


# ---------------------------------------------------------------------------
# Path 1: successful classification
# ---------------------------------------------------------------------------

print("=== Path 1: TaskCompletedEvent ===")

dispatcher = InMemoryDispatcher()
collector  = InMemoryTraceCollector()

instance = start(flow, context={}, dispatcher=dispatcher, emitter=collector)

print(f"  After start()  : status={instance.status.value}")
print(f"  Tasks in queue : {len(dispatcher.tasks)}")
print(f"  Task worker    : {dispatcher.tasks[0].payload['worker']}")

# Simulate the worker finishing and producing a result.
result = simulate_worker(dispatcher)
print(f"  Worker result  : {result}")

event = TaskCompletedEvent(
    instance_id=instance.instance_id,
    node_id="classify",
    payload={"result": result},
)
instance = resume(flow, instance, event, dispatcher=dispatcher, emitter=collector)

print(f"  After resume() : status={instance.status.value}")
print(f"  Classification : {instance.context['classify']}")
print(f"  Logged         : {instance.context['logged']}")

print(f"\n  Trace ({len(collector)} events):")
for ev in collector.list_events():
    node_label = ev.node_id or "(flow)"
    print(f"    {ev.event_type:<25}  {node_label}")


# ---------------------------------------------------------------------------
# Path 2: worker failure
# ---------------------------------------------------------------------------

print("\n=== Path 2: TaskFailedEvent ===")

dispatcher2 = InMemoryDispatcher()
collector2  = InMemoryTraceCollector()

instance2 = start(flow, context={}, dispatcher=dispatcher2, emitter=collector2)

print(f"  After start()  : status={instance2.status.value}")

fail_event = TaskFailedEvent(
    instance_id=instance2.instance_id,
    node_id="classify",
    error="model service unavailable (HTTP 503)",
)
instance2 = resume(flow, instance2, fail_event, dispatcher=dispatcher2, emitter=collector2)

print(f"  After resume() : status={instance2.status.value}")
print(f"  Node error     : {instance2.node_states['classify'].error}")

flow_failed_events = collector2.by_type("flow.failed")
print(f"  flow.failed emitted: {len(flow_failed_events) == 1}")
