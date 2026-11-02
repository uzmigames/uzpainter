"""The adapter's entry: Assets3D's `painter_layer_stack.py`, byte-unchanged, over UzPainter.

    python -m adapters.assets3d --production-round REQUEST [--pin|--import FILE=SHA]... SCRIPT ARGS
    python -m adapters.assets3d --diagnostic-import [--pin|--import FILE=SHA]... SCRIPT ARGS

replaces `"$MCP" "$LS" <its arguments>` (`MIGRATIONS.md` M1, M2). The script's bytes are read once
and compiled with their real path under a module name other than `__main__`; only its two
transport globals are rebound, `CLIENT` to this adapter's client (`client.py`) and `MCP_PYTHON` to
the running interpreter's windowless `pythonw.exe` (`client.windowless_python`), and its own
`main()` then runs with its own arguments. Everything else, its own `execute()` and reply handling
included, is the script's.

- `--pin FILE=SHA256` (repeatable) refuses the call before anything runs when FILE's bytes do not
  hash to SHA256: the wand fixture pins the layer-stack script and the files it `run`s.
- `--import FILE=SHA256` (repeatable, dependencies first) closes the script's imports to a pinned
  import closure (decision 300 item 7): each FILE is refused like a pin, then loaded from the
  bytes checked as module `<stem>` before the script runs, in place of any module of that name
  already loaded. While the script runs, an import of a
  module not loaded yet that is not the standard library is refused, the call refuses with
  `UnpinnedImport` even when the script catches the error, and no Painter call starts after the
  refusal (its `execute` is called through a check of that, its only other rebinding).
  `sys.path`, the loaded modules' entries and `sys.meta_path` are restored after. Without
  `--import` the script imports as it always did.
- A subcommand that needs a capability UzPainter does not have yet is refused before any call
  reaches UzPainter, because its code mutates before the missing call (`GATES`, read from the
  shipped capability manifest: the gate opens by itself once the manifest marks the capability
  `supported`). Code a script sends through `run FILE` is not gated: a missing call raises where
  it is reached, after the script's earlier calls committed, as Painter's contract has it.
  `capture` is not gated: its code changes nothing before the shim refuses.
- `UZP_ASSETS3D_ROOT` defaults to the script's own root (`ROOT`, the folder holding `AGENTS.md`).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import sys
import sysconfig
import types
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

if not __package__:  # run as a file: `python <UzPainter>/adapters/assets3d/layer_stack.py ...`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.assets3d import client, gate_contract

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


USAGE = "usage: python -m adapters.assets3d [--pin|--import FILE=SHA256]... SCRIPT ARGS"


def parse(argv: list[str]) -> tuple[dict[Path, str], list[tuple[Path, str]], Path, list[str]]:
    """The pins, the pinned imports in their order, the script and its arguments."""
    pins: dict[Path, str] = {}
    imports: list[tuple[Path, str]] = []
    rest = list(argv)
    while rest and rest[0] in ("--pin", "--import"):
        if len(rest) < 2 or "=" not in rest[1]:
            raise SystemExit(USAGE)
        file, sha = rest[1].rsplit("=", 1)
        if rest[0] == "--pin":
            pins[Path(file).resolve()] = sha.lower()
        else:
            imports.append((Path(file).resolve(), sha.lower()))
        rest = rest[2:]
    if not rest:
        raise SystemExit(USAGE)
    return pins, imports, Path(rest[0]).resolve(), rest[1:]


def check_sha(file: Path, data: bytes, sha: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha:
        raise Refused("PinMismatch", f"{file} has SHA-256 {actual}, not its pinned {sha}: refused")


def check_pins(pins: dict[Path, str], script: Path, data: bytes) -> None:
    for file, sha in pins.items():
        check_sha(file, data if file == script else file.read_bytes(), sha)


def pinned_imports(imports: list[tuple[Path, str]]) -> list[tuple[Path, bytes]]:
    """Each `--import` file's bytes, read once and checked against its pin."""
    checked = []
    for file, sha in imports:
        data = file.read_bytes()
        check_sha(file, data, sha)
        checked.append((file, data))
    if len({file.stem for file, _ in checked}) != len(checked):
        raise Refused("AdapterError", "two `--import` files give one module name: refused")
    return checked


STANDARD_ROOTS = tuple(
    Path(p).resolve()
    for p in sorted(
        {
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
            str(Path(sys.base_exec_prefix) / "DLLs"),
        }
    )
)


def standard_library(fullname: str, path: Sequence[str] | None) -> bool:
    """Whether an import is the interpreter's own standard library: a built-in or frozen module, or
    a module of a standard-library name whose file lies under the standard library's directories
    outside site-packages (the recorder's rule, `tools.parity.recorder.script_run`). A same-named
    file elsewhere on `sys.path` is not."""
    top = fullname.partition(".")[0]
    if top in sys.builtin_module_names:
        return True
    if top not in sys.stdlib_module_names:
        return False
    if importlib.machinery.FrozenImporter.find_spec(fullname) is not None:
        return True
    spec = importlib.machinery.PathFinder.find_spec(fullname, path)
    if spec is None:
        return True  # nothing to load: the import fails as it would
    if spec.origin is None:
        return False
    origin = Path(spec.origin).resolve()
    return "site-packages" not in origin.parts and any(
        origin.is_relative_to(root) for root in STANDARD_ROOTS
    )


