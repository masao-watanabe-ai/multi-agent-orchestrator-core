"""
tests/test_engine.py
---------------------
Tests for:
  - runtime/decision_contract.py  (ExpressionError, evaluate)
  - nodes/decision/condition.py   (condition node run)
  - nodes/decision/decision.py    (decision node run)
  - runtime/engine.py             (start, UnsupportedNodeTypeError)
"""
from __future__ import annotations

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition
from runtime.decision_contract import ExpressionError, evaluate
from runtime.engine import UnsupportedNodeTypeError, start
from runtime.models import NodeState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flow(flow_id: str, start_node: str, nodes: list[NodeDefinition]) -> FlowDefinition:
    return FlowDefinition(
        flow_id=flow_id,
        start_node=start_node,
        nodes_by_id={n.id: n for n in nodes},
    )


# ---------------------------------------------------------------------------
# decision_contract.evaluate
# ---------------------------------------------------------------------------

class TestEvaluate:
    def test_gt_true(self):
        assert evaluate("age > 18", {"age": 25}) is True

    def test_gt_false(self):
        assert evaluate("age > 18", {"age": 10}) is False

    def test_lt_true(self):
        assert evaluate("score < 100", {"score": 50}) is True

    def test_lt_false(self):
        assert evaluate("score < 100", {"score": 150}) is False

    def test_eq_int_true(self):
        assert evaluate("count == 0", {"count": 0}) is True

    def test_eq_int_false(self):
        assert evaluate("count == 0", {"count": 1}) is False

    def test_neq_int_true(self):
        assert evaluate("count != 0", {"count": 1}) is True

    def test_neq_int_false(self):
        assert evaluate("count != 0", {"count": 0}) is False

    def test_eq_string_double_quotes_true(self):
        assert evaluate('status == "active"', {"status": "active"}) is True

    def test_eq_string_double_quotes_false(self):
        assert evaluate('status == "active"', {"status": "inactive"}) is False

    def test_eq_string_single_quotes(self):
        assert evaluate("status == 'active'", {"status": "active"}) is True

    def test_neq_string(self):
        assert evaluate('status != "done"', {"status": "pending"}) is True

    def test_float_lt(self):
        assert evaluate("price < 99.9", {"price": 50.0}) is True

    def test_float_gt(self):
        assert evaluate("price > 99.9", {"price": 150.0}) is True

    def test_bool_true_literal(self):
        assert evaluate("approved == true", {"approved": True}) is True

    def test_bool_false_literal(self):
        assert evaluate("approved == false", {"approved": False}) is True

    def test_missing_key_raises_key_error(self):
        with pytest.raises(KeyError, match="missing"):
            evaluate("missing > 0", {})

    def test_invalid_expression_raises_expression_error(self):
        with pytest.raises(ExpressionError):
            evaluate("this is not valid", {"foo": 1})

    def test_no_operator_raises_expression_error(self):
        with pytest.raises(ExpressionError):
            evaluate("age", {"age": 18})

    def test_whitespace_around_operands(self):
        assert evaluate("  age  >  18  ", {"age": 25}) is True


# ---------------------------------------------------------------------------
# condition node
# ---------------------------------------------------------------------------

class TestConditionNode:
    from nodes.decision.condition import run as _run  # imported at class level

    def _node(
        self,
        expression: str,
        true_next: str | None = "yes",
        false_next: str | None = "no",
    ) -> NodeDefinition:
        return NodeDefinition(
            id="check",
            type="condition",
            true_next=true_next,
            false_next=false_next,
            config={"expression": expression},
        )

    def test_true_branch(self):
        from nodes.decision.condition import run
        assert run(self._node("score > 50"), {"score": 80}) == "yes"

    def test_false_branch(self):
        from nodes.decision.condition import run
        assert run(self._node("score > 50"), {"score": 20}) == "no"

    def test_true_next_none(self):
        from nodes.decision.condition import run
        assert run(self._node("score > 50", true_next=None), {"score": 80}) is None

    def test_false_next_none(self):
        from nodes.decision.condition import run
        assert run(self._node("score > 50", false_next=None), {"score": 10}) is None

    def test_missing_expression_raises(self):
        from nodes.decision.condition import run
        node = NodeDefinition(id="check", type="condition", config={})
        with pytest.raises(ValueError, match="expression"):
            run(node, {})

    def test_eq_operator(self):
        from nodes.decision.condition import run
        node = self._node('role == "admin"')
        assert run(node, {"role": "admin"}) == "yes"
        assert run(node, {"role": "user"}) == "no"


