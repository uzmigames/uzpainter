"""Painter's asynchronous host: busy state, edition state, `execute_when_not_busy` and the engine
computations (`python/FACADE.md` §9; 10 §4; task phase1.21_pyapi-dispatcher-lifecycle; decision
109).

A transition changes the state first, then delivers its event, so a handler reads the state
Painter's handlers read (Tier 0 `lifecycle-events`): `BusyStatusChanged(True)` sees `is_busy()`
true, `ProjectEditionEntered` sees `is_in_edition_state()` true. Busy events are delivered during
the call (`event.emit_sync`). `ProjectEditionEntered` after a create or open is queued and
delivered once the call returns, and any queued entry is flushed before the edition state changes
again (P21-F, P21-G; decision 319).

- **Busy.** Nested busy sections (a create, open or close, a mesh reload, an export) count; the
  first entry delivers `BusyStatusChanged(True)` and the last exit `BusyStatusChanged(False)`,
  followed by the `execute_when_not_busy` callbacks queued meanwhile, in order, before anything
  else the operation delivers (Tier 0 `phase1-execute-when-not-busy`, second recording).
- **Edition.** True from `ProjectEditionEntered` to `ProjectEditionLeft`; false while no project is
  open (Painter returns False there rather than raising).
- **Engine computations.** The native state (`uzpainter.application`): while disabled, background
  jobs stay queued. Explicit synchronous exports finish without enabling computations (observed
  R10), and their busy section covers only that export. Each state change delivers
  `EngineComputationsStatusChanged`. `engine_computations_status()` also reads False while the UI
  mode is Baking or Visualisation, and the script's state again in Edition
  (`p22b-host-application` s27-s32, both recordings; decision 297).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

import uzpainter

from uzpainter_facade import event
from uzpainter_facade.state import SESSION


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
    # A queued entry must observe its state before close or reload changes that state.
    uzpainter.event.flush()
    HOST.edition = edition
    event.emit_sync(event.ProjectEditionEntered() if edition else event.ProjectEditionLeft())


def enter_edition() -> None:
    """Enters the edition state at the end of `project.create` or `open` and queues
    `ProjectEditionEntered`, delivered after the call returns: Painter's recordings deliver it
    without the call's step marker (P21-F, P21-G; decision 319)."""
    HOST.edition = True
    event.emit(event.ProjectEditionEntered())


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
    """Whether engine computations are enabled: the script's state, in the Edition UI mode."""
    in_edition_mode = SESSION.ui_mode is None or SESSION.ui_mode.name == "Edition"
    return in_edition_mode and bool(uzpainter.application.engine_computations_status())


def enable_engine_computations(enable: bool) -> None:
    """Enables or disables engine computations."""
    enable = bool(enable)
    changed = bool(uzpainter.application.engine_computations_status()) != enable
    uzpainter.application.enable_engine_computations(enable)
    if changed:
        event.emit_sync(event.EngineComputationsStatusChanged(enable))
    from uzpainter_facade import texture_state

    texture_state.configure(enabled=enable)


@contextlib.contextmanager
def disable_engine_computations() -> Iterator[None]:
    """Context manager to disable engine computations (re-enabled when the block ends)."""
    enable_engine_computations(False)
    try:
        yield
    finally:
        enable_engine_computations(True)
