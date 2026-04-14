"""
tests/test_resume.py
---------------------
Tests for:
  - runtime/resume.py        (TaskCompletedEvent, TaskFailedEvent)
  - execution/event_bus.py   (EventBusProtocol, InMemoryEventBus)
  - runtime/engine.resume()  (resume integration)
"""
from __future__ import annotations

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import InMemoryDispatcher
from execution.event_bus import EventBusProtocol, InMemoryEventBus
from runtime.engine import (
    InstanceMismatchError,
    NodeNotWaitingError,
    resume,
    start,
)
from runtime.models import NodeState
from runtime.resume import TaskCompletedEvent, TaskFailedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


def _waiting_instance(flow, context=None, dispatcher=None):
    """Start a flow that hits an action node and returns WAITING."""
    d = dispatcher or InMemoryDispatcher()
    instance = start(flow, context or {}, dispatcher=d)
    assert instance.status == NodeState.WAITING
    return instance, d


# ---------------------------------------------------------------------------
# runtime/resume.py — event model
# ---------------------------------------------------------------------------

class TestTaskCompletedEvent:
    def test_required_fields(self):
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1")
        assert ev.instance_id == "i1"
        assert ev.node_id == "a1"

    def test_default_payload_is_empty(self):
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1")
        assert ev.payload == {}

    def test_payload_stored(self):
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1", payload={"result": 42})
        assert ev.payload["result"] == 42

    def test_payloads_are_independent_across_instances(self):
        e1 = TaskCompletedEvent(instance_id="i1", node_id="a1")
        e2 = TaskCompletedEvent(instance_id="i2", node_id="a1")
        e1.payload["x"] = 1
        assert "x" not in e2.payload


class TestTaskFailedEvent:
    def test_required_fields(self):
        ev = TaskFailedEvent(instance_id="i1", node_id="a1", error="timeout")
        assert ev.instance_id == "i1"
        assert ev.node_id == "a1"
        assert ev.error == "timeout"

    def test_default_payload_is_empty(self):
        ev = TaskFailedEvent(instance_id="i1", node_id="a1", error="boom")
        assert ev.payload == {}

    def test_optional_payload(self):
        ev = TaskFailedEvent(
            instance_id="i1", node_id="a1", error="e",
            payload={"trace": "..."},
        )
        assert ev.payload["trace"] == "..."


# ---------------------------------------------------------------------------
# execution/event_bus.py
# ---------------------------------------------------------------------------

class TestInMemoryEventBus:
    def test_starts_empty(self):
        bus = InMemoryEventBus()
        assert bus.events == []

    def test_publish_appends(self):
        bus = InMemoryEventBus()
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1")
        bus.publish(ev)
        assert bus.events == [ev]

    def test_publish_accumulates_in_order(self):
        bus = InMemoryEventBus()
        e1 = TaskCompletedEvent(instance_id="i1", node_id="a1")
        e2 = TaskFailedEvent(instance_id="i2", node_id="a2", error="x")
        bus.publish(e1)
        bus.publish(e2)
        assert bus.events == [e1, e2]

    def test_buses_are_independent(self):
        b1, b2 = InMemoryEventBus(), InMemoryEventBus()
        b1.publish(TaskCompletedEvent(instance_id="i1", node_id="a1"))
        assert b2.events == []

    def test_satisfies_protocol(self):
        assert isinstance(InMemoryEventBus(), EventBusProtocol)

    def test_accepts_arbitrary_objects(self):
        bus = InMemoryEventBus()
        bus.publish({"arbitrary": "dict"})
        bus.publish(42)
        assert len(bus.events) == 2


# ---------------------------------------------------------------------------
# engine.resume — validation errors
# ---------------------------------------------------------------------------

