"""
dsl/compiler.py
---------------
Compile a validated DSL dict into the engine-ready :class:`FlowDefinition`.

Call :func:`compile_dsl` **after** :func:`dsl.validator.validate` has
passed.  This module contains no validation logic of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Keys that are lifted to first-class attributes; everything else → config
_RESERVED: frozenset[str] = frozenset({"id", "type", "next", "true_next", "false_next"})


# ---------------------------------------------------------------------------
# Internal representation
# ---------------------------------------------------------------------------

@dataclass
class NodeDefinition:
    """Compiled descriptor for a single workflow node.

    Consumed by ``runtime.engine`` — not meant to be constructed manually.

    Attributes
    ----------
    id:
        Unique node identifier within the flow.
    type:
        One of the allowed node types (e.g. ``"action"``, ``"condition"``).
    next:
        Default successor node id (used by action / sequential nodes).
    true_next:
        Successor taken when a condition evaluates to ``True``.
    false_next:
        Successor taken when a condition evaluates to ``False``.
    config:
        All extra DSL keys not listed above (node-specific parameters).
    """

    id:         str
    type:       str
    next:       str | None     = None
    true_next:  str | None     = None
    false_next: str | None     = None
    config:     dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowDefinition:
    """Engine-ready compiled representation of a workflow.

    Produced by :func:`compile_dsl`; consumed by ``runtime.engine``.

    Attributes
    ----------
    flow_id:
        Stable identifier for this workflow definition.
    start_node:
        The node id where execution begins.
    nodes_by_id:
        All nodes keyed by their ``id`` for O(1) lookup.
    """

    flow_id:     str
    start_node:  str
    nodes_by_id: dict[str, NodeDefinition]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_dsl(dsl: dict[str, Any]) -> FlowDefinition:
    """Convert a validated DSL dict into a :class:`FlowDefinition`.

    Parameters
    ----------
    dsl:
        A dict that has already been accepted by
        :func:`dsl.validator.validate`.

    Returns
    -------
    FlowDefinition
    """
    nodes_by_id: dict[str, NodeDefinition] = {}

    for node_raw in dsl["nodes"]:
        node_id = node_raw["id"]

        # Separate known transition keys from arbitrary config
        config = {k: v for k, v in node_raw.items() if k not in _RESERVED}

        nodes_by_id[node_id] = NodeDefinition(
            id=node_id,
            type=node_raw["type"],
            next=node_raw.get("next"),
            true_next=node_raw.get("true_next"),
            false_next=node_raw.get("false_next"),
            config=config,
        )

    return FlowDefinition(
        flow_id=dsl["flow_id"],
        start_node=dsl["start_node"],
        nodes_by_id=nodes_by_id,
    )
