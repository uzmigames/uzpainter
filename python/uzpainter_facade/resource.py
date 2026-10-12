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
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import uzpainter

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
    """Replace a resource in the layer stack; returns the nodes that changed."""
    from uzpainter_facade.nodes import wrap

    changed = uzpainter.resource.update_layer_stack_resource(
        to_native(old_resource_id), to_native(new_resource)
    )
    return [wrap(node) for node in changed]


def show_resources_in_ui(resources: Any) -> None:
    raise uzpainter.UnsupportedInUzPainter(
        "substance_painter.resource.show_resources_in_ui",
        "it highlights resources in Painter's assets window, which changes no texture, render or "
        "script-visible state, and UzPainter has no desktop UI",
        "resource.list_project_resources() to enumerate them",
    )
