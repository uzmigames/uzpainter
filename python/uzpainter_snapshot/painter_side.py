"""Authored snapshot operations; executed only inside Painter's documented remote API."""

from __future__ import annotations

import os
from typing import Any

import substance_painter as sp
import substance_painter.application
import substance_painter.colormanagement
import substance_painter.export
import substance_painter.layerstack
import substance_painter.project
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset

STATE: dict[str, Any] = {}


def same_path(left: Any, right: str) -> bool:
    return isinstance(left, str) and os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def check_owned() -> None:
    current = identity()
    owner = STATE.get("owner")
    if not owner or current["pid"] != owner["pid"] or not same_path(current["mesh"], owner["mesh"]):
        raise RuntimeError("Painter project ownership changed")


def identity() -> dict[str, Any]:
    """Public application version and host process/colour selection."""
    return {
        "pid": os.getpid(),
        "version": sp.application.version(),
        "version_info": list(sp.application.version_info()),
        "OCIO": os.environ.get("OCIO"),
        "PAINTER_ACE_CONFIG": os.environ.get("PAINTER_ACE_CONFIG"),
        "project_open": sp.project.is_open(),
        "mesh": sp.project.last_imported_mesh_path() if sp.project.is_open() else None,
    }


def configure(request: dict[str, Any]) -> None:
    """Bind both sources only after enabling both channels, which resets the source slots."""
    stack = sp.textureset.get_active_stack()
    for node in sp.layerstack.get_root_layer_nodes(stack):
        sp.layerstack.delete_node(node)
    channels = [sp.textureset.ChannelType.User0, sp.textureset.ChannelType.User1]
    stack.add_channel(channels[0], sp.textureset.ChannelFormat.L32F)
    stack.add_channel(channels[1], sp.textureset.ChannelFormat.RGB32F)
    fill = sp.layerstack.insert_fill(sp.layerstack.InsertPosition.from_textureset_stack(stack))
    fill.active_channels = set(channels)
    for channel in channels:
        fill.set_source(channel, sp.resource.ResourceID.from_url(request["resource"]))
        source = fill.get_source(channel)
        if not isinstance(source, sp.source.SourceSubstance):
            raise RuntimeError("resource is not SourceSubstance")
        source.set_parameters(request["parameters"])
        apply_state(source, request)
        fill.set_opacity(1.0, channel)
        fill.set_blending_mode(sp.layerstack.BlendingMode.Normal, channel)
    fill.set_projection_parameters(
        sp.layerstack.UVProjectionParams(
            filtering_mode=sp.layerstack.FilteringMode.Nearest,
            uv_wrapping_mode=sp.layerstack.UVWrapMode.RepeatNone,
            uv_transformation=sp.layerstack.UVTransformationParams(
                scale_mode=sp.layerstack.ScaleMode.Factors,
                scale=[1.0, 1.0],
                rotation=0.0,
                offset=[0.0, 0.0],
            ),
        )
    )
    STATE["fill"] = fill
    STATE["stack"] = stack
    STATE["channels"] = channels


def apply_state(source: Any, request: dict[str, Any]) -> None:
    """The preset, then the image-input sources, of a multi-output capture (decision 412 §3).

    The preset is applied by Painter's own `apply_preset`; a colour input is a working-space
    `Color`, a bitmap input the project resource imported once per file, and `remove` Painter's
    own `remove_source`. A legacy request has neither key and changes nothing here."""
    preset = request.get("preset")
    if preset is not None:
        source.apply_preset(preset)
    for name, plug in sorted((request.get("inputs") or {}).items()):
        if "color" in plug:
            r, g, b = (float(v) for v in plug["color"])
            working = sp.colormanagement.GenericColorSpace.Working
            source.set_source(name, sp.colormanagement.Color(r, g, b, working))
        elif "bitmap" in plug:
            if "bitmaps" not in STATE:
                STATE["bitmaps"] = {}
            bitmaps = STATE["bitmaps"]
            if plug["bitmap"] not in bitmaps:
                usage = sp.resource.Usage.TEXTURE
                imported = sp.resource.import_project_resource(plug["bitmap"], usage)
                bitmaps[plug["bitmap"]] = imported.identifier()
            source.set_source(name, bitmaps[plug["bitmap"]])
        elif plug.get("remove") is True:
            source.remove_source(name)
        else:
            raise ValueError("an image input is plugged with color, bitmap or remove")


def class_name(value: Any) -> str:
    """A value's class name, from the repr of its type (`<class 'module.Name'>`)."""
    return repr(type(value)).split("'")[1].split(".")[-1]


def raised(error: Exception) -> dict[str, Any]:
    return {"raised": {"type": class_name(error), "message": str(error)}}


