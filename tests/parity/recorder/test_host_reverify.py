"""Host reads of a recorder session (decision 037): a transient misread of a host field is
re-read before anything is concluded or recorded; a consistent other value is a change and a
value that never reads back is unverifiable, and both abort naming the expected and observed
values. At session start a field that never reads back refuses the session."""

from __future__ import annotations

import types
from collections.abc import Callable, Iterator

import pytest

from tools.parity.recorder import environment
from tools.parity.recorder.environment import UNKNOWN, cached_host_environment
from tools.parity.recorder.session import (
    HOST_REREAD_DELAYS_S,
    IdentityChanged,
    PainterSession,
    RecorderError,
)

HOST = {
    "gpu_model": "AMD Radeon(TM) Graphics | NVIDIA GeForce RTX 4090",
    "driver_version": "32.0.11024.2 | 32.0.16.1714",
    "os_build": "10.0.26200.1",
}
UNREADABLE = {**HOST, "gpu_model": UNKNOWN, "driver_version": UNKNOWN}


def connected(fake: types.ModuleType, sleeps: list[float]) -> PainterSession:
    session = PainterSession(
        fake.LocalTransport(fake.FakeWorld()),
        sleep=sleeps.append,
        host_environment=lambda: dict(HOST),
    )
    session.connect()
    return session


def reading(*answers: dict[str, str]) -> Callable[[], dict[str, str]]:
    replies: Iterator[dict[str, str]] = iter(answers)
    return lambda: dict(next(replies))


def test_a_transient_unknown_is_reread_and_does_not_abort(fake: types.ModuleType) -> None:
    sleeps: list[float] = []
    connected(fake, sleeps).verify_identity(reading(UNREADABLE, HOST))
    assert sleeps == [HOST_REREAD_DELAYS_S[0]]


def test_a_matching_read_needs_no_reread(fake: types.ModuleType) -> None:
    sleeps: list[float] = []
    connected(fake, sleeps).verify_identity(reading(HOST))
    assert sleeps == []


def test_a_consistent_other_value_is_a_change_naming_expected_and_observed(
    fake: types.ModuleType,
) -> None:
    sleeps: list[float] = []
    updated = {**HOST, "driver_version": "32.0.11024.2 | 32.0.16.9999"}
    reads = len(HOST_REREAD_DELAYS_S) + 1
    with pytest.raises(IdentityChanged) as raised:
        connected(fake, sleeps).verify_identity(reading(*[updated] * reads))
    assert str(raised.value) == (
        "the host environment changed during the run: driver_version: expected "
        "'32.0.11024.2 | 32.0.16.1714', observed '32.0.11024.2 | 32.0.16.9999' "
        f"after {reads} reads"
    )
    assert sleeps == list(HOST_REREAD_DELAYS_S)


def test_a_field_unreadable_after_every_read_is_unverifiable(fake: types.ModuleType) -> None:
    sleeps: list[float] = []
    reads = len(HOST_REREAD_DELAYS_S) + 1
    with pytest.raises(IdentityChanged) as raised:
        connected(fake, sleeps).verify_identity(reading(*[UNREADABLE] * reads))
    message = str(raised.value)
    assert message.startswith("the host environment cannot be verified")
    assert "changed" not in message
    assert (
        "gpu_model: expected 'AMD Radeon(TM) Graphics | NVIDIA GeForce RTX 4090', observed "
        f"'unknown' after {reads} reads" in message
    )
    assert (
        "driver_version: expected '32.0.11024.2 | 32.0.16.1714', observed 'unknown' after "
        f"{reads} reads" in message
    )


def test_inconsistent_reads_are_unverifiable_not_a_change(fake: types.ModuleType) -> None:
    other = {**HOST, "gpu_model": "Microsoft Basic Display Adapter"}
    with pytest.raises(IdentityChanged) as raised:
        connected(fake, []).verify_identity(reading(other, UNREADABLE, other))
    message = str(raised.value)
    assert message.startswith("the host environment cannot be verified")
    assert (
        "gpu_model: expected 'AMD Radeon(TM) Graphics | NVIDIA GeForce RTX 4090', observed "
        "'Microsoft Basic Display Adapter', 'unknown', 'Microsoft Basic Display Adapter' "
        "in 3 reads" in message
    )


def starting(
    fake: types.ModuleType, sleeps: list[float], host: Callable[[], dict[str, str]]
) -> PainterSession:
    return PainterSession(
        fake.LocalTransport(fake.FakeWorld()), sleep=sleeps.append, host_environment=host
    )


def test_a_transient_unknown_at_session_start_is_reread_and_never_recorded(
    fake: types.ModuleType,
) -> None:
    sleeps: list[float] = []
    identity = starting(fake, sleeps, reading(UNREADABLE, HOST)).connect()
    assert identity.environment is not None
    assert {f: identity.environment[f] for f in HOST} == HOST
    assert sleeps == [HOST_REREAD_DELAYS_S[0]]


def test_a_field_unreadable_at_session_start_refuses_the_session(fake: types.ModuleType) -> None:
    sleeps: list[float] = []
    reads = len(HOST_REREAD_DELAYS_S) + 1
    session = starting(fake, sleeps, reading(*[UNREADABLE] * reads))
    with pytest.raises(RecorderError) as raised:
        session.connect()
    assert str(raised.value) == (
        "the host environment cannot be read at session start: gpu_model: expected a readable "
        f"value, observed 'unknown' after {reads} reads; driver_version: expected a readable "
        f"value, observed 'unknown' after {reads} reads"
    )
    assert session.identity is None
    assert sleeps == list(HOST_REREAD_DELAYS_S)


def test_the_process_cache_never_keeps_an_unknown_read(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter([UNREADABLE, HOST, {**HOST, "os_build": "later"}])
    monkeypatch.setattr(environment, "capture_host_environment", lambda: dict(next(replies)))
    monkeypatch.setattr(environment, "HOST_CACHE", [])
    assert cached_host_environment() == UNREADABLE
    assert cached_host_environment() == HOST
    assert cached_host_environment() == HOST
