"""`substance_painter.async_utils`: the stop source of asynchronous computations
(`python/FACADE.md` §9; phase1.21).

A `StopSource` is shared by an asynchronous operation and the script that started it: the script
asks for a stop, the operation checks it at its checkpoints. The bakes that return one
(`baking.bake_async`, `BakingProcessAboutToStart`) are phase3.5_embree-bakers; their events are
delivered on the dispatcher thread like every other (`event.py`).
"""

from __future__ import annotations

import threading
from typing import Any

MODULE = "substance_painter.async_utils"


class _Stop:
    """The shared state behind a StopSource: whether a stop was requested, and whether the
    operation can still be stopped."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requested = False
        self.stoppable = True


class StopSource:
    """An object that can be used to cancel an asynchronous computation."""

    __slots__ = ("_state",)

    def __init__(self, stop_source: Any = None) -> None:
        self._state = stop_source if isinstance(stop_source, _Stop) else _Stop()

    def request_stop(self) -> bool:
        """Makes a stop request; True if the stop request was possible."""
        with self._state.lock:
            if not self._state.stoppable:
                return False
            self._state.requested = True
            return True

    def stop_requested(self) -> bool:
        """Whether a stop request has been made."""
        with self._state.lock:
            return self._state.requested

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StopSource) and other._state is self._state

    def __hash__(self) -> int:
        return id(self._state)


StopSource.__module__ = MODULE
