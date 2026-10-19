"""A process-wide fence over held-out roots while a fitter runs (decision 303 §1).

While a fence is up, a Python audit hook (`sys.addaudithook`, PEP 578) refuses:

- every file-system event naming a path under a fenced root (opening, listing, renaming,
  removing, changing modes, linking, copying), so a fitter can neither read nor change the
  held-out set, the private store or earlier reports;
- every way of leaving the interpreter's file events: starting a process, loading a native
  library through `ctypes` and clearing the audit hooks.

The hook raises `HeldOutAccessError`, which is not an `OSError`, so code that treats a missing
file as "unavailable" does not swallow it, and it records every refused event; the fitting
session refuses its candidate when any event was refused, even when the fitter caught the error.

Limit: native code that is already loaded can still reach the files without an audit event;
the fence covers what a Python fitter can do, not a hostile native extension.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Audit events (https://docs.python.org/3/library/audit_events.html) whose path arguments are
# checked against the fenced roots.
PATH_EVENTS = frozenset(
    {
        "open",
        "os.chdir",
        "os.chflags",
        "os.chmod",
        "os.chown",
        "os.getxattr",
        "os.link",
        "os.listdir",
        "os.listxattr",
        "os.mkdir",
        "os.remove",
        "os.removexattr",
        "os.rename",
        "os.rmdir",
        "os.scandir",
        "os.setxattr",
        "os.symlink",
        "os.truncate",
        "os.utime",
        "shutil.chown",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
        "shutil.make_archive",
        "shutil.move",
        "shutil.rmtree",
        "shutil.unpack_archive",
    }
)
# Events refused outright while a fence is up: each one leaves the reach of the path checks.
BLOCKED_EVENTS = frozenset(
    {
        "_winapi.CreateProcess",
        "ctypes.dlopen",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.system",
        "pty.spawn",
        "subprocess.Popen",
        "sys._clear_audit_hooks",
    }
)


class HeldOutAccessError(RuntimeError):
    """A fenced root was reached while a fitter ran."""


@dataclass
class Fence:
    """One active fence: its normalised roots and the events it refused."""

    label: str
    roots: tuple[str, ...]
    refused: list[str] = field(default_factory=list)


_lock = threading.Lock()
_fences: list[Fence] = []
_installed = False
_inside = threading.local()


def _normalise(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _paths(args: tuple[Any, ...]) -> Iterator[str]:
    for argument in args:
        if isinstance(argument, str | bytes | os.PathLike):
            try:
                yield os.fsdecode(argument)
            except (TypeError, ValueError):
                continue


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not _fences or getattr(_inside, "active", False):
        return
    blocked = event in BLOCKED_EVENTS
    if not blocked and event not in PATH_EVENTS:
        return
    _inside.active = True
    try:
        with _lock:
            fences = list(_fences)
        if not fences:
            return
        if blocked:
            message = f"{event} is refused while a fitter runs"
            for fence in fences:
                fence.refused.append(message)
            raise HeldOutAccessError(f"{fences[0].label}: {message}")
        for raw in _paths(args):
            path = _normalise(raw)
            hits = [fence for fence in fences if any(_under(path, root) for root in fence.roots)]
            if hits:
                message = f"{event} on {raw} reaches a fenced root"
                for fence in hits:
                    fence.refused.append(message)
                raise HeldOutAccessError(f"{hits[0].label}: {message}")
    finally:
        _inside.active = False


def _install() -> None:
    global _installed
    with _lock:
        if not _installed:
            sys.addaudithook(_hook)
            _installed = True


@contextmanager
def fenced(roots: Iterable[Path], label: str) -> Iterator[Fence]:
    """Refuse every access to `roots` (and every process start) until the block ends."""
    fence = Fence(label, tuple(sorted({_normalise(str(root)) for root in roots})))
    if not fence.roots:
        raise ValueError("a fence needs at least one root")
    _install()
    with _lock:
        _fences.append(fence)
    try:
        yield fence
    finally:
        with _lock:
            _fences.remove(fence)
