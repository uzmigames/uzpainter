"""Project resources for the Export resource qualification, run inside Painter (decision 300).

The host (`tools.parity.recorder.resource_qualification`) executes this source into a copy of the
private namespace of `painter_side.py`, right after it (the pattern of `painter_scripts.py`): the
operations below register into its `OPERATIONS`, while the names defined here never replace
`painter_side.py`'s own. Every `substance_painter` symbol used is in `documented_symbols.json`
(approved source A-PYDOC); no private attribute, no shipped Painter source and no community MCP
bridge is used.

- `rq_import` imports one authored bitmap as a project resource with a name and a group
  (`resource.import_project_resource` with usage TEXTURE, the form the UzmiGames create script
  and layer-stack sync use), keeps it as the `resource_step` of its step for `apply_step`'s
  `set_mesh_map_resource`, and returns its identity.
- `rq_project_resources` lists the resources the open project uses (`list_project_resources`)
  whose name is one of `names`, each with the identity of every resource `Resource.retrieve`
  returns for it.
- `rq_show` highlights one resource in the Assets window (`Resource.show_in_ui`), the documented
  navigation that precedes the operator's Export resource; it changes no project state.

A resource's identity is its URL, context, name and version (the `ResourceID` fields), its
location (`Resource.location`: SESSION, PROJECT or SHELF) and its GUI name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import substance_painter.resource

if TYPE_CHECKING:
    # At run time this name comes from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import OPERATIONS, RESOURCES


def resource_identity(resource: Any) -> dict[str, Any]:
    identifier = resource.identifier()
    return {
        "url": identifier.url(),
        "context": identifier.context,
        "name": identifier.name,
        "version": identifier.version,
        "location": resource.location().name,
        "gui_name": resource.gui_name(),
    }


def rq_import(args: dict[str, Any]) -> dict[str, Any]:
    resource = substance_painter.resource.import_project_resource(
        args["path"], substance_painter.resource.Usage.TEXTURE, args["name"], args["group"]
    )
    RESOURCES[int(args["step"])] = resource  # a `resource_step` of `set_mesh_map_resource`
    return resource_identity(resource)


def rq_project_resources(args: dict[str, Any]) -> dict[str, Any]:
    wanted = set(args["names"])
    found: dict[str, Any] = {name: [] for name in sorted(wanted)}
    for identifier in substance_painter.resource.list_project_resources():
        if identifier.name not in wanted:
            continue
        retrieved = substance_painter.resource.Resource.retrieve(identifier)
        found[identifier.name].append(
            {
                "listed_url": identifier.url(),
                "retrieved": [resource_identity(r) for r in retrieved],
            }
        )
    return found


def rq_show(args: dict[str, Any]) -> dict[str, Any]:
    identifier = substance_painter.resource.ResourceID.from_url(args["url"])
    retrieved = substance_painter.resource.Resource.retrieve(identifier)
    if len(retrieved) != 1:
        raise ValueError(f"{args['url']}: Resource.retrieve returned {len(retrieved)} resources")
    retrieved[0].show_in_ui()
    return resource_identity(retrieved[0])


OPERATIONS["rq_import"] = rq_import
OPERATIONS["rq_project_resources"] = rq_project_resources
OPERATIONS["rq_show"] = rq_show
