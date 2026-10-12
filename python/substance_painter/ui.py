"""Painter's documented `substance_painter.ui` module: the facade over the native `uzpainter`
module (10 §3: desktop-only members raise UnsupportedInUzPainter; the UI mode is inert state).
Documented symbols only; the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.ui import (
    ApplicationMenu,
    UIMode,
    add_action,
    add_dock_widget,
    add_menu,
    add_plugins_toolbar_widget,
    add_toolbar,
    delete_ui_element,
    get_current_mode,
    get_layout,
    get_layout_mode,
    get_main_window,
    reset_layout,
    set_layout,
    show_main_window,
    switch_to_mode,
)

__all__ = [
    "ApplicationMenu",
    "UIMode",
    "add_action",
    "add_dock_widget",
    "add_menu",
    "add_plugins_toolbar_widget",
    "add_toolbar",
    "delete_ui_element",
    "get_current_mode",
    "get_layout",
    "get_layout_mode",
    "get_main_window",
    "reset_layout",
    "set_layout",
    "show_main_window",
    "switch_to_mode",
]
