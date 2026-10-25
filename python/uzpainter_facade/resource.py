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

Search (phase3.1_proc-backend-seam item 2.4, decision 324): `search(query)` answers from
UzPainter's own asset library only (`src/procedural/asset_library.h`), never with an invented
Painter result. `s:uzpainter` lists the library by UzPainter names; a Painter shelf (or none) is
answered only for an exact name `n:<name>=` that the library's internal alias table maps to a
certified (exact) asset, and raises `UnsupportedProcedural` for any other Painter name. A result
is an `AssetResource`: its identifier is `resource://uzasset/<family>/<id>?version=<version>`
(the pinned `uzasset://<family>/<id>@<version>`), its GUI name the UzPainter name, and
`provenance()` its provenance record. Any other query form, and a shelf the script added, is a
release gap.

Resource reload and shelves (phase1.21, decision 110):
- `reload_modified_resources_async(filter)` delivers `ReloadResourcesStarted(filter)` before it
  returns True, then reloads on a worker thread and delivers `ReloadResourcesEnded(filter,
  reloaded_resources, resource_errors)` (Tier 0 `phase1-reload-resources`). A resource is modified
  when the bytes of the file it was imported from match none of the versions its name holds; the
  reload imports them as a new version under the same name and leaves every binding as it was
  ("this does not update the resources currently used in the project document"). The recorded
  alias controls retain distinct origins during the session; aliases restored with the same
  current version share the saved origin. Repeated reloads report the latest imported version
  as `old`, including after reopening (`p22b-reload-order-*`).
- Shelves are folders of user files the script adds (`Shelves.add`). `refresh` crawls the folder
  on a worker thread between `ShelfCrawlingStarted` and `ShelfCrawlingEnded`. The application and
  user shelves, whose Painter names are unrecorded, and the resources of a shelf are release gaps.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import uzpainter

from uzpainter_facade import event
from uzpainter_facade.state import (
    RESOURCE_KEY,
    RESOURCE_METADATA,
    RESOURCE_ORIGIN_KEY,
    SESSION,
    edits,
    one_transaction,
)

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
            # Painter's refusal (`p22b-host-resources` s13: an empty scheme names nothing).
            raise ValueError(
                f"Invalid resource URL scheme {parts.scheme}. Only 'resource' scheme is allowed."
            )
        if parts.netloc == "uzasset":
            native = uzpainter.resource.ResourceID.from_url(url)
            return cls(native.context, native.name, native.version)
        versions = parse_qs(parts.query).get("version")
        return cls(parts.netloc, parts.path.lstrip("/"), versions[0] if versions else None)

    def url(self) -> str:
        """The resource URL."""
        if self.context == "uzasset":
            return str(uzpainter.resource.ResourceID(self.context, self.name, self.version).url())
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


class ObservedResourceID(ResourceID):
    """The ResourceID a Painter recording observed for a snapshot source (decision 361): its
    parts and URL exactly as recorded. Provenance only: no call that resolves, imports, binds,
    searches or replaces a resource accepts it (`to_native` refuses it)."""

    __slots__ = ("_url",)

    def __init__(self, native: Any) -> None:
        super().__init__(str(native.context), str(native.name), str(native.version))
        self._url = str(native.url())

    def url(self) -> str:
        """The URL the recording observed, never rebuilt from the parts."""
        return self._url


