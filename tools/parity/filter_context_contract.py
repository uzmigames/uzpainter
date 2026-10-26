"""Closed F readback evidence, not V1 import or permission to accept a real capture."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from tools.parity.recorder.job import canonical_json

SCHEMA = "uzpainter/parity/filter-context-readback/1"
BOUNDARIES = ("after-create", "after-setup6", "pre16-r1", "after-reopen", "pre16-r2")
CONDITIONS = {
    name: "after_save_reopen" if name in BOUNDARIES[3:] else "same_session" for name in BOUNDARIES
}
MISSING_SETTINGS = ("tangent_space", "workflow", "mesh_unit_scale")
# Typed canonical instruction_sequence of source_substance_control.booleans_filter_request.
# Tests compare this pin to the public recipe; validating evidence performs no file access.
A_RECIPE_SHA256 = "b7758f5b14fd4c5c06780f087dc23dee4269529c37cfc512334ebd389ed6a083"
# Public BlendingMode vocabulary in src/uzp_core/types/enums.h.
BLENDING_MODES = frozenset(
    [
        "Normal",
        "PassThrough",
        "Disable",
        "Replace",
        "Multiply",
        "Divide",
        "InverseDivide",
        "Darken",
        "Lighten",
        "LinearDodge",
        "Subtract",
        "InverseSubtract",
        "Difference",
        "Exclusion",
        "SignedAddition",
        "Overlay",
        "Screen",
        "LinearBurn",
        "ColorBurn",
        "ColorDodge",
        "SoftLight",
        "HardLight",
        "VividLight",
        "LinearLight",
        "PinLight",
        "Tint",
        "Saturation",
        "Color",
        "Value",
        "NormalMapCombine",
        "NormalMapDetail",
        "NormalMapInverseDetail",
    ]
)
# Public ChannelType vocabulary in src/uzp_core/types/enums.h.
CHANNEL_TYPES = frozenset(
    [
        "AO",
        "AbsorptionColor",
        "Anisotropyangle",
        "Anisotropylevel",
        "BaseColor",
        "BaseDiffuseRoughness",
        "BaseMetalness",
        "BaseWeight",
        "BlendingMask",
        "CoatColor",
        "CoatNormal",
        "CoatOpacity",
        "CoatRoughness",
        "CoatRoughnessAnisotropy",
        "CoatSpecularLevel",
        "CoatTangent",
        "CoatWeight",
        "Diffuse",
        "Displacement",
        "EmissionColor",
        "Emissive",
        "FuzzColor",
        "FuzzRoughness",
        "FuzzWeight",
        "Glossiness",
        "Height",
        "Ior",
        "Metallic",
        "Normal",
        "Opacity",
        "Reflection",
        "Roughness",
        "Scattering",
        "ScatteringColor",
        "SheenColor",
        "SheenOpacity",
        "SheenRoughness",
        "Specular",
        "SpecularColor",
        "SpecularEdgeColor",
        "SpecularRoughness",
        "SpecularRoughnessAnisotropy",
        "SpecularWeight",
        "Specularlevel",
        "SubsurfaceColor",
        "SubsurfaceRadiusScale",
        "SubsurfaceWeight",
        "Tangent",
        "ThinFilmWeight",
        "Translucency",
        "TransmissionColor",
        "TransmissionWeight",
        "Transmissive",
        "User0",
        "User1",
        "User10",
        "User11",
        "User12",
        "User13",
        "User14",
        "User15",
        "User16",
        "User17",
        "User18",
        "User19",
        "User2",
        "User20",
        "User21",
        "User22",
        "User23",
        "User24",
        "User25",
        "User26",
        "User27",
        "User28",
        "User29",
        "User3",
        "User30",
        "User31",
        "User4",
        "User5",
        "User6",
        "User7",
        "User8",
        "User9",
    ]
)
PREFIX = "substance_painter."
# Public ChannelFormat enum; bit depth describes one component, not the pixel.
CHANNEL_DEPTHS = {
    "sRGB8": 8,
    "L8": 8,
    "RGB8": 8,
    "L16": 16,
    "RGB16": 16,
    "L16F": 16,
    "RGB16F": 16,
    "L32F": 32,
    "RGB32F": 32,
}
NODE = PREFIX + "layerstack.Node."
SOURCE = PREFIX + "source.SourceSubstance."
SPEC = {
    "project": [
        PREFIX + "project." + name
        for name in ("get_uuid", "last_imported_mesh_path", "is_open", "needs_saving")
    ]
    + [PREFIX + "textureset.all_texture_sets"],
    "set": [
        PREFIX + "textureset.TextureSet." + name
        for name in ("name", "get_resolution", "all_stacks")
    ],
    "stack": [PREFIX + "textureset.Stack." + name for name in ("name", "all_channels")]
    + [PREFIX + "layerstack.get_root_layer_nodes"],
    "channel": [
        PREFIX + "textureset.Channel." + name
        for name in ("format", "bit_depth", "is_color", "is_floating", "label")
    ],
    "node": [
        NODE + name
        for name in ("uid", "get_type", "get_name", "is_visible", "get_parent", "is_in_mask_stack")
    ],
    "layer": [
        PREFIX + "layerstack.LayerNode." + name
        for name in ("has_mask", "content_effects", "mask_effects", "get_geometry_mask")
    ],
    "fill": [
        PREFIX + "layerstack.FillLayerNode." + name
        for name in (
            "source_mode",
            "active_channels",
            "get_projection_mode",
            "get_projection_parameters",
            "is_symmetry_enabled",
            "get_symmetry_parameters",
        )
    ],
    "filter": [PREFIX + "layerstack.FilterEffectNode.active_channels"],
    "source": [
        SOURCE + name
        for name in (
            "get_parameters",
            "resource_id",
            "image_inputs",
            "image_outputs",
            "active_output",
            "resolution",
        )
    ],
    "blend": [NODE + "get_blending_mode", NODE + "get_opacity"],
}
RESOLVE = PREFIX + "layerstack.get_node_by_uid"
SUBLAYERS = PREFIX + "layerstack.GroupLayerNode.sub_layers"
ALLOWED_CALLS = frozenset(call for group in SPEC.values() for call in group) | {
    RESOLVE,
    SUBLAYERS,
    SOURCE + "get_source",
}


class ContextRefused(ValueError):
    """Closed evidence or a required F predicate is unavailable."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContextRefused(reason)


