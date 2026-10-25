"""`substance_painter.display`: the display state of the fixed render pipeline (decisions 038, 042
and 132; `python/FACADE.md` §10).

Painter's documented symbols over the native `uzpainter.display`:
- the environment map is a project resource imported with usage ENVIRONMENT; the identifiers are
  Painter-shaped (`resource.ResourceID`, `project<N>` context, `<sha1>.image` version);
- the colour LUT is pinned to none: `set_color_lut_resource(None)` is accepted, any LUT raises
  `UnsupportedInUzPainter` naming decision 038;
- `get_tone_mapping` and `set_tone_mapping` raise `RuntimeError` on a colour-managed project, as
  Painter documents, and `UnsupportedInUzPainter` on a Legacy project;
- `Camera`, `CameraProjectionType` and `ToneMappingFunction` are the native ones.
"""

from __future__ import annotations

from typing import Any

import uzpainter

from uzpainter_facade import resource

MODULE = "substance_painter.display"

Camera = uzpainter.display.Camera
CameraProjectionType = uzpainter.display.CameraProjectionType
ToneMappingFunction = uzpainter.display.ToneMappingFunction
get_tone_mapping = uzpainter.display.get_tone_mapping
set_tone_mapping = uzpainter.display.set_tone_mapping


def get_environment_resource() -> resource.ResourceID | None:
    """Get the environment map resource of the active project."""
    native = uzpainter.display.get_environment_resource()
    return None if native is None else resource.from_native(native)


def set_environment_resource(new_env_map: Any) -> None:
    """Set the environment map resource of the active project."""
    if not isinstance(new_env_map, resource.ResourceID):
        raise TypeError("new_env_map must be a resource.ResourceID")
    uzpainter.display.set_environment_resource(resource.to_native(new_env_map))


def get_color_lut_resource() -> resource.ResourceID | None:
    """Get the color profile LUT resource of the active project: always None (decision 038)."""
    native = uzpainter.display.get_color_lut_resource()
    return None if native is None else resource.from_native(native)


def set_color_lut_resource(new_color_lut: Any) -> None:
    """Set the color profile LUT resource of the active project: only None is accepted."""
    if new_color_lut is None:
        uzpainter.display.set_color_lut_resource(None)
        return
    if not isinstance(new_color_lut, resource.ResourceID):
        raise TypeError("new_color_lut must be a resource.ResourceID")
    resource.refuse_observed(new_color_lut)
    # Any LUT is outside the fixed pipeline: the native call refuses it before any change.
    uzpainter.display.set_color_lut_resource(
        uzpainter.resource.ResourceID("project", new_color_lut.name, None)
    )


for _function in (
    get_environment_resource,
    set_environment_resource,
    get_color_lut_resource,
    set_color_lut_resource,
):
    _function.__module__ = MODULE
