"""Painter's documented `substance_painter.project` module: the facade over the native `uzpainter`
module (projects; the asynchronous lifecycle is phase1.21). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.project import (
    Metadata,
    NormalMapFormat,
    ProjectSaveMode,
    ProjectWorkflow,
    Settings,
    TangentSpace,
    close,
    create,
    file_path,
    get_uuid,
    is_open,
    last_imported_mesh_path,
    name,
    needs_saving,
    open,
    save,
    save_as,
    save_as_copy,
)

__all__ = [
    "Metadata",
    "NormalMapFormat",
    "ProjectSaveMode",
    "ProjectWorkflow",
    "Settings",
    "TangentSpace",
    "close",
    "create",
    "file_path",
    "get_uuid",
    "is_open",
    "last_imported_mesh_path",
    "name",
    "needs_saving",
    "open",
    "save",
    "save_as",
    "save_as_copy",
]
