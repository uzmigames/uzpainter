"""Path roots: `--roots project=<dir>;mesh=<dir>;bake_mesh=<dir>;resource=<dir>;export=<dir>`
(11-mcp-server.md §5; task phase2.5_mcp-transport-registry, decision 158).

The roots are an allowlist for the structured tools. A tool's schema names the root of each path
argument with the extension keyword `x-uzpainter-root` on a string property, or
`x-uzpainter-paths {member: root}` on an object (or its JSON text) whose members are paths. Each
such path is canonicalised before admission:

1. a `file:` URI becomes its Windows path, a `\\\\?\\` prefix is dropped and forward slashes
   become backslashes;
2. a relative path (also a drive-relative `E:x` or a root-relative `\\x`) is taken under the root of
   its operation;
3. the lexical form is checked first, so a path that names another drive or share is refused without
   touching the filesystem (no lookup reaches an untrusted UNC host);
4. reparse points (symbolic links, junctions) are resolved with `os.path.realpath`, and the
   resolved path is checked again: it must lie inside its root (compared case-insensitively, as
   Windows does).

The canonical absolute path is what the worker receives. A refusal names the argument and its root
kind, never the path given or the path it resolved to. A root kind that `--roots` does not name
refuses every path of that kind. Without `--roots` nothing is confined.

Results never reference a path outside the roots: `scrub` replaces the string value of every
path-valued field (`PATH_KEYS`) that is an absolute path or a `file:` URI outside every root with
`OUTSIDE`. Roots are policy for the structured tools; they do not sandbox `run_python` (§6).
"""

from __future__ import annotations

import ntpath
import os
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

KINDS = ("project", "mesh", "bake_mesh", "resource", "export")
ROOT_KEYWORD = "x-uzpainter-root"
PATHS_KEYWORD = "x-uzpainter-paths"
OUTSIDE = "<outside the roots>"
# The result fields whose string value is a path (worker results, receipts, supervisor_status).
PATH_KEYS = frozenset(
    {
        "path",
        "directory",
        "receipt",
        "project",
        "project_path",
        "mesh_path",
        "output_root",
        "exportPath",
        "ledger",
        "crash_dir",
        "minidump",
    }
)


class RootsError(ValueError):
    """A malformed `--roots` value."""


class PathRefused(Exception):
    """A path argument outside its root; the message never contains the path."""

    def __init__(self, pointer: str, root: str, reason: str) -> None:
        super().__init__(f"{pointer}: {reason}")
        self.pointer = pointer
        self.root = root
        self.reason = reason


def _plain(value: str) -> str:
    """`value` with a `file:` URI turned into a path, no `\\\\?\\` prefix and backslashes."""
    if value[:5].lower() == "file:":
        parsed = urllib.parse.urlparse(value)
        path = urllib.request.url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path = "\\\\" + parsed.netloc + path
        value = path
    value = value.replace("/", "\\")
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return value


def _inside(path: str, root: str) -> bool:
    """Whether the absolute `path` is `root` or lies under it (case-insensitive, lexical)."""
    path, root = ntpath.normcase(path), ntpath.normcase(root)
    if ntpath.splitdrive(path)[0] != ntpath.splitdrive(root)[0]:
        return False
    try:
        return ntpath.commonpath([path, root]) == root
    except ValueError:
        return False


@dataclass(frozen=True)
class Roots:
    """The canonical root of each kind `--roots` named."""

    roots: dict[str, str]

    @staticmethod
    def parse(text: str) -> Roots:
        """`kind=<dir>;...`: each kind at most once, each folder existing; `RootsError`."""
        roots: dict[str, str] = {}
        for item in text.split(";"):
            if not item.strip():
                continue
            kind, sep, folder = item.partition("=")
            kind = kind.strip()
            if not sep or not folder.strip():
                raise RootsError(f"--roots entry {kind or item!r} needs <kind>=<folder>")
            if kind not in KINDS:
                raise RootsError(f"--roots names an unknown root kind {kind!r} (one of {KINDS})")
            if kind in roots:
                raise RootsError(f"--roots names the {kind} root twice")
            plain = _plain(folder.strip())
            if not ntpath.isabs(plain):
                raise RootsError(f"the {kind} root must be an absolute folder")
            canonical = os.path.realpath(plain)
            if not os.path.isdir(canonical):
                raise RootsError(f"the {kind} root is not an existing folder")
            roots[kind] = canonical
        if not roots:
            raise RootsError("--roots names no root")
        return Roots(roots)

    def contains(self, path: str) -> bool:
        """Whether the absolute `path` lies inside one of the roots."""
        return any(_inside(path, root) for root in self.roots.values())

    def canonical(self, value: str, kind: str, pointer: str) -> str:
        """The canonical absolute form of the path argument `value` (at `pointer`) of root `kind`;
        `PathRefused` when it lies outside that root. Touches the filesystem: run it off the event
        loop."""
        root = self.roots.get(kind)
        if root is None:
            raise PathRefused(pointer, kind, f"no {kind} root is configured (--roots)")
        plain = _plain(value)
        if "\x00" in plain:
            raise PathRefused(pointer, kind, "the path is malformed")
        if not ntpath.isabs(plain):
            plain = ntpath.join(root, plain)
        lexical = ntpath.normpath(plain)
        if not _inside(lexical, root):
            raise PathRefused(pointer, kind, f"the path lies outside the {kind} root")
        resolved = os.path.realpath(lexical)
        if not _inside(resolved, root):
            raise PathRefused(pointer, kind, f"the path resolves outside the {kind} root")
        return resolved

    def scrub(self, value: Any) -> Any:
        """`value` with every path-valued field outside the roots replaced by `OUTSIDE`."""
        if isinstance(value, dict):
            return {
                key: OUTSIDE
                if key in PATH_KEYS and isinstance(item, str) and self._outside(item)
                else self.scrub(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        return value

    def _outside(self, value: str) -> bool:
        plain = _plain(value)
        if not ntpath.isabs(plain):
            return False  # a relative path names nothing outside by itself
        return not self.contains(ntpath.normpath(plain))


def path_arguments(schema: dict[str, Any], value: Any, pointer: str = "") -> Iterator[PathArgument]:
    """The path arguments of `value` (validated against `schema`) and their root kinds."""
    if not isinstance(schema, dict):
        return
    root = schema.get(ROOT_KEYWORD)
    if isinstance(root, str) and isinstance(value, str):
        yield PathArgument(pointer or "/", root, None)
    members = schema.get(PATHS_KEYWORD)
    if isinstance(members, dict):
        yield PathArgument(pointer or "/", "", {str(k): str(v) for k, v in members.items()})
    if isinstance(value, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, item in value.items():
                if name in properties:
                    yield from path_arguments(properties[name], item, f"{pointer}/{name}")
    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                yield from path_arguments(items, item, f"{pointer}/{index}")


@dataclass(frozen=True)
class PathArgument:
    """A path argument at `pointer` of root `root`, or (`members`) an object or JSON text whose
    named members are paths."""

    pointer: str
    root: str
    members: dict[str, str] | None
