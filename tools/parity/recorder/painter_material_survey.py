"""Material survey operations, run inside Painter (phase3.2_proc-material-families item 2.1).

The host (`tools.parity.recorder.material_survey`) executes this source into a copy of the private
namespace of `painter_side.py`, right after it (the pattern of `painter_generator_survey.py`): the
operations below register into its `OPERATIONS`, while the names defined here never replace
`painter_side.py`'s own. Every `substance_painter` symbol used is in `documented_symbols.json`
(approved source A-PYDOC); no private attribute, no shipped Painter source and no community MCP
bridge is used.

- `material_describe` inserts one fill in the open throwaway project, sets the resource as its
  material source (`FillLayerNode.set_material_source`), reads the fill's source mode and active
  channels and describes the material source with `painter_side.py`'s `substance_description`
  (every documented `properties.Property` getter of every parameter, the preset list, image inputs
  and outputs), plus its `output_mapping` and `mask_output`, then deletes the fill.
- `smart_material_search` lists the resources a documented search query finds that carry the
  `SMART_MATERIAL` usage, by URL and GUI name.
- `smart_material_describe` inserts one smart material at the top of the active stack and walks
  the inserted layers (`GroupLayerNode.sub_layers`, content and mask effects): per node its name,
  type, source mode, active channels, its material source or each active channel's source
  described (a mask's fill effect: its one source), then deletes what it inserted.

A failing call is recorded as its exception class and message. No pixel is read and nothing is
exported. Smart-material structures are private oracle data (`05-procedural-content.md` §3,
publication rule).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

import substance_painter.layerstack
import substance_painter.resource
import substance_painter.textureset

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import (
        OPERATIONS,
        child_nodes,
        json_value,
        raised_by,
        substance_description,
    )


def guarded(getter: Callable[[], Any]) -> Any:
    try:
        return getter()
    except Exception as error:
        return {"raised": raised_by(error)}


def material_contexts(source: Any) -> dict[str, Any]:
    """`output_mapping` as {channel: output} and `mask_output` of a material source."""

    def mapping() -> dict[str, Any]:
        found = source.output_mapping
        return {channel.name: json_value(found[channel]) for channel in found}

    return {
        "output_mapping": guarded(mapping),
        "mask_output": guarded(lambda: json_value(source.mask_output)),
    }


def channel_source(node: Any, channel: Any) -> dict[str, Any]:
    return substance_description(node.get_source(channel))


def fill_description(node: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_mode": guarded(lambda: node.source_mode.name),
        "active_channels": guarded(lambda: sorted(c.name for c in node.active_channels)),
    }
    mode = entry["source_mode"]
    if mode == "Material":
        source = guarded(node.get_material_source)
        if isinstance(source, dict) and "raised" in source:
            entry["material"] = source
        else:
            entry["material"] = {**substance_description(source), **material_contexts(source)}
    elif isinstance(entry["active_channels"], list):
        sources: dict[str, Any] = {}
        for channel in sorted(node.active_channels, key=lambda c: c.name):
            sources[channel.name] = guarded(partial(channel_source, node, channel))
        entry["sources"] = sources
    else:
        # A mask's fill effect has one source and no channel context.
        entry["source"] = guarded(lambda: substance_description(node.get_source()))
    return entry


def material_describe(args: dict[str, Any]) -> dict[str, Any]:
    layerstack = substance_painter.layerstack
    stack = substance_painter.textureset.get_active_stack()
    fill = layerstack.insert_fill(layerstack.InsertPosition.from_textureset_stack(stack))
    result: dict[str, Any] = {"url": args["url"]}
    try:
        identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
        fill.set_material_source(identifier)
        result = {**result, **fill_description(fill)}
    except Exception as error:
        result["raised"] = raised_by(error)
    finally:
        layerstack.delete_node(fill)
    return result


def smart_material_search(args: dict[str, Any]) -> list[dict[str, str]]:
    usage = substance_painter.resource.Usage.SMART_MATERIAL
    found = [
        {"url": resource.identifier().url(), "gui_name": resource.gui_name()}
        for resource in substance_painter.resource.search(str(args["query"]))
        if usage in resource.usages()
    ]
    return sorted(found, key=lambda item: item["url"])


def walk_children(node: Any, field: str) -> list[dict[str, Any]]:
    return [walk(child) for child in child_nodes(node, field)]


def walk(node: Any) -> dict[str, Any]:
    kind = node.get_type().name
    entry: dict[str, Any] = {"name": node.get_name(), "type": kind}
    if kind in ("FillLayer", "FillEffect"):
        entry = {**entry, **fill_description(node)}
    elif kind in ("GeneratorEffect", "FilterEffect"):
        entry["source"] = guarded(lambda: substance_description(node.get_source()))
    children: tuple[str, ...] = ("sub_layers",) if kind == "GroupLayer" else ()
    if kind in ("FillLayer", "PaintLayer", "GroupLayer", "InstanceLayer"):
        children += ("content_effects", "mask_effects")
    for field in children:
        entry[field] = guarded(partial(walk_children, node, field))
    return entry


def smart_material_describe(args: dict[str, Any]) -> dict[str, Any]:
    layerstack = substance_painter.layerstack
    stack = substance_painter.textureset.get_active_stack()
    before = {node.uid() for node in layerstack.get_root_layer_nodes(stack)}
    result: dict[str, Any] = {"url": args["url"]}
    try:
        identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
        node = layerstack.insert_smart_material(
            layerstack.InsertPosition.from_textureset_stack(stack), identifier
        )
        result["structure"] = walk(node)
    except Exception as error:
        result["raised"] = raised_by(error)
    finally:
        # Whatever the insertion added at the root, found by the documented `Node.uid`.
        for node in layerstack.get_root_layer_nodes(stack):
            if node.uid() not in before:
                layerstack.delete_node(node)
    return result


OPERATIONS["material_describe"] = material_describe
OPERATIONS["smart_material_search"] = smart_material_search
OPERATIONS["smart_material_describe"] = smart_material_describe