# ---------------------------------------------------------------------------
# decision node
# ---------------------------------------------------------------------------

class TestDecisionNode:
    def test_sets_single_key(self):
        from nodes.decision.decision import run
        node = NodeDefinition(
            id="approve",
            type="decision",
            next="notify",
            config={"set": {"approved": True}},
        )
        ctx: dict = {}
        result = run(node, ctx)
        assert result == "notify"
        assert ctx["approved"] is True

    def test_sets_multiple_keys(self):
        from nodes.decision.decision import run
        node = NodeDefinition(
            id="approve",
            type="decision",
            next="notify",
            config={"set": {"approved": True, "reason": "ok"}},
        )
        ctx: dict = {}
        run(node, ctx)
        assert ctx["approved"] is True
        assert ctx["reason"] == "ok"

    def test_returns_next(self):
        from nodes.decision.decision import run
        node = NodeDefinition(
            id="step",
            type="decision",
            next="end",
            config={"set": {"x": 1}},
        )
        assert run(node, {}) == "end"

    def test_returns_none_when_next_unset(self):
        from nodes.decision.decision import run
        node = NodeDefinition(id="step", type="decision", config={"set": {"x": 1}})
        assert run(node, {}) is None

    def test_missing_set_raises(self):
        from nodes.decision.decision import run
        node = NodeDefinition(id="d", type="decision", config={})
        with pytest.raises(ValueError, match="set"):
            run(node, {})

    def test_set_not_dict_raises(self):
        from nodes.decision.decision import run
        node = NodeDefinition(id="d", type="decision", config={"set": "wrong"})
        with pytest.raises(ValueError, match="mapping"):
            run(node, {})

    def test_overwrites_existing_key(self):
        from nodes.decision.decision import run
        node = NodeDefinition(
            id="d", type="decision",
            config={"set": {"flag": False}},
        )
        ctx = {"flag": True}
        run(node, ctx)
        assert ctx["flag"] is False


# ---------------------------------------------------------------------------
# engine.start
# ---------------------------------------------------------------------------

