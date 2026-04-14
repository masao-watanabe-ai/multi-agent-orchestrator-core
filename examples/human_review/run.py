"""
examples/human_review/run.py
-----------------------------
Demonstrates the human_gate node: the instance suspends pending a human
decision, then continues or halts depending on the outcome.

Flow:

    flag (decision)
        -> review_gate (human_gate)
            -> process (decision)

Two paths are shown back to back:
  - Path 1: reviewer approves  -> SUCCEEDED, process node runs
  - Path 2: reviewer rejects   -> FAILED, process node never runs

Run from the project root:
    python examples/human_review/run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dsl.compiler import compile_dsl
from dsl.validator import validate
from runtime.engine import resume, start
from runtime.models import NodeState
from runtime.resume import HumanApprovedEvent, HumanRejectedEvent
from trace.collector import InMemoryTraceCollector

# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------

DSL = {
    "flow_id": "expense_review",
    "start_node": "flag",
    "nodes": [
        {
            "id":   "flag",
            "type": "decision",
            "next": "review_gate",
            "set":  {"amount": 2500, "currency": "USD", "flagged_for_review": True},
        },
        {
            "id":   "review_gate",
            "type": "human_gate",
            "next": "process",
        },
        {
            "id":   "process",
            "type": "decision",
            "set":  {"processed": True, "status": "approved"},
        },
    ],
}

validate(DSL)
flow = compile_dsl(DSL)

# ---------------------------------------------------------------------------
# Path 1: approved
# ---------------------------------------------------------------------------

print("=== Path 1: HumanApprovedEvent ===")

collector = InMemoryTraceCollector()
instance  = start(flow, context={}, emitter=collector)

print(f"  After start()    : status={instance.status.value}")
print(f"  Amount flagged   : {instance.context['amount']} {instance.context['currency']}")
print(f"  Waiting at node  : "
      + next(nid for nid, ns in instance.node_states.items()
             if ns.state == NodeState.WAITING))

approve_event = HumanApprovedEvent(
    instance_id=instance.instance_id,
    node_id="review_gate",
    approver="alice",
)
instance = resume(flow, instance, approve_event, emitter=collector)

print(f"  After resume()   : status={instance.status.value}")
print(f"  Gate context     : {instance.context['review_gate']}")
print(f"  Processed        : {instance.context.get('processed')}")

print(f"\n  Trace ({len(collector)} events):")
for ev in collector.list_events():
    node_label = ev.node_id or "(flow)"
    extra = ""
    if ev.event_type == "human_gate.approved":
        extra = f"  approver={ev.payload['approver']!r}"
    print(f"    {ev.event_type:<25}  {node_label}{extra}")


# ---------------------------------------------------------------------------
# Path 2: rejected
# ---------------------------------------------------------------------------

print("\n=== Path 2: HumanRejectedEvent ===")

collector2 = InMemoryTraceCollector()
instance2  = start(flow, context={}, emitter=collector2)

print(f"  After start()    : status={instance2.status.value}")

reject_event = HumanRejectedEvent(
    instance_id=instance2.instance_id,
    node_id="review_gate",
    reason="exceeds quarterly budget",
    approver="bob",
)
instance2 = resume(flow, instance2, reject_event, emitter=collector2)

print(f"  After resume()   : status={instance2.status.value}")
print(f"  Gate context     : {instance2.context['review_gate']}")
print(f"  Processed node ran: {'process' in instance2.node_states}")

print(f"\n  Trace ({len(collector2)} events):")
for ev in collector2.list_events():
    node_label = ev.node_id or "(flow)"
    extra = ""
    if ev.event_type == "human_gate.rejected":
        extra = f"  reason={ev.payload['reason']!r}"
    print(f"    {ev.event_type:<25}  {node_label}{extra}")