def described_input(source: Any, name: str) -> dict[str, Any]:
    """An image input's source through its documented getters, or what `get_source` raised.

    An unplugged input's `get_source` returns a `SourceBitmap` whose `resource_id` raises (Painter
    12.2, the decision-413 capture), so each bitmap getter's outcome is recorded on its own."""
    try:
        plugged = source.get_source(name)
    except ValueError as error:
        return raised(error)
    if isinstance(plugged, sp.source.SourceUniformColor):
        return {"class": "SourceUniformColor", "working": list(plugged.get_color().working)}
    if isinstance(plugged, sp.source.SourceBitmap):
        result: dict[str, Any] = {"class": "SourceBitmap"}
        try:
            result["resource"] = plugged.resource_id.url()
        except ValueError as error:
            result["resource_id"] = raised(error)
        try:
            space = plugged.get_color_space()
            result["colour_space"] = space if isinstance(space, str) else space.name
        except ValueError as error:
            result["colour_space_raised"] = raised(error)
        return result
    raise ValueError(f"image input {name!r} holds a source the snapshot cannot represent")


def set_output(output: str) -> None:
    """Both paired sources evaluate `output` (python-doc `SourceSubstance.active_output`)."""
    fill = STATE["fill"]
    for channel in STATE["channels"]:
        fill.get_source(channel).active_output = output


def preset_parameters() -> dict[str, Any]:
    """Each preset applied by Painter to both sources and their parameters read, then the
    captured parameters set back; the caller checks that the readback equals the captured one."""
    fill = STATE["fill"]
    channels = STATE["channels"]
    original = [fill.get_source(channel).get_parameters() for channel in channels]
    result: dict[str, Any] = {}
    for preset in list(fill.get_source(channels[0]).get_preset_list()):
        observed = []
        for channel in channels:
            fill.get_source(channel).apply_preset(preset)
            observed.append(fill.get_source(channel).get_parameters())
        result[preset] = observed
        for channel, parameters in zip(channels, original, strict=True):
            fill.get_source(channel).set_parameters(parameters)
    return result


def contexts(request: dict[str, Any]) -> dict[str, Any]:
    """The single and multiple output contexts (decision 412): what the split sources'
    `output_mapping` and `mask_output` give, and a material fill of the same resource and state,
    read and deleted again. The captured fill is not changed."""
    split = STATE["fill"].get_source(STATE["channels"][0])
    result: dict[str, Any] = {"split": {}}
    try:
        result["split"]["output_mapping"] = {"returned": class_name(split.output_mapping)}
    except Exception as error:
        result["split"]["output_mapping"] = raised(error)
    try:
        result["split"]["mask_output"] = {"returned": class_name(split.mask_output)}
    except Exception as error:
        result["split"]["mask_output"] = raised(error)
    stack = STATE["stack"]
    material = sp.layerstack.insert_fill(sp.layerstack.InsertPosition.from_textureset_stack(stack))
    try:
        material.set_material_source(sp.resource.ResourceID.from_url(request["resource"]))
        source = material.get_material_source()
        source.set_parameters(request["parameters"])
        apply_state(source, request)
        source = material.get_material_source()
        mapping = source.output_mapping
        context: dict[str, Any] = {
            "output_mapping": {key.name: mapping[key] for key in mapping},
            "mask_output": source.mask_output,
            "active_channels": sorted(c.name for c in material.active_channels),
            "parameters": source.get_parameters(),
            "input_sources": {n: described_input(source, n) for n in source.image_inputs},
        }
        try:
            context["active_output"] = {"value": source.active_output}
        except Exception as error:
            context["active_output"] = raised(error)
        result["material"] = context
    finally:
        sp.layerstack.delete_node(material)
    return result


def plain(value: Any) -> Any:
    """A documented getter's value as JSON (tuples become lists)."""
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return value


def described(prop: Any) -> dict[str, Any]:
    """One `properties.Property` through its documented getters (store/snapshots.h metadata).

    Only finite integer, number and string values are representable; anything else refuses the
    capture before any project change (no typed codec for vectors or colours yet)."""
    value = prop.value()
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or value != value:
        raise ValueError(f"property {prop.name()!r} has a value the snapshot cannot represent")
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        raise ValueError(f"property {prop.name()!r} has a non-finite value")
    return {
        "value": value,
        "name": prop.name(),
        "short_name": prop.short_name(),
        "label": prop.label(),
        "widget_type": prop.widget_type(),
        "enum_values": plain(prop.enum_values()),
        "properties": plain(prop.properties()),
    }


