"""
state/store.py
---------------
State persistence for :class:`~runtime.models.ExecutionInstance`.

Three things are provided:

StateStoreProtocol
    Structural interface (``typing.Protocol``) for store implementations.

InMemoryStateStore
    dict-backed store; snapshots are deep-copied on every save/load so
    mutations to the caller's instance cannot corrupt stored state.

JsonFileStateStore
    Persists each instance as ``<directory>/<instance_id>.json``.
    ``context`` and ``output`` values must be JSON-native types
    (``str``, ``int``, ``float``, ``bool``, ``None``, ``list``, ``dict``).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from runtime.models import ExecutionInstance
from state.snapshot import from_dict, to_dict


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class StateStoreProtocol(Protocol):
    """Structural interface for ExecutionInstance stores."""

    def save_instance(self, instance: ExecutionInstance) -> None:
        """Persist *instance* for the first time.

        Raises
        ------
        ValueError
            If an instance with the same ``instance_id`` already exists.
        """
        ...

    def load_instance(self, instance_id: str) -> ExecutionInstance:
        """Return the stored instance for *instance_id*.

        Raises
        ------
        KeyError
            If no instance with *instance_id* has been saved.
        """
        ...

    def update_instance(self, instance: ExecutionInstance) -> None:
        """Overwrite the stored snapshot for *instance*.

        Raises
        ------
        KeyError
            If the instance has not been saved yet (use :meth:`save_instance`
            first).
        """
        ...


# ---------------------------------------------------------------------------
# InMemoryStateStore
# ---------------------------------------------------------------------------

class InMemoryStateStore:
    """In-memory state store backed by a plain dict.

    Each save or load performs a ``copy.deepcopy`` of the serialised snapshot
    so that external mutations cannot affect the stored state.

    Attributes
    ----------
    _snapshots:
        ``instance_id`` → serialised snapshot dict.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}

    def save_instance(self, instance: ExecutionInstance) -> None:
        """Persist *instance* (raises ``ValueError`` if already present)."""
        if instance.instance_id in self._snapshots:
            raise ValueError(
                f"Instance {instance.instance_id!r} already exists. "
                "Use update_instance() to overwrite."
            )
        self._snapshots[instance.instance_id] = copy.deepcopy(to_dict(instance))

    def load_instance(self, instance_id: str) -> ExecutionInstance:
        """Return a fresh :class:`~runtime.models.ExecutionInstance` copy."""
        if instance_id not in self._snapshots:
            raise KeyError(f"Instance {instance_id!r} not found in store")
        return from_dict(copy.deepcopy(self._snapshots[instance_id]))

    def load_or_none(self, instance_id: str) -> ExecutionInstance | None:
        """Return the instance or ``None`` if it does not exist."""
        if instance_id not in self._snapshots:
            return None
        return from_dict(copy.deepcopy(self._snapshots[instance_id]))

    def update_instance(self, instance: ExecutionInstance) -> None:
        """Overwrite the stored snapshot (raises ``KeyError`` if not found)."""
        if instance.instance_id not in self._snapshots:
            raise KeyError(
                f"Instance {instance.instance_id!r} not found. "
                "Use save_instance() first."
            )
        self._snapshots[instance.instance_id] = copy.deepcopy(to_dict(instance))

    def __len__(self) -> int:
        return len(self._snapshots)


# ---------------------------------------------------------------------------
# JsonFileStateStore
# ---------------------------------------------------------------------------

class JsonFileStateStore:
    """File-backed state store; one JSON file per instance.

    Files are stored as ``<directory>/<instance_id>.json``.  The directory
    is created automatically if it does not exist.

    Parameters
    ----------
    directory:
        Path to the storage directory (string or :class:`pathlib.Path`).
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, instance_id: str) -> Path:
        return self._dir / f"{instance_id}.json"

    def save_instance(self, instance: ExecutionInstance) -> None:
        """Write *instance* to disk (raises ``ValueError`` if file exists)."""
        path = self._path(instance.instance_id)
        if path.exists():
            raise ValueError(
                f"Instance {instance.instance_id!r} already exists at {path}. "
                "Use update_instance() to overwrite."
            )
        path.write_text(json.dumps(to_dict(instance), indent=2), encoding="utf-8")

    def load_instance(self, instance_id: str) -> ExecutionInstance:
        """Read and deserialise the instance file."""
        path = self._path(instance_id)
        if not path.exists():
            raise KeyError(f"Instance {instance_id!r} not found at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return from_dict(data)

    def update_instance(self, instance: ExecutionInstance) -> None:
        """Overwrite the stored JSON file (raises ``KeyError`` if not found)."""
        path = self._path(instance.instance_id)
        if not path.exists():
            raise KeyError(
                f"Instance {instance.instance_id!r} not found at {path}. "
                "Use save_instance() first."
            )
        path.write_text(json.dumps(to_dict(instance), indent=2), encoding="utf-8")
