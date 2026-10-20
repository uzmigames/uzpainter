"""`substance_painter.export`: Painter's texture export over the native export job
(`python/FACADE.md` §2; decision 105 §5).

`export_project_textures(json_config)` writes Painter's flat layout: the native export publishes a
generation with its receipt under `exportPath` and copies its files into `exportPath` under their
fixed names (`fixed_names=[exportPath]`). It returns Painter's `TextureExportResult`: status
Success, the message Painter writes ("Export successfully finished", `export-ocio-encode-legacy`
probes s50-s51) and the files per (texture set, stack). Before anything is evaluated it checks the
colour profile (`colour.require_supported_configuration`) and that no fill reads an unrecorded
default source (`nodes.check_exportable`); a failure raises, as Painter documents.

The observed R10 export emits `ExportTexturesAboutToStart(textures)` before becoming busy,
then `ExportTexturesEnded(status, message, textures)` before clearing busy. Explicit synchronous
exports finish even while engine computations remain disabled; deferred background jobs stay paused.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Any

import uzpainter

from uzpainter_facade import colour, event, host, nodes

MODULE = "substance_painter.export"


class ExportStatus(enum.Enum):
    """Status code of the export process."""

    Success = 0
    Cancelled = 1
    Warning = 2
    Error = 3


class TextureExportResult:
    """Result of the export textures process."""

    __slots__ = ("message", "status", "textures")

    def __init__(
        self, status: ExportStatus, message: str, textures: dict[tuple[str, str], list[str]]
    ) -> None:
        self.status = status
        self.message = message
        self.textures = textures

    def __repr__(self) -> str:
        return f"TextureExportResult({self.status}, {self.message!r}, {self.textures!r})"


for _cls in (ExportStatus, TextureExportResult):
    _cls.__module__ = MODULE


def get_default_export_path() -> str:
    """Return Painter's observed default under this host's Documents folder (decision 320)."""
    documents = Path(uzpainter.export._default_export_path()).parents[1]
    return (documents / "Adobe" / "Adobe Substance 3D Painter" / "export").as_posix()


def list_project_textures(json_config: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """The textures an export of `json_config` would write."""
    listed: dict[tuple[str, str], list[str]] = uzpainter.export.list_project_textures(json_config)
    return listed


def export_project_textures(json_config: dict[str, Any]) -> TextureExportResult:
    """Export the project's textures as `json_config` describes; raises on failure."""
    colour.require_supported_configuration()
    nodes.check_exportable()
    if "exportPath" not in json_config:
        raise ValueError("at /exportPath: Expected a string value")
    textures = list_project_textures(json_config)
    event.emit_sync(event.ExportTexturesAboutToStart(textures))
    with host.busy_section():
        try:
            uzpainter.export.export_project_textures(json_config, [str(json_config["exportPath"])])
        except Exception as error:
            message = "Error during the export (see logs)."
            event.emit_sync(event.ExportTexturesEnded(ExportStatus.Error, message, {}))
            # Capability refusals keep their type and reason for callers and the manifest.
            if isinstance(error, (uzpainter.NotYetSupported, uzpainter.UnsupportedInUzPainter)):
                raise
            raise ValueError(message) from error
        result = TextureExportResult(ExportStatus.Success, "Export successfully finished", textures)
        event.emit_sync(event.ExportTexturesEnded(result.status, result.message, textures))
    return result
