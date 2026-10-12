"""Painter's documented `substance_painter.colormanagement` module: the facade over the native
`uzpainter` module (10 §4 Colour row). Documented symbols only; the implementation is
`uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.colour import (
    Color,
    DataColorSpace,
    GenericColorSpace,
    LegacyColorSpace,
    NormalColorSpace,
)

__all__ = [
    "Color",
    "DataColorSpace",
    "GenericColorSpace",
    "LegacyColorSpace",
    "NormalColorSpace",
]
