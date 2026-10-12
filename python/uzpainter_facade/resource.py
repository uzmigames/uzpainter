"""`substance_painter.resource`: Painter-shaped resource ids over the native project resources
(10 §4; decision 107; `python/FACADE.md` §5).

Painter names a project resource `resource://project<N>/<name>?version=<sha1>.image`:
- `project<N>` is the session's N-th project created or opened (`state.Session.context`);
- the version is the SHA-1 of the imported file and `.image` (Tier 0 `fill-layer-readback` s16,
  `mask-stack` s7, `textureset-project-readback` s3-s4: equal to the SHA-1 of each fixture).

The native resource is named by its name and SHA-256. The facade computes the SHA-1 when it
imports a file and keeps it in the project Metadata context `uzpainter.facade` (key
`resource_sha1`), written in the same native transaction as the import, so the version survives
save and reopen. A binding keeps, for this session, the context of the identifier it was given
(Painter's `textureset-project-readback` s11 after reopen); a reopened project's resources read
back in the new context.

Resource reload and shelves (phase1.21, decision 110):
- `reload_modified_resources_async(filter)` delivers `ReloadResourcesStarted(filter)` before it
  returns True, then reloads on a worker thread and delivers `ReloadResourcesEnded(filter,
  reloaded_resources, resource_errors)` (Tier 0 `phase1-reload-resources`). A resource is modified
  when the bytes of the file it was imported from match none of the versions its name holds; the
  reload imports them as a new version under the same name and leaves every binding as it was
  ("this does not update the resources currently used in the project document"). Painter also
  reported a reload of unchanged bytes after save and reopen; that residual is named in decision
  110, not reproduced.
- Shelves are folders of user files the script adds (`Shelves.add`). `refresh` crawls the folder
  on a worker thread between `ShelfCrawlingStarted` and `ShelfCrawlingEnded`. The application and
  user shelves, whose Painter names are unrecorded, and the resources of a shelf are release gaps.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import uzpainter

from uzpainter_facade import event
from uzpainter_facade.state import RESOURCE_KEY, RESOURCE_METADATA, SESSION, edits, one_transaction

MODULE = "substance_painter.resource"
Usage = uzpainter.resource.Usage


class ResourceID:
    """An identifier of a resource: its context, name and version."""

    __slots__ = ("context", "name", "version")

    def __init__(self, context: str, name: str, version: str | None = None) -> None:
        self.context = context
        self.name = name
        self.version = version

    @classmethod
    def from_project(cls, name: str, version: str | None = None) -> ResourceID:
        """A ResourceID for a resource located in the current project."""
        return cls(SESSION.context(), name, version)

    @classmethod
    def from_url(cls, url: str) -> ResourceID:
        """A ResourceID from its `resource://context/name?version=...` URL."""
        parts = urlsplit(url)
        if parts.scheme != "resource":
            raise ValueError(f"'{url}' is not a resource:// URL")
        versions = parse_qs(parts.query).get("version")
        return cls(parts.netloc, parts.path.lstrip("/"), versions[0] if versions else None)

    def url(self) -> str:
        """The resource URL."""
        query = f"?version={self.version}" if self.version else ""
        return f"resource://{self.context}/{self.name}{query}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ResourceID) and (
            self.context,
            self.name,
            self.version,
        ) == (other.context, other.name, other.version)

    def __hash__(self) -> int:
        return hash((self.context, self.name, self.version))

    def __repr__(self) -> str:
        return f"ResourceID(context={self.context!r}, name={self.name!r}, version={self.version!r})"


class Resource:
    """A resource of the project."""

    __slots__ = ("_id", "_usage")

    def __init__(self, identifier: ResourceID, usage: Any) -> None:
        self._id = identifier
        self._usage = usage

    def identifier(self) -> ResourceID:
        return self._id

    def gui_name(self) -> str:
        return self._id.name

    def usages(self) -> list[Any]:
        return [self._usage]

    def show_in_ui(self) -> None:
        raise uzpainter.UnsupportedInUzPainter(
            "substance_painter.resource.Resource.show_in_ui",
            "it highlights a resource in Painter's assets window, which changes no texture, "
            "render or script-visible state, and UzPainter has no desktop UI",
            "Resource.identifier() to address the resource",
        )

    def __repr__(self) -> str:
        return f"Resource({self._id!r})"


for _cls in (ResourceID, Resource):
    _cls.__module__ = MODULE


# ── Native <-> facade identifiers ───────────────────────────────────────────────────────────────


def facts() -> dict[str, list[Any]]:
    """`{sha256: [sha1, colour image]}` of the resources the facade imported into the project."""
    value = uzpainter.project.Metadata(RESOURCE_METADATA).get(RESOURCE_KEY)
    return dict(value) if isinstance(value, dict) else {}


def version_of(sha256: str) -> str | None:
    """Painter's version of the resource stored under `sha256`, when the facade imported it."""
    fact = facts().get(sha256)
    return f"{fact[0]}.image" if fact else None