def closed(value: Any, keys: set[str], reason: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == keys, reason)
    return cast(dict[str, Any], value)


def typed(value: Any) -> bytes:
    if type(value) is int:
        require(-(1 << 63) <= value < (1 << 63), "integer outside int64")
    elif type(value) is float:
        require(math.isfinite(value), "nonfinite context number")
    elif isinstance(value, dict):
        for key, item in value.items():
            require(type(key) is str, "context key is not text")
            typed(key)
            typed(item)
    elif isinstance(value, list):
        for item in value:
            typed(item)
    else:
        require(value is None or type(value) in (bool, str), "unsupported context value")
        if type(value) is str:
            value.encode("utf-8")
    return canonical_json(value)


def parse_context_readback(data: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate context key")
            result[key] = value
        return result

    def floating(token: str) -> float:
        value = float(token)
        require(
            math.isfinite(value) and (value != 0.0 or Decimal(token).is_zero()),
            "invalid context float",
        )
        return value

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=floating)
        return validate_context_readback(value)
    except (UnicodeError, json.JSONDecodeError):
        raise ContextRefused("invalid UTF-8 context JSON") from None


def selector_scope(selector: Any) -> str:
    require(type(selector) is dict, "invalid context selector")
    keys = set(selector)
    if keys == set():
        return "project"
    if keys in ({"role"}, {"role", "source"}):
        require(selector["role"] in ("host", "filter"), "unknown role")
        if "source" in selector:
            require(selector["source"] is True, "invalid source selector")
            return "source"
        return "role"
    require(
        keys
        in (
            {"set"},
            {"set", "stack"},
            {"set", "stack", "channel"},
            {"set", "stack", "path"},
            {"set", "stack", "path", "parent"},
        ),
        "unknown context selector fields",
    )
    for key in ("set", "stack"):
        if key in selector:
            require(type(selector[key]) is int and selector[key] >= 0, "invalid set/stack index")
    if "channel" in selector:
        require(type(selector["channel"]) is str and bool(selector["channel"]), "invalid channel")
        return "channel"
    if "path" in selector:
        path = selector["path"]
        require(type(path) is list and bool(path), "missing node path")
        for index, part in enumerate(path):
            require(
                type(part) is list
                and len(part) == 2
                and part[0] in (("Root",) if index == 0 else ("Content", "Mask", "Substack"))
                and type(part[1]) is int
                and part[1] >= 0,
                "invalid node path",
            )
        if "parent" in selector:
            require(selector["parent"] is True, "invalid parent selector")
            return "parent"
        return "node"
    return "stack" if "stack" in selector else "set"