class ClosedImports(importlib.abc.MetaPathFinder):
    """Refuses (and records) every import of a module not loaded yet that is not the standard
    library, so neither a live file on `sys.path` nor any other unpinned code is loaded."""

    def __init__(self) -> None:
        self.refused: list[str] = []

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: types.ModuleType | None = None,
    ) -> None:
        if not standard_library(fullname, path):
            self.refused.append(fullname)
            raise ImportError(f"{fullname} is neither a pinned import nor the standard library")
        return None

    def check(self) -> None:
        if self.refused:
            modules = sorted(set(self.refused))
            raise Refused(
                "UnpinnedImport",
                f"the script imports {modules}, which are neither `--import` files nor the "
                "standard library: refused",
                modules=modules,
            )


def pinned_module(file: Path, data: bytes) -> types.ModuleType:
    """The module an import of `file` gives (its stem), executed from its checked bytes; it is in
    `sys.modules` while it executes, as an import puts it (`dataclasses` looks it up there)."""
    spec = importlib.util.spec_from_file_location(file.stem, file)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[file.stem] = module
    exec(compile(data, str(file), "exec", dont_inherit=True), vars(module))
    return module


@contextlib.contextmanager
def closed_imports(modules: list[tuple[Path, bytes]]) -> Iterator[ClosedImports | None]:
    """With `modules`, removes every module of their names already loaded, loads each
    (dependencies first) and refuses every other import while the block runs; `sys.path`, their
    `sys.modules` entries and `sys.meta_path` are restored after.
    Without, nothing changes (None)."""
    if not modules:
        yield None
        return
    guard = ClosedImports()
    saved_path = list(sys.path)
    saved_modules = {file.stem: sys.modules.get(file.stem) for file, _ in modules}
    sys.meta_path.insert(0, guard)
    try:
        for name in saved_modules:  # a cached module of a pinned name is never what loads
            sys.modules.pop(name, None)
        for file, data in modules:
            sys.modules[file.stem] = pinned_module(file, data)
        yield guard
        guard.check()
    except BaseException:
        guard.check()  # a refused import is the cause, whatever the script raised then
        raise
    finally:
        sys.meta_path.remove(guard)
        sys.path[:] = saved_path
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def capability_statuses() -> dict[tuple[str, str], str]:
    """`(symbol, context) -> status` of the shipped manifest (`UzPainter.exe capabilities`)."""
    process = client.run_painter([str(client.painter_exe()), "capabilities"])
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


def run_script(argv: list[str]) -> int:
    pins, imports, script, arguments = parse(argv)
    data = script.read_bytes()
    check_pins(pins, script, data)
    modules = pinned_imports(imports)
    check_gate(arguments)
    with closed_imports(modules) as guard:
        namespace: dict[str, Any] = {"__name__": MODULE_NAME, "__file__": str(script)}
        exec(compile(data, str(script), "exec", dont_inherit=True), namespace)
        if guard is not None:
            guard.check()  # before main(): nothing has reached UzPainter yet
        if not callable(namespace.get("main")) or not callable(namespace.get("execute")):
            raise Refused("AdapterError", f"{script} defines no `main()` and `execute(code)`")
        for name in ("CLIENT", "MCP_PYTHON"):
            if name not in namespace:
                raise Refused("AdapterError", f"{script} defines no transport global `{name}`")
        namespace["CLIENT"] = client.RUNNER.with_name("client.py")
        namespace["MCP_PYTHON"] = client.windowless_python()
        if guard is not None:
            namespace["execute"] = checked_execute(namespace["execute"], guard)
        if "ROOT" in namespace:
            os.environ.setdefault(ROOT_ENV, str(namespace["ROOT"]))
        saved = sys.argv
        sys.argv = [str(script), *arguments]
        try:
            namespace["main"]()
        finally:
            sys.argv = saved
    return 0


def checked_execute(execute: Any, guard: ClosedImports) -> Any:
    """The script's own `execute`, called only while no import was refused: a refused import the
    script caught never lets a later Painter call start."""

    def checked(*args: Any, **kwargs: Any) -> Any:
        guard.check()
        return execute(*args, **kwargs)

    return checked


def run(argv: list[str]) -> int:
    if argv[:1] == ["--production-round"] and len(argv) >= 3:
        request, diagnostic, rest = str(Path(argv[1]).absolute()), "", argv[2:]
    elif argv[:1] == ["--diagnostic-import"]:
        request, diagnostic, rest = "", "1", argv[1:]
    else:
        raise Refused(
            "ProductionContextRequired",
            "select --production-round REQUEST or --diagnostic-import before SCRIPT",
        )
    names = (client.PRODUCTION_ENV, client.IMPORT_DIAGNOSTIC_ENV, ROOT_ENV)
    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ[client.PRODUCTION_ENV] = request
        os.environ[client.IMPORT_DIAGNOSTIC_ENV] = diagnostic
        client.execution_policy()  # Refuse invalid prerequisites before loading external Python.
        if request:
            client.require_production_runtime(client.painter_exe())
        return run_script(rest)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["check-production"]:
        return gate_contract.main(arguments[1:])
    try:
        return run(arguments)
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
