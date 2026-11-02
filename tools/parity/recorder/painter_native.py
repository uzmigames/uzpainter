"""The recorder-native create's mesh map, run inside Substance 3D Painter (decision 300 item 7).

The host (`tools.parity.recorder.script_run`, `ScriptSession`) executes this source into a copy
of the private namespace of `painter_side.py`, after `painter_scripts.py`: the operation below
registers into its `OPERATIONS` (the same dictionary), and the names it uses (`member`,
`MESH_MAP_USAGES`, `resource_id_value`, `substance_painter`) are `painter_side.py`'s own. Only
documented `substance_painter` calls are made; no private attribute, no shipped Painter source
and no community MCP bridge is used.

`bind_mesh_map` runs after the recorder's `project.create` (`painter_side.create_project`). With
exactly the one texture set the step names, it imports the Normal as a TEXTURE project resource
under its name and group, binds it as that set's mesh map, and reads every slot back.
`mesh_maps` reads the slots again (after the sync, and after the reopen of r2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    import substance_painter.resource
    import substance_painter.textureset

    from tools.parity.recorder.painter_side import (
        MESH_MAP_USAGES,
        OPERATIONS,
        member,
        resource_id_value,
    )


def slots(texture_set: Any) -> dict[str, Any]:
    """Every mesh-map slot of a texture set, read back: its resource's URL and fields, or None."""
    maps: dict[str, Any] = {}
    for name in sorted(MESH_MAP_USAGES):
        found = texture_set.get_mesh_map_resource(member(MESH_MAP_USAGES, "MeshMapUsage", name))
        maps[name] = None if found is None else resource_id_value(found)
    return maps


def texture_set_names() -> list[str]:
    return [s.name() for s in substance_painter.textureset.all_texture_sets()]


def bind_mesh_map(args: dict[str, Any]) -> dict[str, Any]:
    """With exactly the one texture set `texture_set`, import `path` as a TEXTURE project resource
    named `name` in `group`, bind it as that set's `usage` mesh map, and read every slot back.
    With other texture sets, nothing is imported and only their names are returned (the host
    refuses)."""
    sets = texture_set_names()
    if sets != [args["texture_set"]]:
        return {"texture_sets": sets}
    resource = substance_painter.resource.import_project_resource(
        args["path"], substance_painter.resource.Usage.TEXTURE, args["name"], args["group"]
    )
    texture_set = substance_painter.textureset.TextureSet.from_name(args["texture_set"])
    usage = member(MESH_MAP_USAGES, "MeshMapUsage", args["usage"])
    texture_set.set_mesh_map_resource(usage, resource.identifier())
    return {
        "texture_sets": sets,
        "resource": resource_id_value(resource.identifier()),
        "mesh_maps": slots(texture_set),
    }


def mesh_maps(args: dict[str, Any]) -> dict[str, Any]:
    """The project's texture sets and, with exactly the one `texture_set`, its slots (read only)."""
    sets = texture_set_names()
    if sets != [args["texture_set"]]:
        return {"texture_sets": sets}
    texture_set = substance_painter.textureset.TextureSet.from_name(args["texture_set"])
    return {"texture_sets": sets, "mesh_maps": slots(texture_set)}


OPERATIONS["bind_mesh_map"] = bind_mesh_map
OPERATIONS["mesh_maps"] = mesh_maps
