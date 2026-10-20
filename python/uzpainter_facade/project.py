"""`substance_painter.project` over the native project store (`python/FACADE.md` §2, §9).

Painter's asynchronous host (task phase1.21_pyapi-dispatcher-lifecycle, decision 109; `host.py`):

- `create` and `open` load the project with `is_busy()` true, then deliver, on the dispatcher
  thread and in Tier 0 `lifecycle-events` order, `BusyStatusChanged(True)` ->
  `BusyStatusChanged(False)` -> `ProjectCreated`/`ProjectOpened` -> `ProjectEditionEntered`, and
  return once the project is in edition: Painter's recorded polls see it ready right after the
  call, 4 times out of 4. `ProjectEditionEntered` is queued and delivered after the call
  returns, as Painter delivers it from its event loop (no P21-F or P21-G recording delivers it
  during the call; decision 319).
- `create(mesh_map_file_paths=...)` imports each `<texture set>_<suffix>` file and binds it to its
  usage, for the seven suffixes P21-A records (`MESH_MAP_SUFFIXES`, decision 319).
- `close` delivers `ProjectEditionLeft` -> `BusyStatusChanged(True)` -> `ProjectAboutToClose` ->
  `ProjectClosed` -> `BusyStatusChanged(False)`, and discards what was not saved, as Painter does
  ("any unsaved data will be lost"): the project returns to its last save before it closes, so
  reopening it gives the saved content. The native API keeps its durable close (decision 105).
- The saves deliver `ProjectAboutToSave(file_path)` -> `ProjectSaved` and are refused with
  `ProjectError` while busy, as Painter documents.
- `reload_mesh` returns at once; a worker thread delivers `ProjectEditionLeft` ->
  `BusyStatusChanged(True)` -> `BusyStatusChanged(False)` -> `ProjectEditionEntered`, then calls
  `loading_status_cb(ReloadMeshStatus)` on the dispatcher thread (a callback, not an event). A file
  that does not exist gives only `ReloadMeshStatus.ERROR` (Tier 0 `phase1-reload-mesh`).

A project file keeps the path the script gives it (`probe.spp` reads back as `probe.spp`,
`textureset-project-readback` s13). `create` takes its colour management from the environment at
the call, as Painter documents (`colour.creation_ocio_config_hash`, decision 207). Opening a
project checks its declared colour configuration against the pinned profiles (`colour.PROFILES`)
before anything is evaluated. Saving drops the content effects of groups first, as Painter's save
and reopen does (`nodes.drop_group_content_effects`).
"""

from __future__ import annotations

import enum
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import uzpainter

from uzpainter_facade import colour, event, host, nodes
from uzpainter_facade.state import SESSION, unsaved

MODULE = "substance_painter.project"
_p = uzpainter.project

NormalMapFormat = _p.NormalMapFormat
TangentSpace = _p.TangentSpace
ProjectWorkflow = _p.ProjectWorkflow
ProjectSaveMode = _p.ProjectSaveMode
Metadata = _p.Metadata


class Settings:
    """Project configuration options. Options left to None use Painter's defaults."""

    __slots__ = (
        "auto_unwrap_settings",
        "default_save_path",
        "default_texture_resolution",
        "export_path",
        "import_cameras",
        "mesh_settings",
        "mesh_unit_scale",
        "normal_map_format",
        "project_workflow",
        "tangent_space_mode",
    )

    def __init__(
        self,
        default_save_path: str | None = None,
        normal_map_format: Any = None,
        tangent_space_mode: Any = None,
        project_workflow: Any = None,
        export_path: str | None = None,
        default_texture_resolution: int | None = None,
        import_cameras: bool | None = None,
        mesh_unit_scale: float | None = None,
        mesh_settings: Any = None,
        auto_unwrap_settings: Any = None,
    ) -> None:
        self.default_save_path = default_save_path
        self.normal_map_format = normal_map_format
        self.tangent_space_mode = tangent_space_mode
        self.project_workflow = project_workflow
        self.export_path = export_path
        self.default_texture_resolution = default_texture_resolution
        self.import_cameras = import_cameras
        self.mesh_unit_scale = mesh_unit_scale
        self.mesh_settings = mesh_settings
        self.auto_unwrap_settings = auto_unwrap_settings

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={getattr(self, name)!r}" for name in sorted(self.__slots__))
        return f"Settings({fields})"


