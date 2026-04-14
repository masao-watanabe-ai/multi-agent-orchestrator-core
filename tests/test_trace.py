"""
tests/test_trace.py
--------------------
Tests for:
  - trace/model.py          (TraceEvent)
  - trace/emitter.py        (TraceEmitterProtocol, TraceEmitter)
  - trace/collector.py      (InMemoryTraceCollector)
  - trace/ledger_adapter.py (to_ledger_record)
  - runtime/engine.py       (trace emission at key execution points)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import InMemoryDispatcher
from runtime.engine import resume, start
from runtime.models import NodeState
from runtime.resume import (
    HumanApprovedEvent,
    HumanRejectedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
)
from trace.collector import InMemoryTraceCollector
from trace.emitter import TraceEmitter, TraceEmitterProtocol
from trace.ledger_adapter import to_ledger_record
from trace.model import TraceEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


def _decision_flow() -> FlowDefinition:
    """Simple two-node decision flow that always succeeds synchronously."""
    return _flow("sync_flow", "d1", [
        NodeDefinition(id="d1", type="decision", next="d2", config={"set": {"step": 1}}),
        NodeDefinition(id="d2", type="decision", config={"set": {"step": 2}}),
    ])


def _action_flow() -> FlowDefinition:
    """Flow with one action node that suspends the instance."""
    return _flow("action_flow", "a1", [
        NodeDefinition(id="a1", type="action", config={"worker": "my_worker"}),
    ])


def _action_then_decision_flow() -> FlowDefinition:
    """action → decision; lets us test a full resume cycle."""
    return _flow("action_decision_flow", "a1", [
        NodeDefinition(id="a1", type="action", next="d1", config={"worker": "my_worker"}),
        NodeDefinition(id="d1", type="decision", config={"set": {"done": True}}),
    ])


def _human_gate_flow() -> FlowDefinition:
    """human_gate → decision; human approval continues to decision."""
    return _flow("hg_flow", "hg1", [
        NodeDefinition(id="hg1", type="human_gate", next="d1", config={}),
        NodeDefinition(id="d1", type="decision", config={"set": {"approved": True}}),
    ])


def _boundary_flow() -> FlowDefinition:
    """boundary → two decision branches."""
    return _flow("boundary_flow", "gate", [
        NodeDefinition(
            id="gate", type="boundary",
            true_next="high", false_next="low",
            config={"expression": "score > 50"},
        ),
        NodeDefinition(id="high", type="decision", config={"set": {"band": "high"}}),
        NodeDefinition(id="low",  type="decision", config={"set": {"band": "low"}}),
    ])


# ---------------------------------------------------------------------------
# TraceEvent
# ---------------------------------------------------------------------------

class TestTraceModel:
    def test_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        ev = TraceEvent(instance_id="i1", node_id="n1", event_type="node.started", timestamp=now)
        assert ev.instance_id == "i1"
        assert ev.node_id == "n1"
        assert ev.event_type == "node.started"
        assert ev.timestamp == now

    def test_payload_defaults_to_empty_dict(self):
        ev = TraceEvent(
            instance_id="i1", node_id=None,
            event_type="flow.started", timestamp=datetime.now(tz=timezone.utc),
        )
        assert ev.payload == {}

    def test_node_id_can_be_none(self):
        ev = TraceEvent(
            instance_id="i1", node_id=None,
            event_type="flow.started", timestamp=datetime.now(tz=timezone.utc),
        )
        assert ev.node_id is None

    def test_payload_stored(self):
        ev = TraceEvent(
            instance_id="i1", node_id="n1",
            event_type="boundary.triggered",
            timestamp=datetime.now(tz=timezone.utc),
            payload={"next_id": "high"},
        )
        assert ev.payload["next_id"] == "high"


# ---------------------------------------------------------------------------
# TraceEmitter
# ---------------------------------------------------------------------------

class TestTraceEmitter:
    def test_starts_empty(self):
        emitter = TraceEmitter()
        assert len(emitter) == 0
        assert emitter.list_events() == []

    def test_emit_appends(self):
        emitter = TraceEmitter()
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="flow.started", timestamp=datetime.now(tz=timezone.utc))
        emitter.emit(ev)
        assert len(emitter) == 1
        assert emitter.list_events()[0] is ev

    def test_list_events_returns_copy(self):
        emitter = TraceEmitter()
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="x", timestamp=datetime.now(tz=timezone.utc))
        emitter.emit(ev)
        lst = emitter.list_events()
        lst.clear()
        assert len(emitter) == 1

    def test_multiple_events_ordered(self):
        emitter = TraceEmitter()
        for i in range(3):
            emitter.emit(TraceEvent(
                instance_id="i1", node_id=None,
                event_type=f"ev{i}", timestamp=datetime.now(tz=timezone.utc),
            ))
        types = [e.event_type for e in emitter.list_events()]
        assert types == ["ev0", "ev1", "ev2"]

    def test_satisfies_protocol(self):
        emitter = TraceEmitter()
        assert isinstance(emitter, TraceEmitterProtocol)

    def test_collector_satisfies_protocol(self):
        collector = InMemoryTraceCollector()
        assert isinstance(collector, TraceEmitterProtocol)


# ---------------------------------------------------------------------------
# InMemoryTraceCollector
# ---------------------------------------------------------------------------

class TestInMemoryTraceCollector:
    def test_starts_empty(self):
        c = InMemoryTraceCollector()
        assert len(c) == 0

    def test_emit_and_list_all(self):
        c = InMemoryTraceCollector()
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="flow.started", timestamp=datetime.now(tz=timezone.utc))
        c.emit(ev)
        assert c.list_events() == [ev]

    def test_list_by_instance_id(self):
        c = InMemoryTraceCollector()
        ev1 = TraceEvent(instance_id="i1", node_id=None,
                         event_type="flow.started", timestamp=datetime.now(tz=timezone.utc))
        ev2 = TraceEvent(instance_id="i2", node_id=None,
                         event_type="flow.started", timestamp=datetime.now(tz=timezone.utc))
        c.emit(ev1)
        c.emit(ev2)
        assert c.list_events("i1") == [ev1]
        assert c.list_events("i2") == [ev2]

    def test_list_none_returns_all(self):
        c = InMemoryTraceCollector()
        for i in range(3):
            c.emit(TraceEvent(instance_id=f"i{i}", node_id=None,
                              event_type="x", timestamp=datetime.now(tz=timezone.utc)))
        assert len(c.list_events(None)) == 3

    def test_by_type_filtered(self):
        c = InMemoryTraceCollector()
        c.emit(TraceEvent(instance_id="i1", node_id="n1",
                          event_type="node.started", timestamp=datetime.now(tz=timezone.utc)))
        c.emit(TraceEvent(instance_id="i1", node_id="n1",
                          event_type="node.succeeded", timestamp=datetime.now(tz=timezone.utc)))
        c.emit(TraceEvent(instance_id="i1", node_id=None,
                          event_type="flow.succeeded", timestamp=datetime.now(tz=timezone.utc)))
        assert len(c.by_type("node.started")) == 1
        assert len(c.by_type("flow.succeeded")) == 1
        assert len(c.by_type("node.failed")) == 0

    def test_by_type_with_instance_filter(self):
        c = InMemoryTraceCollector()
        c.emit(TraceEvent(instance_id="i1", node_id=None,
                          event_type="flow.started", timestamp=datetime.now(tz=timezone.utc)))
        c.emit(TraceEvent(instance_id="i2", node_id=None,
                          event_type="flow.started", timestamp=datetime.now(tz=timezone.utc)))
        assert len(c.by_type("flow.started", "i1")) == 1

    def test_event_types_helper(self):
        c = InMemoryTraceCollector()
        for t in ["flow.started", "node.started", "flow.succeeded"]:
            c.emit(TraceEvent(instance_id="i1", node_id=None,
                              event_type=t, timestamp=datetime.now(tz=timezone.utc)))
        assert c.event_types() == ["flow.started", "node.started", "flow.succeeded"]

    def test_list_events_returns_copy(self):
        c = InMemoryTraceCollector()
        c.emit(TraceEvent(instance_id="i1", node_id=None,
                          event_type="x", timestamp=datetime.now(tz=timezone.utc)))
        lst = c.list_events()
        lst.clear()
        assert len(c) == 1


# ---------------------------------------------------------------------------
# LedgerAdapter
# ---------------------------------------------------------------------------

class TestLedgerAdapter:
    def test_keys_present(self):
        ev = TraceEvent(
            instance_id="i1", node_id="n1",
            event_type="node.succeeded",
            timestamp=datetime.now(tz=timezone.utc),
            payload={"node_type": "decision"},
        )
        record = to_ledger_record(ev)
        assert set(record.keys()) == {"instance_id", "node_id", "event_type", "timestamp", "payload"}

    def test_values_copied(self):
        ev = TraceEvent(
            instance_id="i1", node_id="n1",
            event_type="node.succeeded",
            timestamp=datetime.now(tz=timezone.utc),
            payload={"node_type": "decision"},
        )
        record = to_ledger_record(ev)
        assert record["instance_id"] == "i1"
        assert record["node_id"] == "n1"
        assert record["event_type"] == "node.succeeded"
        assert record["payload"] == {"node_type": "decision"}

    def test_timestamp_is_iso_string(self):
        now = datetime.now(tz=timezone.utc)
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="flow.started", timestamp=now)
        record = to_ledger_record(ev)
        assert isinstance(record["timestamp"], str)
        assert datetime.fromisoformat(record["timestamp"]) == now

    def test_node_id_none_preserved(self):
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="flow.started", timestamp=datetime.now(tz=timezone.utc))
        assert to_ledger_record(ev)["node_id"] is None

    def test_payload_is_independent_copy(self):
        original_payload = {"k": "v"}
        ev = TraceEvent(instance_id="i1", node_id=None,
                        event_type="x", timestamp=datetime.now(tz=timezone.utc),
                        payload=original_payload)
        record = to_ledger_record(ev)
        record["payload"]["k"] = "mutated"
        assert ev.payload["k"] == "v"


# ---------------------------------------------------------------------------
# Sync flow trace
# ---------------------------------------------------------------------------

class TestSyncFlowTrace:
    def test_flow_started_emitted(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert "flow.started" in c.event_types()

    def test_flow_succeeded_emitted(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert "flow.succeeded" in c.event_types()

    def test_node_started_emitted_for_each_node(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert len(c.by_type("node.started")) == 2

    def test_node_succeeded_emitted_for_each_node(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert len(c.by_type("node.succeeded")) == 2

    def test_flow_started_is_first_event(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert c.event_types()[0] == "flow.started"

    def test_flow_succeeded_is_last_event(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        assert c.event_types()[-1] == "flow.succeeded"

    def test_all_events_share_instance_id(self):
        c = InMemoryTraceCollector()
        instance = start(_decision_flow(), {}, emitter=c)
        for ev in c.list_events():
            assert ev.instance_id == instance.instance_id

    def test_node_started_carries_node_type(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        for ev in c.by_type("node.started"):
            assert ev.payload["node_type"] == "decision"

    def test_no_trace_without_emitter(self):
        """Engine still works when emitter is not provided."""
        instance = start(_decision_flow(), {})
        assert instance.status == NodeState.SUCCEEDED

    def test_flow_started_payload_has_workflow_id(self):
        c = InMemoryTraceCollector()
        start(_decision_flow(), {}, emitter=c)
        ev = c.by_type("flow.started")[0]
        assert ev.payload["workflow_id"] == "sync_flow"


# ---------------------------------------------------------------------------
# Action paused trace
# ---------------------------------------------------------------------------

class TestActionPausedTrace:
    def test_action_dispatched_emitted(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        assert len(c.by_type("action.dispatched")) == 1

    def test_node_waiting_emitted(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        assert len(c.by_type("node.waiting")) == 1

    def test_flow_waiting_emitted(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        assert "flow.waiting" in c.event_types()

    def test_flow_waiting_is_last_event(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        assert c.event_types()[-1] == "flow.waiting"

    def test_action_dispatched_payload_has_worker(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        ev = c.by_type("action.dispatched")[0]
        assert ev.payload["worker"] == "my_worker"

    def test_action_dispatched_payload_has_task_id(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        ev = c.by_type("action.dispatched")[0]
        assert ev.payload["task_id"] is not None

    def test_no_flow_succeeded_when_waiting(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        start(_action_flow(), {}, dispatcher=d, emitter=c)
        assert "flow.succeeded" not in c.event_types()


# ---------------------------------------------------------------------------
# Resume trace
# ---------------------------------------------------------------------------

class TestResumeTrace:
    def test_flow_resumed_emitted_on_task_completed(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1", payload={"result": 42})
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        assert "flow.resumed" in c.event_types()

    def test_flow_succeeded_after_task_completed(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1", payload={"result": 42})
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        assert "flow.succeeded" in c.event_types()

    def test_flow_failed_after_task_failed(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskFailedEvent(instance_id=instance.instance_id, node_id="a1", error="boom")
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        assert "flow.failed" in c.event_types()

    def test_node_failed_emitted_on_task_failed(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskFailedEvent(instance_id=instance.instance_id, node_id="a1", error="boom")
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        assert len(c.by_type("node.failed")) == 1

    def test_task_failed_error_in_node_failed_payload(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskFailedEvent(instance_id=instance.instance_id, node_id="a1", error="boom")
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        failed_ev = c.by_type("node.failed")[0]
        assert failed_ev.payload["error"] == "boom"

    def test_flow_resumed_carries_event_type_name(self):
        c = InMemoryTraceCollector()
        d = InMemoryDispatcher()
        flow = _action_then_decision_flow()
        instance = start(flow, {}, dispatcher=d, emitter=c)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1", payload={})
        resume(flow, instance, ev, dispatcher=d, emitter=c)
        resumed_ev = c.by_type("flow.resumed")[0]
        assert resumed_ev.payload["event_type"] == "TaskCompletedEvent"


# ---------------------------------------------------------------------------
# Human gate trace
# ---------------------------------------------------------------------------

class TestHumanGateTrace:
    def test_human_gate_approved_emitted(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        assert instance.status == NodeState.WAITING

        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1", approver="alice")
        resume(flow, instance, ev, emitter=c)
        assert "human_gate.approved" in c.event_types()

    def test_human_gate_approved_flow_succeeds(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1", approver="alice")
        resume(flow, instance, ev, emitter=c)
        assert "flow.succeeded" in c.event_types()

    def test_human_gate_approved_payload_has_approver(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1", approver="alice")
        resume(flow, instance, ev, emitter=c)
        approved_ev = c.by_type("human_gate.approved")[0]
        assert approved_ev.payload["approver"] == "alice"

    def test_human_gate_rejected_emitted(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1",
                                reason="too risky", approver="bob")
        resume(flow, instance, ev, emitter=c)
        assert "human_gate.rejected" in c.event_types()

    def test_human_gate_rejected_flow_failed(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1", reason="no")
        resume(flow, instance, ev, emitter=c)
        assert "flow.failed" in c.event_types()

    def test_human_gate_rejected_payload(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1",
                                reason="too risky", approver="bob")
        resume(flow, instance, ev, emitter=c)
        rejected_ev = c.by_type("human_gate.rejected")[0]
        assert rejected_ev.payload["reason"] == "too risky"
        assert rejected_ev.payload["approver"] == "bob"

    def test_node_waiting_emitted_for_human_gate(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        start(flow, {}, emitter=c)
        assert "node.waiting" in c.event_types()

    def test_human_gate_no_flow_succeeded_when_rejected(self):
        c = InMemoryTraceCollector()
        flow = _human_gate_flow()
        instance = start(flow, {}, emitter=c)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1", reason="no")
        resume(flow, instance, ev, emitter=c)
        assert "flow.succeeded" not in c.event_types()


# ---------------------------------------------------------------------------
# Boundary trace
# ---------------------------------------------------------------------------

class TestBoundaryTrace:
    def test_boundary_triggered_emitted(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 80}, emitter=c)
        assert "boundary.triggered" in c.event_types()

    def test_boundary_triggered_payload_next_id_true_branch(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 80}, emitter=c)
        ev = c.by_type("boundary.triggered")[0]
        assert ev.payload["next_id"] == "high"

    def test_boundary_triggered_payload_next_id_false_branch(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 20}, emitter=c)
        ev = c.by_type("boundary.triggered")[0]
        assert ev.payload["next_id"] == "low"

    def test_boundary_node_id_in_event(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 80}, emitter=c)
        ev = c.by_type("boundary.triggered")[0]
        assert ev.node_id == "gate"

    def test_multiple_boundaries_each_emit(self):
        flow = _flow("double_boundary", "b1", [
            NodeDefinition(
                id="b1", type="boundary",
                true_next="b2", false_next="out_low",
                config={"expression": "x > 10"},
            ),
            NodeDefinition(
                id="b2", type="boundary",
                true_next="out_high", false_next="out_mid",
                config={"expression": "x > 50"},
            ),
            NodeDefinition(id="out_high", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="out_mid",  type="decision", config={"set": {"band": "mid"}}),
            NodeDefinition(id="out_low",  type="decision", config={"set": {"band": "low"}}),
        ])
        c = InMemoryTraceCollector()
        start(flow, {"x": 80}, emitter=c)
        assert len(c.by_type("boundary.triggered")) == 2

    def test_single_boundary_false_only_emits_once(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 10}, emitter=c)
        assert len(c.by_type("boundary.triggered")) == 1

    def test_boundary_and_decision_both_emit_node_succeeded(self):
        c = InMemoryTraceCollector()
        start(_boundary_flow(), {"score": 80}, emitter=c)
        # gate (boundary) + high (decision) = 2 node.succeeded events
        assert len(c.by_type("node.succeeded")) == 2
