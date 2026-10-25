"""The adapter's client: a drop-in for `Pipeline/mcp/painter_mcp_client.py execute_python ARGS.json`
that runs the code through `UzPainter.exe run` instead of the community MCP bridge (`MIGRATIONS.md`
M1). Standard library only: `painter_layer_stack.py`'s own `execute()` spawns this file with the
running interpreter (`python client.py execute_python args.json`).

    python adapters/assets3d/client.py execute_python ARGS.json      # ARGS.json = {"code": "..."}

It prints one JSON reply, a superset of the bridge's `{"success", "data"}` envelope:

    {"success", "data", "stdout", "stderr", "error": {type, message, traceback} | null,
     "code_sha256", "last_committed_revision", "session", "exports", "redirects"[, "diagnostic"]}

and exits 0 on success, 1 on a structured failure (as the MCP client on an error result), 2 on a
usage error and 3 when UzPainter could not run the code (`host_error`). The reply is also written
to `painter-last-response.json` in `SP_MCP_CLIENT_OUTPUT_DIR` when that is set, as the MCP client
writes its response there.

Environment:
- `UZP_ASSETS3D_PRODUCTION_REQUEST`: pinned request, exclusive with diagnostic import;
- `UZP_ASSETS3D_DIAGNOSTIC_IMPORT`: exactly `1` explicitly selects generic diagnostic execution;
- `UZP_ASSETS3D_SCRATCH`: existing transport directory (default: checkout `tmp/scratch`);
- `UZPAINTER_EXE`: `UzPainter.exe` (default: the one on PATH);
- `UZP_ASSETS3D_SESSION`: the session file carrying the open project between calls (default:
  `%LOCALAPPDATA%/UzPainter/assets3d-adapter/session.json`);
- `UZP_ASSETS3D_ROOT`: the Assets3D root the receipts' manifest files are rebased under (set by
  the layer-stack entry from the script's own root);
- `UZP_ASSETS3D_OPEN_REDIRECTS`: fixture only, read by the runner (`runner.py`);
- `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT`: diagnostic fixture only (the Tier 1 runner's
  measure mode, decision 286): exactly `1` passes `--diagnostic-measure-export` to
  `UzPainter.exe run`, whose exports are then NOT conformant (their receipts say
  `non_conformant`, the reply `diagnostic`). Any other value is a host error; never set it in a
  production pipeline.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.assets3d import gate_contract

RUNNER = Path(__file__).resolve().with_name("runner.py")
JSON_PREFIX = "UZP_JSON:"
PAINTER_ENV = "UZPAINTER_EXE"
SESSION_ENV = "UZP_ASSETS3D_SESSION"
DIAGNOSTIC_ENV = "UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT"
DIAGNOSTIC_FLAG = "--diagnostic-measure-export"
PRODUCTION_ENV = "UZP_ASSETS3D_PRODUCTION_REQUEST"
IMPORT_DIAGNOSTIC_ENV = "UZP_ASSETS3D_DIAGNOSTIC_IMPORT"
SCRATCH_ENV = "UZP_ASSETS3D_SCRATCH"
PRODUCTION_FLAG = "--assets3d-production-required"
OK, FAILED, USAGE, HOST_ERROR = 0, 1, 2, 3
TOOL = "execute_python"
# SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
NO_ERROR_DIALOGS = 0x8003


class HostError(RuntimeError):
    """UzPainter could not run the code (exit status 3)."""


class ProductionContextRequired(HostError):
    """Execution needs one explicit production or diagnostic context."""


def execution_policy() -> dict[str, Any] | None:
    request = os.environ.get(PRODUCTION_ENV, "")
    diagnostic = os.environ.get(IMPORT_DIAGNOSTIC_ENV, "")
    if diagnostic not in ("", "1") or bool(request) == bool(diagnostic):
        raise ProductionContextRequired(
            "select exactly one --production-round REQUEST or --diagnostic-import"
        )
    if not request:
        return None
    if diagnostic_flags():
        raise HostError("production cannot use diagnostic measure exports")
    try:
        return gate_contract.production_policy(Path(request))
    except (OSError, ValueError) as error:
        raise HostError(f"production prerequisites refused: {error}") from error


def require_production_runtime(painter: Path) -> None:
    process = run_painter([str(painter), "capabilities", "--runtime"])
    try:
        capability = report_line(process.stdout)
    except (ValueError, TypeError) as error:
        raise HostError("invalid production runtime capability response") from error
    if (
        process.returncode != OK
        or not isinstance(capability, dict)
        or capability.get("schema") != "uzpainter/runtime-capabilities/1"
        or type(capability.get("assets3d_production_guard")) is not int
        or capability.get("assets3d_production_guard") != 1
    ):
        raise HostError("host does not support the required Assets3D production guard")


@contextlib.contextmanager
def request_files() -> Iterator[list[Path]]:
    """Use unique files in an existing directory; never allocate a temporary directory."""
    scratch = Path(os.environ.get(SCRATCH_ENV) or RUNNER.parents[2] / "tmp" / "scratch")
    if not scratch.is_dir():
        raise HostError(f"set {SCRATCH_ENV} to an existing scratch directory: {scratch}")
    with contextlib.ExitStack() as stack:
        paths = []
        for suffix in (".py", ".report.json", ".policy.json"):
            handle = stack.enter_context(
                tempfile.NamedTemporaryFile(
                    dir=scratch,
                    prefix="uzp-a3d-",
                    suffix=suffix,
                    delete_on_close=False,
                )
            )
            paths.append(Path(handle.name))
            handle.close()
        yield paths


def painter_exe() -> Path:
    """`UzPainter.exe`: `UZPAINTER_EXE`, else the one on PATH."""
    configured = os.environ.get(PAINTER_ENV)
    found = configured or shutil.which("UzPainter.exe")
    if not found or not Path(found).is_file():
        raise HostError(f"UzPainter.exe not found: set {PAINTER_ENV} or put it on PATH")
    return Path(found)


def session_file() -> Path:
    configured = os.environ.get(SESSION_ENV)
    if configured:
        return Path(configured)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "UzPainter" / "assets3d-adapter" / "session.json"


@contextlib.contextmanager
def session_lock(session: Path) -> Iterator[None]:
    """One adapter call at a time per session file, as Painter serves one call at a time: an OS
    lock on `<session>.lock`, released by the system if the process dies. A call that cannot
    take it within about ten seconds fails as a host error."""
    session.parent.mkdir(parents=True, exist_ok=True)
    with open(session.with_name(session.name + ".lock"), "a+b") as handle:
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # ten 1 s retries
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError as error:
            raise HostError(f"another adapter call holds the session {session}: {error}") from error
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextlib.contextmanager
def no_error_dialogs() -> Iterator[None]:
    """While UzPainter.exe runs, Windows shows it no error dialog, not even for a DLL that fails
    to load before its `main()`: the child inherits this error mode, so a broken installation
    fails the call instead of blocking it on a click (decision 252). This process's own mode is
    restored afterwards."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    previous = kernel32.SetErrorMode(kernel32.GetErrorMode() | NO_ERROR_DIALOGS)
    try:
        yield
    finally:
        kernel32.SetErrorMode(previous)


