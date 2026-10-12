"""Painter's documented `substance_painter.js` module: the facade over the native `uzpainter`
module (10 §3: the alg.* whitelist). Documented symbols only; the implementation is
`uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.js import (
    evaluate,
)

__all__ = [
    "evaluate",
]
