"""
dsl/validator.py
----------------
Structural validation of a parsed DSL dict.

All errors are collected in a single pass before raising, so callers
receive complete feedback without having to fix-and-retry repeatedly.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_NODE_TYPES: frozenset[str] = frozenset(
    {"action", "condition", "decision", "boundary", "human_gate", "parallel"}
)

# Keys that may reference another node id
_TRANSITION_KEYS: tuple[str, ...] = ("next", "true_next", "false_next")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class DSLValidationError(Exception):
    """Raised when a DSL dict fails structural validation.

    Attributes
    ----------
    messages:
        Every individual failure detected in the validation pass.
    """

    def __init__(self, messages: list[str]) -> None:
        self.messages: list[str] = messages
        bullets = "\n".join(f"  • {m}" for m in messages)
        super().__init__(
            f"DSL validation failed ({len(messages)} error(s)):\n{bullets}"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(dsl: dict[str, Any]) -> None:
    """Validate *dsl* structurally.

    Parameters
    ----------
    dsl:
        A dict previously returned by :func:`dsl.parser.parse`.

    Raises
    ------
    DSLValidationError
        One or more structural rules are violated.  All failures are
        included in :attr:`DSLValidationError.messages`.
    """
    errors: list[str] = []

    # ── 1. required top-level keys ──────────────────────────────────────────
    for key in ("flow_id", "start_node", "nodes"):
        if key not in dsl:
            errors.append(f"Missing required top-level key: '{key}'")

    if errors:
        # Cannot safely continue without the basics
        raise DSLValidationError(errors)

    nodes_raw: Any = dsl["nodes"]
    start_node: Any = dsl["start_node"]

    # ── 2. nodes must be a non-empty list ────────────────────────────────────
    if not isinstance(nodes_raw, list) or len(nodes_raw) == 0:
        errors.append("'nodes' must be a non-empty list")
        raise DSLValidationError(errors)

    # ── 3. per-node field checks ─────────────────────────────────────────────
    seen_ids: dict[str, int] = {}   # id → first-occurrence index
    valid_ids: set[str] = set()

    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict):
            errors.append(f"nodes[{idx}] is not a mapping")
            continue

        node_id: Any = node.get("id")
        node_type: Any = node.get("type")

        # --- id ---
        if not node_id:
            errors.append(f"nodes[{idx}] is missing required field 'id'")
        elif node_id in seen_ids:
            errors.append(
                f"Duplicate node id '{node_id}' "
                f"(first seen at index {seen_ids[node_id]}, repeated at {idx})"
            )
        else:
            seen_ids[node_id] = idx
            valid_ids.add(str(node_id))

        # --- type ---
        label = f"nodes[{idx}]" + (f" ('{node_id}')" if node_id else "")
        if not node_type:
            errors.append(f"{label} is missing required field 'type'")
        elif node_type not in ALLOWED_NODE_TYPES:
            errors.append(
                f"{label} has unknown type '{node_type}'. "
                f"Allowed: {sorted(ALLOWED_NODE_TYPES)}"
            )

    # ── 4. start_node must refer to an existing node ─────────────────────────
    if str(start_node) not in valid_ids:
        errors.append(
            f"'start_node' value '{start_node}' does not match any node id"
        )

    # ── 5. transition references must exist ──────────────────────────────────
    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", f"[{idx}]")
        for key in _TRANSITION_KEYS:
            target = node.get(key)
            if target is not None and str(target) not in valid_ids:
                errors.append(
                    f"Node '{node_id}': '{key}' references unknown node '{target}'"
                )

    if errors:
        raise DSLValidationError(errors)
