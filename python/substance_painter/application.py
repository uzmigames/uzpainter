"""Painter's documented `substance_painter.application` module: the facade over the native
`uzpainter` module (10 §4 Versions row: UzPainter's version; the engine computations, phase1.21).
Documented symbols only; the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.application import (
    version,
    version_info,
)
from uzpainter_facade.host import (
    disable_engine_computations,
    enable_engine_computations,
    engine_computations_status,
)

__all__ = [
    "disable_engine_computations",
    "enable_engine_computations",
    "engine_computations_status",
    "version",
    "version_info",
]