def leaf_key(call: str, selector: dict[str, Any], parameters: dict[str, Any]) -> bytes:
    return typed([call, selector, parameters])


def validate_context_readback(value: Any) -> dict[str, Any]:
    typed(value)
    frame = closed(value, {"schema", "boundary", "condition", "outputs"}, "context envelope fields")
    require(
        frame["schema"] == SCHEMA and frame["boundary"] in BOUNDARIES, "context schema/boundary"
    )
    boundary = frame["boundary"]
    require(frame["condition"] == CONDITIONS[boundary], "boundary condition differs")
    require(type(frame["outputs"]) is list and bool(frame["outputs"]), "context outputs missing")
    seen: set[bytes] = set()
    for index, output in enumerate(frame["outputs"]):
        require(type(output) is dict, "context output is not an object")
        keys = {"output_id", "kind", "call", "args", "value"}
        if "raised" in output:
            keys.add("raised")
            error = closed(output["raised"], {"type", "message"}, "context exception fields")
            require(
                all(type(item) is str for item in error.values()) and output["value"] is None,
                "invalid raised context outcome",
            )
        closed(output, keys, "context output fields")
        call = output["call"]
        require(type(call) is str and call in ALLOWED_CALLS, "unknown context getter")
        require(
            output["kind"] == "api_readback"
            and output["output_id"] == f"context/{boundary}/{index:04d}-{call.rsplit('.', 1)[1]}",
            "context output identity",
        )
        args = closed(output["args"], {"selector", "parameters"}, "context argument fields")
        scope = selector_scope(args["selector"])
        parameters = args["parameters"]
        require(type(parameters) is dict, "context parameters")
        allowed = set(SPEC.get(scope, []))
        if scope == "node":
            allowed |= set(SPEC["layer"] + SPEC["fill"] + SPEC["filter"] + SPEC["blend"]) | {
                SUBLAYERS,
                RESOLVE,
            }
        elif scope == "role":
            allowed = {RESOLVE, NODE + "uid"}
        elif scope == "parent":
            allowed = {NODE + "uid"}
        elif scope == "source":
            allowed.add(SOURCE + "get_source")
        require(call in allowed, "getter does not belong to selector")
        expected_parameters = (
            {"uid"}
            if call == RESOLVE
            else {"channel"}
            if call in SPEC["blend"]
            else {"input_identifier"}
            if call == SOURCE + "get_source"
            else set()
        )
        closed(parameters, expected_parameters, "getter parameters differ")
        if "uid" in parameters:
            require(
                type(parameters["uid"]) is int and 0 < parameters["uid"] < (1 << 63),
                "invalid lookup UID",
            )
        if "channel" in parameters:
            require(
                type(parameters["channel"]) is str or parameters["channel"] is None,
                "invalid blend channel",
            )
        if "input_identifier" in parameters:
            require(
                type(parameters["input_identifier"]) is str
                and bool(parameters["input_identifier"]),
                "invalid image input identifier",
            )
        key = leaf_key(call, args["selector"], parameters)
        require(key not in seen, "duplicate context leaf")
        seen.add(key)
    return frame


def _index(frame: dict[str, Any]) -> dict[bytes, dict[str, Any]]:
    return {
        leaf_key(out["call"], out["args"]["selector"], out["args"]["parameters"]): out
        for out in frame["outputs"]
    }


