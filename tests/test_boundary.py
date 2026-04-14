"""
tests/test_boundary.py
-----------------------
Tests for:
  - nodes/decision/boundary.py   (boundary node run)
  - runtime/engine.py            (start/resume with boundary)
"""
from __future__ import annotations

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from nodes.decision.boundary import run as boundary_run
from runtime.engine import resume, start
from runtime.models import NodeState
from runtime.resume import HumanApprovedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


def _node(
    expression: str,
    true_next: str | None = "yes",
    false_next: str | None = "no",
) -> NodeDefinition:
    return NodeDefinition(
        id="gate",
        type="boundary",
        true_next=true_next,
        false_next=false_next,
        config={"expression": expression},
    )


# ---------------------------------------------------------------------------
# nodes/decision/boundary.py — unit tests
# ---------------------------------------------------------------------------

class TestBoundaryNodeRun:
    def test_true_branch_returned(self):
        assert boundary_run(_node("score > 50"), {"score": 80}) == "yes"

    def test_false_branch_returned(self):
        assert boundary_run(_node("score > 50"), {"score": 20}) == "no"

    def test_eq_operator_true(self):
        assert boundary_run(_node('tier == "premium"'), {"tier": "premium"}) == "yes"

    def test_eq_operator_false(self):
        assert boundary_run(_node('tier == "premium"'), {"tier": "free"}) == "no"

    def test_lt_operator(self):
        assert boundary_run(_node("latency < 200"), {"latency": 150}) == "yes"
        assert boundary_run(_node("latency < 200"), {"latency": 300}) == "no"

    def test_neq_operator(self):
        assert boundary_run(_node("status != 'blocked'"), {"status": "active"}) == "yes"
        assert boundary_run(_node("status != 'blocked'"), {"status": "blocked"}) == "no"

    def test_true_next_none(self):
        node = _node("score > 50", true_next=None)
        assert boundary_run(node, {"score": 80}) is None

    def test_false_next_none(self):
        node = _node("score > 50", false_next=None)
        assert boundary_run(node, {"score": 20}) is None

    def test_missing_expression_raises_value_error(self):
        node = NodeDefinition(id="gate", type="boundary", config={})
        with pytest.raises(ValueError, match="expression"):
            boundary_run(node, {})

    def test_missing_expression_error_mentions_node_id(self):
        node = NodeDefinition(id="my_gate", type="boundary", config={})
        with pytest.raises(ValueError, match="my_gate"):
            boundary_run(node, {})

    def test_missing_context_key_raises_key_error(self):
        from runtime.decision_contract import ExpressionError  # noqa: F401
        node = _node("missing_key > 0")
        with pytest.raises(KeyError, match="missing_key"):
            boundary_run(node, {})

    def test_boundary_is_independent_from_condition(self):
        """boundary and condition evaluate identically but are separate callables."""
        from nodes.decision.condition import run as condition_run
        node_b = NodeDefinition(
            id="b", type="boundary",
            true_next="yes", false_next="no",
            config={"expression": "x > 5"},
        )
        node_c = NodeDefinition(
            id="c", type="condition",
            true_next="yes", false_next="no",
            config={"expression": "x > 5"},
        )
        ctx = {"x": 10}
        assert boundary_run(node_b, ctx) == condition_run(node_c, ctx) == "yes"


# ---------------------------------------------------------------------------
# engine.start — boundary routes synchronously
# ---------------------------------------------------------------------------

