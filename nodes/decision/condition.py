"""
nodes/decision/condition.py
----------------------------
Condition node: evaluates a boolean expression and returns the appropriate
successor node id.

Config keys
-----------
expression : str
    A binary comparison expression, e.g. ``"age > 18"`` or
    ``"status == 'active'"``.  Evaluated by
    :func:`runtime.decision_contract.evaluate`.
"""
from __future__ import annotations

from typing import Any

from dsl.compiler import NodeDefinition
from runtime.decision_contract import evaluate


def run(node: NodeDefinition, context: dict[str, Any]) -> str | None:
    """Execute a condition node.

    Reads ``expression`` from ``node.config``, evaluates it against
    *context*, and returns ``node.true_next`` when the expression is
    truthy or ``node.false_next`` when it is falsy.

    Parameters
    ----------
    node:
        The compiled condition :class:`~dsl.compiler.NodeDefinition`.
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
            f"Condition node {node.id!r} requires 'expression' in config"
        )

    result = evaluate(expression, context)
    return node.true_next if result else node.false_next
