"""
nodes/decision/human_gate.py
-----------------------------
Human gate node: suspends the workflow until a human approves or rejects.

``run(node)`` performs any pre-suspension setup.  The engine is responsible
for recording the WAITING state and halting the execution loop.

Config keys (all optional)
-----------
message : str
    A prompt shown to the approver (e.g. displayed in a UI or notification).
approvers : list[str]
    Identifiers of the users or roles permitted to act on this gate.

The engine resumes this node via
:class:`~runtime.resume.HumanApprovedEvent` or
:class:`~runtime.resume.HumanRejectedEvent`.
"""
from __future__ import annotations

from dsl.compiler import NodeDefinition


def run(node: NodeDefinition) -> None:
    """Prepare a human gate node for suspension.

    Currently a no-op: state management (WAITING) is handled entirely by the
    engine.  Config keys such as ``message`` and ``approvers`` are available
    for external notification systems via ``node.config`` but are not
    validated here.

    Parameters
    ----------
    node:
        The compiled human_gate :class:`~dsl.compiler.NodeDefinition`.
    """
