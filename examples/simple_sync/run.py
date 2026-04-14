"""
examples/simple_sync/run.py
----------------------------
Demonstrates a fully synchronous flow:

    evaluate (decision)
        -> grade (boundary: score > 60)
            true  -> pass_node (decision)
            false -> fail_node (decision)

All nodes complete inline; no external workers or human approvals are needed.
Trace events are collected and printed at the end.

Run from the project root:
    python examples/simple_sync/run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from any directory by adding the project root to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dsl.compiler import compile_dsl
from dsl.validator import validate
from runtime.engine import start
from runtime.models import NodeState
from trace.collector import InMemoryTraceCollector
from trace.ledger_adapter import to_ledger_record

# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------

DSL = {
    "flow_id": "score_grading",
    "start_node": "evaluate",
    "nodes": [
        {
            "id":   "evaluate",
            "type": "decision",
            "next": "grade",
            "set":  {"score": 72, "subject": "mathematics"},
        },
        {
            "id":        "grade",
            "type":      "boundary",
            "true_next": "pass_node",
            "false_next": "fail_node",
            "expression": "score > 60",
        },
        {
            "id":   "pass_node",
            "type": "decision",
            "set":  {"result": "PASS", "grade": "C"},
        },
        {
            "id":   "fail_node",
            "type": "decision",
            "set":  {"result": "FAIL", "grade": "F"},
        },
    ],
}

validate(DSL)
flow = compile_dsl(DSL)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

collector = InMemoryTraceCollector()
instance = start(flow, context={}, emitter=collector)

assert instance.status == NodeState.SUCCEEDED

print("=== Result ===")
print(f"  status  : {instance.status.value}")
print(f"  score   : {instance.context['score']}")
print(f"  result  : {instance.context['result']}")
print(f"  grade   : {instance.context['grade']}")

# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

print("\n=== Trace ({} events) ===".format(len(collector)))
for ev in collector.list_events():
    node_label = ev.node_id or "(flow)"
    payload_str = ", ".join(f"{k}={v!r}" for k, v in ev.payload.items())
    print(f"  {ev.event_type:<25}  node={node_label:<12}  {payload_str}")

# ---------------------------------------------------------------------------
# Ledger records (plain dicts suitable for JSON logging)
# ---------------------------------------------------------------------------

print("\n=== Ledger records ===")
for ev in collector.by_type("boundary.triggered"):
    record = to_ledger_record(ev)
    print(f"  boundary.triggered -> next_id={record['payload']['next_id']!r}"
          f"  at {record['timestamp']}")
