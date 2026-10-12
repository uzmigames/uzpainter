"""Painter's documented `substance_painter.display` module: the facade over the native `uzpainter`
module (decision 042; release gap phase2.3_realtime-preview: every call raises NotYetSupported).
Documented symbols only; the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.display import (
    Camera,
    get_color_lut_resource,
    get_environment_resource,
    get_tone_mapping,
    set_color_lut_resource,
    set_environment_resource,
    set_tone_mapping,
)

__all__ = [
    "Camera",
    "get_color_lut_resource",
    "get_environment_resource",
    "get_tone_mapping",
    "set_color_lut_resource",
    "set_environment_resource",
    "set_tone_mapping",
]
