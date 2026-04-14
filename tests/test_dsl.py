"""tests/test_dsl.py — tests for dsl.parser, dsl.validator, dsl.compiler."""
from __future__ import annotations

import json
from typing import Any

import pytest

from dsl.compiler import FlowDefinition, NodeDefinition, compile_dsl
from dsl.parser import parse
from dsl.validator import ALLOWED_NODE_TYPES, DSLValidationError, validate

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MINIMAL: dict[str, Any] = {
    "flow_id": "min-flow",
    "start_node": "n1",
    "nodes": [{"id": "n1", "type": "action"}],
}

BRANCHING: dict[str, Any] = {
    "flow_id": "branch-flow",
    "start_node": "start",
    "nodes": [
        {"id": "start",    "type": "action",    "next": "gate"},
        {"id": "gate",     "type": "condition", "true_next": "ok", "false_next": "fail"},
        {"id": "ok",       "type": "human_gate"},
        {"id": "fail",     "type": "action"},
    ],
}


# ===========================================================================
# dsl.parser
# ===========================================================================

class TestParser:
    # ── dict input ──────────────────────────────────────────────────────────

    def test_dict_returned_as_copy(self):
        src = {"flow_id": "f", "start_node": "n", "nodes": []}
        result = parse(src)
        assert result == src
        assert result is not src  # shallow copy, not same object

    def test_dict_mutation_does_not_affect_original(self):
        src = {"key": "value"}
        result = parse(src)
        result["extra"] = True
        assert "extra" not in src

    # ── YAML string input ───────────────────────────────────────────────────

    def test_yaml_string_single_node(self):
        yaml_src = """
flow_id: yaml-flow
start_node: n1
nodes:
  - id: n1
    type: action
"""
        result = parse(yaml_src)
        assert result["flow_id"] == "yaml-flow"
        assert result["nodes"][0]["id"] == "n1"

    def test_yaml_string_with_transitions(self):
        yaml_src = """
flow_id: f
start_node: a
nodes:
  - id: a
    type: condition
    true_next: b
    false_next: c
  - id: b
    type: action
  - id: c
    type: action
"""
        result = parse(yaml_src)
        assert result["nodes"][0]["true_next"] == "b"
        assert result["nodes"][0]["false_next"] == "c"

    # ── JSON string input ───────────────────────────────────────────────────

    def test_json_string(self):
        src = {"flow_id": "jf", "start_node": "n1", "nodes": [{"id": "n1", "type": "action"}]}
        result = parse(json.dumps(src))
        assert result == src

    # ── error cases ─────────────────────────────────────────────────────────

    def test_wrong_type_raises_type_error(self):
        with pytest.raises(TypeError, match="parse\\(\\) expects str or dict"):
            parse(42)  # type: ignore[arg-type]

    def test_list_type_raises_type_error(self):
        with pytest.raises(TypeError):
            parse([1, 2, 3])  # type: ignore[arg-type]

    def test_invalid_yaml_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid YAML"):
            parse("key: [unclosed bracket")

    def test_yaml_list_at_root_raises_value_error(self):
        with pytest.raises(ValueError, match="mapping at the top level"):
            parse("- item1\n- item2\n")

    def test_yaml_scalar_at_root_raises_value_error(self):
        with pytest.raises(ValueError, match="mapping at the top level"):
            parse("just a string")


# ===========================================================================
# dsl.validator
# ===========================================================================

