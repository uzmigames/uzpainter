"""Authored snapshot operations; executed only inside Painter's documented remote API."""

from __future__ import annotations

import os
from typing import Any

import substance_painter as sp
import substance_painter.application
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
        properties = source.get_properties()
        sources.append(
            {
                "resource": source.resource_id.url(),
                "parameters": source.get_parameters(),
                "inputs": list(source.image_inputs),
                "outputs": list(source.image_outputs),
                "presets": list(source.get_preset_list()),
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
    if operation in {"configure", "readback", "export", "close", "ready", "idle"}:
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
