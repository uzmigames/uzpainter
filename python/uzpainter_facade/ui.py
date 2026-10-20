"""`substance_painter.ui`, the desktop-only members and the UI mode (10 §3; `python/FACADE.md` §7).

UzPainter has no desktop UI. The Qt members of `ui` change no texture, render or script-visible
state in Painter, so each raises `UnsupportedInUzPainter(symbol, reason, alternative)` instead of
pretending to succeed. The UI mode is script state: `switch_to_mode` stores it and
`get_current_mode` reads it back (Edition until a mode is set). In the Baking and Visualisation
modes `application.engine_computations_status()` reads False, as Painter's does
(`p22b-host-application` s27-s30; `host.engine_computations_status`); nothing else reads it.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Any

import uzpainter

from uzpainter_facade.state import SESSION

MODULE = "substance_painter.ui"
NO_UI = "it is a member of Painter's desktop user interface, which changes no texture, render or script-visible state, and UzPainter has no desktop UI"  # noqa: E501


class UIMode(enum.Enum):
    """UI configurations enumeration."""

    Edition = 1
    Visualisation = 2
    Baking = 4


class ApplicationMenu(enum.Enum):
    """Standard application menus enumeration."""

    File = 0
    Edit = 1
    Mode = 2
    Window = 3
    Viewport = 4
    Help = 5


for _cls in (UIMode, ApplicationMenu):
    _cls.__module__ = MODULE


def desktop_only(name: str, alternative: str) -> Callable[..., Any]:
    """A desktop-only `ui` function: raises UnsupportedInUzPainter naming itself."""

    def call(*args: Any, **kwargs: Any) -> Any:
        raise uzpainter.UnsupportedInUzPainter(f"{MODULE}.{name}", NO_UI, alternative)

    call.__name__ = call.__qualname__ = name
    call.__module__ = MODULE
    call.__doc__ = f"Desktop-only: raises UnsupportedInUzPainter ({alternative})."
    return call


HEADLESS = "a headless script: report through substance_painter.logging or the script's result"
show_main_window = desktop_only("show_main_window", HEADLESS)
get_main_window = desktop_only("get_main_window", HEADLESS)
get_layout = desktop_only("get_layout", "nothing: UzPainter has no window layout")
get_layout_mode = desktop_only("get_layout_mode", "ui.get_current_mode()")
set_layout = desktop_only("set_layout", "ui.switch_to_mode()")
reset_layout = desktop_only("reset_layout", "nothing: UzPainter has no window layout")
add_dock_widget = desktop_only("add_dock_widget", HEADLESS)
add_plugins_toolbar_widget = desktop_only("add_plugins_toolbar_widget", HEADLESS)
add_menu = desktop_only("add_menu", HEADLESS)
add_toolbar = desktop_only("add_toolbar", HEADLESS)
add_action = desktop_only("add_action", HEADLESS)
delete_ui_element = desktop_only("delete_ui_element", "nothing: UzPainter creates no UI element")


def get_current_mode() -> UIMode:
    """The current UI mode (inert script state)."""
    mode: UIMode = SESSION.ui_mode or UIMode.Edition
    return mode


def switch_to_mode(mode: UIMode) -> None:
    """Store the UI mode (inert script state)."""
    if not isinstance(mode, UIMode):
        raise TypeError("mode must be a ui.UIMode")
    SESSION.ui_mode = mode