class TestEngineStartWithBoundary:
    def test_boundary_true_branch(self):
        flow = _flow("f1", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="high", false_next="low",
                config={"expression": "risk_score > 80"},
            ),
            NodeDefinition(id="high", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="low",  type="decision", config={"set": {"band": "low"}}),
        ])
        instance = start(flow, {"risk_score": 90})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["band"] == "high"
        assert instance.node_states["gate"].state == NodeState.SUCCEEDED
        assert instance.node_states["high"].state == NodeState.SUCCEEDED
        assert "low" not in instance.node_states

    def test_boundary_false_branch(self):
        flow = _flow("f2", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="high", false_next="low",
                config={"expression": "risk_score > 80"},
            ),
            NodeDefinition(id="high", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="low",  type="decision", config={"set": {"band": "low"}}),
        ])
        instance = start(flow, {"risk_score": 40})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["band"] == "low"
        assert "high" not in instance.node_states

    def test_boundary_node_state_succeeded(self):
        flow = _flow("f3", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="d1", false_next="d1",
                config={"expression": "x > 0"},
            ),
            NodeDefinition(id="d1", type="decision", config={"set": {"ok": True}}),
        ])
        instance = start(flow, {"x": 1})
        assert instance.node_states["gate"].state == NodeState.SUCCEEDED

    def test_boundary_node_has_timestamps(self):
        flow = _flow("f4", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="d1", false_next="d1",
                config={"expression": "x > 0"},
            ),
            NodeDefinition(id="d1", type="decision", config={"set": {}}),
        ])
        instance = start(flow, {"x": 1})
        ns = instance.node_states["gate"]
        assert ns.started_at is not None
        assert ns.finished_at is not None
        assert ns.finished_at >= ns.started_at

    def test_decision_then_boundary_then_decision(self):
        """Decision → boundary → decision chain executes fully."""
        flow = _flow("f5", "d1", [
            NodeDefinition(id="d1",   type="decision",  next="gate", config={"set": {"score": 90}}),
            NodeDefinition(
                id="gate", type="boundary",
                true_next="ok", false_next="fail",
                config={"expression": "score > 50"},
            ),
            NodeDefinition(id="ok",   type="decision", config={"set": {"result": "pass"}}),
            NodeDefinition(id="fail", type="decision", config={"set": {"result": "fail"}}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["result"] == "pass"

    def test_condition_then_boundary(self):
        """Condition branches into a boundary; both execute synchronously."""
        flow = _flow("f6", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="gate", false_next="skip",
                config={"expression": "active == true"},
            ),
            NodeDefinition(
                id="gate", type="boundary",
                true_next="high", false_next="med",
                config={"expression": "value > 100"},
            ),
            NodeDefinition(id="high", type="decision", config={"set": {"tier": "high"}}),
            NodeDefinition(id="med",  type="decision", config={"set": {"tier": "med"}}),
            NodeDefinition(id="skip", type="decision", config={"set": {"tier": "none"}}),
        ])
        instance = start(flow, {"active": True, "value": 150})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["tier"] == "high"

    def test_multiple_boundaries_in_chain(self):
        """Two consecutive boundary nodes both evaluate correctly."""
        flow = _flow("f7", "b1", [
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
        assert start(flow, {"x": 80}).context["band"] == "high"
        assert start(flow, {"x": 30}).context["band"] == "mid"
        assert start(flow, {"x": 5}).context["band"] == "low"

    def test_boundary_false_next_none_ends_flow(self):
        """false_next=None causes flow to end gracefully (SUCCEEDED)."""
        flow = _flow("f8", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="d1",
                false_next=None,
                config={"expression": "approved == true"},
            ),
            NodeDefinition(id="d1", type="decision", config={"set": {"ran": True}}),
        ])
        instance = start(flow, {"approved": False})
        assert instance.status == NodeState.SUCCEEDED
        assert "ran" not in instance.context

    def test_boundary_missing_expression_marks_node_failed(self):
        """Missing expression propagates as FAILED node and raises."""
        flow = _flow("f9", "gate", [
            NodeDefinition(id="gate", type="boundary", config={}),
        ])
        with pytest.raises(ValueError, match="expression"):
            start(flow, {})


# ---------------------------------------------------------------------------
# boundary → human_gate
# ---------------------------------------------------------------------------

class TestBoundaryThenHumanGate:
    def test_boundary_true_leads_to_human_gate(self):
        """boundary true branch reaches a human_gate → WAITING."""
        flow = _flow("f10", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="hg1", false_next="auto",
                config={"expression": "amount > 1000"},
            ),
            NodeDefinition(id="hg1",  type="human_gate", config={}),
            NodeDefinition(id="auto", type="decision",   config={"set": {"approved": True}}),
        ])
        instance = start(flow, {"amount": 5000})
        assert instance.status == NodeState.WAITING
        assert instance.node_states["gate"].state == NodeState.SUCCEEDED
        assert instance.node_states["hg1"].state == NodeState.WAITING
        assert "auto" not in instance.node_states

    def test_boundary_false_bypasses_human_gate(self):
        """boundary false branch skips human_gate entirely."""
        flow = _flow("f11", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="hg1", false_next="auto",
                config={"expression": "amount > 1000"},
            ),
            NodeDefinition(id="hg1",  type="human_gate", config={}),
            NodeDefinition(id="auto", type="decision",   config={"set": {"approved": True}}),
        ])
        instance = start(flow, {"amount": 200})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["approved"] is True
        assert "hg1" not in instance.node_states

    def test_boundary_then_human_gate_then_resume(self):
        """Full path: boundary → human_gate (WAITING) → approve → decision."""
        flow = _flow("f12", "gate", [
            NodeDefinition(
                id="gate", type="boundary",
                true_next="hg1", false_next="auto",
                config={"expression": "amount > 1000"},
            ),
            NodeDefinition(id="hg1",  type="human_gate", next="done", config={}),
            NodeDefinition(id="auto", type="decision",   config={"set": {"path": "auto"}}),
            NodeDefinition(id="done", type="decision",   config={"set": {"path": "manual"}}),
        ])
        instance = start(flow, {"amount": 5000})
        assert instance.status == NodeState.WAITING

        ev = HumanApprovedEvent(
            instance_id=instance.instance_id,
            node_id="hg1",
            approver="alice",
        )
        result = resume(flow, instance, ev)
        assert result.status == NodeState.SUCCEEDED
        assert result.context["path"] == "manual"
        assert result.context["hg1"]["approved"] is True
        assert result.context["hg1"]["approver"] == "alice"


# ---------------------------------------------------------------------------
# regression — other node types unaffected
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_condition_still_works(self):
        flow = _flow("r1", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="ok", false_next="ok",
                config={"expression": "x > 0"},
            ),
            NodeDefinition(id="ok", type="decision", config={"set": {"done": True}}),
        ])
        assert start(flow, {"x": 1}).context["done"] is True

    def test_decision_still_works(self):
        flow = _flow("r2", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"x": 42}}),
        ])
        assert start(flow, {}).context["x"] == 42

    def test_human_gate_still_works(self):
        flow = _flow("r3", "hg1", [
            NodeDefinition(id="hg1", type="human_gate", config={}),
        ])
        assert start(flow, {}).status == NodeState.WAITING
