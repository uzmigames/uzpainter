"""Painter's documented `substance_painter.exception` module: the facade over the native
`uzpainter` module (Painter's documented exceptions). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.exception import (
    ProjectError,
    ResourceNotFoundError,
    ServiceNotFoundError,
)

__all__ = [
    "ProjectError",
    "ResourceNotFoundError",
    "ServiceNotFoundError",
]
