"""Painter's documented `substance_painter.resource` module: the facade over the native `uzpainter`
module (10 §4; decision 107: Painter-shaped resource ids; phase1.21: reload and shelves).
Documented symbols only; the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.resource import (
    AllResourcesFilter,
    ProjectFilter,
    Resource,
    ResourceID,
    ResourcesListFilter,
    ResourcesUsedByProjectFilter,
    SessionFilter,
    Shelf,
    Shelves,
    ShelvesListFilter,
    Usage,
    import_project_resource,
    is_reload_modified_resources_running,
    list_project_resources,
    reload_modified_resources_async,
    search,
    show_resources_in_ui,
    update_layer_stack_resource,
)

__all__ = [
    "AllResourcesFilter",
    "ProjectFilter",
    "Resource",
    "ResourceID",
    "ResourcesListFilter",
    "ResourcesUsedByProjectFilter",
    "SessionFilter",
    "Shelf",
    "Shelves",
    "ShelvesListFilter",
    "Usage",
    "import_project_resource",
    "is_reload_modified_resources_running",
    "list_project_resources",
    "reload_modified_resources_async",
    "search",
    "show_resources_in_ui",
    "update_layer_stack_resource",
]