def refuse_observed(identifier: Any) -> None:
    if isinstance(identifier, ObservedResourceID):
        raise ValueError(
            "an observed Painter ResourceID is provenance only: it cannot resolve, import, bind, "
            "search or replace a resource"
        )


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
    it has one. `ResourceNotFoundError`, whose message is the identifier's URL as Painter's
    (`p22b-host-resources` s14), when the project holds no such resource."""
    if isinstance(identifier, Resource):
        identifier = identifier.identifier()
    if not isinstance(identifier, ResourceID):
        raise TypeError("the resource must be a resource.ResourceID")
    refuse_observed(identifier)
    known = facts()
    for native in uzpainter.resource.list_project_resources():
        if native.name != identifier.name:
            continue
        fact = known.get(native.version)
        if identifier.version is None or (fact and f"{fact[0]}.image" == identifier.version):
            return native
    raise uzpainter.ResourceNotFoundError(identifier.url())


# Chronological imports survive the native catalog's hash ordering and project reopen.
IMPORT_ORDER_KEY = "resource_import_order"


def reload_origins() -> dict[str, str]:
    """`{sha256: file}`: the shared origin restored when the project is reopened. The last
    import among names still holding that version supplies it; a name that advances to another
    version no longer supplies the old content's origin. Idempotent imports change nothing
    (`p22b-host-resources`: after reopen, s20 reloads `checker` and `checker-reload`, imported
    with equal bytes from two files, from the second file). Saved with the project."""
    value = uzpainter.project.Metadata(RESOURCE_METADATA).get(RESOURCE_ORIGIN_KEY)
    return dict(value) if isinstance(value, dict) else {}


def import_order() -> list[list[str]]:
    """`[name, sha256, file]` in import order, persisted in the import's transaction."""
    value = uzpainter.project.Metadata(RESOURCE_METADATA).get(IMPORT_ORDER_KEY)
    return list(value) if isinstance(value, list) else []


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PROCEDURAL_USAGES = (Usage.GENERATOR, Usage.SMART_MATERIAL)


# ── Module functions ────────────────────────────────────────────────────────────────────────────


@edits
def import_project_resource(
    file_path: str, resource_usage: Any, name: str | None = None, group: str | None = None
) -> Resource:
    """Import a resource into the current project."""
    if Path(file_path).suffix.lower() == ".sbsar":
        # Refused natively before the file is read: UnsupportedProcedural, reason "no runtime".
        uzpainter.resource.import_project_resource(file_path, resource_usage, name, group)
    try:
        data = Path(file_path).read_bytes()
    except OSError as error:
        raise uzpainter.ResourceNotFoundError(f"cannot read {file_path}: {error}") from error
    if resource_usage in PROCEDURAL_USAGES and data.startswith(PNG_SIGNATURE):
        # A bitmap is no procedural resource: Painter refuses it before any change
        # (`p22b-host-resources` s6-s7). Other files of these usages stay NotYetSupported.
        usage = resource_usage.name.lower().replace("_", "")
        raise ValueError(f"Resource '{file_path}' is incompatible with usage '{usage}'.")
    sha1 = hashlib.sha1(data).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    colour = len(data) > 25 and data[25] in (2, 6)  # PNG IHDR colour type: RGB or RGBA
    held = {(n.name, n.version) for n in uzpainter.resource.list_project_resources()}
    with one_transaction("resource.import_project_resource"):
        native = uzpainter.resource.import_project_resource(file_path, resource_usage, name, group)
        metadata = uzpainter.project.Metadata(RESOURCE_METADATA)
        known = facts()
        if known.get(sha256) != [sha1, colour]:
            known[sha256] = [sha1, colour]
            metadata.set(RESOURCE_KEY, known)
        identifier = native.identifier()
        if (identifier.name, identifier.version) not in held:
            order = import_order()
            order.append([identifier.name, identifier.version, file_path])
            metadata.set(IMPORT_ORDER_KEY, order)
            latest = {name: version for name, version, _ in order}
            origins = reload_origins()
            for _, version, _ in order:
                origins.pop(version, None)
            for name, version, origin in order:
                if latest[name] == version:
                    origins[version] = origin
            metadata.set(RESOURCE_ORIGIN_KEY, origins)
    return Resource(from_native(native.identifier()), resource_usage)


def list_project_resources() -> list[ResourceID]:
    """The resources used in the current project, as Painter documents them: those the layer
    stacks and mesh maps bind, and the environment map. An imported resource nothing uses is not
    listed (`p22b-host-resources` s9 and s31); the native `uzpainter.resource
    .list_project_resources` still holds every import. `ProjectError` with Painter's message
    while no project is open (s27)."""
    if not uzpainter.project.is_open():
        raise uzpainter.ProjectError("No project loaded.")
    natives = list(uzpainter.resource.list_used_resources())
    environment = uzpainter.display.get_environment_resource()
    if environment is not None:
        natives.append(environment)
    used: dict[tuple[str, str], Any] = {}
    for native in natives:
        used.setdefault((native.name, native.version), native)
    return [from_native(native) for native in used.values()]