def _value(
    rows: dict[bytes, dict[str, Any]],
    call: str,
    selector: dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> Any:
    output = rows.get(leaf_key(call, selector, parameters or {}))
    require(output is not None and "raised" not in output, "required context getter unavailable")
    assert output is not None
    return output["value"]


@dataclass(frozen=True)
class FContextEvidence:
    """Structurally checked observations; absent effective settings still block acceptance."""

    contexts: tuple[dict[str, Any], ...] = field(repr=False)
    initial_paint_uid: int
    missing_effective_settings: tuple[str, ...] = field(default=MISSING_SETTINGS, init=False)


def validate_context_sequence(
    recipe: dict[str, Any], trace: list[dict[str, Any]], contexts: list[dict[str, Any]]
) -> FContextEvidence:
    """Check exact A operations and boundaries; no verdict about native destination or H."""
    require(
        hashlib.sha256(typed(recipe)).hexdigest() == A_RECIPE_SHA256, "not the unchanged recipe A"
    )
    steps = recipe["steps"]
    expected: list[dict[str, Any]] = []
    for step in steps[:6]:
        expected.append(
            {
                "kind": "step",
                "condition": "same_session",
                "step": step["step"],
                "call": step["call"],
                "args": step["args"],
            }
        )
        if step["step"] in (1, 6):
            expected.append(
                {
                    "kind": "context",
                    "boundary": "after-create" if step["step"] == 1 else "after-setup6",
                }
            )
    for round_index, condition in enumerate(("same_session", "after_save_reopen"), 1):
        if round_index == 2:
            expected += [{"kind": event} for event in ("save", "close", "open", "rebind")]
            expected.append({"kind": "context", "boundary": "after-reopen"})
        for step in steps[6:]:
            if step["step"] == 16:
                expected.append({"kind": "context", "boundary": f"pre16-r{round_index}"})
            expected.append(
                {
                    "kind": "step",
                    "condition": condition,
                    "step": step["step"],
                    "call": step["call"],
                    "args": step["args"],
                }
            )
    operations: list[dict[str, Any]] = []
    for event in trace:
        require(type(event) is dict, "invalid F trace event")
        operation = dict(event)
        if event.get("kind") != "context":
            require("outcome" in operation, "F operation outcome missing")
            outcome = operation.pop("outcome")
            require(type(outcome) is dict, "invalid F operation outcome")
            closed(
                outcome,
                {"value", "raised"} if "raised" in outcome else {"value"},
                "F outcome fields",
            )
            if "raised" in outcome:
                error = closed(
                    outcome["raised"], {"type", "message"}, "F operation exception fields"
                )
                require(
                    outcome["value"] is None
                    and all(type(value) is str for value in error.values()),
                    "F operation exception",
                )
                require(
                    event.get("kind") == "step"
                    and type(event.get("step")) is int
                    and event["step"] >= 7,
                    "F setup/reopen operation failed",
                )
        operations.append(operation)
    typed(trace)
    require(
        typed(operations) == typed(expected), "F lifecycle differs from setup-once/probes-twice"
    )
    frames = tuple(validate_context_readback(frame) for frame in contexts)
    require(
        tuple(frame["boundary"] for frame in frames) == BOUNDARIES, "context boundary order differs"
    )
    censuses = [validate_census(frame) for frame in frames]
    initial = censuses[0]
    require(
        len(initial) == 1 and initial[0]["type"] == "PaintLayer",
        "fresh initial Paint baseline missing",
    )
    paint_uid = initial[0]["uid"]
    paint_name = initial[0]["name"]
    setup_rows = _index(frames[1])
    host_uid = _value(setup_rows, NODE + "uid", {"role": "host"})
    filter_uid = _value(setup_rows, NODE + "uid", {"role": "filter"})
    uuid = _value(_index(frames[0]), PREFIX + "project.get_uuid", {})
    for frame, census in zip(frames[1:], censuses[1:], strict=True):
        rows = _index(frame)
        require(
            _value(rows, PREFIX + "project.get_uuid", {}) == uuid,
            "F project changed across lifecycle",
        )
        require(
            _value(rows, NODE + "uid", {"role": "host"}) == host_uid
            and _value(rows, NODE + "uid", {"role": "filter"}) == filter_uid,
            "F role UIDs changed after setup6",
        )
        require(len({host_uid, filter_uid, paint_uid}) == 3, "F role UIDs collide")
        require(
            [(node["type"], node["uid"], node["path"]) for node in census]
            == [
                ("FillLayer", host_uid, [["Root", 0]]),
                ("FilterEffect", filter_uid, [["Root", 0], ["Content", 0]]),
                ("PaintLayer", paint_uid, [["Root", 1]]),
            ],
            "F roots or role ownership differ",
        )
        require(census[2]["name"] == paint_name, "initial Paint name changed")
    return FContextEvidence(frames, paint_uid)


def require_effective_settings(evidence: FContextEvidence) -> None:
    # This protocol records documented getters only. It has no authenticated effective-settings
    # transport for these omissions in unchanged A; callers cannot override the missing values.
    for frame in evidence.contexts:
        validate_context_readback(frame)
    # No leaf in protocol /1 establishes these settings. Recompute the gap from the protocol,
    # never accept an empty missing-values list supplied by a caller as approval.
    raise ContextRefused("F_EFFECTIVE_SETTINGS_UNVERIFIED: " + ", ".join(MISSING_SETTINGS))


def validate_census(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify complete getter coverage, fresh lookups, parent UIDs and the observable F domain."""
    validate_context_readback(frame)
    rows = _index(frame)
    used: set[bytes] = set()

    def take(
        call: str,
        selector: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        *,
        raised: bool = False,
    ) -> Any:
        key = leaf_key(call, selector, parameters or {})
        require(key in rows, "required context leaf missing")
        used.add(key)
        if raised:
            return rows[key]["value"]
        return _value(rows, call, selector, parameters)

    for call in SPEC["project"]:
        take(call, {})
    require(take(PREFIX + "project.is_open", {}) is True, "F project is not open")
    require(
        type(take(PREFIX + "project.get_uuid", {})) is str
        and bool(take(PREFIX + "project.get_uuid", {})),
        "F project UUID missing",
    )
    sets = take(SPEC["project"][-1], {})
    require(type(sets) is list and len(sets) == 1, "F requires one texture set")
    set_selector = {"set": 0}
    for call in SPEC["set"]:
        take(call, set_selector)
    resolution = take(SPEC["set"][1], set_selector)
    closed(resolution, {"class", "width", "height"}, "resolution serializer fields")
    require(
        type(resolution) is dict
        and type(resolution.get("width")) is int
        and type(resolution.get("height")) is int
        and resolution["width"] == resolution["height"] == 128,
        "F texture resolution differs",
    )
    stacks = take(SPEC["set"][2], set_selector)
    require(type(stacks) is list and len(stacks) == 1, "F requires one stack")
    stack = {"set": 0, "stack": 0}
    for call in SPEC["stack"]:
        take(call, stack)
    channels = take(SPEC["stack"][1], stack)
    require(type(channels) is dict and bool(channels), "F channel census missing")
    require(set(channels) <= CHANNEL_TYPES, "F unknown stack channel")
    for channel in channels:
        selector = {**stack, "channel": channel}
        for call in SPEC["channel"]:
            take(call, selector)
        channel_format, depth, color, floating, label = [
            take(call, selector) for call in SPEC["channel"]
        ]
        require(
            type(channel_format) is str
            and channel_format in CHANNEL_DEPTHS
            and type(depth) is int
            and depth == CHANNEL_DEPTHS[channel_format]
            and type(color) is bool
            and type(floating) is bool
            and floating == channel_format.endswith("F")
            and type(label) is str,
            "F channel getter types or format differ",
        )
    roots = take(SPEC["stack"][2], stack)
    require(type(roots) is list, "F root census missing")
    census: list[dict[str, Any]] = []
    uids: set[int] = set()

    def visit(path: list[list[Any]], parent_uid: int | None, descriptor: Any) -> None:
        selector = {**stack, "path": path}
        uid = take(NODE + "uid", selector)
        require(
            type(uid) is int and 0 < uid < (1 << 63) and uid not in uids,
            "invalid or duplicate F node UID",
        )
        uids.add(uid)
        resolved = take(RESOLVE, selector, {"uid": uid})
        for call in SPEC["node"]:
            take(call, selector)
        node_type = take(NODE + "get_type", selector)
        name = take(NODE + "get_name", selector)
        require(
            type(name) is str
            and type(resolved) is dict
            and resolved == {"node_type": node_type, "name": name},
            "fresh handle differs from census",
        )
        require(resolved == descriptor, "enumerated node differs from fresh handle")
        require(
            take(NODE + "is_visible", selector) is True
            and take(NODE + "is_in_mask_stack", selector) is False,
            "F node visibility or mask role differs",
        )
        parent = take(NODE + "get_parent", selector)
        if parent_uid is None:
            require(parent is None, "root has a parent")
        else:
            observed_parent = take(NODE + "uid", {**selector, "parent": True})
            require(
                type(parent) is dict
                and type(observed_parent) is int
                and observed_parent == parent_uid,
                "parent UID differs from traversal",
            )
        census.append({"uid": uid, "type": node_type, "name": name, "path": path})
        require(
            node_type in ("PaintLayer", "FillLayer", "FilterEffect"),
            "F node type outside closed domain",
        )
        child_nodes: list[Any] = []
        if node_type in ("PaintLayer", "FillLayer"):
            for call in SPEC["layer"]:
                take(call, selector)
            require(
                take(SPEC["layer"][0], selector) is False
                and take(SPEC["layer"][2], selector) == [],
                "F mask structure differs",
            )
            geometry = closed(
                take(SPEC["layer"][3], selector),
                {"class", "inclusion_list", "meshes"},
                "geometry serializer fields",
            )
            require(
                geometry["class"] == "GeometryMaskMeshParams"
                and geometry["inclusion_list"] is False
                and geometry["meshes"] == [],
                "unsupported geometry mask",
            )
            child_nodes = take(SPEC["layer"][1], selector)
            require(type(child_nodes) is list, "F content census missing")
            if node_type == "PaintLayer":
                require(child_nodes == [], "initial Paint has content effects")
        if node_type == "FillLayer":
            for call in SPEC["fill"]:
                take(
                    call,
                    selector,
                    raised=call.endswith((".is_symmetry_enabled", ".get_symmetry_parameters")),
                )
            for call in SPEC["fill"][-2:]:
                outcome = rows[leaf_key(call, selector, {})]
                require(
                    "raised" not in outcome or outcome["raised"]["type"] == "ValueError",
                    "F UV symmetry unavailable for undocumented reason",
                )
            enabled = rows[leaf_key(SPEC["fill"][-2], selector, {})]
            require(
                "raised" in enabled or enabled["value"] is False,
                "F host symmetry must be disabled",
            )
            require(
                take(SPEC["fill"][0], selector) == "Split"
                and take(SPEC["fill"][1], selector) == ["User0"],
                "F host source channels differ",
            )
            require(take(SPEC["fill"][2], selector) == "UV", "F host projection differs")
            projection = closed(
                take(SPEC["fill"][3], selector),
                {"class", "filtering_mode", "uv_wrapping_mode", "uv_transformation"},
                "UV projection serializer fields",
            )
            transform = closed(
                projection["uv_transformation"],
                {"scale_mode", "scale", "rotation", "offset"},
                "nested UV transform fields",
            )
            require(
                projection["class"] == "UVProjectionParams"
                and projection["filtering_mode"] == "BilinearHQ"
                and projection["uv_wrapping_mode"] == "Repeat"
                and transform["scale_mode"] == "Factors",
                "F UV mode outside target domain",
            )
            for key, expected in (("scale", [1, 1]), ("offset", [0, 0])):
                require(
                    type(transform[key]) is list
                    and len(transform[key]) == 2
                    and all(type(item) in (int, float) for item in transform[key])
                    and transform[key] == expected,
                    "F UV transform outside identity domain",
                )
            require(
                type(transform["rotation"]) in (int, float) and transform["rotation"] == 0,
                "F UV rotation outside identity domain",
            )
            require(
                take(SPEC["channel"][0], {**stack, "channel": "User0"}) == "L32F",
                "F User0 format differs",
            )
        active = ["User0"] if node_type == "FillLayer" else []
        if node_type == "FilterEffect":
            active = take(SPEC["filter"][0], selector)
            require(
                type(active) is list
                and bool(active)
                and all(type(channel) is str and channel in channels for channel in active)
                and len(set(active)) == len(active)
                and active == sorted(active, key=json.dumps),
                "F Filter active channels differ",
            )
        for channel in channels:
            for call in SPEC["blend"]:
                take(call, selector, {"channel": channel}, raised=True)
            if channel in active:
                mode = take(SPEC["blend"][0], selector, {"channel": channel})
                opacity = take(SPEC["blend"][1], selector, {"channel": channel})
                require(
                    type(mode) is str
                    and mode in BLENDING_MODES
                    and type(opacity) in (int, float)
                    and math.isfinite(opacity)
                    and 0 <= opacity <= 1,
                    "F active channel blending differs",
                )
                if node_type == "FillLayer":
                    require(mode == "Normal" and opacity == 1, "F host blending is not neutral")
        for index, descriptor in enumerate(child_nodes):
            visit([*path, ["Content", index]], uid, descriptor)

    for index, descriptor in enumerate(roots):
        visit([["Root", index]], None, descriptor)
    if frame["boundary"] != "after-create":
        for role in ("host", "filter"):
            uid = take(NODE + "uid", {"role": role})
            require(type(uid) is int and uid in uids, "role UID is absent from census")
            node = next(node for node in census if node["uid"] == uid)
            require(
                take(RESOLVE, {"role": role}, {"uid": uid})
                == {"node_type": node["type"], "name": node["name"]},
                "role lookup differs from census",
            )
            selector = {"role": role, "source": True}
            for call in SPEC["source"]:
                take(
                    call,
                    selector,
                    raised=role == "filter" and call.endswith((".active_output", ".resolution")),
                )
            parameters = take(SOURCE + "get_parameters", selector)
            require(
                type(parameters) is dict
                and all(type(value) in (int, float, str) for value in parameters.values()),
                "F source parameters outside scalar domain",
            )
            identity = closed(
                take(SOURCE + "resource_id", selector),
                {"resource_id", "url"},
                "source identity fields",
            )
            wrapped = closed(identity["resource_id"], {"resource"}, "resource identity wrapper")
            resource = closed(
                wrapped["resource"], {"context", "name", "version"}, "resource identity parts"
            )
            require(
                all(
                    type(value) is str and value for value in [identity["url"], *resource.values()]
                ),
                "incomplete source identity",
            )
            outputs = take(SOURCE + "image_outputs", selector)
            require(
                type(outputs) is list
                and all(type(item) is str and item for item in outputs)
                and len(set(outputs)) == len(outputs),
                "invalid image output list",
            )
            resolution_row = rows[leaf_key(SOURCE + "resolution", selector, {})]
            if "raised" not in resolution_row:
                source_resolution = closed(
                    resolution_row["value"],
                    {"mode", "value", "value_kind", "log2_offset"},
                    "source resolution fields",
                )
                require(
                    type(source_resolution["mode"]) is str
                    and source_resolution["value_kind"] in ("tuple", "list", "other")
                    and type(source_resolution["log2_offset"]) is int,
                    "source resolution types",
                )
            identifiers = take(SOURCE + "image_inputs", selector)
            require(
                type(identifiers) is list
                and all(type(item) is str and item for item in identifiers)
                and len(set(identifiers)) == len(identifiers),
                "invalid image input slots",
            )
            for identifier in identifiers:
                take(SOURCE + "get_source", selector, {"input_identifier": identifier})
            require(not identifiers, "F_CONTEXT_DOMAIN_UNSUPPORTED: image input bindings")
    require(used == set(rows), "unexpected context leaves or selectors")
    return census
