"""Painter's asynchronous host: busy state, edition state, `execute_when_not_busy` and the engine
computations (`python/FACADE.md` §9; 10 §4; task phase1.21_pyapi-dispatcher-lifecycle; decision
109).

A transition changes the state first, then delivers its event (`event.emit_sync`), so a handler
reads the state Painter's handlers read (Tier 0 `lifecycle-events`): `BusyStatusChanged(True)`
sees `is_busy()` true, `ProjectEditionEntered` sees `is_in_edition_state()` true.

- **Busy.** Nested busy sections (a create, open or close, a mesh reload, an export) count; the
  first entry delivers `BusyStatusChanged(True)` and the last exit `BusyStatusChanged(False)`,
  followed by the `execute_when_not_busy` callbacks queued meanwhile, in order, before anything
  else the operation delivers (Tier 0 `phase1-execute-when-not-busy`, second recording).
- **Edition.** True from `ProjectEditionEntered` to `ProjectEditionLeft`; false while no project is
  open (Painter returns False there rather than raising).
- **Engine computations.** The native state (`uzpainter.application`): while disabled, export jobs
  stay queued; a facade export waits for them, inside its busy section, so `is_busy()` reports the
  deferred backlog until it drains after re-enabling. Each change delivers
  `EngineComputationsStatusChanged`.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

import uzpainter

from uzpainter_facade import event


class Host:
    """The host state of this interpreter."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.busy = 0
        self.edition = False
        self.waiting: list[Callable[[], Any]] = []


HOST = Host()


def is_busy() -> bool:
    """Whether an operation that makes Painter busy is running."""
    return HOST.busy > 0


def is_in_edition_state() -> bool:
    """Whether the current project is ready to work with."""
    return HOST.edition and bool(uzpainter.project.is_open())


def enter_busy() -> None:
    with HOST.lock:
        HOST.busy += 1
        first = HOST.busy == 1
    if first:
        event.emit_sync(event.BusyStatusChanged(True))


def leave_busy() -> None:
    with HOST.lock:
        HOST.busy -= 1
        cleared = HOST.busy == 0
        waiting, HOST.waiting = (HOST.waiting, []) if cleared else ([], HOST.waiting)
    if cleared:
        event.emit_sync(event.BusyStatusChanged(False))
        for callback in waiting:
            event.call_sync(callback)


@contextlib.contextmanager
def busy_section() -> Iterator[None]:
    enter_busy()
    try:
        yield
    finally:
        leave_busy()


def set_edition(edition: bool) -> None:
    """Enters or leaves the edition state and delivers its event."""
    HOST.edition = edition
    event.emit_sync(event.ProjectEditionEntered() if edition else event.ProjectEditionLeft())


def execute_when_not_busy(callback: Callable[[], Any]) -> None:
    """Runs `callback` on the dispatcher thread: now when not busy (before returning), else once
    the busy state clears."""
    if not callable(callback):
        raise TypeError("the callback must be callable")
    with HOST.lock:
        if HOST.busy:
            HOST.waiting.append(callback)
            return
    event.call_sync(callback)


# ── Engine computations (`substance_painter.application`) ──────────────────────────────────────


def engine_computations_status() -> bool:
    """Whether engine computations are enabled."""
    return bool(uzpainter.application.engine_computations_status())


def enable_engine_computations(enable: bool) -> None:
    """Enables or disables engine computations."""
    enable = bool(enable)
    changed = engine_computations_status() != enable
    uzpainter.application.enable_engine_computations(enable)
    if changed:
        event.emit_sync(event.EngineComputationsStatusChanged(enable))


@contextlib.contextmanager
def disable_engine_computations() -> Iterator[None]:
    """Context manager to disable engine computations (re-enabled when the block ends)."""
    enable_engine_computations(False)
    try:
        yield
    finally:
        enable_engine_computations(True)
