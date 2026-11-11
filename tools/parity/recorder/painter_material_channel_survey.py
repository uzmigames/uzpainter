"""Material channel survey operations, run inside Painter (`phase3.3_procedural-families` 2.16).

The host (`tools.parity.recorder.material_channel_survey`) executes this source into a copy of the
private namespace of `painter_side.py`, right after it (the pattern of
`painter_material_survey.py`): the operations below register into its `OPERATIONS`. Every
`substance_painter` symbol used is in `documented_symbols.json` (approved source A-PYDOC).

- `mcs_colour` reads a material source's `get_parameters()`: each value's class and, for a value
  that is not a scalar, every documented `colormanagement.Color` getter. Each colour parameter is
  then set with `set_parameters` to the value it read, to working, sRGB and Raw `Color`s of one
  authored triple, and to a list and a tuple of that triple, each followed by a readback (or what
  it raised), and finally set back to the value it read. A split User0 source of the same
  resource is read the same way.
- `mcs_exports` exports, as OpenEXR 32f with passthrough padding and no dithering, every channel
  of the active stack for: the default material fill of the resource (its active channels as
  Painter sets them), then the same fill with each UV scale mode, then the paired split User0
  L32F / User1 RGB32F source of the same resource at each listed output (the snapshot capture's
  layout, `python/uzpainter_snapshot/painter_side.py`), all in one Painter instance.

A failing call is recorded as its exception class and message. Outputs are private oracle data.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

import substance_painter.colormanagement
import substance_painter.export
import substance_painter.layerstack
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import OPERATIONS, json_value, raised_by

TRIPLE = (0.25, 0.5, 0.75)


def guarded(getter: Callable[[], Any]) -> Any:
    try:
        return getter()
    except Exception as error:
        return {"raised": raised_by(error)}


def type_name(value: Any) -> str:
    return repr(type(value)).split("'")[1]


def colour_getters(value: Any) -> dict[str, Any]:
    """Every documented getter of a `colormanagement.Color`, each guarded."""
    return {
        "class": type_name(value),
        "working": guarded(lambda: list(value.working)),
        "sRGB": guarded(lambda: list(value.sRGB)),
        "value": guarded(lambda: json_value(value.value)),
        "value_raw": guarded(lambda: json_value(value.value_raw)),
        "color_space": guarded(lambda: repr(value.color_space)),
    }


def described_parameters(source: Any) -> dict[str, Any]:
    params = source.get_parameters()
    return {
        "classes": {name: type_name(value) for name, value in params.items()},
        "colours": {
            name: colour_getters(value)
            for name, value in params.items()
            if not isinstance(value, (bool, int, float, str))
        },
    }


def property_colour(get_source: Callable[[], Any], name: str) -> dict[str, Any]:
    return colour_getters(get_source().get_properties()[name].value())


def colour_trials(get_source: Callable[[], Any]) -> dict[str, Any]:
    cm = substance_painter.colormanagement
    first = get_source().get_parameters()
    colours = {k: v for k, v in first.items() if not isinstance(v, (bool, int, float, str))}
    trials: dict[str, Any] = {}
    for name, original in sorted(colours.items()):
        values = {
            "same": original,
            "working": cm.Color(*TRIPLE, cm.GenericColorSpace.Working),
            "srgb": cm.Color(*TRIPLE, cm.GenericColorSpace.sRGB),
            "raw": cm.Color(*TRIPLE, cm.GenericColorSpace.Raw),
            "list": list(TRIPLE),
            "tuple": tuple(TRIPLE),
            "restore": original,
        }
        observed: dict[str, Any] = {}
        for label, value in values.items():
            try:
                get_source().set_parameters({name: value})
                after = get_source().get_parameters()
                observed[label] = {
                    "colour": colour_getters(after[name]),
                    "others_unchanged": all(
                        repr(after[k]) == repr(first[k]) for k in first if k != name
                    ),
                }
            except Exception as error:
                observed[label] = {"raised": raised_by(error)}
        observed["property_value"] = guarded(partial(property_colour, get_source, name))
        trials[name] = observed
    return trials


def mcs_colour(args: dict[str, Any]) -> dict[str, Any]:
    ls = substance_painter.layerstack
    ts = substance_painter.textureset
    stack = ts.get_active_stack()
    identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
    result: dict[str, Any] = {"url": args["url"]}
    fill = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
    try:
        fill.set_material_source(identifier)
        result["material"] = described_parameters(fill.get_material_source())
        result["material_trials"] = colour_trials(fill.get_material_source)
        result["material_after"] = described_parameters(fill.get_material_source())
    except Exception as error:
        result["material_raised"] = raised_by(error)
    finally:
        ls.delete_node(fill)
    if not stack.has_channel(ts.ChannelType.User0):
        stack.add_channel(ts.ChannelType.User0, ts.ChannelFormat.L32F)
    split = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
    try:
        split.active_channels = {ts.ChannelType.User0}
        split.set_source(ts.ChannelType.User0, identifier)
        result["split"] = described_parameters(split.get_source(ts.ChannelType.User0))
    except Exception as error:
        result["split_raised"] = raised_by(error)
    finally:
        ls.delete_node(split)
    return result


def export_all(directory: str, label: str, texture_set: str) -> dict[str, Any]:
    """Every channel of the active stack, one map per channel, exported once."""
    stack = substance_painter.textureset.get_active_stack()
    maps = []
    formats = {}
    for channel_type, channel in stack.all_channels().items():
        fmt = channel.format().name
        formats[channel_type.name] = fmt
        # A document map is named by its channel type in lower case (`specularroughness`).
        name = channel_type.name.lower()
        layout = "RGB" if "RGB" in fmt else "L"
        maps.append(
            {
                "fileName": f"{label}-{channel_type.name}",
                "channels": [
                    {
                        "destChannel": c,
                        "srcChannel": c,
                        "srcMapType": "documentMap",
                        "srcMapName": name,
                    }
                    for c in layout
                ],
            }
        )
    config = {
        "exportPath": directory,
        "exportShaderParams": False,
        "defaultExportPreset": "uzp_mcs",
        "exportPresets": [{"name": "uzp_mcs", "maps": maps}],
        "exportList": [{"rootPath": texture_set}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "exr",
                    "bitDepth": "32f",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }
    exported = substance_painter.export.export_project_textures(config)
    return {
        "formats": formats,
        "status": exported.status.name,
        "message": exported.message,
        "files": [p for paths in exported.textures.values() for p in paths],
    }


def projection(fill: Any) -> dict[str, Any]:
    params = fill.get_projection_parameters()
    transform = params.uv_transformation
    return {
        "mode": fill.get_projection_mode().name,
        "filtering": params.filtering_mode.name,
        "wrapping": params.uv_wrapping_mode.name,
        "scale_mode": transform.scale_mode.name,
        "scale": list(transform.scale),
        "rotation": transform.rotation,
        "offset": list(transform.offset),
    }


def set_uv(fill: Any, scale_mode: str, scale: list[float]) -> None:
    ls = substance_painter.layerstack
    current = fill.get_projection_parameters()
    fill.set_projection_parameters(
        ls.UVProjectionParams(
            filtering_mode=current.filtering_mode,
            uv_wrapping_mode=current.uv_wrapping_mode,
            uv_transformation=ls.UVTransformationParams(
                scale_mode=getattr(ls.ScaleMode, scale_mode),
                scale=[float(v) for v in scale],
                rotation=0.0,
                offset=[0.0, 0.0],
            ),
        )
    )


def mcs_exports(args: dict[str, Any]) -> dict[str, Any]:
    ls = substance_painter.layerstack
    ts = substance_painter.textureset
    stack = ts.get_active_stack()
    texture_set = ts.all_texture_sets()[0].name()
    identifier = substance_painter.resource.ResourceID.from_url(str(args["url"]))
    directory, prefix = str(args["directory"]), str(args["prefix"])
    for node in ls.get_root_layer_nodes(stack):
        ls.delete_node(node)
    result: dict[str, Any] = {"url": args["url"], "texture_set": texture_set}
    fill = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
    try:
        fill.set_material_source(identifier)
        source = fill.get_material_source()
        mapping = source.output_mapping
        result["material"] = {
            "source_mode": fill.source_mode.name,
            "active_channels": sorted(c.name for c in fill.active_channels),
            "output_mapping": {k.name: mapping[k] for k in mapping},
            "mask_output": guarded(lambda: source.mask_output),
            "resolution": guarded(
                lambda: {
                    "mode": source.resolution.mode.name,
                    "value": list(source.resolution.value),
                    "log2_offset": source.resolution.log2_offset,
                }
            ),
            "projection": guarded(lambda: projection(fill)),
            "opacity": {c.name: fill.get_opacity(c) for c in fill.active_channels},
            "blending": {c.name: fill.get_blending_mode(c).name for c in fill.active_channels},
        }
        result["material"]["export"] = guarded(
            lambda: export_all(directory, f"{prefix}-material", texture_set)
        )
        scales: dict[str, Any] = {}
        for label, mode, scale in args.get("scales", []):
            entry: dict[str, Any] = {"set": guarded(partial(set_uv, fill, mode, scale))}
            entry["projection"] = guarded(lambda: projection(fill))
            entry["export"] = guarded(
                partial(export_all, directory, f"{prefix}-scale-{label}", texture_set)
            )
            scales[label] = entry
        result["scales"] = scales
    except Exception as error:
        result["material_raised"] = raised_by(error)
    finally:
        ls.delete_node(fill)
    channels = [ts.ChannelType.User0, ts.ChannelType.User1]
    for channel, fmt in zip(
        channels, (ts.ChannelFormat.L32F, ts.ChannelFormat.RGB32F), strict=True
    ):
        if not stack.has_channel(channel):
            stack.add_channel(channel, fmt)
    split = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
    try:
        split.active_channels = set(channels)
        for channel in channels:
            split.set_source(channel, identifier)
            split.set_opacity(1.0, channel)
            split.set_blending_mode(ls.BlendingMode.Normal, channel)
        split.set_projection_parameters(
            ls.UVProjectionParams(
                filtering_mode=ls.FilteringMode.Nearest,
                uv_wrapping_mode=ls.UVWrapMode.RepeatNone,
                uv_transformation=ls.UVTransformationParams(
                    scale_mode=ls.ScaleMode.Factors,
                    scale=[1.0, 1.0],
                    rotation=0.0,
                    offset=[0.0, 0.0],
                ),
            )
        )
        outputs = list(split.get_source(channels[0]).image_outputs)
        result["split"] = {"outputs": outputs, "exports": {}}
        for index, output in enumerate(outputs):
            for channel in channels:
                split.get_source(channel).active_output = output
            result["split"]["exports"][output] = guarded(
                partial(export_all, directory, f"{prefix}-split{index}", texture_set)
            )
    except Exception as error:
        result["split_raised"] = raised_by(error)
    finally:
        ls.delete_node(split)
    return result


OPERATIONS["mcs_colour"] = mcs_colour
OPERATIONS["mcs_exports"] = mcs_exports
