"""
dsl/parser.py
-------------
Normalise a YAML string, JSON string, or plain dict into a ``dict``.

This is the entry point for all DSL input.  It does *not* validate
structure — that is :mod:`dsl.validator`'s job.
"""
from __future__ import annotations

import json
from typing import Any


def parse(source: str | dict[str, Any]) -> dict[str, Any]:
    """Return a normalised ``dict`` from *source*.

    Parameters
    ----------
    source:
        - ``dict``  — returned as a shallow copy (caller mutations are
          isolated from the original).
        - ``str``   — parsed as YAML first (superset of JSON); falls back
          to :func:`json.loads` when *pyyaml* is not installed.

    Returns
    -------
    dict[str, Any]

    Raises
    ------
    TypeError
        *source* is neither a ``str`` nor a ``dict``.
    ValueError
        *source* is a string that cannot be parsed, or the top-level
        parsed value is not a mapping.
    """
    if isinstance(source, dict):
        return dict(source)

    if not isinstance(source, str):
        raise TypeError(
            f"parse() expects str or dict, got {type(source).__name__!r}"
        )

    result = _load_string(source)

    if not isinstance(result, dict):
        raise ValueError(
            "DSL must be a mapping at the top level, "
            f"got {type(result).__name__!r}"
        )

    return result


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _load_string(text: str) -> Any:
    """Parse *text* as YAML (preferred) or JSON."""
    try:
        import yaml  # type: ignore[import]

        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"DSL string is not valid YAML: {exc}") from exc

    except ImportError:
        pass

    # Fallback: stdlib JSON only
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"DSL string is not valid JSON: {exc}") from exc
