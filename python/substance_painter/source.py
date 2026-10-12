"""Painter's documented `substance_painter.source` module: the facade over the native `uzpainter`
module (fill sources). Documented symbols only; the implementation is `uzpainter_facade`
(`python/FACADE.md`)."""

from uzpainter_facade.nodes import (
    SourceBitmap,
    SourceMode,
    SourceSubstance,
    SourceUniformColor,
)

__all__ = [
    "SourceBitmap",
    "SourceMode",
    "SourceSubstance",
    "SourceUniformColor",
]
