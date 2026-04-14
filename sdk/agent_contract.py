"""
sdk/agent_contract.py
----------------------
Minimal descriptor for a registered agent.

An :class:`AgentContract` captures the metadata needed by the
:class:`~sdk.agent_registry.AgentRegistry` to look up agents by id and by
worker type.  Business logic lives in the concrete worker implementations
(see :mod:`execution.worker_interface`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContract:
    """Descriptor for a single registered agent.

    Attributes
    ----------
    agent_id:
        Globally unique identifier for this agent.
    worker_type:
        Logical role or capability label (e.g. ``"summariser"``,
        ``"code-reviewer"``).  Used by dispatchers to route tasks.
    description:
        Human-readable summary of what this agent does.
    metadata:
        Arbitrary key/value pairs for extension (model name, endpoint, …).
    """

    agent_id:    str
    worker_type: str
    description: str            = ""
    metadata:    dict[str, Any] = field(default_factory=dict)
