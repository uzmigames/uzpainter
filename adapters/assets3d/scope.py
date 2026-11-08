"""The amended scope of a production round (task phase3.1_assets3d-cutover item 2.6, `MIGRATIONS.md`
M13): what UzPainter paints for Assets3D is what the shipped capability manifest marks `supported`
(`docs/architecture/10-python-api.md` §3); everything else stays with Substance 3D Painter until
G5 (decision 026). A production round that names anything else is refused before it runs, with a
structured error that names Painter as the tool for it.

The check reads the code a production call would run, never runs it: every name the code binds to
a module of `substance_painter`, `uzpainter` or the adapter's shim (`_substance_painter`) by an
`import`, and every attribute chain read from such a name, is resolved to its manifest symbol. A
symbol is in scope when its `any` entry is `supported`; `pending-evidence`, `release-gap`,
`desktop-only-omitted` and a symbol the manifest does not list are outside it. What this static
reading cannot see (a method called on an object, `getattr`, a name bound at run time) is still
checked where it is called: the facade raises `NotYetSupported` before a `release-gap` call
mutates anything, and the native production guard (M12) keeps every other boundary. A reference
on a branch the code never takes is refused all the same: nothing of a refused round runs.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "uzpainter/assets3d-scope-refusal/1"
PAINTER = "Adobe Substance 3D Painter"
IN_SCOPE = "supported"
ROOTS = frozenset({"substance_painter", "uzpainter", "_substance_painter"})
# The adapter's shim (`MIGRATIONS.md` M3) is a UzmiGames name for a native call: it is in scope
# exactly when the call it makes is.
SHIM = {"_substance_painter.display.save_viewport": "uzpainter.render.capture"}
SHIM_MODULES = frozenset({"_substance_painter", "_substance_painter.display"})
MANIFEST_FILE = "capabilities.json"


class OutOfAmendedScope(Exception):
    """A production round names a capability outside the amended scope; `error` is its reply."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error["message"])
        self.error = error


def load_manifest(painter: Path) -> tuple[dict[str, str], str]:
    """`symbol -> status` of the `any` entries of the manifest shipped beside `painter`, and the
    SHA-256 of its bytes (the manifest version the scope was read from)."""
    raw = painter.with_name(MANIFEST_FILE).read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schema") != "uzpainter/capabilities/1":
        raise ValueError(f"{painter.with_name(MANIFEST_FILE)} is not a capability manifest")
    statuses = {
        entry["symbol"]: entry["status"]
        for entry in manifest["entries"]
        if entry.get("context") == "any"
    }
    return statuses, hashlib.sha256(raw).hexdigest()


def dotted(node: ast.expr, names: dict[str, str]) -> str | None:
    """The qualified name an attribute chain reads from a bound module name, or None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in names:
        return None
    return ".".join([names[node.id], *reversed(parts)])


def referenced(code: str) -> list[str]:
    """Every qualified name the code reads from a bound API module, longest chains only, sorted."""
    tree = ast.parse(code)
    names: dict[str, str] = {}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.partition(".")[0] not in ROOTS:
                    continue
                found.add(alias.name)
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    top = alias.name.partition(".")[0]
                    names[top] = top
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if node.module.partition(".")[0] not in ROOTS:
                continue
            for alias in node.names:
                # A star import binds names no reading can resolve: `<module>.*` is never listed.
                symbol = f"{node.module}.{alias.name}"
                found.add(symbol)
                if alias.name != "*":
                    names[alias.asname or alias.name] = symbol
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            inner.add(id(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and id(node) not in inner:
            name = dotted(node, names)
            if name is not None:
                found.add(name)
    return sorted(found)


def resolve(name: str, statuses: dict[str, str]) -> tuple[str, str]:
    """The manifest symbol `name` reads and its status: the name itself, else its longest listed
    prefix when only dunder attributes follow it (`ChannelType.__members__`); anything else is
    `absent`."""
    name = SHIM.get(name, name)
    if name in statuses:
        return name, statuses[name]
    parts = name.split(".")
    for end in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:end])
        if prefix in statuses:
            tail = parts[end:]
            if all(p.startswith("__") and p.endswith("__") for p in tail):
                return prefix, statuses[prefix]
            break
    return name, "absent"


def outside(code: str, statuses: dict[str, str]) -> list[dict[str, str]]:
    """The symbols the code names that are outside the amended scope, with their status."""
    result: dict[str, str] = {}
    for name in referenced(code):
        if name in SHIM_MODULES:
            continue
        symbol, status = resolve(name, statuses)
        if status != IN_SCOPE:
            result[symbol] = status
    return [{"symbol": s, "context": "any", "status": result[s]} for s in sorted(result)]


def refusal(operation: str, missing: list[dict[str, str]], manifest_sha256: str) -> dict[str, Any]:
    """The structured error of an out-of-scope production round."""
    symbols = ", ".join(f"{m['symbol']} ({m['status']})" for m in missing)
    return {
        "type": "OutOfAmendedScope",
        "schema": SCHEMA,
        "message": (
            f"{operation} is outside the amended scope of UzPainter in the Assets3D pipeline "
            f"(capabilities `supported` in the capability manifest): {symbols}. Do this work in "
            f"{PAINTER}; refused before anything ran"
        ),
        "operation": operation,
        "tool": PAINTER,
        "outside": missing,
        "capabilities_sha256": manifest_sha256,
    }


def scope_of(painter: Path, operation: str) -> tuple[dict[str, str], str]:
    """The amended scope (`load_manifest`), or an `OutOfAmendedScope` refusal when the manifest
    beside `painter` cannot be read: without it nothing is in scope."""
    try:
        return load_manifest(painter)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise OutOfAmendedScope(
            {
                "type": "OutOfAmendedScope",
                "schema": SCHEMA,
                "message": f"the amended scope cannot be read ({error}); nothing ran",
                "operation": operation,
                "tool": PAINTER,
                "outside": [],
                "capabilities_sha256": None,
            }
        ) from error


def check_needs(
    operation: str, needs: list[str], statuses: dict[str, str], manifest_sha256: str
) -> None:
    """Refuse `operation` when any symbol it needs is outside the amended scope."""
    missing = [
        {"symbol": s, "context": "any", "status": statuses.get(s, "absent")}
        for s in needs
        if statuses.get(s) != IN_SCOPE
    ]
    if missing:
        raise OutOfAmendedScope(refusal(operation, missing, manifest_sha256))


def check_code(code: str, painter: Path, operation: str = "execute_python") -> str:
    """Refuse `code` (`OutOfAmendedScope`) when it names anything outside the amended scope; the
    manifest's SHA-256 when it does not. Code that does not parse is refused too: its references
    cannot be read."""
    statuses, sha = scope_of(painter, operation)
    try:
        missing = outside(code, statuses)
    except SyntaxError as error:
        missing = [{"symbol": f"<unparsable: {error.msg}>", "context": "any", "status": "absent"}]
    if missing:
        raise OutOfAmendedScope(refusal(operation, missing, sha))
    return sha
