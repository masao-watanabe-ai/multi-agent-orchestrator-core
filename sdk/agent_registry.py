"""
sdk/agent_registry.py
----------------------
Minimal in-process agent registry.

:class:`AgentRegistry` stores :class:`~sdk.agent_contract.AgentContract`
instances by ``agent_id`` and supports ``register`` / ``get`` operations.
A later implementation may back this with a remote store; the interface is
intentionally simple so callers have no external dependencies.
"""
from __future__ import annotations

from sdk.agent_contract import AgentContract


class AgentRegistry:
    """In-memory registry for :class:`~sdk.agent_contract.AgentContract` entries.

    Usage::

        registry = AgentRegistry()
        registry.register(AgentContract(agent_id="summariser", worker_type="llm"))
        contract = registry.get("summariser")
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentContract] = {}

    def register(self, contract: AgentContract) -> None:
        """Store *contract*, replacing any previous entry with the same id.

        Parameters
        ----------
        contract:
            The :class:`~sdk.agent_contract.AgentContract` to register.
        """
        self._agents[contract.agent_id] = contract

    def get(self, agent_id: str) -> AgentContract:
        """Return the contract registered under *agent_id*.

        Parameters
        ----------
        agent_id:
            The id to look up.

        Returns
        -------
        AgentContract

        Raises
        ------
        KeyError
            If no contract with *agent_id* has been registered.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id!r} is not registered")
        return self._agents[agent_id]

    def __len__(self) -> int:
        return len(self._agents)
