"""
runtime/decision_contract.py
-----------------------------
Minimal expression evaluator for condition nodes.

Supports binary comparisons: >, <, ==, !=
Left-hand side must be a context key; right-hand side is a literal.

Example expressions::

    "age > 18"
    "status == 'active'"
    "score != 0"
    "price < 99.9"
    "approved == true"
"""
from __future__ import annotations

import re
from typing import Any

_OPS: dict[str, Any] = {
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

# Matches: <identifier> <op> <literal>
# Groups:  (key, op, raw_value)
_EXPR_RE = re.compile(r"^\s*(\w[\w.]*)\s*(>|<|==|!=)\s*(.+?)\s*$")


class ExpressionError(ValueError):
    """Raised when an expression string cannot be parsed."""


def evaluate(expression: str, context: dict[str, Any]) -> bool:
    """Evaluate *expression* against *context* and return a ``bool``.

    Parameters
    ----------
    expression:
        A simple binary expression, e.g. ``"age > 18"`` or
        ``"status == 'active'"``.
    context:
        Mapping of variable names to their current values.  The left-hand
        side of the expression is looked up here.

    Returns
    -------
    bool

    Raises
    ------
    ExpressionError
        If the expression cannot be parsed (bad syntax or unknown operator).
    KeyError
        If the left-hand side key is absent from *context*.
    """
    m = _EXPR_RE.match(expression)
    if not m:
        raise ExpressionError(f"Cannot parse expression: {expression!r}")

    key, op, raw = m.groups()

    if key not in context:
        raise KeyError(f"Context key {key!r} not found in context")

    left = context[key]
    right = _parse_literal(raw.strip())

    return bool(_OPS[op](left, right))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_literal(raw: str) -> Any:
    """Convert a raw string token to a Python value."""
    # Quoted string — single or double quotes
    if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
        return raw[1:-1]

    # Boolean literals
    if raw == "true":
        return True
    if raw == "false":
        return False

    # Null / None
    if raw in ("null", "None"):
        return None

    # Integer
    try:
        return int(raw)
    except ValueError:
        pass

    # Float
    try:
        return float(raw)
    except ValueError:
        pass

    # Bare (unquoted) string fallback
    return raw
