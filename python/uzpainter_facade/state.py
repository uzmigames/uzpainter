"""The facade's per-interpreter state (`python/FACADE.md` §3).

Painter keeps some script-visible state outside the project: the session counter behind resource
contexts (`project<N>`), the layer selection, the selection type of each layer and the UI mode.
They are inert: nothing in evaluation or export reads them. They live here, per open project, and
are cleared whenever a project is created, opened or closed (a created or opened project then
selects its top root layer, `Session.project_started`); none is saved.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
from collections.abc import Callable, Iterator
from typing import Any

import uzpainter

# The project Metadata context holding the SHA-1 of each imported resource (keyed by its SHA-256),
# from which Painter's resource version `<sha1>.image` is rebuilt after save and reopen.
RESOURCE_METADATA = "uzpainter.facade"
RESOURCE_KEY = "resource_sha1"


@dataclasses.dataclass
class RenameRun:
    """Consecutive `set_name` calls on one node with no other edit between them: Painter merges
    them into one edit, which is none once the name is back to where the run started."""

    uid: int
    start_name: str
    unsaved_before: bool  # needs_saving() before the run's first rename
    revision: int  # the native revision after the run's last rename


class Session:
    """The facade state of this interpreter."""

    def __init__(self) -> None:
        self.projects = -1  # index of the current project among those created or opened
        self.scopes: list[str] = []  # names of the open `layerstack.ScopedModification` blocks
        self.dirty = False
        self.reset()

    def reset(self) -> None:
        """Forgets the per-project state (a project was created, opened or closed)."""
        # An edit call since the last save, even one that left every value as it was: Painter
        # then reports the project as needing saving (`textureset-project-readback` s12 after
        # reopen: re-binding the same mesh map), where the native store sees no new revision.
        self.dirty = False
        # The native revision at which the project is as saved although the store counts
        # revisions since the save: a rename run that ended on its start name (`set_name`).
        self.clean_revision: int | None = None
        self.rename_run: RenameRun | None = None
        self.selection: dict[tuple[int, int], list[int]] = {}
        self.selection_type: dict[int, Any] = {}
        self.ui_mode: Any = None
        # The context of the ResourceID last bound per binding key, in this session only
        # (Painter keeps the identifier it was given until the project is reloaded).
        self.bound_context: dict[tuple[Any, ...], str] = {}

    def project_started(self) -> None:
        """A project was created or opened: Painter then selects the top root layer of the active
        stack (`phase1-layer-navigation` s88 after save and reopen; after creation, Painter's
        default paint layer, which UzPainter does not create yet: phase4.1_nodes-paint-layers)."""
        self.projects += 1
        self.reset()
        stack = uzpainter.textureset.get_active_stack()
        roots = uzpainter.layerstack.get_root_layer_nodes(stack)
        if roots:
            self.selection = {(int(stack.material().uid()), int(stack.uid())): [roots[0].uid()]}

    def saved(self) -> None:
        """The project was saved: nothing is left to save."""
        self.dirty = False
        self.clean_revision = None
        self.rename_run = None

    def context(self) -> str:
        """Painter's resource context of the current project: `project<N>`."""
        return f"project{max(self.projects, 0)}"


SESSION = Session()


def unsaved() -> bool:
    """Painter's `project.needs_saving()`: an edit call since the last save, or a native revision
    since it that no merged rename run brought back to the saved state."""
    if SESSION.dirty:
        return True
    project = uzpainter.project
    return bool(project.needs_saving()) and project.revision() != SESSION.clean_revision


def edits[F: Callable[..., Any]](function: F) -> F:
    """Marks an edit call: once it returns, the project needs saving as Painter reports it."""

    @functools.wraps(function)
    def call(*args: Any, **kwargs: Any) -> Any:
        result = function(*args, **kwargs)
        SESSION.dirty = True
        SESSION.rename_run = None
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
