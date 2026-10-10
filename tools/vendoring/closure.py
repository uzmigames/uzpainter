"""Include closure of a C/C++ file set (`13-engine-integration.md` §2.2, check (b) of §3.1).

The closure follows every `#include` directive textually (preprocessor conditions are not
evaluated, so every branch counts) through a list of include directories to a fixed point, and
adds the `.cpp` beside every reached header. Lookup is case-insensitive, as on Windows, the only
platform the vendored code is built for.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*([<"])([^>"\r\n]+)[>"]', re.MULTILINE)
HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx", ".inl")
SOURCE_SUFFIX = ".cpp"


@dataclass(frozen=True, order=True)
class Include:
    """One `#include` directive: the including file (root-relative, `/`-separated) and its text."""

    source: str
    spelling: str
    angled: bool


@dataclass(frozen=True)
class ClosureResult:
    """Files reached, includes that resolve to no file under the root, and includes not followed."""

    files: frozenset[str]
    unresolved: tuple[Include, ...]
    cut: tuple[Include, ...]


def index_tree(root: Path) -> dict[str, str]:
    """Map the lower-cased root-relative path of every file under `root` to its real spelling."""
    index: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            index[rel.lower()] = rel
    return index


def parse_includes(text: str, source: str) -> list[Include]:
    """Return the `#include` directives of a file in order of appearance."""
    return [
        Include(source=source, spelling=m.group(2).strip(), angled=m.group(1) == "<")
        for m in INCLUDE_RE.finditer(text)
    ]


def _lookup(index: dict[str, str], directory: str, spelling: str) -> str | None:
    candidate = (
        posixpath.normpath(posixpath.join(directory, spelling))
        if directory
        else (posixpath.normpath(spelling))
    )
    if candidate.startswith("../") or candidate == ".." or posixpath.isabs(candidate):
        return None
    return index.get(candidate.lower())


def resolve_include(
    index: dict[str, str], include: Include, include_dirs: Sequence[str]
) -> str | None:
    """Resolve an include like the compiler: the includer's folder first for quoted includes,
    then each include directory in order. Returns the root-relative path or None."""
    search: list[str] = []
    if not include.angled:
        search.append(posixpath.dirname(include.source))
    search.extend("" if d in ("", ".") else d for d in include_dirs)
    for directory in search:
        found = _lookup(index, directory, include.spelling)
        if found is not None:
            return found
    return None


def paired_source(index: dict[str, str], header: str) -> str | None:
    """The `.cpp` with the same stem in the same folder as `header`, if it exists."""
    stem, suffix = posixpath.splitext(header)
    if suffix.lower() not in HEADER_SUFFIXES:
        return None
    return index.get((stem + SOURCE_SUFFIX).lower())


def compute_closure(
    root: Path,
    seeds: Iterable[str],
    include_dirs: Sequence[str],
    cuts: Collection[tuple[str, str]] = (),
    header_only: Collection[str] = (),
    pair_sources: bool = True,
) -> ClosureResult:
    """Compute the include closure of `seeds` under `root`.

    `cuts` holds `(source, spelling)` pairs that are not followed (includes a recorded local
    modification removes). `header_only` lists headers whose `.cpp` is deliberately not added;
    `pair_sources=False` adds no `.cpp` at all (headers-only selections).
    Seeds missing under `root` raise `FileNotFoundError`.
    """
    index = index_tree(root)
    cut_set = set(cuts)
    header_only_set = {h.lower() for h in header_only}
    reached: set[str] = set()
    pending: list[str] = []
    for seed in seeds:
        real = index.get(seed.lower())
        if real is None:
            raise FileNotFoundError(f"seed {seed} not found under {root}")
        if real not in reached:
            reached.add(real)
            pending.append(real)

    unresolved: set[Include] = set()
    cut: set[Include] = set()
    while pending:
        current = pending.pop()
        found: list[str] = []
        text = (root / current).read_text(encoding="utf-8", errors="replace")
        for include in parse_includes(text, current):
            if (include.source, include.spelling) in cut_set:
                cut.add(include)
                continue
            target = resolve_include(index, include, include_dirs)
            if target is None:
                unresolved.add(include)
            else:
                found.append(target)
        if pair_sources and current.lower() not in header_only_set:
            source = paired_source(index, current)
            if source is not None:
                found.append(source)
        for target in found:
            if target not in reached:
                reached.add(target)
                pending.append(target)

    return ClosureResult(
        files=frozenset(reached), unresolved=tuple(sorted(unresolved)), cut=tuple(sorted(cut))
    )
