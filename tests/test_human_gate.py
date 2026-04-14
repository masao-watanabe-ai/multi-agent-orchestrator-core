"""
tests/test_human_gate.py
-------------------------
Tests for:
  - nodes/decision/human_gate.py   (human_gate node run)
  - runtime/resume.py              (HumanApprovedEvent, HumanRejectedEvent)
  - runtime/engine.py              (start/resume with human_gate)
"""
from __future__ import annotations

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import InMemoryDispatcher
from nodes.decision.human_gate import run as hg_run
from runtime.engine import (
    InstanceMismatchError,
    NodeNotWaitingError,
    UnsupportedNodeTypeError,
    resume,
    start,
)
from runtime.models import NodeState
from runtime.resume import (
    HumanApprovedEvent,
    HumanRejectedEvent,
    TaskCompletedEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


def _waiting_hg_instance(flow, context=None):
    """Start a flow that hits a human_gate and returns WAITING."""
    instance = start(flow, context or {})
    assert instance.status == NodeState.WAITING
    return instance


# ---------------------------------------------------------------------------
# nodes/decision/human_gate.py
# ---------------------------------------------------------------------------

class TestHumanGateRun:
    def test_run_returns_none(self):
        node = NodeDefinition(id="hg1", type="human_gate", config={})
        assert hg_run(node) is None

    def test_run_with_optional_config(self):
        node = NodeDefinition(
            id="hg1", type="human_gate",
            config={"message": "Please approve", "approvers": ["alice"]},
        )
        # Should not raise; config is available but not validated
        assert hg_run(node) is None

    def test_run_with_empty_config(self):
        node = NodeDefinition(id="hg1", type="human_gate", config={})
        hg_run(node)   # must not raise


# ---------------------------------------------------------------------------
# runtime/resume.py — HumanApprovedEvent / HumanRejectedEvent
# ---------------------------------------------------------------------------

class TestHumanApprovedEvent:
    def test_required_fields(self):
        ev = HumanApprovedEvent(instance_id="i1", node_id="hg1")
        assert ev.instance_id == "i1"
        assert ev.node_id == "hg1"

    def test_defaults(self):
        ev = HumanApprovedEvent(instance_id="i1", node_id="hg1")
        assert ev.approver == ""
        assert ev.payload == {}

    def test_approver_stored(self):
        ev = HumanApprovedEvent(instance_id="i1", node_id="hg1", approver="alice")
        assert ev.approver == "alice"

    def test_payload_stored(self):
        ev = HumanApprovedEvent(
            instance_id="i1", node_id="hg1", payload={"note": "looks good"}
        )
        assert ev.payload["note"] == "looks good"

    def test_payloads_independent(self):
        e1 = HumanApprovedEvent(instance_id="i1", node_id="hg1")
        e2 = HumanApprovedEvent(instance_id="i2", node_id="hg1")
        e1.payload["x"] = 1
        assert "x" not in e2.payload


class TestHumanRejectedEvent:
    def test_required_fields(self):
        ev = HumanRejectedEvent(instance_id="i1", node_id="hg1")
        assert ev.instance_id == "i1"
        assert ev.node_id == "hg1"

    def test_defaults(self):
        ev = HumanRejectedEvent(instance_id="i1", node_id="hg1")
        assert ev.reason == ""
        assert ev.approver == ""
        assert ev.payload == {}

    def test_reason_stored(self):
        ev = HumanRejectedEvent(
            instance_id="i1", node_id="hg1", reason="too risky"
        )
        assert ev.reason == "too risky"

    def test_approver_stored(self):
        ev = HumanRejectedEvent(
            instance_id="i1", node_id="hg1", approver="bob"
        )
        assert ev.approver == "bob"

    def test_payload_stored(self):
        ev = HumanRejectedEvent(
            instance_id="i1", node_id="hg1", payload={"trace": "..."}
        )
        assert ev.payload["trace"] == "..."


# ---------------------------------------------------------------------------
# engine.start — human_gate suspends execution
# ---------------------------------------------------------------------------

class TestStartWithHumanGate:
    def test_human_gate_returns_waiting_status(self):
        flow = _flow("f1", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.WAITING

    def test_human_gate_node_state_is_waiting(self):
        flow = _flow("f1", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = start(flow, {})
        assert instance.node_states["hg1"].state == NodeState.WAITING

    def test_human_gate_node_has_timestamps(self):
        flow = _flow("f1", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = start(flow, {})
        ns = instance.node_states["hg1"]
        assert ns.started_at is not None
        assert ns.finished_at is not None

    def test_decision_then_human_gate(self):
        """Decision before gate executes; gate suspends."""
        flow = _flow("f2", "d1", [
            NodeDefinition(id="d1", type="decision", next="hg1", config={"set": {"ready": True}}),
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.WAITING
        assert instance.context["ready"] is True
        assert instance.node_states["d1"].state == NodeState.SUCCEEDED
        assert instance.node_states["hg1"].state == NodeState.WAITING

    def test_condition_routes_to_human_gate(self):
        flow = _flow("f3", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="hg1", false_next="done",
                config={"expression": "need_approval == true"},
            ),
            NodeDefinition(id="hg1",  type="human_gate", config={}),
            NodeDefinition(id="done", type="decision",   config={"set": {"ok": True}}),
        ])
        instance = start(flow, {"need_approval": True})
        assert instance.status == NodeState.WAITING
        assert "hg1" in instance.node_states
        assert "done" not in instance.node_states

    def test_condition_skips_human_gate(self):
        flow = _flow("f4", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="hg1", false_next="done",
                config={"expression": "need_approval == true"},
            ),
            NodeDefinition(id="hg1",  type="human_gate", config={}),
            NodeDefinition(id="done", type="decision",   config={"set": {"ok": True}}),
        ])
        instance = start(flow, {"need_approval": False})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["ok"] is True
        assert "hg1" not in instance.node_states

    def test_human_gate_does_not_require_dispatcher(self):
        """human_gate suspends without a dispatcher (unlike action)."""
        flow = _flow("f5", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        # Must not raise — no dispatcher needed
        instance = start(flow, {})
        assert instance.status == NodeState.WAITING


# ---------------------------------------------------------------------------
# engine.resume — HumanApprovedEvent
# ---------------------------------------------------------------------------

class TestResumeApproved:
    def _gate_only_flow(self):
        return _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])

    def test_node_state_becomes_succeeded(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.node_states["hg1"].state == NodeState.SUCCEEDED

    def test_instance_status_succeeded_when_no_next(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED

    def test_approved_context_stored(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(
            instance_id=instance.instance_id, node_id="hg1", approver="alice"
        )
        resume(flow, instance, ev)
        ctx = instance.context["hg1"]
        assert ctx["approved"] is True
        assert ctx["approver"] == "alice"

    def test_approved_context_without_approver(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.context["hg1"]["approved"] is True
        assert instance.context["hg1"]["approver"] == ""

    def test_continue_to_decision_after_approval(self):
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="d1", config={}),
            NodeDefinition(id="d1",  type="decision",              config={"set": {"done": True}}),
        ])
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["done"] is True
        assert result.node_states["d1"].state == NodeState.SUCCEEDED

    def test_continue_through_condition_after_approval(self):
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="cond", config={}),
            NodeDefinition(
                id="cond", type="condition",
                true_next="high", false_next="low",
                config={"expression": "score > 50"},
            ),
            NodeDefinition(id="high", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="low",  type="decision", config={"set": {"band": "low"}}),
        ])
        instance = _waiting_hg_instance(flow, context={"score": 80})
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["band"] == "high"

    def test_approval_then_action_waits_again(self):
        """After approval, hitting an action node suspends again."""
        d = InMemoryDispatcher()
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="act", config={}),
            NodeDefinition(id="act", type="action",                  config={"worker": "w"}),
        ])
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev, dispatcher=d)
        assert result.status == NodeState.WAITING
        assert result.node_states["hg1"].state == NodeState.SUCCEEDED
        assert result.node_states["act"].state == NodeState.WAITING
        assert len(d.tasks) == 1
        assert d.tasks[0].node_id == "act"

    def test_approval_then_another_human_gate_waits(self):
        """Two human gates in sequence: first approval reveals second gate."""
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="hg2", config={}),
            NodeDefinition(id="hg2", type="human_gate",              config={}),
        ])
        instance = _waiting_hg_instance(flow)
        ev1 = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev1)
        assert result.status == NodeState.WAITING
        assert result.node_states["hg1"].state == NodeState.SUCCEEDED
        assert result.node_states["hg2"].state == NodeState.WAITING

    def test_finished_at_set_on_approved_node(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.node_states["hg1"].finished_at is not None

    def test_updated_at_changes_after_approval(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        before = instance.updated_at
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.updated_at >= before


# ---------------------------------------------------------------------------
# engine.resume — HumanRejectedEvent
# ---------------------------------------------------------------------------

class TestResumeRejected:
    def _gate_only_flow(self):
        return _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])

    def test_node_state_becomes_failed(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(
            instance_id=instance.instance_id, node_id="hg1", reason="too risky"
        )
        resume(flow, instance, ev)
        assert instance.node_states["hg1"].state == NodeState.FAILED

    def test_instance_status_becomes_failed(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.FAILED

    def test_error_stored_on_node_state(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(
            instance_id=instance.instance_id, node_id="hg1", reason="not authorised"
        )
        resume(flow, instance, ev)
        assert instance.node_states["hg1"].error == "not authorised"

    def test_empty_reason_uses_default_error(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        # error should be a non-empty default message
        assert instance.node_states["hg1"].error

    def test_rejected_context_stored(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(
            instance_id=instance.instance_id,
            node_id="hg1",
            reason="too risky",
            approver="bob",
        )
        resume(flow, instance, ev)
        ctx = instance.context["hg1"]
        assert ctx["approved"] is False
        assert ctx["reason"] == "too risky"
        assert ctx["approver"] == "bob"

    def test_next_nodes_not_executed(self):
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="d1", config={}),
            NodeDefinition(id="d1",  type="decision",              config={"set": {"ran": True}}),
        ])
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.FAILED
        assert "d1" not in result.node_states
        assert "ran" not in result.context

    def test_finished_at_set_on_rejected_node(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.node_states["hg1"].finished_at is not None

    def test_updated_at_changes_after_rejection(self):
        flow = self._gate_only_flow()
        instance = _waiting_hg_instance(flow)
        before = instance.updated_at
        ev = HumanRejectedEvent(instance_id=instance.instance_id, node_id="hg1")
        resume(flow, instance, ev)
        assert instance.updated_at >= before


# ---------------------------------------------------------------------------
# engine.resume — validation still works for human_gate nodes
# ---------------------------------------------------------------------------

class TestResumeValidationHumanGate:
    def test_instance_mismatch_raises(self):
        flow = _flow("f", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = _waiting_hg_instance(flow)
        ev = HumanApprovedEvent(instance_id="WRONG", node_id="hg1")
        with pytest.raises(InstanceMismatchError):
            resume(flow, instance, ev)

    def test_node_not_waiting_raises(self):
        flow = _flow("f", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {}}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.SUCCEEDED
        ev = HumanApprovedEvent(instance_id=instance.instance_id, node_id="d1")
        with pytest.raises(NodeNotWaitingError):
            resume(flow, instance, ev)


# ---------------------------------------------------------------------------
# regression — existing behaviour unaffected
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_unsupported_type_still_raises(self):
        """parallel is still unsupported."""
        flow = _flow("f", "p1", [
            NodeDefinition(id="p1", type="parallel", config={}),
        ])
        with pytest.raises(UnsupportedNodeTypeError) as exc_info:
            start(flow, {})
        assert exc_info.value.node_type == "parallel"

    def test_task_completed_event_still_works(self):
        """TaskCompletedEvent path unaffected by human_gate additions."""
        d = InMemoryDispatcher()
        flow = _flow("f", "a1", [
            NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
            NodeDefinition(id="d1", type="decision",            config={"set": {"ok": True}}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.status == NodeState.WAITING
        ev = TaskCompletedEvent(
            instance_id=instance.instance_id, node_id="a1",
            payload={"result": 42},
        )
        result = resume(flow, instance, ev, dispatcher=d)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["a1"] == 42
        assert result.context["ok"] is True

    def test_condition_decision_flow_unaffected(self):
        flow = _flow("f", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="ok", false_next="ok",
                config={"expression": "x > 0"},
            ),
            NodeDefinition(id="ok", type="decision", config={"set": {"done": True}}),
        ])
        instance = start(flow, {"x": 1})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["done"] is True