Settings.__module__ = MODULE

# Settings the native project does not take yet, with what settles each (decision 110).
# `default_save_path` and `export_path` are taken and change nothing a documented call reads, as
# Painter's P21-B recordings show (decision 319): `get_default_export_path`, an export without
# `exportPath`, `save()` of the untitled project and `file_path()` are as without them.
SETTING_GAPS = {
    "mesh_settings": "phase3.1_assets3d-cutover",
    "auto_unwrap_settings": "phase4.5_uv-tiles",
}

# The mesh-map files `create` binds, by the suffix of their name `<texture set>_<suffix>`: the
# seven Painter's P21-A recordings bind (decision 319). Any other name is unrecorded.
MESH_MAP_SUFFIXES = {
    "ambient_occlusion": "AO",
    "curvature": "Curvature",
    "id": "ID",
    "normal_base": "Normal",
    "position": "Position",
    "thickness": "Thickness",
    "world_space_normals": "WorldSpaceNormal",
}


def mesh_map_binding(path: str) -> tuple[str, str]:
    """The texture set name and the `MeshMapUsage` name a mesh-map file of `create` binds, from
    its file name; any other file raises `NotYetSupported` before anything changes."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for suffix in sorted(MESH_MAP_SUFFIXES, key=len, reverse=True):
        texture_set = stem[: -len(suffix) - 1]
        if stem.endswith("_" + suffix) and texture_set:
            if not os.path.isfile(path):
                raise uzpainter.NotYetSupported(
                    f"create(mesh_map_file_paths=[{path!r}]): the file does not exist, and what "
                    "Painter does then is unrecorded (recording P21-A, decision 319)"
                )
            return texture_set, MESH_MAP_SUFFIXES[suffix]
    raise uzpainter.NotYetSupported(
        f"create(mesh_map_file_paths=[{path!r}]): Painter's binding of this file name is "
        "unrecorded; recording P21-A binds `<texture set>_<suffix>` for the suffixes "
        f"{', '.join(sorted(MESH_MAP_SUFFIXES))} (decision 319)"
    )


def bind_mesh_maps(bindings: list[tuple[str, str, str]]) -> None:
    """Imports each mesh-map file as a project resource named by its file and binds it to its
    texture set's usage (P21-A); a name that matches no texture set raises `NotYetSupported`."""
    if not bindings:
        return
    from uzpainter_facade import resource, textureset

    sets = {ts.name(): ts for ts in textureset.all_texture_sets()}
    for path, set_name, _ in bindings:
        if set_name not in sets:
            raise uzpainter.NotYetSupported(
                f"create(mesh_map_file_paths=[{path!r}]): no texture set is named {set_name!r}, "
                "and what Painter does then is unrecorded (recording P21-A, decision 319)"
            )
    for path, set_name, usage in bindings:
        imported = resource.import_project_resource(path, resource.Usage.TEXTURE)
        sets[set_name].set_mesh_map_resource(
            getattr(textureset.MeshMapUsage, usage), imported.identifier()
        )


def template_id(template_file_path: str) -> str:
    """The installed template that reproduces the Painter template `template_file_path` names
    (decision 116): the one whose shipped file has that file name, exactly. The file must exist;
    UzPainter never reads it. Any other template raises `NotYetSupported` before anything
    changes: a custom template's content is not something UzPainter can know."""
    name = template_file_path.replace("\\", "/").rsplit("/", 1)[-1]
    for installed in _p.templates():
        shipped = installed["painter_template"]
        if shipped is not None and shipped.rsplit("/", 1)[-1] == name:
            if not os.path.isfile(template_file_path):
                raise uzpainter.NotYetSupported(
                    f"create(template_file_path={template_file_path!r}): the file does not exist, "
                    "and what Painter does then is unrecorded (recording P24-A, decision 116)"
                )
            return str(installed["id"])
    raise uzpainter.NotYetSupported(
        f"create(template_file_path={template_file_path!r}): only the project templates shipped "
        "with Painter 12.1 are reproduced, by file name; a custom template is a release gap "
        "(decision 116)"
    )


