"""`substance_painter_plugins`: non-UI `startup/` and `plugins/` modules (10 §1;
`python/FACADE.md` §8).

A plugins directory holds `plugins/` (optional components), `startup/` (always loaded by
`load_startup_modules`) and `modules/` (shared code), each added to `sys.path` by
`update_sys_path`, `plugins/` first so it takes precedence. `path` starts from the
`SUBSTANCE_PAINTER_PLUGINS_PATH` environment variable; UzPainter has no installation or user
resource directory of its own to add. A started module's `start_plugin()` runs after loading and
its `close_plugin()` before unloading. A module that needs Painter's desktop UI (PySide6) fails to
import: only non-UI modules are supported.
"""

from __future__ import annotations

import gc
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

PACKAGE = "substance_painter_plugins"
SUBDIRECTORIES = ("plugins", "startup", "modules")


def initial_path() -> list[str]:
    value = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_PATH", "")
    return [entry for entry in value.split(os.pathsep) if entry]


def _package() -> Any:
    return sys.modules[PACKAGE]


def _roots() -> list[Path]:
    roots: list[str] = list(_package().path)
    for entry in initial_path():
        if entry not in roots:
            roots.append(entry)
    return [Path(entry) for entry in roots]


def update_sys_path() -> None:
    """Update sys.path from `substance_painter_plugins.path` and the environment variable."""
    for root in _roots():
        for sub in SUBDIRECTORIES:
            folder = str(root / sub)
            if folder not in sys.path:
                sys.path.append(folder)


def _module_names(sub: str) -> list[str]:
    names: list[str] = []
    for root in _roots():
        folder = root / sub
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.suffix == ".py" and entry.stem != "__init__":
                name = entry.stem
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                name = entry.name
            else:
                continue
            if name not in names:
                names.append(name)
    return names


def startup_module_names() -> list[str]:
    """The names of the available startup modules."""
    return _module_names("startup")


def plugin_module_names() -> list[str]:
    """The names of the available plugins modules."""
    return _module_names("plugins")


def start_plugin(module: ModuleType) -> None:
    """Start the given plugin: its `start_plugin()` runs and it joins `plugins`."""
    plugins: dict[str, ModuleType] = _package().plugins
    if module.__name__ in plugins:
        return
    if hasattr(module, "start_plugin"):
        module.start_plugin()
    plugins[module.__name__] = module


def close_plugin(module: ModuleType, gc_collect: bool = True) -> None:
    """Close the given plugin: its `close_plugin()` runs and it leaves `plugins`."""
    plugins: dict[str, ModuleType] = _package().plugins
    if plugins.pop(module.__name__, None) is None:
        return
    if hasattr(module, "close_plugin"):
        module.close_plugin()
    if gc_collect:
        gc.collect()


def is_plugin_started(module: ModuleType) -> bool:
    return module.__name__ in _package().plugins


def reload_plugin(module: ModuleType) -> ModuleType:
    """Close the plugin, reload it (running its `reload_plugin()` if any) and start it."""
    close_plugin(module)
    if hasattr(module, "reload_plugin"):
        module.reload_plugin()
    reloaded = importlib.reload(module)
    start_plugin(reloaded)
    return reloaded


def load_startup_modules() -> None:
    """Load and start every startup module."""
    update_sys_path()
    for name in startup_module_names():
        start_plugin(importlib.import_module(name))


def close_all_plugins() -> None:
    for module in list(_package().plugins.values()):
        close_plugin(module, gc_collect=False)
    gc.collect()
