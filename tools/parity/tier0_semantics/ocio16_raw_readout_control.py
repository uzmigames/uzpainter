"""Authored Raw readout/UNORM16 controls; offline preparation, never capture or fitting.

Calibration and normalization are separate experiments. A FLOAT EXR does not imply
an identity readout: equal PNG/EXR outputs establish only observable transfer in
the recorded context. Adjacent inputs occupy different RGB channels: interpreting
their differences as scalar readout collisions requires independent evidence of
channel invariance. Neither experiment identifies sRGB decoding or authorizes a
production capability.

Public contracts: Adobe SourceBitmap, colormanagement, Channel and Texture Set
settings documentation (2026-10-25); approved A-PYDOC/A-JSDOC and S-EXR. RGB32F
describes storage, not the User channel's independent Color channel flag. That
flag is unobserved, never presumed false. Raw must read back as GenericColorSpace
Raw; Data, strings and other enum classes are not aliases here.

All fixtures derive from complete integer domains, independently of private
differences. Capability requests contain no exports. Export requests remain
pending review and separate authorization; this module never launches Painter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.decode import Array
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, canonical_json
from tools.parity.recorder.probes import is_read
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, Golden, start
from tools.parity.tier0_semantics.fixtures import png16

PREFIX = "ocio16-raw-readout"
STATES = ("calibration-float", "normalization-png16", "normalization-float")
CHANNEL = "User0"
FILL = "substance_painter.layerstack.FillLayerNode."
NODE = "substance_painter.layerstack.Node."
LAYER = "substance_painter.layerstack.LayerNode."
BITMAP = "substance_painter.source.SourceBitmap."
ROOT_LAYERS = "substance_painter.layerstack.get_root_layer_nodes"
RAW = {"class": "GenericColorSpace", "name": "Raw"}
UV = {
    "filtering_mode": "Nearest",
    "uv_wrapping_mode": "Repeat",
    "scale_mode": "Factors",
    "scale": [1.0, 1.0],
    "rotation": 0.0,
    "offset": [0.0, 0.0],
}
NAME = "Authored Raw readout control"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def fixture_path(state: str) -> Path:
    require(state in STATES, "unknown authored state")
    extension = "png" if state == "normalization-png16" else "exr"
    return Path(FIXTURE_DIR) / "bitmaps" / f"{PREFIX}-{state}.{extension}"


def authored_values(state: str) -> Array:
    require(state in STATES, "unknown authored state")
    n = np.arange(65536, dtype=np.uint32).reshape(256, 256)
    if state == "calibration-float":
        center = (n.astype(np.float64) / 65535.0).astype(np.float32)
        return np.stack(
            (center, np.nextafter(center, np.float32(0)), np.nextafter(center, np.float32(1))),
            axis=-1,
        )
    codes = np.stack((n, (n + 21845) % 65536, (n + 43690) % 65536), axis=-1)
    if state == "normalization-png16":
        return codes.astype(np.uint16)
    return (codes.astype(np.float64) / 65535.0).astype(np.float32)


def write_fixture(state: str, path: Path) -> None:
    """Write an authored destination; caller owns its existing parent directory."""
    values = authored_values(state)
    require(path.parent.is_dir(), "fixture parent must already exist")
    if state == "normalization-png16":
        path.write_bytes(png16(256, 256, 3, lambda x, y: tuple(int(v) for v in values[y, x])))
        return
    import OpenEXR

    header = {
        "compression": OpenEXR.NO_COMPRESSION,
        "type": OpenEXR.scanlineimage,
        "lineOrder": OpenEXR.INCREASING_Y,
        "pixelAspectRatio": 1.0,
        "screenWindowCenter": np.array([0.0, 0.0], dtype=np.float32),
        "screenWindowWidth": 1.0,
    }
    channels = {c: np.ascontiguousarray(values[..., i]) for i, c in enumerate("RGB")}
    OpenEXR.File(header, channels).write(str(path))


def fixed_readbacks() -> dict[str, Any]:
    """Only literal authored values; runtime resource identity must be joined separately."""
    return {
        ROOT_LAYERS: [
            {
                "node_type": "FillLayer",
                "name": NAME,
                "visible": True,
                "has_mask": False,
                "Content": [],
                "Mask": [],
            }
        ],
        NODE + "get_name": NAME,
        NODE + "is_visible": True,
        NODE + "get_blending_mode": "Normal",
        NODE + "get_opacity": 1.0,
        LAYER + "get_geometry_mask": {"type": "Mesh", "inclusion_list": False, "items": []},
        LAYER + "has_mask": False,
        LAYER + "content_effects": [],
        FILL + "source_mode": "Split",
        FILL + "active_channels": [CHANNEL],
        FILL + "get_projection_mode": "UV",
        FILL + "get_projection_parameters": {
            "class": "UVProjectionParams",
            "filtering_mode": UV["filtering_mode"],
            "uv_wrapping_mode": UV["uv_wrapping_mode"],
            "uv_transformation": {k: UV[k] for k in ("scale_mode", "scale", "rotation", "offset")},
        },
        BITMAP + "get_color_space": RAW,
    }


def request(state: str, *, exports: bool = False, root: Path = REPO_ROOT) -> dict[str, Any]:
    path = fixture_path(state)
    name = f"{PREFIX}-{state}-{'export' if exports else 'capability'}-v2"
    s = start("plane", resolution=256)
    s.add("substance_painter.layerstack.delete_node", initial_root=True, expected_type="PaintLayer")
    s.channels(((CHANNEL, "RGB32F"),))
    imported = s.add(ps.IMPORT_RESOURCE, input=state, usage="TEXTURE")
    node = s.fill([CHANNEL], position="top", texture_set="uzp_plane")
    s.add(NODE + "set_name", node_step=node, name=NAME)
    s.add(NODE + "set_visible", node_step=node, visible=True)
    s.blend(node, CHANNEL, "Normal", 1.0)
    s.add(LAYER + "set_geometry_mask", node_step=node, inclusion_list=False, meshes=[])
    s.add(FILL + "set_projection_mode", node_step=node, projection_mode="UV")
    s.add(FILL + "set_projection_parameters", node_step=node, **UV)
    s.add(ps.SET_SOURCE, node_step=node, channel=CHANNEL, resource_step=imported)
    s.add(
        BITMAP + "set_color_space",
        node_step=node,
        channel=CHANNEL,
        color_space="GenericColorSpace.Raw",
    )
    for call in fixed_readbacks():
        args: dict[str, Any] = {} if call == ROOT_LAYERS else {"node_step": node}
        if call in (NODE + "get_blending_mode", NODE + "get_opacity", BITMAP + "get_color_space"):
            args["channel"] = CHANNEL
        if call == BITMAP + "get_color_space":
            args["typed"] = True
        s.add(call, **args)
    s.add(BITMAP + "list_available_color_spaces", node_step=node, channel=CHANNEL)
    s.add(ps.GET_SOURCE, node_step=node, channel=CHANNEL)
    if exports:
        s.add(
            EXPORT,
            maps=["documentMap/user0:RGB"],
            file_format="exr",
            bit_depth="32f",
            padding="passthrough",
            dithering=False,
            key_by_step=True,
        )
    description = (
        f"Offline authored {state} control; pending review and separate capture authorization. "
        "Capability-only requests precede exports. Pinned Substance OCIO configuration; "
        "default template, 256px public plane, User0 RGB32F, one visible Split fill, "
        "Normal opacity 1, neutral geometry, identity Nearest Repeat UV. Explicit enum "
        "GenericColorSpace.Raw must roundtrip exactly; Data/string aliases refuse. "
        "Color channel flag remains unobserved; format does not imply color management. "
        "Setup once; fresh getters in same_session and after Full save/reopen, no r2 setters. "
        "Template capture checks channels and resolution in each round. Resource identity "
        "must join the pinned import receipt, not a guessed URL. Calibration uses "
        "f32(n/65535) and adjacent floats toward 0/1 in different RGB channels; "
        "endpoints stay 0/1. Cross-channel differences do not establish scalar readout "
        "collisions without independent channel-invariance evidence. "
        "Normalization uses complete RGB codes "
        "n,(n+21845)%65536,(n+43690)%65536, n=256*y+x. PNG16 and normalized FLOAT EXR "
        "compare observable transfer only. No identity-readout assumption, sRGB-float, "
        "decoder identification, fit, tolerance tuning or production promotion. "
        "All pixel inputs are public formulas, never selected from private differences."
    )
    golden = Golden(
        name,
        "tier0/api-probes/" + PREFIX,
        description,
        "plane",
        ["plane"],
        s,
        [dict(rr.OCIO_SETTING)],
    )
    hashes = {"plane": hashlib.sha256((root / rr.fixture("plane")[1]).read_bytes()).hexdigest()}
    result = rr.request_manifest(golden, hashes, current_envelope(root))
    result["golden_id"] = "tier0/api-probes/" + name
    result["inputs"].append(
        {
            "input_id": state,
            "kind": "image",
            "path": path.as_posix(),
            "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
            "provenance": {
                "origin": "uzmigames_authored",
                "licence": "Apache-2.0",
                "note": (
                    "Public integer/float formulas in "
                    "tools/parity/tier0_semantics/ocio16_raw_readout_control.py; "
                    "no captured pixels."
                ),
            },
        }
    )
    return result


def validate_observed_state(
    recording: dict[str, Any], manifest: dict[str, Any], imported_resource: dict[str, str]
) -> None:
    """Pure state gate, not admission. Caller verifies authored manifest and receipt joins.

    `imported_resource` is the full identity from the verified import receipt; never
    inferred from a name. Capability approval also needs project topology review.
    """
    require(recording["condition"] in ("same_session", "after_save_reopen"), "recording condition")
    require(set(imported_resource) == {"context", "name", "version"}, "import identity fields")
    require(all(type(v) is str and v for v in imported_resource.values()), "import identity values")
    outputs = recording["outputs"]
    expected = fixed_readbacks()
    expected[ps.GET_SOURCE] = {"bitmap": {"resource": imported_resource}, "color_space": "Raw"}
    steps = [
        step
        for step in manifest["instruction_sequence"]["steps"]
        if is_read(step["call"], step["args"])
    ]
    for call in {*expected, BITMAP + "list_available_color_spaces"}:
        require(sum(step["call"] == call for step in steps) == 1, "required authored readback")
    for step in steps:
        call = step["call"]
        if call not in expected and call != BITMAP + "list_available_color_spaces":
            continue
        matches = [
            o
            for o in outputs
            if o.get("kind") == "api_readback"
            and o.get("output_id") == f"s{step['step']}/{call.rsplit('.', 1)[1]}"
        ]
        require(len(matches) == 1, "readback identity")
        found = matches[0]
        require(
            "raised" not in found
            and found.get("call") == call
            and canonical_json(found.get("args")) == canonical_json(step["args"]),
            "readback context",
        )
        if call == BITMAP + "list_available_color_spaces":
            names = found.get("value")
            require(
                type(names) is list
                and all(type(n) is str for n in names)
                and names.count("Raw") == 1,
                "Raw availability",
            )
        else:
            require(
                canonical_json(found.get("value")) == canonical_json(expected[call]),
                "authored readback differs",
            )
    templates = [
        o
        for o in outputs
        if o.get("kind") == "template_capture" and o.get("output_id") == "template/texture-sets"
    ]
    require(len(templates) == 1, "template identity")
    sets = templates[0]["values"]["texture_sets"]
    require(set(sets) == {"uzp_plane"}, "texture set identity")
    texture = sets["uzp_plane"]
    require(
        canonical_json(texture["resolution"]) == canonical_json([256, 256]), "texture resolution"
    )
    require(len(texture["stacks"]) == 1, "stack count")
    channel = next(iter(texture["stacks"].values()))[CHANNEL]
    require(
        canonical_json({k: channel[k] for k in ("format", "bit_depth", "is_color", "is_floating")})
        == canonical_json(
            {"format": "RGB32F", "bit_depth": 32, "is_color": True, "is_floating": True}
        ),
        "channel format",
    )


def write_authored() -> None:
    for state in STATES:
        write_fixture(state, REPO_ROOT / fixture_path(state))
    directory = rr.request_root(REPO_ROOT) / "tier0/api-probes"
    require(directory.is_dir(), "request parent must already exist")
    for exports in (False, True):
        for state in STATES:
            manifest = request(state, exports=exports)
            path = directory / (manifest["golden_id"].rsplit("/", 1)[1] + ".json")
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    write_authored()


if __name__ == "__main__":
    main()