class TestResumeValidation:
    def _simple_action_flow(self):
        return _flow("f", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])

    def test_instance_mismatch_raises(self):
        flow = self._simple_action_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id="WRONG-ID", node_id="a1")
        with pytest.raises(InstanceMismatchError) as exc_info:
            resume(flow, instance, ev)
        assert exc_info.value.event_instance_id == "WRONG-ID"
        assert exc_info.value.instance_id == instance.instance_id

    def test_node_not_waiting_raises_when_succeeded(self):
        """A node that already SUCCEEDED cannot be resumed."""
        flow = _flow("f", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"x": 1}}),
        ])
        instance = start(flow, {})
        assert instance.node_states["d1"].state == NodeState.SUCCEEDED
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="d1")
        with pytest.raises(NodeNotWaitingError) as exc_info:
            resume(flow, instance, ev)
        assert exc_info.value.node_id == "d1"
        assert exc_info.value.actual_state == NodeState.SUCCEEDED

    def test_node_not_waiting_raises_when_never_started(self):
        """A node that hasn't been started (no entry in node_states) cannot be resumed."""
        flow = self._simple_action_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(
            instance_id=instance.instance_id, node_id="nonexistent"
        )
        with pytest.raises(NodeNotWaitingError) as exc_info:
            resume(flow, instance, ev)
        assert exc_info.value.actual_state == NodeState.PENDING

    def test_instance_mismatch_attributes(self):
        flow = self._simple_action_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id="bad", node_id="a1")
        exc = pytest.raises(InstanceMismatchError, resume, flow, instance, ev)
        assert "bad" in str(exc.value)
        assert instance.instance_id in str(exc.value)


# ---------------------------------------------------------------------------
# engine.resume — TaskCompletedEvent
# ---------------------------------------------------------------------------