@edits
def update_layer_stack_resource(old_resource_id: Any, new_resource: Any) -> list[Any]:
    """Replace a resource in the layer stacks and mesh maps; returns the identifiers of the
    resources replaced, as Painter documents and returns them (`phase1-resource-update` s12: the
    identifier given, once, when a binding used it). A mesh map bound to it then binds the new
    resource under its name (`phase1-mesh-map-update` s9-s11, both recordings), in the same
    transaction as the layer stacks; a mesh map bound to another name of the same bytes keeps it,
    and replacing a resource by itself replaces nothing (`p22b-mesh-map-alias-update` s8-s11,
    both recordings)."""
    from uzpainter_facade import textureset  # it imports this module

    old, new = to_native(old_resource_id), to_native(new_resource)
    if (old.name, old.version) == (new.name, new.version):
        return []
    with one_transaction("resource.update_layer_stack_resource"):
        mesh_maps = textureset.replace_mesh_map_resource(old, new_resource)
        changed = uzpainter.resource.update_layer_stack_resource(old, new)
    return [old_resource_id] if changed or mesh_maps else []


def show_resources_in_ui(resources: Any) -> None:
    raise uzpainter.UnsupportedInUzPainter(
        "substance_painter.resource.show_resources_in_ui",
        "it highlights resources in Painter's assets window, which changes no texture, render or "
        "script-visible state, and UzPainter has no desktop UI",
        "resource.list_project_resources() to enumerate them",
    )


# ── Search over the asset library (decision 324) ────────────────────────────────────────────────

ASSET_CONTEXT = "uzasset"
# The terms of a query: runs of characters or backslash escapes, separated by unescaped blanks.
_QUERY_TERM = re.compile(r"(?:\\.|[^\s\\])+|\\$")
_ESCAPE = re.compile(r"\\(.)")


class AssetResource(Resource):
    """A resource of UzPainter's asset library, pinned at one version, with its provenance."""

    __slots__ = ("_record",)

    def __init__(self, record: dict[str, Any]) -> None:
        identifier = ResourceID(
            ASSET_CONTEXT, f"{record['family']}/{record['id']}", str(record["version"])
        )
        super().__init__(identifier, record["usage"])
        self._record = record

    def gui_name(self) -> str:
        return str(self._record["name"])

    def usages(self) -> list[Any]:
        member = getattr(Usage, str(self._usage), None)
        if member is None:
            raise uzpainter.NotYetSupported(
                f"resource.Usage.{self._usage} is a release gap (phase3.3_procedural-families)"
            )
        return [member]

    def asset_url(self) -> str:
        """The pinned `uzasset://<family>/<id>@<version>` URL a project stores."""
        return str(self._record["url"])

    def parity_status(self) -> str:
        """`exact`, `calibrated` or `unavailable` (05-procedural-content.md §3)."""
        return str(self._record["status"])

    def provenance(self) -> dict[str, Any]:
        """The asset's provenance record (public sources, author, domain, corpus, parity)."""
        return dict(self._record["provenance"])

    def __repr__(self) -> str:
        return f"AssetResource({self._record['url']!r})"


def search(query: str) -> list[Resource]:
    """List the resources that match `query`: only what UzPainter's asset library holds."""
    if not isinstance(query, str):
        raise TypeError("the query must be a str")
    for term in _QUERY_TERM.findall(query):
        shelf = _ESCAPE.sub(r"\1", term[2:]) if term.startswith("s:") else None
        if shelf is not None and shelf in _SHELVES:
            raise uzpainter.NotYetSupported(
                f"resource.search of the shelf {shelf!r} is a release gap ({SHELF_GAP})"
            )
    return [AssetResource(record) for record in uzpainter.resource._search_assets(query)]


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