class TestValidator:
    # ── happy path ──────────────────────────────────────────────────────────

    def test_minimal_flow_is_valid(self):
        validate(MINIMAL)  # must not raise

    def test_branching_flow_is_valid(self):
        validate(BRANCHING)  # must not raise

    def test_all_allowed_types_accepted(self):
        for node_type in ALLOWED_NODE_TYPES:
            dsl = {
                "flow_id": "f",
                "start_node": "n",
                "nodes": [{"id": "n", "type": node_type}],
            }
            validate(dsl)  # must not raise

    def test_returns_none_on_success(self):
        assert validate(MINIMAL) is None

    # ── missing top-level keys ───────────────────────────────────────────────

    def test_missing_flow_id(self):
        dsl = {"start_node": "n1", "nodes": [{"id": "n1", "type": "action"}]}
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("flow_id" in m for m in exc_info.value.messages)

    def test_missing_start_node(self):
        dsl = {"flow_id": "f", "nodes": [{"id": "n1", "type": "action"}]}
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("start_node" in m for m in exc_info.value.messages)

    def test_missing_nodes(self):
        dsl = {"flow_id": "f", "start_node": "n1"}
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("nodes" in m for m in exc_info.value.messages)

    def test_empty_nodes_list(self):
        dsl = {"flow_id": "f", "start_node": "n1", "nodes": []}
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("non-empty" in m for m in exc_info.value.messages)

    # ── per-node field errors ────────────────────────────────────────────────

    def test_node_missing_id(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"type": "action"}, {"id": "n1", "type": "action"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("missing required field 'id'" in m for m in exc_info.value.messages)

    def test_node_missing_type(self):
        dsl = {"flow_id": "f", "start_node": "n1", "nodes": [{"id": "n1"}]}
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("missing required field 'type'" in m for m in exc_info.value.messages)

    def test_node_unknown_type(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"id": "n1", "type": "magic_wizard"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("magic_wizard" in m for m in exc_info.value.messages)

    # ── duplicate node id ────────────────────────────────────────────────────

    def test_duplicate_node_id(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [
                {"id": "n1", "type": "action"},
                {"id": "n1", "type": "action"},
            ],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("Duplicate" in m and "n1" in m for m in exc_info.value.messages)

    # ── start_node reference ─────────────────────────────────────────────────

    def test_start_node_not_in_nodes(self):
        dsl = {
            "flow_id": "f", "start_node": "ghost",
            "nodes": [{"id": "n1", "type": "action"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("ghost" in m and "start_node" in m for m in exc_info.value.messages)

    # ── transition reference errors ──────────────────────────────────────────

    def test_invalid_next_reference(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"id": "n1", "type": "action", "next": "nowhere"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("nowhere" in m and "'next'" in m for m in exc_info.value.messages)

    def test_invalid_true_next_reference(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"id": "n1", "type": "condition", "true_next": "ghost"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("ghost" in m and "'true_next'" in m for m in exc_info.value.messages)

    def test_invalid_false_next_reference(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"id": "n1", "type": "condition", "false_next": "phantom"}],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert any("phantom" in m and "'false_next'" in m for m in exc_info.value.messages)

    # ── multi-error collection ───────────────────────────────────────────────

    def test_multiple_errors_collected_at_once(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [
                {"id": "n1", "type": "bad_type"},        # unknown type
                {"id": "n1", "type": "action"},          # duplicate id
                {"id": "n3", "type": "action", "next": "ghost"},  # bad ref
            ],
        }
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert len(exc_info.value.messages) >= 2

    # ── DSLValidationError structure ─────────────────────────────────────────

    def test_error_messages_attribute(self):
        dsl = {"start_node": "x"}  # missing flow_id and nodes
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        err = exc_info.value
        assert isinstance(err.messages, list)
        assert len(err.messages) >= 1

    def test_error_string_contains_count(self):
        dsl = {"start_node": "x"}  # missing flow_id and nodes
        with pytest.raises(DSLValidationError) as exc_info:
            validate(dsl)
        assert "error" in str(exc_info.value).lower()


# ===========================================================================
# dsl.compiler
# ===========================================================================

class TestCompiler:
    # ── FlowDefinition structure ─────────────────────────────────────────────

    def test_returns_flow_definition(self):
        result = compile_dsl(MINIMAL)
        assert isinstance(result, FlowDefinition)

    def test_flow_id_and_start_node(self):
        fd = compile_dsl(MINIMAL)
        assert fd.flow_id    == "min-flow"
        assert fd.start_node == "n1"

    def test_nodes_by_id_is_dict(self):
        fd = compile_dsl(MINIMAL)
        assert isinstance(fd.nodes_by_id, dict)

    def test_nodes_by_id_keyed_by_node_id(self):
        fd = compile_dsl(BRANCHING)
        assert set(fd.nodes_by_id.keys()) == {"start", "gate", "ok", "fail"}

    # ── NodeDefinition fields ────────────────────────────────────────────────

    def test_node_definition_type(self):
        fd = compile_dsl(MINIMAL)
        assert isinstance(fd.nodes_by_id["n1"], NodeDefinition)

    def test_node_id_and_type(self):
        fd = compile_dsl(BRANCHING)
        gate = fd.nodes_by_id["gate"]
        assert gate.id   == "gate"
        assert gate.type == "condition"

    def test_next_transition(self):
        fd = compile_dsl(BRANCHING)
        assert fd.nodes_by_id["start"].next == "gate"

    def test_true_next_and_false_next(self):
        fd = compile_dsl(BRANCHING)
        gate = fd.nodes_by_id["gate"]
        assert gate.true_next  == "ok"
        assert gate.false_next == "fail"

    def test_absent_transitions_are_none(self):
        fd = compile_dsl(MINIMAL)
        n1 = fd.nodes_by_id["n1"]
        assert n1.next       is None
        assert n1.true_next  is None
        assert n1.false_next is None

    # ── config passthrough ───────────────────────────────────────────────────

    def test_extra_keys_go_into_config(self):
        dsl = {
            "flow_id": "f", "start_node": "n1",
            "nodes": [{"id": "n1", "type": "action", "timeout": 30, "retries": 3}],
        }
        fd = compile_dsl(dsl)
        assert fd.nodes_by_id["n1"].config == {"timeout": 30, "retries": 3}

    def test_reserved_keys_not_in_config(self):
        dsl = {
            "flow_id": "f", "start_node": "a",
            "nodes": [
                {"id": "a", "type": "condition", "true_next": "b", "false_next": "c", "label": "check"},
                {"id": "b", "type": "action"},
                {"id": "c", "type": "action"},
            ],
        }
        fd = compile_dsl(dsl)
        cfg = fd.nodes_by_id["a"].config
        assert "id"         not in cfg
        assert "type"       not in cfg
        assert "true_next"  not in cfg
        assert "false_next" not in cfg
        assert cfg == {"label": "check"}

    def test_node_with_no_extra_keys_has_empty_config(self):
        fd = compile_dsl(MINIMAL)
        assert fd.nodes_by_id["n1"].config == {}

    # ── integration: parse → validate → compile ──────────────────────────────

    def test_full_pipeline_from_yaml(self):
        yaml_src = """
flow_id: pipeline-test
start_node: step1
nodes:
  - id: step1
    type: action
    next: step2
    timeout: 60
  - id: step2
    type: human_gate
"""
        dsl = parse(yaml_src)
        validate(dsl)
        fd = compile_dsl(dsl)

        assert fd.flow_id    == "pipeline-test"
        assert fd.start_node == "step1"
        assert fd.nodes_by_id["step1"].next == "step2"
        assert fd.nodes_by_id["step1"].config == {"timeout": 60}
        assert fd.nodes_by_id["step2"].type == "human_gate"
