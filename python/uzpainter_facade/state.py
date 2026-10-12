"""The facade's per-interpreter state (`python/FACADE.md` §3).

Painter keeps some script-visible state outside the project: the session counter behind resource
contexts (`project<N>`), the layer selection, the selection type of each layer and the UI mode.
They are inert: nothing in evaluation or export reads them. They live here, per open project, and
are cleared whenever a project is created, opened or closed; none is saved.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable, Iterator
from typing import Any

import uzpainter

# The project Metadata context holding the SHA-1 of each imported resource (keyed by its SHA-256),
# from which Painter's resource version `<sha1>.image` is rebuilt after save and reopen.
RESOURCE_METADATA = "uzpainter.facade"
RESOURCE_KEY = "resource_sha1"


class Session:
    """The facade state of this interpreter."""

    def __init__(self) -> None:
        self.projects = -1  # index of the current project among those created or opened
        self.scoped = 0  # depth of open `layerstack.ScopedModification` blocks
        self.dirty = False
        self.reset()

    def reset(self) -> None:
        """Forgets the per-project state (a project was created, opened or closed)."""
        # An edit call since the last save, even one that left every value as it was: Painter
        # then reports the project as needing saving (`textureset-project-readback` s12 after
        # reopen: re-binding the same mesh map), where the native store sees no new revision.
        self.dirty = False
        self.selection: dict[tuple[int, int], list[int]] = {}
        self.selection_type: dict[int, Any] = {}
        self.ui_mode: Any = None
        # The context of the ResourceID last bound per binding key, in this session only
        # (Painter keeps the identifier it was given until the project is reloaded).
        self.bound_context: dict[tuple[Any, ...], str] = {}

    def project_started(self) -> None:
        self.projects += 1
        self.reset()

    def context(self) -> str:
        """Painter's resource context of the current project: `project<N>`."""
        return f"project{max(self.projects, 0)}"


SESSION = Session()


def edits[F: Callable[..., Any]](function: F) -> F:
    """Marks an edit call: once it returns, the project needs saving as Painter reports it."""

    @functools.wraps(function)
    def call(*args: Any, **kwargs: Any) -> Any:
        result = function(*args, **kwargs)
        SESSION.dirty = True
        return result

    return call  # type: ignore[return-value]


@contextlib.contextmanager
def one_transaction(name: str) -> Iterator[None]:
    """One native transaction around several native calls, so a facade call commits one revision
    (10 §5); inside an open native `Transaction` the calls join it."""
    block = uzpainter.Transaction(name)
    try:
        block.__enter__()
    except RuntimeError as error:
        if "already open" not in str(error):
            raise
        yield  # a native Transaction is open on this thread: the calls join it
        return
    try:
        yield
    except BaseException as error:
        block.__exit__(type(error), error, error.__traceback__)
        raise
    block.__exit__(None, None, None)
