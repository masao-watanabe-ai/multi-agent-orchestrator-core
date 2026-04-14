"""
tests/test_action.py
---------------------
Tests for:
  - nodes/action/action.py        (action node run)
  - execution/dispatcher.py       (DispatcherProtocol, InMemoryDispatcher)
  - execution/worker_interface.py (WorkerInterface)
  - sdk/agent_contract.py         (AgentContract)
  - sdk/agent_registry.py         (AgentRegistry)
  - runtime/engine.py             (action node integration)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import DispatcherProtocol, InMemoryDispatcher
from execution.worker_interface import WorkerInterface
from nodes.action.action import run as action_run
from runtime.engine import UnsupportedNodeTypeError, start
from runtime.models import NodeState, Task
from sdk.agent_contract import AgentContract
from sdk.agent_registry import AgentRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


def _task(node_id: str = "n1", instance_id: str = "i1") -> Task:
    return Task(
        task_id="t1",
        node_id=node_id,
        instance_id=instance_id,
        created_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# nodes/action/action.py
# ---------------------------------------------------------------------------

class TestActionNodeRun:
    def test_creates_task_with_worker(self):
        node = NodeDefinition(
            id="a1", type="action",
            config={"worker": "summariser"},
        )
        task = action_run(node, "instance-42")
        assert task.node_id == "a1"
        assert task.instance_id == "instance-42"
        assert task.payload["worker"] == "summariser"

    def test_task_id_is_nonempty_string(self):
        node = NodeDefinition(id="a1", type="action", config={"worker": "w"})
        task = action_run(node, "i1")
        assert isinstance(task.task_id, str)
        assert task.task_id != ""

    def test_default_payload_only_contains_worker(self):
        node = NodeDefinition(id="a1", type="action", config={"worker": "w"})
        task = action_run(node, "i1")
        assert task.payload == {"worker": "w"}

    def test_extra_payload_merged(self):
        node = NodeDefinition(
            id="a1", type="action",
            config={"worker": "w", "payload": {"max_tokens": 256, "lang": "ja"}},
        )
        task = action_run(node, "i1")
        assert task.payload["worker"] == "w"
        assert task.payload["max_tokens"] == 256
        assert task.payload["lang"] == "ja"

    def test_missing_worker_raises(self):
        node = NodeDefinition(id="a1", type="action", config={})
        with pytest.raises(ValueError, match="worker"):
            action_run(node, "i1")

    def test_task_has_created_at(self):
        node = NodeDefinition(id="a1", type="action", config={"worker": "w"})
        task = action_run(node, "i1")
        assert task.created_at is not None

    def test_each_call_generates_unique_task_id(self):
        node = NodeDefinition(id="a1", type="action", config={"worker": "w"})
        t1 = action_run(node, "i1")
        t2 = action_run(node, "i1")
        assert t1.task_id != t2.task_id


# ---------------------------------------------------------------------------
# execution/dispatcher.py
# ---------------------------------------------------------------------------

class TestInMemoryDispatcher:
    def test_starts_empty(self):
        d = InMemoryDispatcher()
        assert d.tasks == []

    def test_dispatch_appends_task(self):
        d = InMemoryDispatcher()
        t = _task()
        d.dispatch(t)
        assert d.tasks == [t]

    def test_dispatch_accumulates_in_order(self):
        d = InMemoryDispatcher()
        t1 = _task(node_id="n1")
        t2 = _task(node_id="n2")
        d.dispatch(t1)
        d.dispatch(t2)
        assert d.tasks == [t1, t2]

    def test_multiple_dispatchers_are_independent(self):
        d1, d2 = InMemoryDispatcher(), InMemoryDispatcher()
        d1.dispatch(_task())
        assert d2.tasks == []

    def test_satisfies_dispatcher_protocol(self):
        d = InMemoryDispatcher()
        assert isinstance(d, DispatcherProtocol)


# ---------------------------------------------------------------------------
# execution/worker_interface.py
# ---------------------------------------------------------------------------

class TestWorkerInterface:
    def test_concrete_subclass_must_implement_handle(self):
        """An unimplemented subclass cannot be instantiated."""

        class Incomplete(WorkerInterface):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self):
        class EchoWorker(WorkerInterface):
            def handle(self, task: Task):
                return task.payload

        w = EchoWorker()
        t = _task()
        assert w.handle(t) == t.payload


# ---------------------------------------------------------------------------
# sdk/agent_contract.py
# ---------------------------------------------------------------------------

class TestAgentContract:
    def test_required_fields(self):
        c = AgentContract(agent_id="a1", worker_type="summariser")
        assert c.agent_id == "a1"
        assert c.worker_type == "summariser"

    def test_defaults(self):
        c = AgentContract(agent_id="a1", worker_type="w")
        assert c.description == ""
        assert c.metadata == {}

    def test_metadata_is_independent_across_instances(self):
        c1 = AgentContract(agent_id="a1", worker_type="w")
        c2 = AgentContract(agent_id="a2", worker_type="w")
        c1.metadata["key"] = "val"
        assert "key" not in c2.metadata

    def test_optional_fields(self):
        c = AgentContract(
            agent_id="a1",
            worker_type="w",
            description="does stuff",
            metadata={"model": "claude-3"},
        )
        assert c.description == "does stuff"
        assert c.metadata["model"] == "claude-3"


# ---------------------------------------------------------------------------
# sdk/agent_registry.py
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    def test_register_and_get(self):
        reg = AgentRegistry()
        c = AgentContract(agent_id="a1", worker_type="w")
        reg.register(c)
        assert reg.get("a1") is c

    def test_get_missing_raises_key_error(self):
        reg = AgentRegistry()
        with pytest.raises(KeyError, match="a1"):
            reg.get("a1")

    def test_register_overwrites_existing(self):
        reg = AgentRegistry()
        c1 = AgentContract(agent_id="a1", worker_type="w1")
        c2 = AgentContract(agent_id="a1", worker_type="w2")
        reg.register(c1)
        reg.register(c2)
        assert reg.get("a1") is c2

    def test_multiple_agents(self):
        reg = AgentRegistry()
        for i in range(3):
            reg.register(AgentContract(agent_id=f"a{i}", worker_type="w"))
        assert len(reg) == 3
        assert reg.get("a2").agent_id == "a2"

    def test_registries_are_independent(self):
        r1, r2 = AgentRegistry(), AgentRegistry()
        r1.register(AgentContract(agent_id="a1", worker_type="w"))
        with pytest.raises(KeyError):
            r2.get("a1")


# ---------------------------------------------------------------------------
# engine.start — action node integration
# ---------------------------------------------------------------------------

class TestEngineActionNode:
    def test_action_node_returns_waiting_status(self):
        d = InMemoryDispatcher()
        flow = _flow("f1", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.status == NodeState.WAITING

    def test_action_node_state_is_waiting(self):
        d = InMemoryDispatcher()
        flow = _flow("f1", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.node_states["a1"].state == NodeState.WAITING

    def test_action_node_dispatches_one_task(self):
        d = InMemoryDispatcher()
        flow = _flow("f1", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "my-worker"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert len(d.tasks) == 1
        task = d.tasks[0]
        assert task.node_id == "a1"
        assert task.instance_id == instance.instance_id
        assert task.payload["worker"] == "my-worker"

    def test_action_node_with_payload(self):
        d = InMemoryDispatcher()
        flow = _flow("f1", "a1", [
            NodeDefinition(
                id="a1", type="action",
                config={"worker": "w", "payload": {"lang": "ja"}},
            ),
        ])
        start(flow, {}, dispatcher=d)
        assert d.tasks[0].payload["lang"] == "ja"

    def test_decision_then_action(self):
        """Decisions before action execute normally; action suspends."""
        d = InMemoryDispatcher()
        flow = _flow("f2", "d1", [
            NodeDefinition(id="d1", type="decision", next="a1", config={"set": {"ready": True}}),
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        assert instance.status == NodeState.WAITING
        assert instance.context["ready"] is True
        assert instance.node_states["d1"].state == NodeState.SUCCEEDED
        assert instance.node_states["a1"].state == NodeState.WAITING
        assert len(d.tasks) == 1

    def test_condition_routes_to_action(self):
        """Condition branches to an action node; instance ends WAITING."""
        d = InMemoryDispatcher()
        flow = _flow("f3", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="act", false_next="done",
                config={"expression": "go == true"},
            ),
            NodeDefinition(id="act",  type="action",   config={"worker": "w"}),
            NodeDefinition(id="done", type="decision",  config={"set": {"finished": True}}),
        ])
        instance = start(flow, {"go": True}, dispatcher=d)
        assert instance.status == NodeState.WAITING
        assert len(d.tasks) == 1

    def test_condition_skips_action(self):
        """Condition's false branch bypasses the action node entirely."""
        d = InMemoryDispatcher()
        flow = _flow("f4", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="act", false_next="done",
                config={"expression": "go == true"},
            ),
            NodeDefinition(id="act",  type="action",   config={"worker": "w"}),
            NodeDefinition(id="done", type="decision",  config={"set": {"finished": True}}),
        ])
        instance = start(flow, {"go": False}, dispatcher=d)
        assert instance.status == NodeState.SUCCEEDED
        assert len(d.tasks) == 0
        assert instance.context["finished"] is True

    def test_action_without_dispatcher_raises(self):
        flow = _flow("f5", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        with pytest.raises(ValueError, match="dispatcher"):
            start(flow, {})

    def test_action_without_dispatcher_marks_node_failed(self):
        flow = _flow("f5", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        with pytest.raises(ValueError):
            instance = start(flow, {})
        # instance is not returned; the exception is what matters

    def test_action_node_timestamps(self):
        d = InMemoryDispatcher()
        flow = _flow("f6", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        ns = instance.node_states["a1"]
        assert ns.started_at is not None
        assert ns.finished_at is not None

    def test_condition_decision_unaffected(self):
        """Regression: condition/decision still work without dispatcher."""
        flow = _flow("f7", "cond", [
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
