"""Painter's documented `substance_painter.properties` module: the facade over the native
`uzpainter` module (parameters: the keys of the bake parameters). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.properties import (
    Property,
)

__all__ = [
    "Property",
]
