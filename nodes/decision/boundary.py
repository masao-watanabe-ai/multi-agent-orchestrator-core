"""
nodes/decision/boundary.py
---------------------------
Boundary node: evaluates a boolean expression and routes execution to
``true_next`` or ``false_next``.

A boundary marks a semantically significant branch point in a workflow —
e.g. an SLA threshold, a risk gate, or a capability limit — where the
branching condition is explicitly named in the node rather than embedded in
a generic condition chain.  The evaluation logic is identical to
:mod:`nodes.decision.condition`; the distinction is intentional and
communicative.

Config keys
-----------
expression : str  (required)
    A binary comparison expression evaluated by
    :func:`runtime.decision_contract.evaluate`.
    E.g. ``"risk_score > 80"`` or ``"tier == 'premium'"``.

Example DSL::

    - id: risk_gate
      type: boundary
      expression: "risk_score > 80"
      true_next: escalate
      false_next: auto_approve
"""
from __future__ import annotations

from typing import Any

from dsl.compiler import NodeDefinition
from runtime.decision_contract import evaluate


def run(node: NodeDefinition, context: dict[str, Any]) -> str | None:
    """Execute a boundary node.

    Reads ``expression`` from ``node.config``, evaluates it against
    *context*, and returns ``node.true_next`` when the expression is
    truthy or ``node.false_next`` when it is falsy.

    Parameters
    ----------
    node:
        The compiled boundary :class:`~dsl.compiler.NodeDefinition`.
    context:
        Current execution context used to resolve expression variables.

    Returns
    -------
    str | None
        The id of the next node to execute, or ``None`` if the taken
        branch has no successor.

    Raises
    ------
    ValueError
        If ``node.config`` does not contain an ``"expression"`` key.
    """
    expression = node.config.get("expression")
    if expression is None:
        raise ValueError(
            f"Boundary node {node.id!r} requires 'expression' in config"
        )

    result = evaluate(expression, context)
    return node.true_next if result else node.false_next
