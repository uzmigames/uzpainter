"""Recorder session: connect to Painter and record its software identity (task item 2.1).

Build guard (decision 037): the running build must be the build of the current envelope or of
the candidate envelope being recorded (`parity/envelopes/registry.json`,
`tools.parity.envelope.registry`). An unseen build raises `UnseenBuild`, which starts the
envelope refresh; there is no other way past the guard. A session can also verify, before
every call that is not a readiness poll, that it still talks to the same Painter process and
build (`verify_calls`), so that an update or restart in the middle of a run aborts it. The host
re-check re-reads a field that differs or cannot be read (`HOST_REREAD_DELAYS_S`): only a value
that consistently differs is a change, and a field that never reads back is unverifiable; both
abort, naming each field's expected and observed values. At session start a field reading
`unknown` is re-read the same way, and one that never reads back refuses the session.

Painter is started by the operator with `--enable-remote-scripting`. Its documented remote
control (Painter Python API guide *Remote control / headless*, approved source A-PYDOC) accepts
`POST /run.json` with `{"python": <base64 source>}` on `localhost:60041`; the reply is the
JSON-encoded value of an expression (`null` for statements) or `{"error": {"description": ...}}`.
Everything sent is UzmiGames code: `painter_side.py` is executed into a private namespace once,
then each operation is one `dispatch(...)` expression.
"""

from __future__ import annotations

import base64
import http.client
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from tools.parity.recorder.environment import (
    HOST_FIELDS,
    UNKNOWN,
    HostEnvironment,
    cached_host_environment,
    environment_record,
)

PAINTER_PRODUCT = "Adobe Substance 3D Painter"
REMOTE_HOST = "localhost"
REMOTE_PORT = 60041
REMOTE_ROUTE = "/run.json"
PAINTER_SIDE = Path(__file__).with_name("painter_side.py")


class RecorderError(Exception):
    """A recording is refused; nothing is written."""


class RemoteError(RecorderError):
    """The remote endpoint reported an error executing the sent code."""


class PainterCallError(RecorderError):
    """A painter-side operation raised; `kind` is the exception class name Painter reported."""

    def __init__(self, operation: str, kind: str, message: str) -> None:
        self.args = (f"{operation}: {kind}: {message}",)
        self.operation = operation
        self.kind = kind
        self.message = message


class UnseenBuild(RecorderError):
    """The running Painter build belongs to no current or candidate envelope (decision 037)."""

    def __init__(self, identity: PainterIdentity, allowed: frozenset[str]) -> None:
        names = ", ".join(sorted(allowed)) or "no envelope"
        self.args = (
            f"oracle must be {PAINTER_PRODUCT} {names} (current or candidate envelope), found "
            f"{identity.build_id}: an unseen build starts the envelope refresh "
            "(`python -m tools.parity.recorder refresh`)",
        )
        self.identity = identity
        self.allowed = allowed


class IdentityChanged(RecorderError):
    """The Painter process, build or host environment changed (or could not be verified)
    during a run; the run is aborted."""


class Transport(Protocol):
    """Executes Python source in Painter and returns the decoded JSON reply."""

    def run(self, code: str) -> Any: ...