def is_colour_image(sha256: str) -> bool:
    """Whether the resource stored under `sha256` is an RGB or RGBA image."""
    fact = facts().get(sha256)
    return bool(fact and fact[1])


def from_native(native: Any, context: str | None = None) -> ResourceID:
    """The facade identifier of a native project resource id."""
    return ResourceID(context or SESSION.context(), native.name, version_of(native.version))


def to_native(identifier: Any) -> Any:
    """The native resource id a facade identifier names: by name, and by Painter's version when
    it has one. `ResourceNotFoundError` when the project holds no such resource."""
    if isinstance(identifier, Resource):
        identifier = identifier.identifier()
    if not isinstance(identifier, ResourceID):
        raise TypeError("the resource must be a resource.ResourceID")
    known = facts()
    for native in uzpainter.resource.list_project_resources():
        if native.name != identifier.name:
            continue
        fact = known.get(native.version)
        if identifier.version is None or (fact and f"{fact[0]}.image" == identifier.version):
            return native
    raise uzpainter.ResourceNotFoundError(f"no project resource {identifier.url()}")


# ── Module functions ────────────────────────────────────────────────────────────────────────────


@edits
def import_project_resource(
    file_path: str, resource_usage: Any, name: str | None = None, group: str | None = None
) -> Resource:
    """Import a resource into the current project."""
    try:
        data = Path(file_path).read_bytes()
    except OSError as error:
        raise uzpainter.ResourceNotFoundError(f"cannot read {file_path}: {error}") from error
    sha1 = hashlib.sha1(data).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    colour = len(data) > 25 and data[25] in (2, 6)  # PNG IHDR colour type: RGB or RGBA
    with one_transaction("resource.import_project_resource"):
        native = uzpainter.resource.import_project_resource(file_path, resource_usage, name, group)
        known = facts()
        if known.get(sha256) != [sha1, colour]:
            known[sha256] = [sha1, colour]
            uzpainter.project.Metadata(RESOURCE_METADATA).set(RESOURCE_KEY, known)
    return Resource(from_native(native.identifier()), resource_usage)


def list_project_resources() -> list[ResourceID]:
    """The resources of the current project."""
    return [from_native(native) for native in uzpainter.resource.list_project_resources()]


@edits
def update_layer_stack_resource(old_resource_id: Any, new_resource: Any) -> list[Any]:
    """Replace a resource in the layer stacks and mesh maps; returns the identifiers of the
    resources replaced, as Painter documents and returns them (`phase1-resource-update` s12: the
    identifier given, once, when a binding used it)."""
    changed = uzpainter.resource.update_layer_stack_resource(
        to_native(old_resource_id), to_native(new_resource)
    )
    return [old_resource_id] if changed else []


def show_resources_in_ui(resources: Any) -> None:
    raise uzpainter.UnsupportedInUzPainter(
        "substance_painter.resource.show_resources_in_ui",
        "it highlights resources in Painter's assets window, which changes no texture, render or "
        "script-visible state, and UzPainter has no desktop UI",
        "resource.list_project_resources() to enumerate them",
    )


# ── Resource reload ─────────────────────────────────────────────────────────────────────────────


class AllResourcesFilter:
    """Filter used to reload all modified resources known to UzPainter."""


class ProjectFilter:
    """Filter used to reload modified resources contained in the project context."""


class ResourcesListFilter:
    """Filter used to reload modified resources amongst a given list of resources."""

    def __init__(self, resources: list[ResourceID]) -> None:
        self.resources = list(resources)


class ResourcesUsedByProjectFilter:
    """Filter used to reload modified resources currently in use by the project."""


class SessionFilter:
    """Filter used to reload modified resources contained in the session."""