PROJECT_CONTEXT = re.compile(r"^project\d+$")
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
        latest = {name: version for name, version, _ in import_order()}
        natives = [n for n in natives if n.version == latest.get(n.name, n.version)]
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
            if (
                isinstance(identifier, ResourceID)
                and PROJECT_CONTEXT.match(identifier.context)
                and identifier.context != SESSION.context()
            ):
                # The context of a closed project is gone (`p22b-host-resources` r2 s22, s24).
                problems.append(f"For resource {identifier.url()}, context not found.")
                continue
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
    returned = threading.Event()
    try:
        candidates = _candidates(resource_filter)
        context = SESSION.context()
        event.emit_sync(event.ReloadResourcesStarted(resource_filter))
        uzpainter.event.hold()
        worker = threading.Thread(
            target=_reload_resources,
            args=(resource_filter, candidates, context, returned),
            name="uzpainter-reload-resources",
            daemon=True,
        )
        worker.start()
        if not candidates:
            # Nothing to reload: the operation is over when the call returns, and its end is
            # still delivered after it (`p22b-host-resources` s19 and s21, both recordings).
            _RELOAD["running"] = False
    except BaseException:
        _RELOAD["running"] = False
        raise
    finally:
        returned.set()
    return True


def _reload_resources(
    resource_filter: Any, candidates: list[Any], context: str, returned: threading.Event
) -> None:
    """The reload's worker: once the starting call returned, one import per modified resource,
    then `ReloadResourcesEnded`, which Painter never delivers during that call (its recordings
    have no step marker on it, whatever the filter)."""
    reloaded: list[event.ReloadedResourceResult] = []
    errors: list[event.ReloadedResourceError] = []
    returned.wait()
    try:
        versions: dict[str, set[str]] = {}
        for native in uzpainter.resource.list_project_resources():
            versions.setdefault(native.name, set()).add(native.version)
        # Within a session, names imported from distinct files keep distinct origins. Only
        # contents restored from a saved project share its captured canonical origin.
        origins = SESSION.opened_resource_origins
        ranks = {(name, version): i for i, (name, version, _) in enumerate(import_order())}
        latest: dict[tuple[str, str], Any] = {}
        for native in candidates:
            origin = origins.get(native.version) or uzpainter.resource.resource_origin(native)
            if origin is None:
                continue
            key = (native.name, origin)
            previous = latest.get(key)
            # Native enumeration is hash-ordered, not chronological. Each file reload starts
            # from its last imported version, including after save/reopen and prior reloads.
            if previous is None or ranks.get((native.name, native.version), -1) > ranks.get(
                (previous.name, previous.version), -1
            ):
                latest[key] = native
        for (_, origin), native in latest.items():
            old = from_native(native, context)
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


@contextlib.contextmanager
def _call_returning() -> Iterator[threading.Event]:
    """An event set once the public call that starts crawls is returning: a walk starts after
    it, so `ShelfCrawlingEnded` is never delivered during that call, as in every Painter
    recording (`phase1-shelves` s3 and s9, `p22b-host-resources` s16 and s17)."""
    returned = threading.Event()
    try:
        yield returned
    finally:
        returned.set()


def _crawl(name: str, returned: threading.Event) -> None:
    """Walks a shelf's folder on a worker thread between the crawling events:
    `ShelfCrawlingStarted` is delivered before the call that starts the crawl returns, and
    `ShelfCrawlingEnded` once the walk, which starts after that call returned, is done
    (`phase1-shelves` s3 and s9, both recordings; decision 319)."""
    shelf = _SHELVES[name]
    shelf["crawling"] = True
    event.emit_sync(event.ShelfCrawlingStarted(name))
    uzpainter.event.hold()

    def walk() -> None:
        returned.wait()
        try:
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
        with _call_returning() as returned:
            _crawl(self._name, returned)

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
        with _call_returning() as returned:
            _crawl(name, returned)  # a new shelf crawls its folder, as Painter's does (P21-D s3)
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
        with _call_returning() as returned:
            for name in list(_SHELVES):
                _crawl(name, returned)

    @staticmethod
    def remove(name: str) -> None:
        if uzpainter.project.is_open():
            # Painter's refusal while a project is open (`p22b-host-resources` s18).
            raise uzpainter.ProjectError("The project is loaded.")
        if name not in _SHELVES:
            raise ValueError(f"the shelf {name!r} doesn't exist")
        del _SHELVES[name]


for _shelf_cls in (*FILTERS, Shelf, Shelves):
    _shelf_cls.__module__ = MODULE