class TestResumeCompleted:
    def _action_only_flow(self):
        return _flow("f1", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])

    def test_node_state_becomes_succeeded(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        resume(flow, instance, ev)
        assert instance.node_states["a1"].state == NodeState.SUCCEEDED

    def test_instance_status_succeeded_when_no_next(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED

    def test_result_stored_in_context(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(
            instance_id=instance.instance_id,
            node_id="a1",
            payload={"result": {"score": 99}},
        )
        resume(flow, instance, ev)
        assert instance.context["a1"] == {"score": 99}

    def test_result_is_none_when_payload_missing_result_key(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        resume(flow, instance, ev)
        assert instance.context["a1"] is None

    def test_node_finished_at_set(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        resume(flow, instance, ev)
        assert instance.node_states["a1"].finished_at is not None

    def test_continue_to_decision_after_resume(self):
        """After resume, remaining nodes execute synchronously."""
        flow = _flow("f2", "a1", [
            NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
            NodeDefinition(id="d1", type="decision", config={"set": {"done": True}}),
        ])
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["done"] is True
        assert result.node_states["d1"].state == NodeState.SUCCEEDED

    def test_continue_through_condition_after_resume(self):
        """Condition branching works correctly after resume."""
        flow = _flow("f3", "a1", [
            NodeDefinition(id="a1", type="action", next="cond", config={"worker": "w"}),
            NodeDefinition(
                id="cond", type="condition",
                true_next="yes", false_next="no",
                config={"expression": "score > 50"},
            ),
            NodeDefinition(id="yes", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="no",  type="decision", config={"set": {"band": "low"}}),
        ])
        instance, _ = _waiting_instance(flow, context={"score": 80})
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["band"] == "high"

    def test_resume_then_another_action_stays_waiting(self):
        """If a second action node is encountered after resume, stop WAITING."""
        d = InMemoryDispatcher()
        flow = _flow("f4", "a1", [
            NodeDefinition(id="a1", type="action", next="a2", config={"worker": "w1"}),
            NodeDefinition(id="a2", type="action",             config={"worker": "w2"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.status == NodeState.WAITING
        assert len(d.tasks) == 1  # only a1 dispatched

        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        result = resume(flow, instance, ev, dispatcher=d)

        assert result.status == NodeState.WAITING
        assert result.node_states["a1"].state == NodeState.SUCCEEDED
        assert result.node_states["a2"].state == NodeState.WAITING
        assert len(d.tasks) == 2  # a2 also dispatched

    def test_resume_second_action_dispatches_correct_task(self):
        """The Task dispatched for the second action has the right node_id."""
        d = InMemoryDispatcher()
        flow = _flow("f5", "a1", [
            NodeDefinition(id="a1", type="action", next="a2", config={"worker": "w1"}),
            NodeDefinition(id="a2", type="action",             config={"worker": "w2"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        resume(flow, instance, ev, dispatcher=d)
        assert d.tasks[1].node_id == "a2"
        assert d.tasks[1].payload["worker"] == "w2"

    def test_context_from_previous_resume_is_available(self):
        """Result stored from first resume is accessible to subsequent nodes."""
        flow = _flow("f6", "a1", [
            NodeDefinition(id="a1", type="action", next="cond", config={"worker": "w"}),
            NodeDefinition(
                id="cond", type="condition",
                true_next="ok", false_next="fail",
                config={"expression": "a1 > 50"},  # reads context["a1"]
            ),
            NodeDefinition(id="ok",   type="decision", config={"set": {"result": "ok"}}),
            NodeDefinition(id="fail", type="decision", config={"set": {"result": "fail"}}),
        ])
        instance, _ = _waiting_instance(flow)
        ev = TaskCompletedEvent(
            instance_id=instance.instance_id,
            node_id="a1",
            payload={"result": 90},
        )
        result = resume(flow, instance, ev)
        assert result.context["result"] == "ok"

    def test_updated_at_changes_after_resume(self):
        flow = _flow("f7", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance, _ = _waiting_instance(flow)
        before = instance.updated_at
        ev = TaskCompletedEvent(instance_id=instance.instance_id, node_id="a1")
        resume(flow, instance, ev)
        assert instance.updated_at >= before


# ---------------------------------------------------------------------------
# engine.resume — TaskFailedEvent
# ---------------------------------------------------------------------------

class TestResumeFailed:
    def _action_only_flow(self):
        return _flow("f", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])

    def test_node_state_becomes_failed(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="timeout"
        )
        resume(flow, instance, ev)
        assert instance.node_states["a1"].state == NodeState.FAILED

    def test_instance_status_becomes_failed(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="timeout"
        )
        result = resume(flow, instance, ev)
        assert result.status == NodeState.FAILED

    def test_error_stored_on_node_state(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="worker crashed"
        )
        resume(flow, instance, ev)
        assert instance.node_states["a1"].error == "worker crashed"

    def test_next_nodes_not_executed(self):
        """On failure, downstream nodes must NOT run."""
        flow = _flow("f", "a1", [
            NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
            NodeDefinition(id="d1", type="decision", config={"set": {"ran": True}}),
        ])
        instance, _ = _waiting_instance(flow)
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="crash"
        )
        result = resume(flow, instance, ev)
        assert result.status == NodeState.FAILED
        assert "d1" not in result.node_states
        assert "ran" not in result.context

    def test_finished_at_set_on_failed_node(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="e"
        )
        resume(flow, instance, ev)
        assert instance.node_states["a1"].finished_at is not None

    def test_updated_at_changes_after_failure(self):
        flow = self._action_only_flow()
        instance, _ = _waiting_instance(flow)
        before = instance.updated_at
        ev = TaskFailedEvent(
            instance_id=instance.instance_id, node_id="a1", error="e"
        )
        resume(flow, instance, ev)
        assert instance.updated_at >= before


# ---------------------------------------------------------------------------
# engine.start regression — existing behaviour unchanged
# ---------------------------------------------------------------------------

class TestStartRegression:
    def test_condition_decision_still_work(self):
        flow = _flow("r1", "cond", [
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

    def test_action_flow_still_waits(self):
        d = InMemoryDispatcher()
        flow = _flow("r2", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.status == NodeState.WAITING
        assert len(d.tasks) == 1
