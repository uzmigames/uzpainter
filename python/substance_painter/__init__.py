"""UzPainter's `substance_painter` compatibility facade (task phase1.20_pyapi-facade). Painter's
documented Python API, written from its public documentation and its Tier 0 probes (clean room,
decision 002), over the native `uzpainter` module: the Assets3D scripts run unchanged.
Documented symbols only: a private name is absent like any unknown attribute. `__version__` is
the API level (0.3.7); `application.version()` is UzPainter's version. See `python/FACADE.md`
and `docs/architecture/10-python-api.md` §0, §1, §3, §4."""

from substance_painter import (
    application,
    baking,
    colormanagement,
    display,
    event,
    exception,
    export,
    js,
    layerstack,
    levels,
    logging,
    project,
    properties,
    resource,
    source,
    textureset,
    ui,
)
from substance_painter._version import __version__

__all__ = [
    "__version__",
    "application",
    "baking",
    "colormanagement",
    "display",
    "event",
    "exception",
    "export",
    "js",
    "layerstack",
    "levels",
    "logging",
    "project",
    "properties",
    "resource",
    "source",
    "textureset",
    "ui",
]
