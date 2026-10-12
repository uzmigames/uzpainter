"""`substance_painter.event`: the 27 documented event classes and the dispatcher
(`python/FACADE.md` §9; 10 §4; task phase1.21_pyapi-dispatcher-lifecycle).

Handlers run on the Python dispatcher thread of the native module (`uzpainter.event`,
`src/python/dispatcher.h`), after the transition they report is committed, and never while the
document lock is held. `emit_sync` is how a synchronous operation reports a transition: it queues
the delivery and waits for it, so the handlers run before the operation returns, as Painter calls
them (the Tier 0 `during_step` of the save and lifecycle events); on the dispatcher thread itself
the delivery runs inline. `emit` queues without waiting (an asynchronous operation's worker).

`Dispatcher.connect` holds the callback weakly (it is dropped once the callback is collected) and
`connect_strong` strongly, as Painter documents. A handler's exception is printed on the standard
error and the other handlers still run.

Events whose operations arrive in later phases are connectable and emitted by their owners:
`BakingProcessAboutToStart/Progress/Ended` (phase3.5_embree-bakers), `CameraPropertiesChanged`
and `TextureStateEvent` (phase2.3_realtime-preview). `GraphicalUserInterfaceStarted` is
desktop-only: connectable, never emitted, and creating it raises.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import functools
import sys
import threading
import traceback
import weakref
from collections.abc import Callable
from typing import Any

import uzpainter

MODULE = "substance_painter.event"


class Event:
    """Base event class."""


class GraphicalUserInterfaceStarted(Event):
    """Event sent once Painter's desktop UI has started: UzPainter has none, so the event never
    happens and creating it raises UnsupportedInUzPainter."""

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise uzpainter.UnsupportedInUzPainter(
            "substance_painter.event.GraphicalUserInterfaceStarted",
            "it marks the start of Painter's desktop user interface, which changes no texture, "
            "render or script-visible state, and UzPainter has no desktop UI",
            "start the script's work directly, or connect to ProjectEditionEntered",
        )


# ── Export events ───────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class ExportTexturesAboutToStart(Event):
    """Event triggered just before a textures export."""

    textures: dict[tuple[str, str], list[str]]


@dataclasses.dataclass
class ExportTexturesEnded(Event):
    """Event triggered after textures export is finished."""

    status: Any
    message: str
    textures: dict[tuple[str, str], list[str]]


# ── Project events ──────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class ProjectOpened(Event):
    """Event triggered when an existing project has been opened."""


@dataclasses.dataclass
class ProjectCreated(Event):
    """Event triggered when a new project has been created."""


@dataclasses.dataclass
class ProjectAboutToClose(Event):
    """Event triggered just before closing the current project."""


@dataclasses.dataclass
class ProjectClosed(Event):
    """Event triggered once the current project is closed."""


@dataclasses.dataclass
class ProjectAboutToSave(Event):
    """Event triggered just before saving the current project."""

    file_path: str


@dataclasses.dataclass
class ProjectSaved(Event):
    """Event triggered once the current project is saved."""


@dataclasses.dataclass
class ProjectEditionEntered(Event):
    """Event triggered when the project is fully loaded and ready to work with."""


@dataclasses.dataclass
class ProjectEditionLeft(Event):
    """Event triggered when the current project can no longer be edited."""


@dataclasses.dataclass
class BusyStatusChanged(Event):
    """Event triggered when the busy state changed."""

    busy: bool


class TextureStateEventAction(enum.Enum):
    """The TextureStateEvent possible actions."""

    ADD = 0
    UPDATE = 1
    REMOVE = 2


# The minimum period between two texture update events, once a script set it. Painter's default
# is unrecorded (recording P21-C).
_THROTTLING: dict[str, datetime.timedelta] = {}


@dataclasses.dataclass
class TextureStateEvent(Event):
    """Event triggered when a document texture is added, removed or updated."""

    action: TextureStateEventAction
    stack_id: int
    tile_indices: tuple[int, int]
    channel_type: Any
    cache_key: int

    @staticmethod
    def cache_key_invalidation_throttling_period() -> datetime.timedelta:
        """The minimum duration between two texture update events (for a given texture)."""
        if "period" not in _THROTTLING:
            raise uzpainter.NotYetSupported(
                "TextureStateEvent.cache_key_invalidation_throttling_period: Painter's default "
                "period is unrecorded (recording P21-C, decision 110)"
            )
        return _THROTTLING["period"]

    @staticmethod
    def set_cache_key_invalidation_throttling_period(period: datetime.timedelta) -> None:
        """Set the minimum duration between two texture update events (at least 500 ms)."""
        if period < datetime.timedelta(milliseconds=500):
            raise ValueError("the throttling period can't be lower than 500ms")
        _THROTTLING["period"] = period


# ── Shelf, baking, layer stack, application, display and resource events ────────────────────────


@dataclasses.dataclass
class ShelfCrawlingStarted(Event):
    """Event triggered when a shelf starts reading the file system to discover new resources."""

    shelf_name: str


@dataclasses.dataclass
class ShelfCrawlingEnded(Event):
    """Event triggered when a shelf has finished discovering new resources."""

    shelf_name: str


@dataclasses.dataclass
class BakingProcessAboutToStart(Event):
    """Event triggered when a baking is about to start."""

    stop_source: Any


@dataclasses.dataclass
class BakingProcessProgress(Event):
    """Event triggered when baking process progress changes."""

    progress: float


@dataclasses.dataclass
class BakingProcessEnded(Event):
    """Event triggered after baking is finished."""

    status: Any


@dataclasses.dataclass
class LayerStacksModelDataChanged(Event):
    """Event triggered whenever the status of the Layer Stacks changes."""


@dataclasses.dataclass
class EngineComputationsStatusChanged(Event):
    """Event triggered whenever the status of the engine computations changes."""

    engine_computations_enabled: bool


@dataclasses.dataclass
class CameraPropertiesChanged(Event):
    """Event triggered when the camera properties change."""

    camera_id: int


@dataclasses.dataclass
class ReloadResourcesStarted(Event):
    """Event triggered when a resource reload operation has started."""

    filter: Any


@dataclasses.dataclass
class ReloadedResourceResult:
    """Per resource result of a successful resource reload operation."""

    old_resource_id: Any
    new_resource_id: Any


@dataclasses.dataclass
class ReloadedResourceError:
    """Per resource result of an unsuccessful resource reload operation."""

    resource_id: Any
    error_msg: str


@dataclasses.dataclass
class ReloadResourcesEnded(Event):
    """Event triggered when a resource reload operation has completed."""

    filter: Any
    reloaded_resources: list[ReloadedResourceResult]
    resource_errors: list[ReloadedResourceError]


EVENT_CLASSES: tuple[type, ...] = (
    Event,
    GraphicalUserInterfaceStarted,
    ExportTexturesAboutToStart,
    ExportTexturesEnded,
    ProjectOpened,
    ProjectCreated,
    ProjectAboutToClose,
    ProjectClosed,
    ProjectAboutToSave,
    ProjectSaved,
    ProjectEditionEntered,
    ProjectEditionLeft,
    BusyStatusChanged,
    TextureStateEvent,
    TextureStateEventAction,
    ShelfCrawlingStarted,
    ShelfCrawlingEnded,
    BakingProcessAboutToStart,
    BakingProcessProgress,
    BakingProcessEnded,
    LayerStacksModelDataChanged,
    EngineComputationsStatusChanged,
    CameraPropertiesChanged,
    ReloadResourcesStarted,
    ReloadResourcesEnded,
    ReloadedResourceResult,
    ReloadedResourceError,
)


# ── The dispatcher ──────────────────────────────────────────────────────────────────────────────


class Dispatcher:
    """The Event Dispatcher."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # event class -> [(callback or weak reference, strong)], in connection order
        self._handlers: dict[Any, list[tuple[Any, bool]]] = {}

    def connect(self, event_cls: Any, callback: Callable[[Any], Any]) -> None:
        """Connect a callback to handle the given event type (held by a weak reference)."""
        self._add(event_cls, callback, strong=False)

    def connect_strong(self, event_cls: Any, callback: Callable[[Any], Any]) -> None:
        """Connect a callback to handle the given event type (held by a strong reference)."""
        self._add(event_cls, callback, strong=True)

    def disconnect(self, event_cls: Any, callback: Callable[[Any], Any]) -> None:
        """Disconnect a previously connected callback."""
        with self._lock:
            entries = self._handlers.get(event_cls, [])
            self._handlers[event_cls] = [e for e in entries if _resolve(e) not in (None, callback)]

    def _add(self, event_cls: Any, callback: Callable[[Any], Any], strong: bool) -> None:
        if not callable(callback):
            raise TypeError("the callback must be callable")
        held: Any = callback
        if not strong:
            try:
                held = (
                    weakref.WeakMethod(callback)
                    if hasattr(callback, "__self__") and hasattr(callback, "__func__")
                    else weakref.ref(callback)
                )
            except TypeError:
                strong = True  # a builtin cannot be held weakly: it is never collected anyway
        with self._lock:
            entries = [e for e in self._handlers.get(event_cls, []) if _resolve(e) is not None]
            if any(_resolve(e) == callback for e in entries):
                self._handlers[event_cls] = entries
                return
            entries.append((held, strong))
            self._handlers[event_cls] = entries

    def _callbacks(self, event_cls: Any) -> list[Callable[[Any], Any]]:
        with self._lock:
            live = [e for e in self._handlers.get(event_cls, []) if _resolve(e) is not None]
            self._handlers[event_cls] = live
            return [callback for callback in map(_resolve, live) if callback is not None]

    def _deliver(self, event: Any) -> None:
        for callback in self._callbacks(type(event)):
            _guarded(callback, event)


def _resolve(entry: tuple[Any, bool]) -> Any:
    held, strong = entry
    return held if strong else held()


def _guarded(callback: Callable[..., Any], *args: Any) -> None:
    try:
        callback(*args)
    except Exception:  # a handler's error is reported, never propagated
        traceback.print_exc(file=sys.stderr)


DISPATCHER = Dispatcher()

for _cls in (*EVENT_CLASSES, Dispatcher):
    _cls.__module__ = MODULE


# ── Delivery helpers of the facade's operations ─────────────────────────────────────────────────


def emit(event: Any) -> None:
    """Queues the delivery of `event` on the dispatcher thread."""
    uzpainter.event.post(functools.partial(DISPATCHER._deliver, event))


def emit_sync(event: Any) -> None:
    """Delivers `event` on the dispatcher thread before returning."""
    emit(event)
    uzpainter.event.flush()


def call_sync(callback: Callable[..., Any], *args: Any) -> None:
    """Calls a facade callback on the dispatcher thread before returning."""
    uzpainter.event.post(functools.partial(_guarded, callback, *args))
    uzpainter.event.flush()
