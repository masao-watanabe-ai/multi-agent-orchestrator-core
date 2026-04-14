"""
execution/dispatcher.py
------------------------
Dispatcher protocol and a minimal in-memory implementation.

``DispatcherProtocol`` is a structural type (``typing.Protocol``) so any
object that exposes ``dispatch(task)`` satisfies it — no inheritance needed.

``InMemoryDispatcher`` accumulates dispatched tasks in a plain list and is
the default implementation used by tests and local runs.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from runtime.models import Task


@runtime_checkable
class DispatcherProtocol(Protocol):
    """Structural interface for task dispatchers."""

    def dispatch(self, task: Task) -> None:
        """Accept *task* for execution.

        Implementations may enqueue, persist, or immediately forward the task
        to a worker.  The caller does not wait for the task to complete.
        """
        ...


class InMemoryDispatcher:
    """Accumulates dispatched tasks in memory.

    Attributes
    ----------
    tasks:
        Ordered list of every :class:`~runtime.models.Task` that has been
        dispatched since this instance was created.
    """

    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def dispatch(self, task: Task) -> None:
        """Append *task* to the internal list."""
        self.tasks.append(task)
