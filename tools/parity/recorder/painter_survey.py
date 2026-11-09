"""Starter Substance survey operations, run inside Painter (decision 412).

The host (`tools.parity.recorder.substance_survey`) executes this source into a copy of the
private namespace of `painter_side.py`, right after it (the pattern of `painter_resources.py`):
the operations below register into its `OPERATIONS`, while the names defined here never replace
`painter_side.py`'s own. Every `substance_painter` symbol used is in `documented_symbols.json`
(approved source A-PYDOC); no private attribute, no shipped Painter source and no community MCP
bridge is used.

- `survey_search` lists the resources a documented search query finds, by URL and GUI name.
- `survey_one` inserts one fill in the open throwaway project, binds the resource as the fill's
  material source (multiple output context) or as its BaseColor source (single output
  context), reads how many presets, image inputs and outputs the source lists, and deletes the
  fill. A failing call is recorded as its exception class and message.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import substance_painter.layerstack
import substance_painter.resource
import substance_painter.textureset

if TYPE_CHECKING:
    # At run time this name comes from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import OPERATIONS


def survey_search(args: dict[str, Any]) -> list[dict[str, str]]:
    found = [
        {"url": resource.identifier().url(), "gui_name": resource.gui_name()}
        for resource in substance_painter.resource.search(str(args["query"]))
    ]
    return sorted(found, key=lambda item: item["url"])


def failure(error: Exception) -> str:
    # repr(error) starts with the exception class name, e.g. "ValueError('...')".
    return f"{repr(error).split('(', 1)[0]}: {str(error)[:200]}"


def outcome(function: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"value": function()}
    except Exception as error:
        return {"raised": failure(error)}


def survey_one(args: dict[str, Any]) -> dict[str, Any]:
    layerstack = substance_painter.layerstack
    stack = substance_painter.textureset.get_active_stack()
    fill = layerstack.insert_fill(layerstack.InsertPosition.from_textureset_stack(stack))
    material = args["material"] is True
    result: dict[str, Any] = {"url": args["url"], "material": material}
    try:
        identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
        if material:
            fill.set_material_source(identifier)
            source = fill.get_material_source()
        else:
            base_color = substance_painter.textureset.ChannelType.BaseColor
            fill.active_channels = {base_color}
            fill.set_source(base_color, identifier)
            source = fill.get_source(base_color)
        result["source_class"] = repr(type(source)).split("'")[1]
        result["presets"] = outcome(lambda: len(source.get_preset_list()))
        result["image_inputs"] = outcome(lambda: len(source.image_inputs))
        result["image_outputs"] = outcome(lambda: len(source.image_outputs))
        result["output_mapping"] = outcome(lambda: len(list(source.output_mapping)))
    except Exception as error:
        result["raised"] = failure(error)
    finally:
        layerstack.delete_node(fill)
    return result


OPERATIONS["survey_search"] = survey_search
OPERATIONS["survey_one"] = survey_one
