"""`substance_painter.baking`: the bake parameters over the native `uzpainter.baking`
(`python/FACADE.md` §2; phase3.1_baker-request-model, decision 323).

`BakingParameters` holds its native handle and resolves it again on every call. `common()` and
`baker(usage)` return the native `properties.Property` handles, so a `Property` is the same class
whichever package reached it. The link groups, the texture set's baking state setters and the
UV-tile members raise `NotYetSupported` naming phase3.5_embree-bakers.

`bake_async(texture_set)` and `bake_selected_textures_async()` (decision 355) start the native bake
job (`uzpainter.baking`) and return its `StopSource`. Every refusal raises before any event (an
enabled baker UzPainter cannot publish, such as the default configuration's Curvature, a parameter
without an established value). Then, during the call, `BakingProcessAboutToStart(stop_source)` is
delivered and the busy section entered (`BusyStatusChanged(True)`); a follower thread delivers
`BakingProcessProgress(progress)` at each change of the job's progress,
`BakingProcessEnded(status)` and the end of the busy section, all on the dispatcher thread.
`stop_source.request_stop()` cancels the job at once and returns False once it ended. A bake whose
usages are `pending-evidence` bakes and ends with `BakingStatus.Fail`, nothing bound (decision
001); the cause goes to the log. Painter documents the events, the payloads and that the
application is busy while baking; the order of the busy section around `BakingProcessAboutToStart`
follows the recorded export's and awaits the bake probe (decision 355).
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Any

import uzpainter

from uzpainter_facade import event, host
from uzpainter_facade import logging as sp_logging
from uzpainter_facade.async_utils import StopSource
from uzpainter_facade.state import edits
from uzpainter_facade.textureset import TextureSet, native_of

_baking = uzpainter.baking

CurvatureMethod = _baking.CurvatureMethod


class BakingParameters:
    """A texture set's bake parameters."""

    __slots__ = ("_native",)

    def __init__(self, material_id: Any) -> None:
        # Painter's constructor takes the texture set's uid; the facade also passes a native handle.
        native = material_id
        if not isinstance(native, _baking.BakingParameters):
            native = _baking.BakingParameters(material_id)
        self._native = native

    @staticmethod
    def from_texture_set(texture_set: Any) -> BakingParameters:
        return BakingParameters(_baking.BakingParameters.from_texture_set(native_of(texture_set)))

    @staticmethod
    def from_texture_set_name(texture_set_name: str) -> BakingParameters:
        return BakingParameters(_baking.BakingParameters.from_texture_set_name(texture_set_name))

    def texture_set(self) -> TextureSet:
        return TextureSet(self._native.texture_set())

    def common(self) -> dict[str, Any]:
        return dict(self._native.common())

    def baker(self, baked_map: Any) -> dict[str, Any]:
        return dict(self._native.baker(baked_map))

    @staticmethod
    @edits
    def set(property_values: dict[Any, Any]) -> None:
        _baking.BakingParameters.set(property_values)

    def get_curvature_method(self) -> Any:
        return self._native.get_curvature_method()

    def get_enabled_bakers(self) -> list[Any]:
        return list(self._native.get_enabled_bakers())

    def is_textureset_enabled(self) -> bool:
        return bool(self._native.is_textureset_enabled())

    # Release gaps (phase3.5_embree-bakers; decision 323): the native call raises before any change.
    def set_textureset_enabled(self, enable: bool) -> None:
        self._native.set_textureset_enabled(enable)

    def set_enabled_bakers(self, enabled_usages: list[Any]) -> None:
        self._native.set_enabled_bakers(enabled_usages)

    def is_baker_enabled(self, usage: Any) -> bool:
        return bool(self._native.is_baker_enabled(usage))

    def set_baker_enabled(self, usage: Any, enable: bool) -> None:
        self._native.set_baker_enabled(usage, enable)

    def set_curvature_method(self, method: Any) -> None:
        self._native.set_curvature_method(method)

    def get_enabled_uv_tiles(self) -> list[Any]:
        return list(self._native.get_enabled_uv_tiles())

    def set_enabled_uv_tiles(self, uv_tiles: list[Any]) -> None:
        self._native.set_enabled_uv_tiles(uv_tiles)

    def is_uv_tile_enabled(self, uv_tile: Any) -> bool:
        return bool(self._native.is_uv_tile_enabled(uv_tile))

    def set_uv_tile_enabled(self, uv_tile: Any, enable: bool) -> None:
        self._native.set_uv_tile_enabled(uv_tile, enable)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BakingParameters) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native)

    def __repr__(self) -> str:
        return f"BakingParameters({self._native.texture_set().name()!r})"


class BakingStatus(enum.Enum):
    """Status code of the baking process."""

    Success = 0
    Cancel = 1
    Fail = 2


_STATUS = {
    "succeeded": BakingStatus.Success,
    "cancelled": BakingStatus.Cancel,
    "failed": BakingStatus.Fail,
}


def bake_async(texture_set: TextureSet) -> StopSource:
    """Launch the baking process for a Texture Set, using the current baking configuration."""
    if not isinstance(texture_set, TextureSet):
        raise TypeError("bake_async takes a TextureSet")
    return start(texture_set)


def bake_selected_textures_async() -> StopSource:
    """Launch the baking process, using the current baking configuration."""
    return start()


def start(texture_set: TextureSet | None = None, usages: list[Any] | None = None) -> StopSource:
    """UzPainter's bake launch behind `bake_async` (`texture_set`) and
    `bake_selected_textures_async` (None: every texture set), with `usages` (`MeshMapUsage`
    members) or, when None, each set's enabled bakers. The native call raises every refusal before
    any event; then `BakingProcessAboutToStart(stop_source)` is delivered and the busy section
    entered before this returns, and a follower thread delivers the progress events,
    `BakingProcessEnded(status)` and the end of the busy section (decision 355)."""
    native_usages = None if usages is None else list(usages)
    if texture_set is None:
        job = _baking.bake_selected_textures_async(native_usages)
    else:
        job = _baking.bake_async(texture_set.name(), native_usages)
    stop = StopSource()
    uzpainter.event.hold()
    try:
        event.emit_sync(event.BakingProcessAboutToStart(stop))
        host.enter_busy()
    except BaseException:
        job.cancel()
        uzpainter.event.release()
        raise
    threading.Thread(target=_follow, args=(job, stop), name="uzpainter-bake", daemon=True).start()
    return stop


def _follow(job: Any, stop: StopSource) -> None:
    """Follows the native bake job: a stop request cancels it (acknowledged at once), each change
    of its progress is a `BakingProcessProgress`, its end a `BakingProcessEnded`. Each event is
    delivered before the follower goes on, so its handlers read the busy state it was sent in."""
    try:
        last = None
        while job.status not in _STATUS:
            if stop.stop_requested():
                job.cancel()
            progress = float(job.progress)
            if progress != last:
                event.emit_sync(event.BakingProcessProgress(progress))
                last = progress
            time.sleep(0.02)
        progress = float(job.progress)
        if progress != last:
            event.emit_sync(event.BakingProcessProgress(progress))
        with stop._state.lock:
            stop._state.stoppable = False
        status = _STATUS[job.status]
        if status is BakingStatus.Fail:
            try:
                job.wait()
            except Exception as error:  # Painter details a failure's cause in the log
                sp_logging.error(f"the bake failed: {error}")
        event.emit_sync(event.BakingProcessEnded(status))
        host.leave_busy()
    finally:
        uzpainter.event.release()
