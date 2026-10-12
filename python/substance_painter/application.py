"""Painter's documented `substance_painter.application` module: the facade over the native
`uzpainter` module (10 §4 Versions row: UzPainter's version). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.application import (
    version,
    version_info,
)

__all__ = [
    "version",
    "version_info",
]