class HttpTransport:
    """The documented remote control of Painter (`--enable-remote-scripting`)."""

    def __init__(
        self, host: str = REMOTE_HOST, port: int = REMOTE_PORT, timeout_s: float = 3600.0
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s

    def run(self, code: str) -> Any:
        body = json.dumps({"python": base64.b64encode(code.encode("utf-8")).decode("ascii")})
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_s)
        try:
            connection.request(
                "POST",
                REMOTE_ROUTE,
                body.encode("utf-8"),
                {"Content-type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            data = response.read()
        finally:
            connection.close()
        if response.status != 200:
            raise RemoteError(f"remote control answered HTTP {response.status}")
        return decode_reply(data)


def decode_reply(data: bytes) -> Any:
    reply = json.loads(data.decode("utf-8")) if data.strip() else None
    if isinstance(reply, dict) and set(reply) == {"error"}:
        error = reply["error"]
        description = error.get("description") if isinstance(error, dict) else error
        raise RemoteError(f"Painter could not execute the sent code: {description}")
    return reply


def bootstrap_code(painter_side_source: str) -> str:
    """Statements that load `painter_side.py` into `uzp_recorder` with a per-process session id.

    The session id survives re-bootstrapping in the same Painter process and changes after a
    restart, which is how the recorder tells sessions apart (Tier 3 `separate_session`).
    """
    encoded = base64.b64encode(painter_side_source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "import uuid\n"
        "try:\n"
        "    uzp_recorder_session_id\n"
        "except NameError:\n"
        "    uzp_recorder_session_id = uuid.uuid4().hex\n"
        "uzp_recorder = {}\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_recorder)\n"
        "uzp_recorder['session_id'] = uzp_recorder_session_id\n"
    )


def dispatch_code(operation: str, args: dict[str, Any]) -> str:
    payload = base64.b64encode(json.dumps(args).encode("utf-8")).decode("ascii")
    return f"uzp_recorder['dispatch']({operation!r}, {payload!r})"


@dataclass(frozen=True)
class PainterIdentity:
    """Software identity required by the schemas (`painter_build`, `software.painter`)."""

    version: str
    version_info: tuple[int, int, int]
    js_api_version: str
    session_id: str
    colour_management: dict[str, Any]
    environment: dict[str, Any] | None = None

    @property
    def build_id(self) -> str:
        """The most specific build identity the documented APIs expose.

        `application.version()` and `alg.version.painter` both return only "12.1.0"; the
        documented JavaScript API version (`alg.version.api`) distinguishes builds further.
        """
        return f"{self.version}+js-api.{self.js_api_version}"

    def painter_build(self) -> dict[str, str]:
        return {"product": PAINTER_PRODUCT, "version": self.version, "build_id": self.build_id}


@dataclass(frozen=True)
class ProjectState:
    is_open: bool
    in_edition: bool
    busy: bool
    file_path: str | None
    now: float

    @property
    def ready(self) -> bool:
        """Edition state entered and not busy: the project can be queried, exported and saved."""
        return self.is_open and self.in_edition and not self.busy


# Readiness polls: never preceded by an identity check (they run in tight loops).
UNVERIFIED_OPERATIONS = frozenset({"hello", "state", "baking_state", "catalog_ready"})

BuildPolicy = Callable[[], frozenset[str]]

# Waits before each host re-read when a field differs or reads `unknown` (decision 037): the
# operating-system queries behind the host fields can fail transiently while Painter loads the
# GPU, so a field is concluded only after three reads over 30 s.
HOST_REREAD_DELAYS_S = (10.0, 20.0)


def envelope_builds() -> frozenset[str]:
    """Builds a recording may run on: the current and the candidate envelope's."""
    from tools.parity.envelope.registry import recordable_builds

    return recordable_builds()


def observed(reads: list[str]) -> str:
    """The reads of one host field, for a refusal message."""
    if len(set(reads)) == 1:
        return f"{reads[0]!r} after {len(reads)} reads"
    return f"{', '.join(repr(v) for v in reads)} in {len(reads)} reads"


def default_host_environment() -> dict[str, str]:
    """The host fields of the environment record, read once per host process."""
    return cached_host_environment()


class PainterSession:
    """One connection to one running Painter process."""

    def __init__(
        self,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_s: float = 0.5,
        allowed_builds: BuildPolicy | None = None,
        host_environment: HostEnvironment | None = None,
        verify_calls: bool = False,
    ) -> None:
        self.transport = transport
        self.sleep = sleep
        self.monotonic = monotonic
        self.poll_interval_s = poll_interval_s
        self.allowed_builds = allowed_builds
        self.host_environment = host_environment
        self.verify_calls = verify_calls
        self.identity: PainterIdentity | None = None

    def read_identity(self) -> PainterIdentity:
        """Load the painter-side code and read the running build and environment, without the
        build guard (detection only: no recording runs on an identity read this way)."""
        self.identity = None
        self.transport.run(bootstrap_code(PAINTER_SIDE.read_text(encoding="utf-8")))
        hello = self.call("hello")
        info = [int(v) for v in hello["version_info"]]
        if len(info) != 3 or ".".join(str(v) for v in info) != hello["version"]:
            raise RecorderError(
                f"Painter reports version {hello['version']!r} and version_info {info}, which "
                "disagree: the build cannot be identified"
            )
        identity = PainterIdentity(
            version=str(hello["version"]),
            version_info=(info[0], info[1], info[2]),
            js_api_version=str(hello["js_api_version"]),
            session_id=str(hello["session_id"]),
            colour_management=dict(hello["colour_management"]),
        )
        environment = environment_record(
            painter_build=identity.build_id,
            colour_management=identity.colour_management,
            host=self.read_host_environment(),
        )
        return replace(identity, environment=environment)

    def read_host_environment(self) -> dict[str, str]:
        """The host fields at session start, a field reading `unknown` read again (see
        `HOST_REREAD_DELAYS_S`); refuse when one never reads back, since a run recorded under an
        unknown environment belongs to no envelope."""
        host = self.host_environment or default_host_environment
        reads = self.read_host(host, lambda field, value: value != UNKNOWN)
        unreadable = [
            f"{field}: expected a readable value, observed {observed(reads[field])}"
            for field in HOST_FIELDS
            if reads[field][-1] == UNKNOWN
        ]
        if unreadable:
            raise RecorderError(
                "the host environment cannot be read at session start: " + "; ".join(unreadable)
            )
        return {field: reads[field][-1] for field in HOST_FIELDS}

    def read_host(
        self, host: HostEnvironment, settled: Callable[[str, str], bool]
    ) -> dict[str, list[str]]:
        """Every read of each host field: a field not yet `settled` is read again after each
        delay of `HOST_REREAD_DELAYS_S`; its last read is the settled one, if any."""
        reads: dict[str, list[str]] = {field: [] for field in HOST_FIELDS}
        pending = list(HOST_FIELDS)
        for delay in (None, *HOST_REREAD_DELAYS_S):
            if delay is not None:
                self.sleep(delay)
            now = host()
            for field in pending:
                reads[field].append(str(now.get(field) or UNKNOWN))
            pending = [f for f in pending if not settled(f, reads[f][-1])]
            if not pending:
                break
        return reads

    def connect(self) -> PainterIdentity:
        """Load the painter-side code and check the build against the envelope registry."""
        identity = self.read_identity()
        allowed = (self.allowed_builds or envelope_builds)()
        if identity.build_id not in allowed:
            raise UnseenBuild(identity, allowed)
        if self.call("hello")["project_open"]:
            raise RecorderError(
                "a project is already open in Painter; the recorder works only on throwaway "
                "projects it creates itself"
            )
        self.identity = identity
        return identity

    def verify_identity(self, host: HostEnvironment | None = None) -> None:
        """Refuse when the Painter process or build changed or cannot be read; with `host`,
        also re-read the host fields of the environment and refuse when they changed."""
        expected = self.identity
        if expected is None:
            raise IdentityChanged("no identity to verify: the session is not connected")
        try:
            hello = self.call("hello")
            current = (
                str(hello["version"]),
                str(hello["js_api_version"]),
                str(hello["session_id"]),
            )
        except (RecorderError, OSError, KeyError, TypeError) as error:
            raise IdentityChanged(f"the Painter identity cannot be verified: {error}") from error
        wanted = (expected.version, expected.js_api_version, expected.session_id)
        if current != wanted:
            raise IdentityChanged(
                f"Painter changed during the run: expected build {expected.build_id} in session "
                f"{expected.session_id}, found {current[0]}+js-api.{current[1]} in session "
                f"{current[2]}"
            )
        if host is not None and expected.environment is not None:
            self.verify_host(host, expected.environment)

    def verify_host(self, host: HostEnvironment, expected: dict[str, Any]) -> None:
        """Refuse when a host field differs from `expected` on every read (see
        `HOST_REREAD_DELAYS_S`): changed when every read gives the same known value,
        unverifiable otherwise. A field that reads its expected value once is verified."""
        reads = self.read_host(host, lambda field, value: value == expected.get(field))
        pending = [f for f in HOST_FIELDS if reads[f][-1] != expected.get(f)]
        if not pending:
            return
        changed: list[str] = []
        unverifiable: list[str] = []
        for field in pending:
            seen = reads[field]
            text = f"{field}: expected {expected.get(field)!r}, observed {observed(seen)}"
            consistent = len(set(seen)) == 1 and seen[0] != UNKNOWN
            (changed if consistent else unverifiable).append(text)
        problems = []
        if changed:
            problems.append("changed during the run: " + "; ".join(changed))
        if unverifiable:
            problems.append(
                "cannot be verified (unreadable or inconsistent on every read): "
                + "; ".join(unverifiable)
            )
        raise IdentityChanged("the host environment " + "; and ".join(problems))

    def call(self, operation: str, **args: Any) -> Any:
        if (
            self.verify_calls
            and self.identity is not None
            and operation not in UNVERIFIED_OPERATIONS
        ):
            self.verify_identity()
        reply = self.transport.run(dispatch_code(operation, args))
        if not isinstance(reply, str):
            raise RemoteError(f"{operation}: unexpected reply {reply!r}")
        decoded = json.loads(reply)
        if not decoded["ok"]:
            error = decoded["error"]
            raise PainterCallError(operation, error["type"], error["message"])
        return decoded["value"]

    def state(self) -> ProjectState:
        value = self.call("state")
        return ProjectState(
            is_open=bool(value["is_open"]),
            in_edition=bool(value["in_edition"]),
            busy=bool(value["busy"]),
            file_path=value["file_path"],
            now=float(value["now"]),
        )

    def wait_for(
        self, condition: Callable[[ProjectState], bool], what: str, timeout_s: float = 600.0
    ) -> ProjectState:
        deadline = self.monotonic() + timeout_s
        while True:
            current = self.state()
            if condition(current):
                return current
            if self.monotonic() >= deadline:
                raise RecorderError(f"timed out after {timeout_s:.0f} s waiting for {what}")
            self.sleep(self.poll_interval_s)

    def wait_ready(self, timeout_s: float = 600.0) -> ProjectState:
        return self.wait_for(lambda s: s.ready, "the project to be ready", timeout_s)

    def wait_catalog_ready(self, timeout_s: float = 120.0) -> None:
        """Refresh once, then poll documented crawling state; never capture a partial catalog."""
        self.call("refresh_catalog")
        deadline = self.monotonic() + timeout_s
        while True:
            ready = self.call("catalog_ready")
            if not isinstance(ready, bool):
                raise RecorderError("shelf readiness did not return a boolean")
            if ready:
                return
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise RecorderError(
                    f"timed out after {timeout_s:.0f} s waiting for shelf discovery"
                )
            self.sleep(min(self.poll_interval_s, remaining))

    def wait_closed(self, timeout_s: float = 600.0) -> ProjectState:
        return self.wait_for(lambda s: not s.is_open, "the project to close", timeout_s)
