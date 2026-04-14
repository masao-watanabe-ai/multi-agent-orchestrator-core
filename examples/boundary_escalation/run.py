"""
examples/boundary_escalation/run.py
-------------------------------------
Demonstrates boundary-based policy escalation combined with state persistence.

Flow:

    init (decision)
        -> amount_gate (boundary: amount > 1000)
            true  -> manual_review (human_gate) -> finalize (decision)
            false -> auto_approve  (decision)   -> finalize (decision)

Two scenarios are run:

  Scenario A (amount=500):
    boundary routes to auto_approve -> finalize synchronously; no suspension.

  Scenario B (amount=2500):
    boundary routes to manual_review (human_gate) -> WAITING.
    The instance is saved to a JsonFileStateStore, simulating a process
    boundary (e.g. the web request ends and state must survive until a
    reviewer responds hours later).
    The instance is then reloaded and resumed with HumanApprovedEvent.

Run from the project root:
    python examples/boundary_escalation/run.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dsl.compiler import compile_dsl
from dsl.validator import validate
from runtime.engine import resume, start
from runtime.models import NodeState
from runtime.resume import HumanApprovedEvent
from state.store import JsonFileStateStore
from trace.collector import InMemoryTraceCollector

# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------

DSL = {
    "flow_id": "payment_approval",
    "start_node": "init",
    "nodes": [
        {
            "id":   "init",
            "type": "decision",
            "next": "amount_gate",
            "set":  {"currency": "USD"},
        },
        {
            "id":         "amount_gate",
            "type":       "boundary",
            "true_next":  "manual_review",
            "false_next": "auto_approve",
            "expression": "amount > 1000",
        },
        {
            "id":   "manual_review",
            "type": "human_gate",
            "next": "finalize",
        },
        {
            "id":   "auto_approve",
            "type": "decision",
            "next": "finalize",
            "set":  {"approval_method": "automatic"},
        },
        {
            "id":   "finalize",
            "type": "decision",
            "set":  {"status": "complete"},
        },
    ],
}

validate(DSL)
flow = compile_dsl(DSL)

# ---------------------------------------------------------------------------
# Scenario A: low amount — auto-approved synchronously
# ---------------------------------------------------------------------------

print("=== Scenario A: amount=500 (auto-approve) ===")

collector_a = InMemoryTraceCollector()
instance_a  = start(flow, context={"amount": 500}, emitter=collector_a)

assert instance_a.status == NodeState.SUCCEEDED
print(f"  status            : {instance_a.status.value}")
print(f"  approval_method   : {instance_a.context['approval_method']}")
print(f"  status (finalize) : {instance_a.context['status']}")

boundary_ev = collector_a.by_type("boundary.triggered")[0]
print(f"  boundary next_id  : {boundary_ev.payload['next_id']!r}")

print(f"\n  Trace ({len(collector_a)} events):")
for ev in collector_a.list_events():
    node_label = ev.node_id or "(flow)"
    print(f"    {ev.event_type:<25}  {node_label}")


# ---------------------------------------------------------------------------
# Scenario B: high amount — escalated to human_gate, persisted, then resumed
# ---------------------------------------------------------------------------

print("\n=== Scenario B: amount=2500 (manual review required) ===")

with tempfile.TemporaryDirectory() as state_dir:
    store = JsonFileStateStore(state_dir)

    # --- Phase 1: start the flow and save the WAITING instance ---
    collector_b = InMemoryTraceCollector()
    instance_b  = start(flow, context={"amount": 2500}, emitter=collector_b)

    assert instance_b.status == NodeState.WAITING
    print(f"  After start()     : status={instance_b.status.value}")

    boundary_ev_b = collector_b.by_type("boundary.triggered")[0]
    print(f"  boundary next_id  : {boundary_ev_b.payload['next_id']!r}")

    waiting_node = next(
        nid for nid, ns in instance_b.node_states.items()
        if ns.state == NodeState.WAITING
    )
    print(f"  Waiting at node   : {waiting_node!r}")

    store.save_instance(instance_b)
    saved_id = instance_b.instance_id
    print(f"  Saved instance    : {saved_id}")

    state_files = list(Path(state_dir).glob("*.json"))
    print(f"  JSON files on disk: {len(state_files)}")

    # --- Phase 2: simulate a process restart — reload from disk ---
    print("\n  [simulating process restart — reloading from disk]")
    loaded = store.load_instance(saved_id)
    assert loaded.status == NodeState.WAITING
    print(f"  Loaded status     : {loaded.status.value}")
    print(f"  amount in context : {loaded.context['amount']}")

    # --- Phase 3: reviewer approves ---
    approve_event = HumanApprovedEvent(
        instance_id=loaded.instance_id,
        node_id="manual_review",
        approver="carol",
    )
    collector_b2 = InMemoryTraceCollector()
    result = resume(flow, loaded, approve_event, emitter=collector_b2)

    assert result.status == NodeState.SUCCEEDED
    print(f"\n  After resume()    : status={result.status.value}")
    print(f"  Gate context      : {result.context['manual_review']}")
    print(f"  status (finalize) : {result.context['status']}")

    # Persist the final state.
    store.update_instance(result)
    print(f"  Updated store     : OK")

    print(f"\n  Resume trace ({len(collector_b2)} events):")
    for ev in collector_b2.list_events():
        node_label = ev.node_id or "(flow)"
        print(f"    {ev.event_type:<25}  {node_label}")
