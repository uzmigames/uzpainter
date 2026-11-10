"""Filter parameter survey operations, run inside Painter (phase3.2_proc-filter-families 2.1).

The host (`tools.parity.recorder.filter_survey`) executes this source into a copy of the private
namespace of `painter_side.py`, right after it (the pattern of `painter_generator_survey.py`): the
operations below register into its `OPERATIONS`, while the names defined here never replace
`painter_side.py`'s own. Every `substance_painter` symbol used is in `documented_symbols.json`
(approved source A-PYDOC); no private attribute, no shipped Painter source and no community MCP
bridge is used.

- `filter_search` lists the resources a documented search query finds that carry the `FILTER`
  usage, by URL and GUI name.
- `filter_describe` inserts one fill in the open throwaway project, inserts the filter in its
  content stack, describes its source with `painter_side.py`'s `substance_description` (every
  documented `properties.Property` getter of every parameter, the preset list, image inputs and
  outputs), and deletes the fill. A failing call is recorded as its exception class and message.
  No pixel is read and nothing is exported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import substance_painter.layerstack
import substance_painter.resource
import substance_painter.textureset

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import OPERATIONS, substance_description


def filter_search(args: dict[str, Any]) -> list[dict[str, str]]:
    usage = substance_painter.resource.Usage.FILTER
    found = [
        {"url": resource.identifier().url(), "gui_name": resource.gui_name()}
        for resource in substance_painter.resource.search(str(args["query"]))
        if usage in resource.usages()
    ]
    return sorted(found, key=lambda item: item["url"])


def filter_failure(error: Exception) -> str:
    # repr(error) starts with the exception class name, e.g. "ValueError('...')".
    return f"{repr(error).split('(', 1)[0]}: {str(error)[:200]}"


def filter_describe(args: dict[str, Any]) -> dict[str, Any]:
    layerstack = substance_painter.layerstack
    stack = substance_painter.textureset.get_active_stack()
    fill = layerstack.insert_fill(layerstack.InsertPosition.from_textureset_stack(stack))
    result: dict[str, Any] = {"url": args["url"]}
    try:
        identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
        position = layerstack.InsertPosition.inside_node(fill, layerstack.NodeStack.Content)
        effect = layerstack.insert_filter_effect(position, identifier)
        result["source"] = substance_description(effect.get_source())
    except Exception as error:
        result["raised"] = filter_failure(error)
    finally:
        layerstack.delete_node(fill)
    return result


OPERATIONS["filter_search"] = filter_search
OPERATIONS["filter_describe"] = filter_describe
