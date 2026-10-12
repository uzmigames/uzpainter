"""UzPainter's `substance_painter_plugins`: non-UI `startup/` and `plugins/` modules
(`docs/architecture/10-python-api.md` §1; `python/FACADE.md` §8). The implementation is
`uzpainter_facade.plugins`."""

from uzpainter_facade.plugins import (
    close_all_plugins,
    close_plugin,
    initial_path,
    is_plugin_started,
    load_startup_modules,
    plugin_module_names,
    reload_plugin,
    start_plugin,
    startup_module_names,
    update_sys_path,
)

path = initial_path()
plugins: "dict[str, object]" = {}
del initial_path

__all__ = [
    "close_all_plugins",
    "close_plugin",
    "is_plugin_started",
    "load_startup_modules",
    "path",
    "plugin_module_names",
    "plugins",
    "reload_plugin",
    "start_plugin",
    "startup_module_names",
    "update_sys_path",
]
