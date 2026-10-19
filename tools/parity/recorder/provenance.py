"""Provenance check of the recorder sources (task item 3.1; spec `oracle-recorder`).

Rules over every `tools/parity/recorder/*.py`:

1. No import of, and no reference to, the community Substance Painter MCP bridge.
2. No access to an underscore-prefixed attribute (no private or dunder interface).
3. Every `substance_painter` symbol used — attribute chains on imported `substance_painter`
   modules and their aliases, and dotted `substance_painter.*` names in string constants (the
   instruction vocabulary) — is listed in `documented_symbols.json`, whose entries each name the
   object of Painter's public Python API documentation (A-PYDOC) that documents them. The same
   holds for the documented `substance_painter_plugins` module (decision 297).
4. In files that import `substance_painter`: every attribute read on any other object is either
   a member name of a listed symbol or a member of a builtin Python type in `PYTHON_MEMBERS`,
   and dynamic attribute access (`getattr`, `setattr`, `delattr`, `__import__`) is refused.

`documented_symbols.json` is checked against the shipped python-doc's Sphinx inventory
(`objects.inv`) by `inventory_problems` when that documentation is available.
"""

from __future__ import annotations

import ast
import json
import re
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

RECORDER_DIR = Path(__file__).resolve().parent
SYMBOLS_PATH = RECORDER_DIR / "documented_symbols.json"
ROOT = "substance_painter"
ROOTS = (ROOT, "substance_painter_plugins")
SYMBOL_PATTERN = re.compile(r"^substance_painter(_plugins)?(\.[A-Za-z_][A-Za-z0-9_]*)+$")
BRIDGE_MARKERS = ("mcp",)
BRIDGE_TEXT = re.compile(
    r"substance[_-]?painter[_-]?mcp|painter[_-]?mcp|mcp[_-]?client", re.IGNORECASE
)
DYNAMIC_ACCESS = frozenset({"getattr", "setattr", "delattr", "__import__"})

# Members of builtin Python types (dict, list, str, bytes, float) used on plain values.
PYTHON_MEMBERS = frozenset(
    {"append", "clear", "decode", "get", "index", "items", "startswith", "split", "values"}
)


@dataclass(frozen=True)
class Problem:
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


@cache
def documented_symbols(path: Path = SYMBOLS_PATH) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    symbols: dict[str, dict[str, str]] = data["symbols"]
    return symbols


def member_names(symbols: Iterable[str]) -> frozenset[str]:
    return frozenset(s.rsplit(".", 1)[1] for s in symbols if s.count(".") >= 2)


