"""tests/test_models.py — minimum tests for runtime.models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.models import (
    ExecutionInstance,
    NodeExecutionState,
    NodeState,
    ResumeEvent,
    Task,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# NodeState
# ---------------------------------------------------------------------------

class TestNodeState:
    def test_all_values_are_strings(self):
        for state in NodeState:
            assert isinstance(state.value, str)

    def test_str_equality(self):
        # NodeState(str, Enum) must compare equal to its raw string value
        assert NodeState.RUNNING == "running"
        assert NodeState.PENDING == "pending"

    def test_membership(self):
        assert NodeState("succeeded") is NodeState.SUCCEEDED

    def test_pending_and_running_are_not_terminal(self):
        terminal = {NodeState.SUCCEEDED, NodeState.FAILED,
                    NodeState.SKIPPED, NodeState.CANCELLED}
        assert NodeState.PENDING not in terminal
        assert NodeState.RUNNING not in terminal

    def test_waiting_is_distinct_from_terminal(self):
        assert NodeState.WAITING not in {NodeState.SUCCEEDED, NodeState.FAILED}


# ---------------------------------------------------------------------------
# NodeExecutionState
# ---------------------------------------------------------------------------

class TestNodeExecutionState:
    def test_default_values(self):
        nes = NodeExecutionState(node_id="n1")
        assert nes.state      == NodeState.PENDING
        assert nes.started_at  is None
        assert nes.finished_at is None
        assert nes.attempt    == 0
        assert nes.error      is None
        assert nes.output     is None

    def test_duration_none_without_start(self):
        nes = NodeExecutionState(node_id="n1")
        assert nes.duration_seconds is None

    def test_duration_none_without_finish(self):
        nes = NodeExecutionState(node_id="n1", started_at=_now())
        assert nes.duration_seconds is None

    def test_duration_computed_correctly(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc)
        nes = NodeExecutionState(node_id="n1", started_at=t0, finished_at=t1)
        assert nes.duration_seconds == 7.0

    def test_state_mutation(self):
        nes = NodeExecutionState(node_id="n1")
        nes.state = NodeState.RUNNING
        assert nes.state == NodeState.RUNNING
        nes.state = NodeState.FAILED
        nes.error = "timeout"
        assert nes.state == NodeState.FAILED
        assert nes.error == "timeout"

    def test_attempt_increments(self):
        nes = NodeExecutionState(node_id="n1", attempt=2)
        assert nes.attempt == 2

    def test_output_stored(self):
        nes = NodeExecutionState(node_id="n1", output={"result": 42})
        assert nes.output["result"] == 42


# ---------------------------------------------------------------------------
# ExecutionInstance
# ---------------------------------------------------------------------------

class TestExecutionInstance:
    def _make(self, **kwargs) -> ExecutionInstance:
        now = _now()
        return ExecutionInstance(
            instance_id="inst-1",
            workflow_id="wf-abc",
            created_at=now,
            updated_at=now,
            **kwargs,
        )

    def test_default_status_is_pending(self):
        assert self._make().status == NodeState.PENDING

    def test_default_collections_are_empty(self):
        inst = self._make()
        assert inst.node_states == {}
        assert inst.context == {}

    def test_node_states_are_independent_across_instances(self):
        a = self._make()
        b = self._make()
        a.node_states["n1"] = NodeExecutionState(node_id="n1")
        assert "n1" not in b.node_states

    def test_context_is_independent_across_instances(self):
        a = self._make()
        b = self._make()
        a.context["key"] = "value"
        assert "key" not in b.context

    def test_attach_and_retrieve_node_state(self):
        inst = self._make()
        inst.node_states["n2"] = NodeExecutionState(
            node_id="n2", state=NodeState.RUNNING
        )
        assert inst.node_states["n2"].state == NodeState.RUNNING

    def test_status_transition(self):
        inst = self._make()
        inst.status = NodeState.RUNNING
        assert inst.status == NodeState.RUNNING
        inst.status = NodeState.SUCCEEDED
        assert inst.status == NodeState.SUCCEEDED


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TestTask:
    def _make(self, **kwargs) -> Task:
        return Task(
            task_id="t-1",
            node_id="n1",
            instance_id="inst-1",
            created_at=_now(),
            **kwargs,
        )

    def test_default_payload_and_priority(self):
        task = self._make()
        assert task.payload  == {}
        assert task.priority == 0

    def test_payload_stored(self):
        task = self._make(payload={"input": "hello"})
        assert task.payload["input"] == "hello"

    def test_priority_stored(self):
        task = self._make(priority=5)
        assert task.priority == 5

    def test_payload_independent_across_tasks(self):
        a = self._make()
        b = self._make()
        a.payload["x"] = 1
        assert "x" not in b.payload

    def test_all_fields_accessible(self):
        now = _now()
        task = Task(
            task_id="t-99",
            node_id="n3",
            instance_id="inst-7",
            created_at=now,
        )
        assert task.task_id     == "t-99"
        assert task.node_id     == "n3"
        assert task.instance_id == "inst-7"
        assert task.created_at  is now


# ---------------------------------------------------------------------------
# ResumeEvent
# ---------------------------------------------------------------------------

class TestResumeEvent:
    def _make(self, **kwargs) -> ResumeEvent:
        return ResumeEvent(
            event_id="ev-1",
            instance_id="inst-1",
            node_id="n1",
            arrived_at=_now(),
            **kwargs,
        )

    def test_default_payload_and_source(self):
        ev = self._make()
        assert ev.payload == {}
        assert ev.source  is None

    def test_source_stored(self):
        ev = self._make(source="human-gate")
        assert ev.source == "human-gate"

    def test_payload_stored(self):
        ev = self._make(payload={"approved": True})
        assert ev.payload["approved"] is True

    def test_payload_independent_across_events(self):
        a = self._make()
        b = self._make()
        a.payload["k"] = "v"
        assert "k" not in b.payload

    def test_all_fields_accessible(self):
        now = _now()
        ev = ResumeEvent(
            event_id="ev-42",
            instance_id="inst-3",
            node_id="n5",
            arrived_at=now,
            payload={"data": 1},
            source="timer",
        )
        assert ev.event_id    == "ev-42"
        assert ev.instance_id == "inst-3"
        assert ev.node_id     == "n5"
        assert ev.arrived_at  is now
        assert ev.source      == "timer"