class ShelvesListFilter:
    """Filter used to reload modified resources contained in designated shelves."""

    def __init__(self, shelves: list[Any]) -> None:
        self.shelves = list(shelves)


FILTERS = (
    AllResourcesFilter,
    ProjectFilter,
    ResourcesListFilter,
    ResourcesUsedByProjectFilter,
    SessionFilter,
    ShelvesListFilter,
)
_RELOAD = {"running": False}
_RELOAD_LOCK = threading.Lock()


def is_reload_modified_resources_running() -> bool:
    """Whether a reload modified resources operation is currently running."""
    return _RELOAD["running"]


def _candidates(resource_filter: Any) -> list[Any]:
    """The imported project resources `resource_filter` names (the mesh is reloaded by
    `project.reload_mesh`; session and shelf resources are not project resources, and UzPainter
    holds none to reload)."""
    if not uzpainter.project.is_open():
        return []
    if isinstance(resource_filter, (AllResourcesFilter, ProjectFilter)):
        natives = list(uzpainter.resource.list_project_resources())
    elif isinstance(resource_filter, ResourcesUsedByProjectFilter):
        natives = list(uzpainter.resource.list_used_resources())
    elif isinstance(resource_filter, ResourcesListFilter):
        natives = [to_native(identifier) for identifier in resource_filter.resources]
    else:
        return []
    imported = facts()
    return [native for native in natives if native.version in imported]


def reload_modified_resources_async(resource_filter: Any) -> bool:
    """Reload the modified resources the filter names; False when a reload already runs."""
    if not isinstance(resource_filter, FILTERS):
        raise ValueError("the resource filter is not of a known type")
    if isinstance(resource_filter, ResourcesListFilter):
        problems = []
        for identifier in resource_filter.resources:
            try:
                to_native(identifier)
            except (TypeError, uzpainter.ResourceNotFoundError) as error:
                problems.append(str(error))
        if problems:
            raise ValueError(problems)
    with _RELOAD_LOCK:
        if _RELOAD["running"]:
            return False
        _RELOAD["running"] = True
    try:
        candidates = _candidates(resource_filter)
        context = SESSION.context()
        event.emit_sync(event.ReloadResourcesStarted(resource_filter))
        uzpainter.event.hold()
        worker = threading.Thread(
            target=_reload_resources,
            args=(resource_filter, candidates, context),
            name="uzpainter-reload-resources",
            daemon=True,
        )
        worker.start()
    except BaseException:
        _RELOAD["running"] = False
        raise
    return True


def _reload_resources(resource_filter: Any, candidates: list[Any], context: str) -> None:
    """The reload's worker: one import per modified resource, then `ReloadResourcesEnded`."""
    reloaded: list[event.ReloadedResourceResult] = []
    errors: list[event.ReloadedResourceError] = []
    try:
        versions: dict[str, set[str]] = {}
        for native in uzpainter.resource.list_project_resources():
            versions.setdefault(native.name, set()).add(native.version)
        seen: set[tuple[str, str]] = set()
        for native in candidates:
            old = from_native(native, context)
            origin = uzpainter.resource.resource_origin(native)
            if origin is None or (native.name, origin) in seen:
                continue
            seen.add((native.name, origin))
            try:
                data = Path(origin).read_bytes()
            except OSError as error:
                errors.append(event.ReloadedResourceError(old, f"cannot read {origin}: {error}"))
                continue
            if hashlib.sha256(data).hexdigest() in versions.get(native.name, set()):
                continue
            try:
                new = import_project_resource(origin, Usage.TEXTURE, native.name)
            except Exception as error:  # reported in the event, as Painter
                errors.append(event.ReloadedResourceError(old, f"{type(error).__name__}: {error}"))
                continue
            reloaded.append(event.ReloadedResourceResult(old, new.identifier()))
    finally:
        _RELOAD["running"] = False
        try:
            event.emit_sync(event.ReloadResourcesEnded(resource_filter, reloaded, errors))
        finally:
            uzpainter.event.release()


# ── Shelves ─────────────────────────────────────────────────────────────────────────────────────

SHELF_NAME = re.compile(r"^[a-z0-9_-]+$")
SHELF_GAP = "phase3.3_procedural-families: shelf resources are procedural content"
# Shelves the script added: name -> {"path": folder, "crawling": bool}.
_SHELVES: dict[str, dict[str, Any]] = {}


