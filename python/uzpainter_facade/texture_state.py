"""Document-texture notifications from committed native invalidations.

The native queue supplies immutable snapshots, including successful no-op source edits.
Delivery uses the Python dispatcher; one worker waits for invalidations or throttle deadlines.
"""

from __future__ import annotations

import atexit
import dataclasses
import functools
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

Address = tuple[int, int, int, int, Any]


def _require_complete(snapshot: Mapping[str, Any]) -> None:
    errors = snapshot.get("errors", ())
    if errors:
        raise RuntimeError("incomplete native texture snapshot: " + "; ".join(map(str, errors)))


@dataclasses.dataclass(frozen=True)
class Texture:
    address: Address
    digest: str
    cache_key: int

    @classmethod
    def read(cls, value: Mapping[str, Any]) -> Texture:
        u, v = value["tile_indices"]
        return cls(
            (value["set_id"], value["stack_id"], u, v, value["channel_type"]),
            value["digest"],
            value["cache_key"],
        )


class Notifications:
    """Clock-injected notification state; queued callbacks reject obsolete project generations."""

    def __init__(
        self,
        post: Callable[[Callable[[], None]], None],
        emit: Callable[[str, Texture], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._post, self._emit, self._clock = post, emit, clock
        self._lock = threading.RLock()
        self._generation: int | None = None
        self._revision = -1
        self._serial = 0
        self._textures: dict[Address, Texture] = {}
        self._pending: set[Address] = set()
        self._queued: dict[Address, int] = {}
        self._epochs: dict[Address, int] = {}
        self._last: dict[Address, float] = {}
        self._enabled = True
        self._period = 2.0

    def opened(self, snapshot: Mapping[str, Any]) -> None:
        """Run on dispatcher while the new project is open and still busy."""
        _require_complete(snapshot)
        with self._lock:
            self._serial += 1
            self._generation = snapshot["generation"]
            self._revision = snapshot["revision"]
            self._textures = {t.address: t for t in map(Texture.read, snapshot["textures"])}
            self._pending.clear()
            self._queued.clear()
            self._last.clear()
            self._epochs.clear()
            textures = list(self._textures.values())
        for texture in textures:
            self._emit("ADD", texture)

    def closed(self) -> None:
        """Run on dispatcher before native close/discard, while old texture keys still exist."""
        with self._lock:
            textures = list(self._textures.values())
            self._serial += 1
            self._generation = None
            self._textures.clear()
            self._pending.clear()
            self._queued.clear()
            self._last.clear()
            self._epochs.clear()
        for texture in textures:
            self._emit("REMOVE", texture)

    def accept(self, snapshot: Mapping[str, Any]) -> None:
        """Queue one committed native snapshot; reject older revisions and lifecycle generations."""
        with self._lock:
            if snapshot["generation"] != self._generation or snapshot["revision"] < self._revision:
                return
            _require_complete(snapshot)
            self._revision = snapshot["revision"]
            current = {t.address: t for t in map(Texture.read, snapshot["textures"])}
            removed = [t for a, t in self._textures.items() if a not in current]
            added = [t for a, t in current.items() if a not in self._textures]
            for texture in (*removed, *added):
                address = texture.address
                self._epochs[address] = self._epochs.get(address, 0) + 1
                self._queued.pop(address, None)
            forced = {tuple(a) for a in snapshot.get("invalidated", ())}
            for address, texture in current.items():
                previous = self._textures.get(address)
                if previous is not None and (
                    previous.digest != texture.digest or address in forced
                ):
                    self._pending.add(address)
            self._textures = current
            self._pending.intersection_update(current)
            for texture in removed:
                self._last.pop(texture.address, None)
            serial = self._serial
        for action, textures in (("REMOVE", removed), ("ADD", added)):
            for texture in textures:
                self._post(functools.partial(self._structural, serial, action, texture))
        self.pump()

    def _structural(self, serial: int, action: str, texture: Texture) -> None:
        with self._lock:
            if serial != self._serial:
                return
        self._emit(action, texture)

    def configure(self, *, enabled: bool | None = None, period: float | None = None) -> None:
        with self._lock:
            if enabled is not None:
                self._enabled = enabled
            if period is not None:
                if period < 0.5:
                    raise ValueError("the throttling period can't be lower than 500ms")
                self._period = period
        self.pump()

    def delay(self) -> float | None:
        """Seconds to the next deadline, or None when no timed work can progress."""
        with self._lock:
            waiting = self._pending - self._queued.keys()
            if not self._enabled or not waiting:
                return None
            now = self._clock()
            return max(
                0.0,
                min(self._last.get(a, now - self._period) + self._period for a in waiting) - now,
            )

    def pump(self) -> None:
        with self._lock:
            if not self._enabled:
                return
            now = self._clock()
            ready = [
                a
                for a in self._pending - self._queued.keys()
                if now >= self._last.get(a, now - self._period) + self._period
            ]
            epochs = {a: self._epochs.get(a, 0) for a in ready}
            self._queued.update(epochs)
            serial = self._serial
        for address in ready:
            self._post(functools.partial(self._update, serial, address, epochs[address]))

    def _update(self, serial: int, address: Address, epoch: int) -> None:
        with self._lock:
            if serial != self._serial or self._epochs.get(address, 0) != epoch:
                return
            self._queued.pop(address, None)
            if not self._enabled or address not in self._pending:
                return
            texture = self._textures.get(address)
            if texture is None:
                return
            self._pending.remove(address)
            self._last[address] = self._clock()
        self._emit("UPDATE", texture)


_notifications: Notifications | None = None
_token: int | None = None
_install_lock = threading.Lock()
_thread: threading.Thread | None = None


class Barrier:
    """A request made during a drain is acknowledged only after the following drain."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.requested = self.completed = 0
        self.stopped = False
        self.failure: BaseException | None = None

    def begin(self) -> tuple[int, bool]:
        with self.condition:
            return self.requested, self.requested > self.completed

    def complete(self, request: int) -> None:
        with self.condition:
            self.completed = max(self.completed, request)
            self.condition.notify_all()

    def stop(self, failure: BaseException | None = None) -> None:
        with self.condition:
            self.stopped = True
            if failure is not None:
                self.failure = failure
            self.condition.notify_all()

    def check(self) -> None:
        if self.failure is not None:
            raise RuntimeError("texture notification worker failed") from self.failure
        if self.stopped:
            raise RuntimeError("texture notification worker stopped")

    def synchronize(self, wake: Callable[[], None], timeout: float) -> None:
        with self.condition:
            self.check()
            self.requested += 1
            request = self.requested
        wake()
        with self.condition:
            finished = self.condition.wait_for(
                lambda: self.completed >= request or self.stopped, timeout
            )
            self.check()
            if not finished:
                raise TimeoutError("texture notification synchronization timed out")


_barrier = Barrier()


def _emit(action: str, texture: Texture) -> None:
    from uzpainter_facade import event, textureset

    _, stack, u, v, channel = texture.address
    event.DISPATCHER._deliver(
        event.TextureStateEvent(
            event.TextureStateEventAction[action],
            stack,
            (u, v),
            textureset.ChannelType(channel),
            texture.cache_key,
        )
    )


def _worker(notifications: Notifications, token: int) -> None:
    import uzpainter

    try:
        while not _barrier.stopped:
            request, urgent = _barrier.begin()
            delay = notifications.delay()
            snapshots: Iterable[Mapping[str, Any]] = uzpainter.event._texture_state_drain(
                token, 0.0 if urgent else 60.0 if delay is None else delay
            )
            if _barrier.stopped:
                return
            for snapshot in snapshots:
                notifications.accept(snapshot)
            notifications.pump()
            _barrier.complete(request)
    except BaseException as error:
        _barrier.stop(error)


def _install() -> Notifications:
    import uzpainter

    from uzpainter_facade import event

    global _notifications, _token, _thread
    with _install_lock:
        if _notifications is None:
            _token = uzpainter.event._texture_state_subscribe()
            _notifications = Notifications(uzpainter.event.post, _emit)
            _notifications.configure(
                enabled=bool(uzpainter.application.engine_computations_status()),
                period=event.TextureStateEvent.cache_key_invalidation_throttling_period().total_seconds(),
            )
            _thread = threading.Thread(
                target=_worker,
                args=(_notifications, _token),
                daemon=True,
                name="uzpainter-texture-state",
            )
            _thread.start()
            atexit.register(shutdown)
        return _notifications


def opened() -> None:
    """Hook after native create/open succeeds, inside facade busy_section."""
    import uzpainter

    from uzpainter_facade import event

    notifications = _install()
    snapshot = uzpainter.event._texture_state_snapshot()
    _require_complete(snapshot)
    event.call_sync(notifications.opened, snapshot)


def closing() -> None:
    """Hook before discard/native close, inside facade busy_section."""
    from uzpainter_facade import event

    if _notifications is not None:
        synchronize()
        event.call_sync(_notifications.closed)


def configure(*, enabled: bool | None = None, period: float | None = None) -> None:
    """Hooks for engine enable and throttling-period changes; never starts a project."""
    import uzpainter

    if _notifications is not None:
        _notifications.configure(enabled=enabled, period=period)
        uzpainter.event._texture_state_wake(_token)


def synchronize(timeout: float = 30.0) -> None:
    """Post native work through the current event-loop boundary, without waiting for throttles.

    Callers flush the dispatcher afterwards. Disabled-engine updates remain pending.
    """
    import uzpainter

    if _notifications is None:
        return
    if _thread is None or not _thread.is_alive():
        _barrier.check()
        raise RuntimeError("texture notification worker is not running")
    _barrier.synchronize(lambda: uzpainter.event._texture_state_wake(_token), timeout)


def shutdown() -> None:
    """Wake and stop the native subscription before interpreter teardown."""
    import uzpainter

    global _token
    if _token is None:
        return
    token, _token = _token, None
    _barrier.stop()
    uzpainter.event._texture_state_unsubscribe(token)
    if _thread is not None and _thread is not threading.current_thread():
        _thread.join(timeout=5.0)
