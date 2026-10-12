"""Painter's documented `substance_painter.event` module: the facade over the native `uzpainter`
module (10 §3: the desktop-only event; the dispatcher is phase1.21). Documented symbols only;
the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.event import (
    GraphicalUserInterfaceStarted,
)

__all__ = [
    "GraphicalUserInterfaceStarted",
]
