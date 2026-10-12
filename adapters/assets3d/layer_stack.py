"""The adapter's entry: Assets3D's `painter_layer_stack.py`, byte-unchanged, over UzPainter.

    python -m adapters.assets3d [--pin FILE=SHA256]... <painter_layer_stack.py> <its arguments>
    python <UzPainter>/adapters/assets3d/layer_stack.py [--pin FILE=SHA256]... <...> <...>

replaces `"$MCP" "$LS" <its arguments>` (`MIGRATIONS.md` M1, M2). The script's bytes are read once
and compiled with their real path under a module name other than `__main__`; only its two
transport globals are rebound, `CLIENT` to this adapter's client (`client.py`) and `MCP_PYTHON` to
the running interpreter, and its own `main()` then runs with its own arguments. Everything else,
its own `execute()` and reply handling included, is the script's.

- `--pin FILE=SHA256` (repeatable) refuses the call before anything runs when FILE's bytes do not
  hash to SHA256: the wand fixture pins the layer-stack script and the files it `run`s.
- A subcommand that needs a capability UzPainter does not have yet is refused before any call
  reaches UzPainter, because its code mutates before the missing call (`GATES`, read from the
  shipped capability manifest: the gate opens by itself once the manifest marks the capability
  `supported`). Code a script sends through `run FILE` is not gated: a missing call raises where
  it is reached, after the script's earlier calls committed, as Painter's contract has it.
  `capture` is not gated: its code changes nothing before the shim refuses.
- `UZP_ASSETS3D_ROOT` defaults to the script's own root (`ROOT`, the folder holding `AGENTS.md`).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if not __package__:  # run as a file: `python <UzPainter>/adapters/assets3d/layer_stack.py ...`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.assets3d import client

ROOT_ENV = "UZP_ASSETS3D_ROOT"
MODULE_NAME = "uzp_assets3d_painter_layer_stack"

# Subcommand -> (capability, owner, the manifest entries it needs as (symbol, context)).
GATES: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    "smart": (
        "smart presets",
        "phase3.6_smart-presets-projections",
        (
            ("substance_painter.layerstack.insert_smart_mask", "any"),
            ("substance_painter.resource.search", "any"),
        ),
    ),
}
# The gate opens only on `supported` (decision 113): a `pending-evidence` symbol works but is
# unverified, and these subcommands mutate before they reach it.
OPEN = frozenset({"supported"})


class Refused(Exception):
    """The call is refused before anything runs; `reply` is printed and the exit status is 1."""

    def __init__(self, error_type: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.reply: dict[str, Any] = {
            "success": False,
            "data": None,
            "error": {"type": error_type, "message": message, **details},
        }


def parse(argv: list[str]) -> tuple[dict[Path, str], Path, list[str]]:
    pins: dict[Path, str] = {}
    rest = list(argv)
    while rest and rest[0] == "--pin":
        if len(rest) < 2 or "=" not in rest[1]:
            raise SystemExit(
                "usage: python -m adapters.assets3d [--pin FILE=SHA256]... SCRIPT ARGS"
            )
        file, sha = rest[1].rsplit("=", 1)
        pins[Path(file).resolve()] = sha.lower()
        rest = rest[2:]
    if not rest:
        raise SystemExit("usage: python -m adapters.assets3d [--pin FILE=SHA256]... SCRIPT ARGS")
    return pins, Path(rest[0]).resolve(), rest[1:]


def check_pins(pins: dict[Path, str], script: Path, data: bytes) -> None:
    for file, sha in pins.items():
        actual = hashlib.sha256(data if file == script else file.read_bytes()).hexdigest()
        if actual != sha:
            raise Refused(
                "PinMismatch", f"{file} has SHA-256 {actual}, not its pinned {sha}: refused"
            )


def capability_statuses() -> dict[tuple[str, str], str]:
    """`(symbol, context) -> status` of the shipped manifest (`UzPainter.exe capabilities`)."""
    process = subprocess.run(
        [str(client.painter_exe()), "capabilities"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    manifest = client.report_line(process.stdout)
    if process.returncode != 0 or manifest is None:
        raise client.HostError(f"UzPainter.exe capabilities exited {process.returncode}")
    return {(e["symbol"], e["context"]): e["status"] for e in manifest["entries"]}


def check_gate(arguments: list[str]) -> None:
    command = next((a for a in arguments if not a.startswith("-")), None)
    if command not in GATES:
        return
    capability, owner, needs = GATES[command]
    statuses = capability_statuses()
    missing = [
        {"symbol": s, "context": c, "status": statuses.get((s, c), "absent")}
        for s, c in needs
        if statuses.get((s, c)) not in OPEN
    ]
    if missing:
        raise Refused(
            "NotYetSupported",
            f"`{command}` needs {capability}, which UzPainter does not have yet ({owner}); "
            "refused before any call reached UzPainter",
            capability=capability,
            owner=owner,
            missing=missing,
        )


def run(argv: list[str]) -> int:
    pins, script, arguments = parse(argv)
    data = script.read_bytes()
    check_pins(pins, script, data)
    check_gate(arguments)
    namespace: dict[str, Any] = {"__name__": MODULE_NAME, "__file__": str(script)}
    exec(compile(data, str(script), "exec", dont_inherit=True), namespace)
    if not callable(namespace.get("main")) or not callable(namespace.get("execute")):
        raise Refused("AdapterError", f"{script} defines no `main()` and `execute(code)`")
    for name in ("CLIENT", "MCP_PYTHON"):
        if name not in namespace:
            raise Refused("AdapterError", f"{script} defines no transport global `{name}`")
    namespace["CLIENT"] = client.RUNNER.with_name("client.py")
    namespace["MCP_PYTHON"] = Path(sys.executable)
    if "ROOT" in namespace:
        os.environ.setdefault(ROOT_ENV, str(namespace["ROOT"]))
    saved = sys.argv
    sys.argv = [str(script), *arguments]
    try:
        namespace["main"]()
    finally:
        sys.argv = saved
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Refused as refused:
        print(json.dumps(refused.reply))
        return client.FAILED
    except client.HostError as error:
        print(
            json.dumps(
                {
                    "success": False,
                    "data": None,
                    "error": {"type": "HostError", "message": str(error)},
                }
            )
        )
        return client.HOST_ERROR


if __name__ == "__main__":
    sys.exit(main())
