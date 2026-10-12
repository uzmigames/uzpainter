"""Painter's documented `substance_painter.resource` module: the facade over the native `uzpainter`
module (10 §4; decision 107: Painter-shaped resource ids). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.resource import (
    Resource,
    ResourceID,
    Usage,
    import_project_resource,
    list_project_resources,
    show_resources_in_ui,
    update_layer_stack_resource,
)

__all__ = [
    "Resource",
    "ResourceID",
    "Usage",
    "import_project_resource",
    "list_project_resources",
    "show_resources_in_ui",
    "update_layer_stack_resource",
]