def attribute_chain(node: ast.expr) -> tuple[str, list[str]] | None:
    """`a.b.c` -> ("a", ["b", "c"]); None when the chain does not start at a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, list(reversed(parts))
    return None


def module_bindings(tree: ast.Module) -> tuple[dict[str, str], set[str]]:
    """Names bound to `substance_painter` paths, and names bound to other imported modules."""
    painter: dict[str, str] = {}
    others: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in ROOTS:
                    if alias.asname:
                        painter[alias.asname] = alias.name
                    else:
                        painter[root] = root
                else:
                    others.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                target = alias.asname or alias.name
                if node.module.split(".")[0] in ROOTS:
                    painter[target] = f"{node.module}.{alias.name}"
                else:
                    others.add(target)
    # Simple aliases: `name = substance_painter.x.y` (flow-insensitive).
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id not in painter
            ):
                chain = attribute_chain(node.value)
                if chain and chain[0] in painter:
                    painter[node.targets[0].id] = ".".join([painter[chain[0]], *chain[1]])
                    changed = True
    return painter, others


def imports_bridge(node: ast.AST) -> str | None:
    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom):
        names = [node.module or "", *(a.name for a in node.names)]
    for name in names:
        lowered = name.lower()
        if any(m in part for part in lowered.split(".") for m in BRIDGE_MARKERS):
            return name
        if BRIDGE_TEXT.search(name):
            return name
    return None


def check_source(
    source: str, file: str, symbols: dict[str, dict[str, str]] | None = None
) -> list[Problem]:
    known = documented_symbols() if symbols is None else symbols
    members = member_names(known)
    tree = ast.parse(source, filename=file)
    painter, others = module_bindings(tree)
    problems: list[Problem] = []

    def report(node: ast.AST, message: str) -> None:
        problems.append(Problem(file, getattr(node, "lineno", 0), message))

    chained: set[int] = set()
    for node in ast.walk(tree):
        bridge = imports_bridge(node)
        if bridge is not None:
            report(node, f"imports the community MCP bridge ({bridge})")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if BRIDGE_TEXT.search(node.value):
                report(node, "refers to the community MCP bridge")
            if SYMBOL_PATTERN.match(node.value) and node.value not in known:
                report(node, f"undocumented substance_painter symbol {node.value}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            report(node, f"private attribute access .{node.attr}")
        if (
            painter
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in DYNAMIC_ACCESS
        ):
            report(node, f"dynamic attribute access {node.func.id}() hides the symbol used")
        if isinstance(node, ast.Attribute) and id(node) not in chained:
            chain = attribute_chain(node)
            inner = node.value
            while isinstance(inner, ast.Attribute):
                chained.add(id(inner))
                inner = inner.value
            if chain and chain[0] in painter:
                symbol = ".".join([painter[chain[0]], *chain[1]])
                if symbol not in known:
                    report(node, f"undocumented substance_painter symbol {symbol}")
            elif chain and chain[0] in others:
                continue
            elif painter:
                attrs = chain[1] if chain else [node.attr]
                for attr in attrs:
                    if not attr.startswith("_") and attr not in members | PYTHON_MEMBERS:
                        report(node, f"attribute .{attr} is not a member of a documented symbol")
    return problems


def check_files(paths: Iterable[Path]) -> list[Problem]:
    problems: list[Problem] = []
    for path in sorted(paths):
        problems += check_source(path.read_text(encoding="utf-8"), path.name)
    return problems


def recorder_sources(directory: Path = RECORDER_DIR) -> list[Path]:
    return sorted(directory.glob("*.py"))


def inventory_symbols(objects_inv: Path) -> dict[str, str]:
    """Documented objects and pages of a Sphinx inventory (version 2): name -> page.

    Python objects use dotted names; documentation pages (`std:doc`) use their page path, which
    is how a module without a `py:module` entry (e.g. `substance_painter/colormanagement`) is
    found.
    """
    data = objects_inv.read_bytes()
    header_end = 0
    for _ in range(4):
        header_end = data.index(b"\n", header_end) + 1
    body = zlib.decompress(data[header_end:]).decode("utf-8")
    symbols: dict[str, str] = {}
    for line in body.splitlines():
        match = re.match(r"^(\S+)\s+(py:\S+|std:doc)\s+-?\d+\s+(\S+)", line)
        if match:
            symbols[match.group(1)] = match.group(3).split("#", 1)[0]
    return symbols


def inventory_problems(
    objects_inv: Path, symbols: dict[str, dict[str, str]] | None = None
) -> list[str]:
    """Each listed symbol's `documented_as` object exists on its `page` in the python-doc."""
    known = documented_symbols() if symbols is None else symbols
    inventory = inventory_symbols(objects_inv)
    problems: list[str] = []
    for symbol, entry in sorted(known.items()):
        anchor = entry["documented_as"]
        if anchor not in inventory:
            problems.append(f"{symbol}: {anchor} is not in the python-doc inventory")
        elif inventory[anchor] != entry["page"]:
            problems.append(f"{symbol}: {anchor} is documented on {inventory[anchor]}")
        elif not (
            symbol == anchor
            or symbol.startswith(anchor + ".")
            or anchor == symbol.replace(".", "/")
        ):
            problems.append(f"{symbol}: documented_as {anchor} is not the symbol or its owner")
    return problems
