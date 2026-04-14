"""
tests/test_state_store.py
--------------------------
Tests for:
  - state/snapshot.py      (to_dict, from_dict)
  - state/store.py         (StateStoreProtocol, InMemoryStateStore, JsonFileStateStore)
  - state/event_store.py   (InMemoryEventStore)

Integration:
  - save WAITING instance → load → resume() via runtime.engine
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from execution.dispatcher import InMemoryDispatcher
from runtime.engine import resume, start
from runtime.models import ExecutionInstance, NodeExecutionState, NodeState
from runtime.resume import HumanApprovedEvent, HumanRejectedEvent, TaskCompletedEvent
from state.event_store import InMemoryEventStore
from state.snapshot import from_dict, to_dict
from state.store import InMemoryStateStore, JsonFileStateStore, StateStoreProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _minimal_instance(
    instance_id: str = "inst-1",
    status: NodeState = NodeState.SUCCEEDED,
) -> ExecutionInstance:
    now = _now()
    return ExecutionInstance(
        instance_id=instance_id,
        workflow_id="wf-1",
        created_at=now,
        updated_at=now,
        status=status,
        node_states={},
        context={},
    )


def _waiting_instance() -> tuple[ExecutionInstance, InMemoryDispatcher, FlowDefinition]:
    """Create a WAITING instance via engine.start()."""
    d = InMemoryDispatcher()
    flow = _flow("wf-action", "a1", [
        NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
        NodeDefinition(id="d1", type="decision",            config={"set": {"done": True}}),
    ])
    instance = start(flow, {"initial": "value"}, dispatcher=d)
    assert instance.status == NodeState.WAITING
    return instance, d, flow


def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


# ---------------------------------------------------------------------------
# state/snapshot.py — to_dict / from_dict
# ---------------------------------------------------------------------------

class TestSnapshotToDict:
    def test_all_scalar_fields_present(self):
        instance = _minimal_instance()
        d = to_dict(instance)
        assert d["instance_id"] == instance.instance_id
        assert d["workflow_id"] == instance.workflow_id
        assert d["status"] == "succeeded"

    def test_datetime_serialised_as_string(self):
        instance = _minimal_instance()
        d = to_dict(instance)
        assert isinstance(d["created_at"], str)
        assert isinstance(d["updated_at"], str)

    def test_node_state_enum_serialised_as_string(self):
        instance = _minimal_instance(status=NodeState.WAITING)
        d = to_dict(instance)
        assert d["status"] == "waiting"

    def test_empty_node_states(self):
        instance = _minimal_instance()
        d = to_dict(instance)
        assert d["node_states"] == {}

    def test_node_states_serialised(self):
        now = _now()
        instance = _minimal_instance()
        instance.node_states["a1"] = NodeExecutionState(
            node_id="a1",
            state=NodeState.WAITING,
            started_at=now,
            finished_at=now,
            attempt=1,
            error=None,
        )
        d = to_dict(instance)
        ns = d["node_states"]["a1"]
        assert ns["state"] == "waiting"
        assert isinstance(ns["started_at"], str)
        assert isinstance(ns["finished_at"], str)
        assert ns["attempt"] == 1
        assert ns["error"] is None

    def test_node_state_none_timestamps(self):
        instance = _minimal_instance()
        instance.node_states["n1"] = NodeExecutionState(node_id="n1")
        d = to_dict(instance)
        assert d["node_states"]["n1"]["started_at"] is None
        assert d["node_states"]["n1"]["finished_at"] is None

    def test_context_preserved(self):
        instance = _minimal_instance()
        instance.context = {"x": 42, "y": "hello", "z": True}
        d = to_dict(instance)
        assert d["context"] == {"x": 42, "y": "hello", "z": True}

    def test_empty_context(self):
        d = to_dict(_minimal_instance())
        assert d["context"] == {}


class TestSnapshotFromDict:
    def test_roundtrip_minimal(self):
        original = _minimal_instance()
        restored = from_dict(to_dict(original))
        assert restored.instance_id == original.instance_id
        assert restored.workflow_id == original.workflow_id
        assert restored.status == original.status

    def test_roundtrip_datetime(self):
        original = _minimal_instance()
        restored = from_dict(to_dict(original))
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at

    def test_roundtrip_all_node_states(self):
        for state in NodeState:
            instance = _minimal_instance(status=state)
            restored = from_dict(to_dict(instance))
            assert restored.status == state

    def test_roundtrip_node_execution_state(self):
        now = _now()
        instance = _minimal_instance()
        instance.node_states["a1"] = NodeExecutionState(
            node_id="a1",
            state=NodeState.SUCCEEDED,
            started_at=now,
            finished_at=now,
            attempt=2,
            error=None,
            output={"result": 99},
        )
        restored = from_dict(to_dict(instance))
        ns = restored.node_states["a1"]
        assert ns.node_id == "a1"
        assert ns.state == NodeState.SUCCEEDED
        assert ns.started_at == now
        assert ns.finished_at == now
        assert ns.attempt == 2
        assert ns.output == {"result": 99}

    def test_roundtrip_with_error(self):
        instance = _minimal_instance()
        instance.node_states["n1"] = NodeExecutionState(
            node_id="n1", state=NodeState.FAILED, error="something went wrong"
        )
        restored = from_dict(to_dict(instance))
        assert restored.node_states["n1"].error == "something went wrong"

    def test_roundtrip_context(self):
        instance = _minimal_instance()
        instance.context = {"approved": True, "score": 99, "label": "high"}
        restored = from_dict(to_dict(instance))
        assert restored.context == instance.context

    def test_roundtrip_waiting_node_state(self):
        instance, _, _ = _waiting_instance()
        restored = from_dict(to_dict(instance))
        assert restored.status == NodeState.WAITING
        assert restored.node_states["a1"].state == NodeState.WAITING

    def test_none_timestamps_roundtrip(self):
        instance = _minimal_instance()
        instance.node_states["n1"] = NodeExecutionState(node_id="n1")
        restored = from_dict(to_dict(instance))
        ns = restored.node_states["n1"]
        assert ns.started_at is None
        assert ns.finished_at is None


# ---------------------------------------------------------------------------
# state/store.py — InMemoryStateStore
# ---------------------------------------------------------------------------

class TestInMemoryStateStore:
    def test_save_and_load(self):
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.instance_id == "i1"
        assert loaded.status == NodeState.SUCCEEDED

    def test_load_not_found_raises_key_error(self):
        store = InMemoryStateStore()
        with pytest.raises(KeyError, match="not-found"):
            store.load_instance("not-found")

    def test_save_duplicate_raises_value_error(self):
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        with pytest.raises(ValueError):
            store.save_instance(instance)

    def test_update_changes_stored_state(self):
        store = InMemoryStateStore()
        instance = _minimal_instance("i1", status=NodeState.RUNNING)
        store.save_instance(instance)
        instance.status = NodeState.SUCCEEDED
        store.update_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.status == NodeState.SUCCEEDED

    def test_update_not_found_raises_key_error(self):
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        with pytest.raises(KeyError, match="i1"):
            store.update_instance(instance)

    def test_load_returns_independent_copy(self):
        """Mutations to the loaded instance do not affect the stored snapshot."""
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        instance.context = {"x": 1}
        store.save_instance(instance)

        loaded = store.load_instance("i1")
        loaded.context["x"] = 999  # mutate loaded copy

        reloaded = store.load_instance("i1")
        assert reloaded.context["x"] == 1  # stored snapshot unchanged

    def test_save_is_isolated_from_caller_mutations(self):
        """Mutations to the original instance after save do not corrupt the store."""
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        instance.context = {"x": 1}
        store.save_instance(instance)

        instance.context["x"] = 999  # mutate original after save

        loaded = store.load_instance("i1")
        assert loaded.context["x"] == 1

    def test_multiple_instances_independent(self):
        store = InMemoryStateStore()
        for i in range(3):
            store.save_instance(_minimal_instance(f"i{i}"))
        assert len(store) == 3
        for i in range(3):
            assert store.load_instance(f"i{i}").instance_id == f"i{i}"

    def test_load_or_none_returns_none_when_missing(self):
        store = InMemoryStateStore()
        assert store.load_or_none("missing") is None

    def test_load_or_none_returns_instance_when_present(self):
        store = InMemoryStateStore()
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        loaded = store.load_or_none("i1")
        assert loaded is not None
        assert loaded.instance_id == "i1"

    def test_satisfies_protocol(self):
        assert isinstance(InMemoryStateStore(), StateStoreProtocol)


# ---------------------------------------------------------------------------
# state/store.py — JsonFileStateStore
# ---------------------------------------------------------------------------

class TestJsonFileStateStore:
    def test_save_and_load(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.instance_id == "i1"
        assert loaded.status == NodeState.SUCCEEDED

    def test_json_file_created(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        store.save_instance(_minimal_instance("i1"))
        assert (tmp_path / "i1.json").exists()

    def test_load_not_found_raises_key_error(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        with pytest.raises(KeyError, match="missing"):
            store.load_instance("missing")

    def test_save_duplicate_raises_value_error(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        with pytest.raises(ValueError):
            store.save_instance(instance)

    def test_update_changes_stored_file(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance = _minimal_instance("i1", status=NodeState.RUNNING)
        store.save_instance(instance)
        instance.status = NodeState.SUCCEEDED
        store.update_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.status == NodeState.SUCCEEDED

    def test_update_not_found_raises_key_error(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        with pytest.raises(KeyError):
            store.update_instance(_minimal_instance("i1"))

    def test_creates_directory_if_not_exists(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        store = JsonFileStateStore(nested)
        store.save_instance(_minimal_instance("i1"))
        assert (nested / "i1.json").exists()

    def test_roundtrip_node_states(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance, _, _ = _waiting_instance()
        store.save_instance(instance)
        loaded = store.load_instance(instance.instance_id)
        assert loaded.status == NodeState.WAITING
        assert loaded.node_states["a1"].state == NodeState.WAITING

    def test_roundtrip_context(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance = _minimal_instance("i1")
        instance.context = {"approved": True, "score": 42, "label": "high"}
        store.save_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.context == {"approved": True, "score": 42, "label": "high"}

    def test_roundtrip_datetime(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        instance = _minimal_instance("i1")
        store.save_instance(instance)
        loaded = store.load_instance("i1")
        assert loaded.created_at == instance.created_at
        assert loaded.updated_at == instance.updated_at

    def test_satisfies_protocol(self, tmp_path):
        assert isinstance(JsonFileStateStore(tmp_path), StateStoreProtocol)

    def test_multiple_instances(self, tmp_path):
        store = JsonFileStateStore(tmp_path)
        for i in range(3):
            store.save_instance(_minimal_instance(f"i{i}"))
        for i in range(3):
            assert store.load_instance(f"i{i}").instance_id == f"i{i}"


# ---------------------------------------------------------------------------
# WAITING instance persistence + resume — integration
# ---------------------------------------------------------------------------

class TestWaitingInstancePersistAndResume:
    def test_save_load_preserves_waiting_status(self):
        store = InMemoryStateStore()
        instance, _, _ = _waiting_instance()
        store.save_instance(instance)
        restored = store.load_instance(instance.instance_id)
        assert restored.status == NodeState.WAITING

    def test_save_load_preserves_waiting_node_state(self):
        store = InMemoryStateStore()
        instance, _, _ = _waiting_instance()
        store.save_instance(instance)
        restored = store.load_instance(instance.instance_id)
        assert restored.node_states["a1"].state == NodeState.WAITING

    def test_save_load_preserves_context(self):
        store = InMemoryStateStore()
        instance, _, _ = _waiting_instance()
        assert instance.context["initial"] == "value"
        store.save_instance(instance)
        restored = store.load_instance(instance.instance_id)
        assert restored.context["initial"] == "value"

    def test_save_load_preserves_instance_id(self):
        store = InMemoryStateStore()
        instance, _, _ = _waiting_instance()
        store.save_instance(instance)
        restored = store.load_instance(instance.instance_id)
        assert restored.instance_id == instance.instance_id

    def test_resume_after_in_memory_load(self):
        """WAITING instance saved to InMemoryStateStore can be resumed."""
        store = InMemoryStateStore()
        d = InMemoryDispatcher()
        flow = _flow("wf-1", "a1", [
            NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
            NodeDefinition(id="d1", type="decision",            config={"set": {"done": True}}),
        ])
        instance = start(flow, {}, dispatcher=d)
        store.save_instance(instance)

        # Simulate receiving a TaskCompletedEvent after process restart
        restored = store.load_instance(instance.instance_id)
        ev = TaskCompletedEvent(
            instance_id=restored.instance_id,
            node_id="a1",
            payload={"result": 42},
        )
        result = resume(flow, restored, ev, dispatcher=d)

        assert result.status == NodeState.SUCCEEDED
        assert result.context["done"] is True
        assert result.context["a1"] == 42

    def test_resume_with_result_after_json_load(self, tmp_path):
        """Full persistence round-trip via JsonFileStateStore."""
        store = JsonFileStateStore(tmp_path)
        d = InMemoryDispatcher()
        flow = _flow("wf-2", "a1", [
            NodeDefinition(id="a1", type="action", next="d1", config={"worker": "w"}),
            NodeDefinition(id="d1", type="decision",            config={"set": {"ok": True}}),
        ])
        instance = start(flow, {"user": "alice"}, dispatcher=d)
        store.save_instance(instance)

        restored = store.load_instance(instance.instance_id)
        assert restored.status == NodeState.WAITING
        assert restored.context["user"] == "alice"

        ev = TaskCompletedEvent(
            instance_id=restored.instance_id,
            node_id="a1",
            payload={"result": "success"},
        )
        result = resume(flow, restored, ev, dispatcher=d)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["ok"] is True

    def test_update_after_resume_persists_final_state(self):
        """After resume, update_instance stores the completed state."""
        store = InMemoryStateStore()
        d = InMemoryDispatcher()
        flow = _flow("wf-3", "a1", [
            NodeDefinition(id="a1", type="action", config={"worker": "w"}),
        ])
        instance = start(flow, {}, dispatcher=d)
        store.save_instance(instance)

        restored = store.load_instance(instance.instance_id)
        ev = TaskCompletedEvent(instance_id=restored.instance_id, node_id="a1")
        result = resume(flow, restored, ev, dispatcher=d)
        assert result.status == NodeState.SUCCEEDED

        store.update_instance(result)

        final = store.load_instance(result.instance_id)
        assert final.status == NodeState.SUCCEEDED
        assert final.node_states["a1"].state == NodeState.SUCCEEDED

    def test_human_gate_waiting_persists_and_approves(self):
        """Human gate WAITING state survives save/load and resumes on approval."""
        store = InMemoryStateStore()
        flow = _flow("wf-4", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", next="d1", config={}),
            NodeDefinition(id="d1",  type="decision",              config={"set": {"approved": True}}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.WAITING

        store.save_instance(instance)
        restored = store.load_instance(instance.instance_id)
        assert restored.node_states["hg1"].state == NodeState.WAITING

        ev = HumanApprovedEvent(
            instance_id=restored.instance_id, node_id="hg1", approver="alice"
        )
        result = resume(flow, restored, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["approved"] is True

    def test_human_gate_rejection_persists(self):
        """Rejection result is preserved in the updated store."""
        store = InMemoryStateStore()
        flow = _flow("wf-5", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        instance = start(flow, {})
        store.save_instance(instance)

        restored = store.load_instance(instance.instance_id)
        ev = HumanRejectedEvent(
            instance_id=restored.instance_id, node_id="hg1", reason="too risky"
        )
        result = resume(flow, restored, ev)
        assert result.status == NodeState.FAILED

        store.update_instance(result)
        final = store.load_instance(result.instance_id)
        assert final.status == NodeState.FAILED
        assert final.node_states["hg1"].state == NodeState.FAILED
        assert final.context["hg1"]["approved"] is False


# ---------------------------------------------------------------------------
# state/event_store.py — InMemoryEventStore
# ---------------------------------------------------------------------------

class TestInMemoryEventStore:
    def test_starts_empty(self):
        es = InMemoryEventStore()
        assert es.list_events("any-id") == []
        assert len(es) == 0

    def test_append_and_list(self):
        es = InMemoryEventStore()
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1")
        es.append(ev)
        events = es.list_events("i1")
        assert events == [ev]

    def test_append_multiple_ordered(self):
        es = InMemoryEventStore()
        e1 = TaskCompletedEvent(instance_id="i1", node_id="a1")
        e2 = HumanApprovedEvent(instance_id="i1", node_id="hg1")
        es.append(e1)
        es.append(e2)
        events = es.list_events("i1")
        assert events == [e1, e2]

    def test_events_are_independent_per_instance(self):
        es = InMemoryEventStore()
        e1 = TaskCompletedEvent(instance_id="i1", node_id="a1")
        e2 = TaskCompletedEvent(instance_id="i2", node_id="a1")
        es.append(e1)
        es.append(e2)
        assert es.list_events("i1") == [e1]
        assert es.list_events("i2") == [e2]

    def test_list_events_returns_copy(self):
        es = InMemoryEventStore()
        ev = TaskCompletedEvent(instance_id="i1", node_id="a1")
        es.append(ev)
        result = es.list_events("i1")
        result.clear()  # mutate the returned list
        assert len(es.list_events("i1")) == 1  # store unaffected

    def test_unknown_instance_returns_empty_list(self):
        es = InMemoryEventStore()
        assert es.list_events("unknown") == []

    def test_len_counts_all_events(self):
        es = InMemoryEventStore()
        es.append(TaskCompletedEvent(instance_id="i1", node_id="a1"))
        es.append(TaskCompletedEvent(instance_id="i1", node_id="a2"))
        es.append(HumanApprovedEvent(instance_id="i2", node_id="hg1"))
        assert len(es) == 3

    def test_append_without_instance_id_raises(self):
        es = InMemoryEventStore()
        with pytest.raises(AttributeError):
            es.append(object())  # no instance_id attribute

    def test_multiple_stores_are_independent(self):
        es1, es2 = InMemoryEventStore(), InMemoryEventStore()
        es1.append(TaskCompletedEvent(instance_id="i1", node_id="a1"))
        assert es2.list_events("i1") == []
