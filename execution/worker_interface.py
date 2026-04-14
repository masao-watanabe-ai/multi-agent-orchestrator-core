"""
execution/worker_interface.py
------------------------------
Abstract base class for worker implementations.

Concrete workers (LLM agents, tool runners, human-approval handlers, …)
inherit from :class:`WorkerInterface` and implement :meth:`handle`.
The engine never calls workers directly — tasks are routed through a
dispatcher that resolves the correct worker at runtime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from runtime.models import Task


class WorkerInterface(ABC):
    """Contract that every worker implementation must satisfy."""

    @abstractmethod
    def handle(self, task: Task) -> Any:
        """Process *task* and return a result.

        Parameters
        ----------
        task:
            The task to execute.  ``task.payload["worker"]`` identifies
            which worker type this task was routed to.

        Returns
        -------
        Any
            An arbitrary result that callers may inspect.  The engine
            currently does not consume this value (resume is not yet
            implemented).

        Raises
        ------
        Exception
            Implementations may raise any exception to signal failure.
        """
