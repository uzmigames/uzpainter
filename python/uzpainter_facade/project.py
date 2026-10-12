"""`substance_painter.project` over the native project store (`python/FACADE.md` §2).

The calls are synchronous here; the asynchronous lifecycle, events and the busy state are
phase1.21_pyapi-dispatcher-lifecycle. A project file keeps the path the script gives it
(`probe.spp` reads back as `probe.spp`, `textureset-project-readback` s13). Opening a project
checks its declared colour configuration against the pinned profiles (`colour.PROFILES`) before
anything is evaluated. Saving drops the content effects of groups first, as Painter's save and
reopen does (`nodes.drop_group_content_effects`).
"""

from __future__ import annotations

from typing import Any

import uzpainter

from uzpainter_facade import colour, nodes
from uzpainter_facade.state import SESSION

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

# Settings the native project does not take yet, with the task that owns each.
SETTING_GAPS = {
    "default_save_path": "phase1.21_pyapi-dispatcher-lifecycle",
    "export_path": "phase1.21_pyapi-dispatcher-lifecycle",
    "mesh_settings": "phase3.1_assets3d-cutover",
    "auto_unwrap_settings": "phase4.5_uv-tiles",
}


def create(
    mesh_file_path: str,
    mesh_map_file_paths: list[str] | None = None,
    template_file_path: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Create a project from a mesh."""
    if mesh_map_file_paths:
        raise uzpainter.NotYetSupported(
            "create(mesh_map_file_paths=...) is a release gap: bind mesh maps with "
            "TextureSet.set_mesh_map_resource after importing them "
            "(phase1.21_pyapi-dispatcher-lifecycle)"
        )
    if template_file_path is not None:
        raise uzpainter.NotYetSupported(
            "create(template_file_path=...) is a release gap: projects use the default template "
            "(phase1.21_pyapi-dispatcher-lifecycle)"
        )
    settings = settings or Settings()
    for name, owner in SETTING_GAPS.items():
        if getattr(settings, name) is not None:
            raise uzpainter.NotYetSupported(f"Settings.{name} is a release gap ({owner})")
    _p.create(
        mesh_file_path,
        _p.Settings(
            normal_map_format=settings.normal_map_format,
            tangent_space_mode=settings.tangent_space_mode,
            project_workflow=settings.project_workflow,
            default_texture_resolution=settings.default_texture_resolution,
            mesh_unit_scale=settings.mesh_unit_scale,
            import_cameras=settings.import_cameras,
        ),
    )
    SESSION.project_started()


def open(project_file_path: str) -> None:
    """Open a project."""
    _p.open(project_file_path)
    SESSION.project_started()
    try:
        colour.require_supported_configuration()
    except uzpainter.NotYetSupported:
        _p.close()
        SESSION.reset()
        raise


def close() -> None:
    """Close the current project."""
    _p.close()
    SESSION.reset()


def is_open() -> bool:
    return bool(_p.is_open())


def save(mode: Any = ProjectSaveMode.Incremental) -> None:
    nodes.drop_group_content_effects()
    _p.save(mode)
    SESSION.dirty = False


def save_as(project_file_path: str, mode: Any = ProjectSaveMode.Incremental) -> None:
    nodes.drop_group_content_effects()
    _p.save_as(project_file_path, mode)
    SESSION.dirty = False


def save_as_copy(backup_file_path: str, mode: Any = ProjectSaveMode.Incremental) -> None:
    nodes.drop_group_content_effects()
    _p.save_as_copy(backup_file_path, mode)


def needs_saving() -> bool:
    return bool(_p.needs_saving()) or SESSION.dirty


def file_path() -> str | None:
    path = _p.file_path()
    return None if path is None else str(path)


def name() -> str | None:
    return str(_p.name())


def get_uuid() -> Any:
    return _p.get_uuid()


def last_imported_mesh_path() -> str:
    return str(_p.last_imported_mesh_path())
