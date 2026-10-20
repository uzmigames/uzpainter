"""Deterministic scheduler checks; native snapshot/transaction tests cover the producer."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from uzpainter_facade.texture_state import Barrier, Notifications, Texture
else:
    from importlib import import_module

    _module = import_module("python.uzpainter_facade.texture_state")
    Notifications, Texture = _module.Notifications, _module.Texture
    Barrier = _module.Barrier


def snapshot(
    revision: int, key: int = 1, *, generation: int = 1, forced: bool = False
) -> dict[str, Any]:
    return {
        "generation": generation,
        "revision": revision,
        "textures": [
            {
                "set_id": 1,
                "stack_id": 2,
                "tile_indices": (0, 0),
                "channel_type": "BaseColor",
                "digest": str(key),
                "cache_key": key,
            }
        ],
        "invalidated": [(1, 2, 0, 0, "BaseColor")] if forced else [],
    }


class Harness:
    def __init__(self) -> None:
        self.now = 100.0
        self.queue: list[Callable[[], None]] = []
        self.events: list[tuple[str, int]] = []
        self.state = Notifications(self.queue.append, self.emit, lambda: self.now)
        self.state.opened(snapshot(1))
        self.events.clear()

    def emit(self, action: str, texture: Texture) -> None:
        self.events.append((action, texture.cache_key))

    def deliver(self) -> None:
        while self.queue:
            self.queue.pop(0)()


def test_updates_coalesce_to_latest_key_and_use_delivery_deadline() -> None:
    h = Harness()
    h.state.accept(snapshot(2, 2))
    h.state.accept(snapshot(3, 3))
    h.deliver()
    assert h.events == [("UPDATE", 3)]
    h.state.accept(snapshot(4, 4))
    assert h.state.delay() == 2.0
    h.now += 1.999
    h.state.pump()
    h.deliver()
    assert h.events == [("UPDATE", 3)]
    h.now = 102.0
    h.state.pump()
    h.deliver()
    assert h.events == [("UPDATE", 3), ("UPDATE", 4)]


def test_equal_source_invalidation_updates_but_metadata_snapshot_does_not() -> None:
    h = Harness()
    h.state.accept(snapshot(2))
    h.deliver()
    assert h.events == []
    h.state.accept(snapshot(2, forced=True))
    h.deliver()
    assert h.events == [("UPDATE", 1)]


def test_disabled_engine_keeps_latest_pending_state() -> None:
    h = Harness()
    h.state.accept(snapshot(2, 2))
    h.state.configure(enabled=False)
    h.deliver()
    h.state.accept(snapshot(3, 3))
    assert h.state.delay() is None
    assert h.events == []
    h.state.configure(enabled=True)
    h.deliver()
    assert h.events == [("UPDATE", 3)]


def test_close_reopen_cancels_queued_update_and_rejects_old_generation() -> None:
    h = Harness()
    h.state.accept(snapshot(2, 2))
    h.state.closed()
    h.state.opened(snapshot(2, 2, generation=3))
    h.state.accept(snapshot(999, 9, generation=1))
    h.deliver()
    assert h.events == [("REMOVE", 2), ("ADD", 2)]


def test_old_revision_cannot_roll_texture_state_back() -> None:
    h = Harness()
    h.state.accept(snapshot(4, 4))
    h.state.accept(snapshot(3, 3))
    h.deliver()
    assert h.events == [("UPDATE", 4)]


def test_removing_then_readding_address_cancels_old_update() -> None:
    h = Harness()
    h.state.accept(snapshot(2, 2))
    h.state.accept({"generation": 1, "revision": 3, "textures": []})
    h.state.accept(snapshot(4, 4))
    h.deliver()
    assert h.events == [("REMOVE", 2), ("ADD", 4)]
    h.state.accept(snapshot(5, 5))
    h.deliver()
    assert h.events[-1] == ("UPDATE", 5)


def test_throttle_change_recomputes_existing_deadline() -> None:
    h = Harness()
    h.state.accept(snapshot(2, 2))
    h.deliver()
    h.state.accept(snapshot(3, 3))
    h.now += 0.75
    h.state.configure(period=0.75)
    h.deliver()
    assert h.events == [("UPDATE", 2), ("UPDATE", 3)]
    with pytest.raises(ValueError, match="500ms"):
        h.state.configure(period=0.499)


def test_channels_have_independent_deadlines() -> None:
    h = Harness()
    both = snapshot(1)
    both["textures"].append({**both["textures"][0], "channel_type": "Height"})
    h.state.opened(both)
    h.events.clear()
    both["invalidated"] = [(1, 2, 0, 0, "BaseColor")]
    h.state.accept(both)
    h.deliver()
    h.now += 0.1
    both["invalidated"] = [(1, 2, 0, 0, "Height")]
    h.state.accept(both)
    h.deliver()
    assert h.events == [("UPDATE", 1), ("UPDATE", 1)]


def test_barrier_request_during_drain_waits_for_next_drain() -> None:
    barrier = Barrier()
    old_request, urgent = barrier.begin()
    assert (old_request, urgent) == (0, False)
    woke = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []

    def synchronize() -> None:
        try:
            barrier.synchronize(woke.set, 2.0)
            finished.set()
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=synchronize)
    worker.start()
    assert woke.wait(1.0)
    barrier.complete(old_request)
    assert not finished.is_set()
    request, urgent = barrier.begin()
    assert (request, urgent) == (1, True)
    barrier.complete(request)
    worker.join(1.0)
    assert not worker.is_alive() and not failures and finished.is_set()


def test_barrier_timeout_shutdown_and_worker_failure_are_visible() -> None:
    barrier = Barrier()
    with pytest.raises(TimeoutError, match="timed out"):
        barrier.synchronize(lambda: None, 0.0)
    barrier.stop()
    with pytest.raises(RuntimeError, match="stopped"):
        barrier.synchronize(lambda: None, 0.0)
    failed = Barrier()
    cause = ValueError("native drain failed")
    with pytest.raises(RuntimeError, match="worker failed") as raised:
        failed.synchronize(lambda: failed.stop(cause), 0.0)
    assert raised.value.__cause__ is cause


def test_barrier_acknowledges_disabled_engine_without_waiting_for_updates() -> None:
    h = Harness()
    h.state.configure(enabled=False)
    barrier = Barrier()

    def consume() -> None:
        request, urgent = barrier.begin()
        assert urgent
        h.state.accept(snapshot(2, 2))
        h.state.pump()
        barrier.complete(request)

    barrier.synchronize(consume, 0.0)
    h.deliver()
    assert h.events == [] and h.state.delay() is None
    h.state.configure(enabled=True)
    h.deliver()
    assert h.events == [("UPDATE", 2)]


def test_incomplete_snapshot_reports_failure_without_removing_live_textures() -> None:
    h = Harness()
    incomplete = {"generation": 1, "revision": 4, "textures": [], "errors": ["DAG failed"]}
    with pytest.raises(RuntimeError, match="DAG failed"):
        h.state.accept(incomplete)
    h.deliver()
    assert h.events == []
    h.state.closed()
    assert h.events == [("REMOVE", 1)]