def readback() -> dict[str, Any]:
    """Effective source state, layer identity and texture set resolution."""
    fill = STATE["fill"]
    sources = []
    for channel in STATE["channels"]:
        source = fill.get_source(channel)
        identifier = source.resource_id
        properties = source.get_properties()
        sources.append(
            {
                "resource": identifier.url(),
                "resource_id": {
                    "url": identifier.url(),
                    "context": identifier.context,
                    "name": identifier.name,
                    "version": identifier.version,
                },
                "parameters": source.get_parameters(),
                "inputs": list(source.image_inputs),
                "outputs": list(source.image_outputs),
                "presets": list(source.get_preset_list()),
                "input_sources": {n: described_input(source, n) for n in source.image_inputs},
                "properties": {name: described(properties[name]) for name in sorted(properties)},
                "active_output": source.active_output,
                "resolution": {
                    "mode": source.resolution.mode.name,
                    "value": list(source.resolution.value),
                    "log2_offset": source.resolution.log2_offset,
                },
                "opacity": fill.get_opacity(channel),
                "blending": fill.get_blending_mode(channel).name,
            }
        )
    projection = fill.get_projection_parameters()
    transform = projection.uv_transformation
    return {
        "channel_formats": {
            channel.name: STATE["stack"].get_channel(channel).format().name
            for channel in STATE["channels"]
        },
        "isolated_tree": {
            "roots": [node.uid() for node in sp.layerstack.get_root_layer_nodes(STATE["stack"])],
            "fill": fill.uid(),
            "visible": fill.is_visible(),
            "mask": fill.has_mask(),
            "content_effects": [node.uid() for node in fill.content_effects()],
            "mask_effects": [node.uid() for node in fill.mask_effects()],
        },
        "sources": sources,
        # The bitmaps a multi-output capture imported, by staged file: their ResourceID URLs.
        "bitmaps": {path: key.url() for path, key in STATE.get("bitmaps", {}).items()},
        "source_mode": fill.source_mode.name,
        "projection_mode": fill.get_projection_mode().name,
        "active_channels": sorted(c.name for c in fill.active_channels),
        "projection": {
            "filtering": projection.filtering_mode.name,
            "wrapping": projection.uv_wrapping_mode.name,
            "scale_mode": transform.scale_mode.name,
            "scale": list(transform.scale),
            "rotation": transform.rotation,
            "offset": list(transform.offset),
        },
        "sets": [
            {
                "name": t.name(),
                "resolution": [t.get_resolution().width, t.get_resolution().height],
                "has_uv_tiles": t.has_uv_tiles(),
            }
            for t in sp.textureset.all_texture_sets()
        ],
    }


def dispatch(operation: str, args: dict[str, Any]) -> Any:
    """Closed operation vocabulary, no source text or dynamic API names in payloads."""
    if operation in {
        "configure",
        "readback",
        "export",
        "close",
        "ready",
        "idle",
        "set_output",
        "preset_parameters",
        "contexts",
    }:
        check_owned()
    if operation == "identity":
        return identity()
    if operation == "refresh":
        sp.resource.Shelves.refresh_all()
        return None
    if operation == "catalog_ready":
        return not any(s.is_crawling() for s in sp.resource.Shelves.all())
    if operation == "lookup":
        return [
            {
                "url": r.identifier().url(),
                "type": r.type().name,
                "procedural": sp.resource.Usage.PROCEDURAL in r.usages(),
            }
            for r in sp.resource.search("")
            if r.identifier().url() == args["resource"]
        ]
    if operation == "create":
        if sp.project.is_open():
            raise RuntimeError("Painter already has an open project")
        STATE["owner"] = {"pid": os.getpid(), "mesh": args["mesh_path"]}
        sp.project.create(
            mesh_file_path=args["mesh_path"],
            settings=sp.project.Settings(
                default_texture_resolution=128,
                normal_map_format=sp.project.NormalMapFormat.OpenGL,
                tangent_space_mode=sp.project.TangentSpace.PerVertex,
                mesh_unit_scale=1.0,
            ),
        )
        return None
    if operation == "ready":
        return sp.project.is_in_edition_state() and not sp.project.is_busy()
    if operation == "idle":
        return not sp.project.is_busy()
    if operation == "configure":
        configure(args)
        return None
    if operation == "readback":
        return readback()
    if operation == "set_output":
        set_output(args["output"])
        return None
    if operation == "preset_parameters":
        return preset_parameters()
    if operation == "contexts":
        return contexts(args)
    if operation == "export":
        result = sp.export.export_project_textures(args)
        return {
            "status": result.status.name,
            "message": result.message,
            "files": [p for paths in result.textures.values() for p in paths],
        }
    if operation == "close":
        current = identity()
        if (
            current["pid"] != args["pid"]
            or not isinstance(current["mesh"], str)
            or os.path.normcase(os.path.abspath(current["mesh"]))
            != os.path.normcase(os.path.abspath(args["mesh"]))
        ):
            raise RuntimeError("Painter project ownership changed; current project left open")
        sp.project.close()
        return None
    raise ValueError("unknown snapshot operation")
