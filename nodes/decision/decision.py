"""
nodes/decision/decision.py
---------------------------
Decision node: writes one or more key/value pairs to the execution context
and returns the successor node id.

Config keys
-----------
set : dict[str, Any]
    Mapping of context keys to their new values.  All entries are merged
    into the execution context before the node is considered complete.

Example DSL::

    - id: approve
      type: decision
      set:
        approved: true
        reason: "manager-override"
      next: notify
"""
from __future__ import annotations

from typing import Any

from dsl.compiler import NodeDefinition


def run(node: NodeDefinition, context: dict[str, Any]) -> str | None:
    """Execute a decision node.

    Merges ``node.config["set"]`` into *context* (in-place) and returns
    ``node.next``.

    Parameters
    ----------
    node:
        The compiled decision :class:`~dsl.compiler.NodeDefinition`.
    context:
        Current execution context; mutated in-place with the values from
        ``node.config["set"]``.

    Returns
    -------
    str | None
        ``node.next``, the id of the successor node (``None`` when the
        flow ends here).

    Raises
    ------
    ValueError
        If ``node.config`` does not contain a ``"set"`` key, or its value
        is not a mapping.
    """
    assignments = node.config.get("set")
    if assignments is None:
        raise ValueError(
            f"Decision node {node.id!r} requires 'set' in config"
        )
    if not isinstance(assignments, dict):
        raise ValueError(
            f"Decision node {node.id!r}: 'set' must be a mapping, "
            f"got {type(assignments).__name__}"
        )

    context.update(assignments)
    return node.next