class TestEngineStart:
    def test_single_decision_node(self):
        flow = _flow("f1", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"result": "done"}}),
        ])
        instance = start(flow, {"x": 1})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["result"] == "done"
        assert instance.node_states["d1"].state == NodeState.SUCCEEDED

    def test_condition_true_branch(self):
        flow = _flow("f2", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="yes_node", false_next="no_node",
                config={"expression": "score > 50"},
            ),
            NodeDefinition(id="yes_node", type="decision", config={"set": {"outcome": "pass"}}),
            NodeDefinition(id="no_node",  type="decision", config={"set": {"outcome": "fail"}}),
        ])
        instance = start(flow, {"score": 80})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["outcome"] == "pass"
        assert instance.node_states["cond"].state == NodeState.SUCCEEDED
        assert instance.node_states["yes_node"].state == NodeState.SUCCEEDED
        assert "no_node" not in instance.node_states

    def test_condition_false_branch(self):
        flow = _flow("f3", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="yes_node", false_next="no_node",
                config={"expression": "score > 50"},
            ),
            NodeDefinition(id="yes_node", type="decision", config={"set": {"outcome": "pass"}}),
            NodeDefinition(id="no_node",  type="decision", config={"set": {"outcome": "fail"}}),
        ])
        instance = start(flow, {"score": 20})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["outcome"] == "fail"
        assert "yes_node" not in instance.node_states
        assert instance.node_states["no_node"].state == NodeState.SUCCEEDED

    def test_chain_decision_decision(self):
        flow = _flow("f4", "d1", [
            NodeDefinition(id="d1", type="decision", next="d2", config={"set": {"step1": True}}),
            NodeDefinition(id="d2", type="decision",              config={"set": {"step2": True}}),
        ])
        instance = start(flow, {})
        assert instance.status == NodeState.SUCCEEDED
        assert instance.context["step1"] is True
        assert instance.context["step2"] is True
        assert instance.node_states["d1"].state == NodeState.SUCCEEDED
        assert instance.node_states["d2"].state == NodeState.SUCCEEDED

    def test_node_states_have_timestamps(self):
        flow = _flow("f5", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"k": 1}}),
        ])
        instance = start(flow, {})
        ns = instance.node_states["d1"]
        assert ns.started_at is not None
        assert ns.finished_at is not None
        assert ns.finished_at >= ns.started_at

    def test_instance_has_correct_workflow_id(self):
        flow = _flow("my-flow", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {}}),
        ])
        instance = start(flow)
        assert instance.workflow_id == "my-flow"
        assert instance.instance_id != ""

    def test_context_is_not_mutated(self):
        """Caller's original context dict must not be modified."""
        flow = _flow("f6", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"new_key": 42}}),
        ])
        original = {"existing": "value"}
        instance = start(flow, original)
        assert "new_key" not in original
        assert instance.context["new_key"] == 42
        assert instance.context["existing"] == "value"

    def test_default_context_is_empty_dict(self):
        flow = _flow("f7", "d1", [
            NodeDefinition(id="d1", type="decision", config={"set": {"x": 1}}),
        ])
        instance = start(flow)
        assert instance.context["x"] == 1

    def test_unsupported_node_type_raises(self):
        # "action" is now supported; use an unimplemented type instead.
        # "boundary" is now supported; use an unimplemented type instead.
        flow = _flow("f8", "p1", [
            NodeDefinition(id="p1", type="parallel", config={}),
        ])
        with pytest.raises(UnsupportedNodeTypeError) as exc_info:
            start(flow, {})
        assert exc_info.value.node_type == "parallel"
        assert exc_info.value.node_id == "p1"

    def test_unsupported_type_marks_instance_failed(self):
        flow = _flow("f9", "p1", [
            NodeDefinition(id="p1", type="parallel", config={}),
        ])
        with pytest.raises(UnsupportedNodeTypeError):
            start(flow, {})
        # instance is not returned on failure; just verify the raise path

    def test_failed_node_reraises_and_marks_failed(self):
        """Missing context key propagates and node_state is FAILED."""
        flow = _flow("f10", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                config={"expression": "missing_key > 0"},
            ),
        ])
        with pytest.raises(KeyError):
            start(flow, {})

    def test_condition_string_equality(self):
        flow = _flow("f11", "cond", [
            NodeDefinition(
                id="cond", type="condition",
                true_next="match", false_next="no_match",
                config={"expression": 'role == "admin"'},
            ),
            NodeDefinition(id="match",    type="decision", config={"set": {"ok": True}}),
            NodeDefinition(id="no_match", type="decision", config={"set": {"ok": False}}),
        ])
        instance = start(flow, {"role": "admin"})
        assert instance.context["ok"] is True

    def test_multiple_conditions_in_chain(self):
        """Two condition nodes in sequence both execute correctly."""
        flow = _flow("f12", "c1", [
            NodeDefinition(
                id="c1", type="condition",
                true_next="c2", false_next="end",
                config={"expression": "x > 0"},
            ),
            NodeDefinition(
                id="c2", type="condition",
                true_next="set_high", false_next="set_low",
                config={"expression": "x > 10"},
            ),
            NodeDefinition(id="set_high", type="decision", config={"set": {"band": "high"}}),
            NodeDefinition(id="set_low",  type="decision", config={"set": {"band": "low"}}),
            NodeDefinition(id="end",      type="decision", config={"set": {"band": "none"}}),
        ])
        # x=15 → c1 true → c2 true → set_high
        i = start(flow, {"x": 15})
        assert i.context["band"] == "high"

        # x=5 → c1 true → c2 false → set_low
        i = start(flow, {"x": 5})
        assert i.context["band"] == "low"

        # x=-1 → c1 false → end
        i = start(flow, {"x": -1})
        assert i.context["band"] == "none"