def run_painter(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """UzPainter.exe `argv` without any window (decision 252): every standard handle is
    redirected, and its console is a windowless one of its own (`CREATE_NO_WINDOW`), which a
    console child of a process without a console would otherwise get with a window."""
    with no_error_dialogs():
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=False,
        )


def windowless_python() -> Path:
    """The running interpreter's windowless twin, `pythonw.exe` beside `python.exe`, which
    Windows never gives a console. The layer-stack script's own `execute()` starts this client
    with it and without creation flags, where `python.exe` would get a new console with a window
    whenever the adapter itself runs without one (decision 252). The running interpreter when it
    has no such twin."""
    executable = Path(sys.executable)
    twin = executable.with_name("pythonw.exe")
    if sys.platform == "win32" and executable.name.lower() == "python.exe" and twin.is_file():
        return twin
    return executable


def diagnostic_flags() -> list[str]:
    """`--diagnostic-measure-export` when `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT` is `1` (above),
    none when it is unset or empty; any other value is a host error."""
    value = os.environ.get(DIAGNOSTIC_ENV, "")
    if value not in ("", "1"):
        raise HostError(f"{DIAGNOSTIC_ENV} must be 1 or unset, not {value!r}")
    return [DIAGNOSTIC_FLAG] if value == "1" else []


