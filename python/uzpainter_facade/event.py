"""`substance_painter.event`: the desktop-only event (10 §3). The dispatcher and the other 26
event classes are phase1.21_pyapi-dispatcher-lifecycle."""

from __future__ import annotations

from typing import Any

import uzpainter


class GraphicalUserInterfaceStarted:
    """Event sent once Painter's desktop UI has started: UzPainter has none, so the event never
    happens and creating it raises UnsupportedInUzPainter."""

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise uzpainter.UnsupportedInUzPainter(
            "substance_painter.event.GraphicalUserInterfaceStarted",
            "it marks the start of Painter's desktop user interface, which changes no texture, "
            "render or script-visible state, and UzPainter has no desktop UI",
            "start the script's work directly, or connect to ProjectEditionEntered",
        )


GraphicalUserInterfaceStarted.__module__ = "substance_painter.event"