def _crawl(name: str) -> None:
    """Walks a shelf's folder on a worker thread between the crawling events."""
    shelf = _SHELVES[name]
    shelf["crawling"] = True
    uzpainter.event.hold()

    def walk() -> None:
        try:
            event.emit_sync(event.ShelfCrawlingStarted(name))
            shelf["files"] = sorted(
                os.path.relpath(os.path.join(folder, file), shelf["path"])
                for folder, _, files in os.walk(shelf["path"])
                for file in files
            )
        finally:
            shelf["crawling"] = False
            try:
                event.emit_sync(event.ShelfCrawlingEnded(name))
            finally:
                uzpainter.event.release()

    try:
        threading.Thread(target=walk, name=f"uzpainter-shelf-{name}", daemon=True).start()
    except BaseException:
        shelf["crawling"] = False
        uzpainter.event.release()
        raise


class Shelf:
    """A shelf of resources, identified by a unique name."""

    __slots__ = ("_name",)

    def __init__(self, _name: str) -> None:
        self._name = _name

    def name(self) -> str:
        return self._name

    def path(self) -> str:
        if self._name not in _SHELVES:
            raise ValueError(f"the shelf {self._name!r} doesn't exist")
        return str(_SHELVES[self._name]["path"])

    def is_crawling(self) -> bool:
        return bool(self._name in _SHELVES and _SHELVES[self._name]["crawling"])

    def refresh(self) -> None:
        """Forces discovering of resources in the shelf's folder."""
        if self._name not in _SHELVES:
            raise ValueError(f"the shelf {self._name!r} doesn't exist")
        _crawl(self._name)

    def can_import_resources(self) -> bool:
        raise uzpainter.NotYetSupported(
            f"Shelf.can_import_resources is a release gap ({SHELF_GAP})"
        )

    def import_resource(self, *args: Any, **kwargs: Any) -> Resource:
        raise uzpainter.NotYetSupported(f"Shelf.import_resource is a release gap ({SHELF_GAP})")

    def resources(self, query: str = "") -> list[Resource]:
        raise uzpainter.NotYetSupported(f"Shelf.resources is a release gap ({SHELF_GAP})")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Shelf) and other._name == self._name

    def __hash__(self) -> int:
        return hash(self._name)

    def __repr__(self) -> str:
        return f"Shelf({self._name!r})"


class Shelves:
    """Collection of static methods to manipulate shelves."""

    @staticmethod
    def add(name: str, path: str) -> Shelf:
        """Add a shelf of the folder `path` for this session."""
        if not isinstance(name, str) or not SHELF_NAME.match(name):
            raise ValueError(
                f"invalid shelf name {name!r}: lowercase letters, numbers, underscores or hyphens"
            )
        if name in _SHELVES:
            raise ValueError(f"a shelf named {name!r} already exists")
        if not os.path.isdir(path):
            raise ValueError(f"the shelf folder {path!r} does not exist")
        _SHELVES[name] = {"path": os.path.abspath(path), "crawling": False, "files": []}
        return Shelf(name)

    @staticmethod
    def all() -> list[Shelf]:
        return [Shelf(name) for name in _SHELVES]

    @staticmethod
    def application_shelf() -> Shelf:
        raise uzpainter.NotYetSupported(
            "Shelves.application_shelf is a release gap: Painter's shelf names are unrecorded "
            "(recording P21-D, decision 110)"
        )

    @staticmethod
    def user_shelf() -> Shelf:
        raise uzpainter.NotYetSupported(
            "Shelves.user_shelf is a release gap: Painter's shelf names are unrecorded "
            "(recording P21-D, decision 110)"
        )

    @staticmethod
    def exists(name: str) -> bool:
        return name in _SHELVES

    @staticmethod
    def refresh_all() -> None:
        for name in list(_SHELVES):
            _crawl(name)

    @staticmethod
    def remove(name: str) -> None:
        if uzpainter.project.is_open():
            raise uzpainter.ProjectError("a shelf cannot be removed while a project is open")
        if name not in _SHELVES:
            raise ValueError(f"the shelf {name!r} doesn't exist")
        del _SHELVES[name]


for _shelf_cls in (*FILTERS, Shelf, Shelves):
    _shelf_cls.__module__ = MODULE