def report_line(stdout: str) -> dict[str, Any] | None:
    lines = [line for line in stdout.splitlines() if line.startswith(JSON_PREFIX)]
    return json.loads(lines[-1][len(JSON_PREFIX) :]) if lines else None


def execute_python(code: str) -> tuple[dict[str, Any], int]:
    """Run `code` in UzPainter as the bridge runs it; the reply and the exit status."""
    policy = execution_policy()
    painter, session, diagnostic = painter_exe(), session_file(), diagnostic_flags()
    if policy is not None:
        require_production_runtime(painter)
    with session_lock(session), request_files() as files:
        code_file, report_file, policy_file = files
        code_file.write_bytes(code.encode("utf-8"))
        policy_file.write_text(json.dumps(policy), encoding="utf-8")
        process = run_painter(
            [
                str(painter),
                "run",
                str(RUNNER),
                *diagnostic,
                *([PRODUCTION_FLAG] if policy is not None else []),
                "--",
                str(code_file),
                str(session),
                str(report_file),
                str(policy_file),
            ]
        )
        host = report_line(process.stdout)
        if (
            host is None
            or process.returncode not in (OK, FAILED)
            or host.get("status") == "host_error"
        ):
            raise HostError(
                f"UzPainter.exe run exited {process.returncode}: "
                f"{(host or {}).get('error') or process.stderr.strip() or process.stdout.strip()}"
            )
        extra: dict[str, Any] = (
            json.loads(report_file.read_text(encoding="utf-8"))
            if report_file.stat().st_size
            else {}
        )
        if policy is not None:
            guard = extra.get("production_guard")
            if not isinstance(guard, dict) or (
                guard.get("schema") != "uzpainter/assets3d-production-status/1"
                or guard.get("mode") != "armed"
                or guard.get("policy_installed") is not True
                or guard.get("request_sha256") != policy["request_sha256"]
                or guard.get("source_sha256") != policy["source_sha256"]
            ):
                raise HostError("host did not acknowledge the required production policy")
    success = host["status"] == "ok"
    reply = {
        "success": success,
        "data": host["result"] if success else extra.get("script_result"),
        "stdout": host["stdout"],
        "stderr": host["stderr"],
        "error": None if success else host.get("error"),
        "code_sha256": extra.get("code_sha256"),
        "last_committed_revision": host.get("last_committed_revision"),
        "session": extra.get("session"),
        "exports": extra.get("exports", []),
        "redirects": extra.get("redirects", {}),
    }
    if "diagnostic" in host:  # `UzPainter.exe run --diagnostic-measure-export`: not conformant
        reply["diagnostic"] = host["diagnostic"]
    elif policy is None:
        reply["diagnostic"] = "diagnostic-import"
    if policy is not None:
        reply["production_guard"] = extra["production_guard"]
    return reply, OK if success else FAILED


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != TOOL:
        print(
            f"usage: client.py {TOOL} ARGS.json (the adapter serves {TOOL} only)",
            file=sys.stderr,
        )
        return USAGE
    arguments = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    if not isinstance(arguments, dict) or not isinstance(arguments.get("code"), str):
        print(f'usage: {argv[2]} must hold {{"code": "..."}}', file=sys.stderr)
        return USAGE
    try:
        reply, status = execute_python(arguments["code"])
    except HostError as error:
        reply = {
            "success": False,
            "data": None,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
        status = HOST_ERROR
    text = json.dumps(reply)  # ASCII: the caller decodes the pipe with its locale's encoding
    output = os.environ.get("SP_MCP_CLIENT_OUTPUT_DIR")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output) / "painter-last-response.json").write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