def create(
    mesh_file_path: str,
    mesh_map_file_paths: list[str] | None = None,
    template_file_path: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Create a project from a mesh; returns once it is in edition."""
    bindings = [(path, *mesh_map_binding(path)) for path in mesh_map_file_paths or []]
    template = None if template_file_path is None else template_id(template_file_path)
    settings = settings or Settings()
    for name, owner in SETTING_GAPS.items():
        if getattr(settings, name) is not None:
            raise uzpainter.NotYetSupported(f"Settings.{name} is a release gap ({owner})")
    if _p.is_open():
        raise uzpainter.ProjectError("a project is already open")
    ocio_config_hash = colour.creation_ocio_config_hash()
    native = _p.Settings(
        normal_map_format=settings.normal_map_format,
        tangent_space_mode=settings.tangent_space_mode,
        project_workflow=settings.project_workflow,
        default_texture_resolution=settings.default_texture_resolution,
        mesh_unit_scale=settings.mesh_unit_scale,
        import_cameras=settings.import_cameras,
        template=template,
        ocio_config_hash=ocio_config_hash,
    )
    with host.busy_section():
        _p.create(mesh_file_path, native)
        SESSION.project_started()
        try:
            bind_mesh_maps(bindings)
        except uzpainter.NotYetSupported:
            _p.close()
            SESSION.reset()
            raise
    event.emit_sync(event.ProjectCreated())
    host.enter_edition()


def open(project_file_path: str) -> None:
    """Open a project; returns once it is in edition."""
    if _p.is_open():
        raise uzpainter.ProjectError("a project is already open")
    with host.busy_section():
        _p.open(project_file_path)
        SESSION.project_started()
        try:
            colour.require_supported_configuration()
        except uzpainter.NotYetSupported:
            _p.close()
            SESSION.reset()
            raise
    event.emit_sync(event.ProjectOpened())
    host.enter_edition()


def close() -> None:
    """Close the current project; what was not saved is lost."""
    if not _p.is_open():
        raise uzpainter.ProjectError("no project is open")
    if host.is_busy():
        raise uzpainter.ProjectError("the project cannot be closed while UzPainter is busy")
    job = uzpainter.jobs.busy()
    if job is not None:
        raise uzpainter.BusyError(job, f"close() is refused while job {job} is running")
    host.set_edition(False)
    with host.busy_section():
        event.emit_sync(event.ProjectAboutToClose())
        discard_unsaved()
        _p.close()
        SESSION.reset()
        event.emit_sync(event.ProjectClosed())


def discard_unsaved() -> None:
    """Returns a saved project to its last save (Painter's close loses unsaved data): one revert
    to the last named checkpoint, marked as the saved state, so the file reopens as it was saved
    with needs_saving() false. An untitled project's folder is removed by the native close."""
    if _p.file_path() is None:
        return
    checkpoints = _p.checkpoints()
    named = checkpoints["named"]
    if named is None or checkpoints["current"] == named:
        return
    _p.revert(int(named))
    _p.save(ProjectSaveMode.Incremental)


def is_busy() -> bool:
    """Whether UzPainter is busy: a project is loading or closing, a mesh is reloading or an
    export runs. An explicit export finishes while engine computations are disabled (R10,
    decision 319), so none waits deferred."""
    return host.is_busy()


def is_in_edition_state() -> bool:
    """Whether the current project is ready to work with."""
    return host.is_in_edition_state()


def execute_when_not_busy(callback: Callable[[], None]) -> None:
    """Execute `callback` on the dispatcher thread when UzPainter is not busy."""
    host.execute_when_not_busy(callback)


def is_open() -> bool:
    return bool(_p.is_open())


def _check_save() -> None:
    if host.is_busy():
        raise uzpainter.ProjectError("the project cannot be saved while UzPainter is busy")


def save(mode: Any = ProjectSaveMode.Incremental) -> None:
    _check_save()
    path = _p.file_path()
    if path is None:
        event.emit_sync(event.ProjectAboutToSave(""))
        raise uzpainter.ProjectError("Failed to save project")
    event.emit_sync(event.ProjectAboutToSave(str(path)))
    nodes.drop_group_content_effects()
    _p.save(mode)
    SESSION.saved()
    event.emit_sync(event.ProjectSaved())


def save_as(project_file_path: str, mode: Any = ProjectSaveMode.Incremental) -> None:
    _check_save()
    _p.file_path()  # ProjectError when no project is open
    event.emit_sync(event.ProjectAboutToSave(project_file_path))
    nodes.drop_group_content_effects()
    _p._save_as_replace(project_file_path, mode)
    SESSION.saved()
    event.emit_sync(event.ProjectSaved())


def save_as_copy(backup_file_path: str, mode: Any = ProjectSaveMode.Incremental) -> None:
    _check_save()
    _p.file_path()
    event.emit_sync(event.ProjectAboutToSave(backup_file_path))
    nodes.drop_group_content_effects()
    _p.save_as_copy(backup_file_path, mode)
    event.emit_sync(event.ProjectSaved())


def needs_saving() -> bool:
    return unsaved()


def file_path() -> str | None:
    path = _p.file_path()
    return None if path is None else str(path)


def name() -> str | None:
    return str(_p.name())


def get_uuid() -> Any:
    return _p.get_uuid()


def last_imported_mesh_path() -> str:
    return str(_p.last_imported_mesh_path())


# ── Mesh reload ─────────────────────────────────────────────────────────────────────────────────


class ReloadMeshStatus(enum.Enum):
    """Reload mesh status, used in mesh reload asynchronous callback."""

    SUCCESS = 0
    ERROR = 2


class MeshReloadingSettings:
    """Settings used when reloading a mesh.

    `preserve_strokes` is accepted and has nothing to act on: UzPainter has no brush strokes and
    exposes no stroke symbol (owner Q5, decision 019)."""

    __slots__ = ("_preserve_strokes", "auto_unwrap_settings", "import_cameras", "mesh_settings")

    def __init__(
        self,
        import_cameras: bool = True,
        preserve_strokes: bool = True,
        mesh_settings: Any = None,
        auto_unwrap_settings: Any = None,
    ) -> None:
        self.import_cameras = import_cameras
        self._preserve_strokes = preserve_strokes
        self.mesh_settings = mesh_settings
        self.auto_unwrap_settings = auto_unwrap_settings

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{name.lstrip('_')}={getattr(self, name)!r}" for name in sorted(self.__slots__)
        )
        return f"MeshReloadingSettings({fields})"


for _cls in (ReloadMeshStatus, MeshReloadingSettings):
    _cls.__module__ = MODULE


def reload_mesh(
    mesh_file_path: str,
    settings: MeshReloadingSettings,
    loading_status_cb: Callable[[ReloadMeshStatus], Any],
) -> None:
    """Import a new mesh into the current project; returns at once and calls
    `loading_status_cb` on the dispatcher thread when the reload attempt is finished."""
    if not isinstance(settings, MeshReloadingSettings):
        raise TypeError("settings must be a project.MeshReloadingSettings")
    if settings.mesh_settings is not None:
        raise uzpainter.NotYetSupported(
            "MeshReloadingSettings.mesh_settings is a release gap "
            f"({SETTING_GAPS['mesh_settings']})"
        )
    if settings.auto_unwrap_settings is not None:
        raise uzpainter.NotYetSupported(
            "MeshReloadingSettings.auto_unwrap_settings is a release gap "
            f"({SETTING_GAPS['auto_unwrap_settings']})"
        )
    if not _p.is_open():
        raise uzpainter.ProjectError("no project is open")
    if host.is_busy():
        raise uzpainter.ProjectError("a mesh cannot be reloaded while UzPainter is busy")
    uzpainter.event.hold()
    worker = threading.Thread(
        target=_reload,
        args=(mesh_file_path, bool(settings.import_cameras), loading_status_cb),
        name="uzpainter-reload-mesh",
        daemon=True,
    )
    try:
        worker.start()
    except BaseException:
        uzpainter.event.release()
        raise


def _reload(path: str, import_cameras: bool, callback: Callable[[ReloadMeshStatus], Any]) -> None:
    """The reload's worker: the transitions, the native reload, then the callback."""
    try:
        if not os.path.isfile(path):
            print(f"[ERROR] reload_mesh: {path} does not exist", file=sys.stderr)
            event.call_sync(callback, ReloadMeshStatus.ERROR)
            return
        host.set_edition(False)
        status = ReloadMeshStatus.SUCCESS
        with host.busy_section():
            try:
                _p.reload_mesh(path, import_cameras=import_cameras)
                SESSION.dirty = True
                SESSION.rename_run = None
            except Exception as error:  # reported through the status, as Painter
                print(f"[ERROR] reload_mesh: {type(error).__name__}: {error}", file=sys.stderr)
                status = ReloadMeshStatus.ERROR
        host.set_edition(True)
        event.call_sync(callback, status)
    finally:
        uzpainter.event.release()
