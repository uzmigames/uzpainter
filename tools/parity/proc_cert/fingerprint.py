"""The candidate's fingerprint: its declared identity bound to the code that runs it (decision 303).

The fingerprint is the SHA-256 of
- the candidate's declared identity (`Candidate.fingerprint()`), which must name every piece of
  fitted state that changes its outputs: the guarantee holds only as far as that declaration is
  complete, because instance state the declaration leaves out is not seen;
- the qualified name of its class;
- the bytes of every project module in the import closure of the modules that define the class
  and its bases: each module's own file, the modules it imports (at any depth, including imports
  inside functions) and their parent packages, as long as they live in the project tree.

Imports are read from the source with `ast`, so the closure is the same whether or not a lazy
import has run yet, and nothing is imported to find it. Modules outside the project tree (the
standard library, installed packages, a virtual environment inside the tree) are not hashed;
neither are modules reached only through `importlib.import_module` or `__import__` with a
computed name.
"""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import inspect
import sys
from collections.abc import Iterator, Mapping
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

from tools.parity.proc_cert.batch import canonical, sha256_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FingerprintError(Exception):
    """A candidate whose code cannot be bound to its fingerprint."""


def _spec(name: str) -> ModuleSpec | None:
    """The spec of module `name` without importing anything: the loaded module's, else found on
    the search path of its parent package."""
    module = sys.modules.get(name)
    if module is not None:
        spec: ModuleSpec | None = getattr(module, "__spec__", None)
        if spec is None and isinstance(getattr(module, "__file__", None), str):
            spec = importlib.util.spec_from_file_location(name, module.__file__)
        return spec
    parent = name.rpartition(".")[0]
    path: list[str] | None = None
    if parent:
        parent_spec = _spec(parent)
        if parent_spec is None or parent_spec.submodule_search_locations is None:
            return None
        path = list(parent_spec.submodule_search_locations)
    try:
        return importlib.machinery.PathFinder.find_spec(name, path)
    except (ImportError, ValueError):
        return None


def _interpreter_trees() -> tuple[Path, ...]:
    """Interpreter trees that may sit inside the project (a virtual environment) and are not
    project code."""
    prefixes = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    return tuple(Path(prefix).resolve() for prefix in sorted(prefixes))


def _project_file(spec: ModuleSpec, root: Path) -> Path | None:
    if not spec.has_location or not isinstance(spec.origin, str):
        return None
    origin = Path(spec.origin).resolve()
    if not origin.is_file() or not origin.is_relative_to(root):
        return None
    if any(origin.is_relative_to(prefix) for prefix in _interpreter_trees()):
        return None
    return origin


def _with_parents(name: str) -> Iterator[str]:
    parts = name.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


def _imported(name: str, spec: ModuleSpec, source: bytes) -> Iterator[str]:
    """Every module name the source imports, with the parent packages an import runs."""
    package = name if spec.submodule_search_locations is not None else name.rpartition(".")[0]
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield from _with_parents(alias.name)
        elif isinstance(node, ast.ImportFrom):
            try:
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            except (ImportError, ValueError):
                continue
            base = base.rstrip(".")
            if not base:
                continue
            yield from _with_parents(base)
            for alias in node.names:
                if alias.name != "*":
                    yield f"{base}.{alias.name}"  # a submodule, when one has that name


def import_closure(modules: list[str], root: Path) -> dict[str, str]:
    """{module name: SHA-256 of its file} for every project module the given modules reach."""
    root = root.resolve()
    hashes: dict[str, str] = {}
    seen: set[str] = set()
    pending = [name for module in modules for name in _with_parents(module)]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        spec = _spec(name)
        if spec is None or (origin := _project_file(spec, root)) is None:
            continue
        data = origin.read_bytes()
        hashes[name] = sha256_bytes(data)
        if origin.suffix == ".py":
            pending.extend(n for n in _imported(name, spec, data) if n not in seen)
    return dict(sorted(hashes.items()))


def candidate_sha256(candidate: Any, root: Path = PROJECT_ROOT) -> str:
    """The candidate's fingerprint: declared identity, class and the code that runs it."""
    kind = type(candidate)
    if inspect.getsourcefile(kind) is None:
        raise FingerprintError(f"{kind.__qualname__} has no source file to bind its fingerprint to")
    defining = [cls.__module__ for cls in kind.__mro__ if cls.__module__ != "builtins"]
    closure = import_closure(sorted(set(defining)), root)
    if kind.__module__ not in closure:
        raise FingerprintError(
            f"{kind.__module__}.{kind.__qualname__} is not defined in a module of the project tree "
            f"{root}"
        )
    declared: Mapping[str, Any] = candidate.fingerprint()
    return sha256_bytes(
        canonical(
            {
                "declared": declared,
                "class": f"{kind.__module__}.{kind.__qualname__}",
                "modules": closure,
            }
        )
    )
