"""Recorder session: connect to Painter 12.1.0 and record its software identity (task item 2.1).

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PAINTER_PRODUCT = "Adobe Substance 3D Painter"
PAINTER_VERSION = "12.1.0"
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


class PainterSession:
    """One connection to one running Painter process."""

    def __init__(
        self,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_s: float = 0.5,
    ) -> None:
        self.transport = transport
        self.sleep = sleep
        self.monotonic = monotonic
        self.poll_interval_s = poll_interval_s
        self.identity: PainterIdentity | None = None

    def connect(self) -> PainterIdentity:
        """Load the painter-side code and check that this is Painter 12.1.0."""
        self.transport.run(bootstrap_code(PAINTER_SIDE.read_text(encoding="utf-8")))
        hello = self.call("hello")
        version_info = tuple(int(v) for v in hello["version_info"])
        if hello["version"] != PAINTER_VERSION or version_info != (12, 1, 0):
            raise RecorderError(
                f"oracle must be {PAINTER_PRODUCT} {PAINTER_VERSION}, found {hello['version']} "
                f"{list(version_info)}"
            )
        self.identity = PainterIdentity(
            version=hello["version"],
            version_info=(12, 1, 0),
            js_api_version=str(hello["js_api_version"]),
            session_id=str(hello["session_id"]),
            colour_management=dict(hello["colour_management"]),
        )
        if hello["project_open"]:
            raise RecorderError(
                "a project is already open in Painter; the recorder works only on throwaway "
                "projects it creates itself"
            )
        return self.identity

    def call(self, operation: str, **args: Any) -> Any:
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

    def wait_closed(self, timeout_s: float = 600.0) -> ProjectState:
        return self.wait_for(lambda s: not s.is_open, "the project to close", timeout_s)
