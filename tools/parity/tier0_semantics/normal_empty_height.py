"""Decision 245 section 2's recording: a virtual Normal on the islanded sphere with no Height layer.

An API probe golden, so that the stack's precondition is observed rather than assumed. A fresh
`project.create` holds one initial Paint layer, whose Height channel would be a Height layer; the
guarded one-shot cleanup (`painter_probes.remove_initial_paint`, step 2) deletes it and records an
empty root list. Then the authored 16-bit normal-b is bound as the Normal mesh map, and one fill
with only Normal active carries normal-a. The probe steps read the full public layer tree, the
fill's state and both resource joins in the session that built the state (r1) and again after
save and reopen (r2), without replaying a setter; the captures export Normal_OpenGL at PNG 16
and OpenEXR 32f under infinite and passthrough padding, each twice in the recording, and one
OpenEXR 32f infinite control of Height, the Normal channel and the bound mesh map, twice too.

`validate_observed_state` is the pure void gate of one recording, `validate_cleanup` that of the
cleanup's r1 receipt, and `validate_pair` both plus the agreement of r1 and r2 on what is
measured rather than authored. The caller verifies the manifest and the import receipt they are
given. None of them admits or scores anything; the
expected pixels and the predictions are declared in
parity/reports/phase1/normal-empty-height-freeze.md before any capture. This module never
launches Painter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, canonical_json
from tools.parity.recorder.probes import is_read
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.corpus import Golden, Sequence, start
from tools.parity.tier0_semantics.ocio16_raw_readout_control import (
    FILL,
    LAYER,
    NODE,
    PROJECT_UUID,
    RESOURCE_FROM_PROJECT,
    RESOURCE_RETRIEVE,
    ROOT_LAYERS,
    UV,
)

NAME = "export-padding-normal-empty-height"
DOMAIN = "tier0/api-probes/" + NAME
MESH = "sphere"
TEXTURE_SET = "uzp_sphere"
CHANNEL = "Normal"
FILL_INPUT = "normal-a"
MESH_MAP_INPUT = "normal-b"
INPUTS = (MESH, FILL_INPUT, MESH_MAP_INPUT)
LAYER_NAME = "Authored Normal-only fill"
NORMAL_MAPS = ["virtualMap/Normal_OpenGL:RGB"]
CONTROL_MAPS = ["documentMap/height:L", "documentMap/normal:RGB", "meshMap/normal_base:RGB"]
# (maps, file format, bit depth, padding) of each capture, every one done twice in a row.
CAPTURES = (
    (NORMAL_MAPS, "png", 16, "infinite"),
    (NORMAL_MAPS, "png", 16, "passthrough"),
    (NORMAL_MAPS, "exr", "32f", "infinite"),
    (NORMAL_MAPS, "exr", "32f", "passthrough"),
    (CONTROL_MAPS, "exr", "32f", "infinite"),
)
CONDITIONS = ("same_session", "after_save_reopen")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def fixed_readbacks() -> dict[str, Any]:
    """The authored state every recording must read back exactly; resource joins come apart."""
    return {
        ROOT_LAYERS: [
            {
                "node_type": "FillLayer",
                "name": LAYER_NAME,
                "visible": True,
                "has_mask": False,
                "Content": [],
                "Mask": [],
            }
        ],
        NODE + "get_name": LAYER_NAME,
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
    }


def readback_args(call: str, node: int) -> dict[str, Any]:
    args: dict[str, Any] = {} if call == ROOT_LAYERS else {"node_step": node}
    if call in (NODE + "get_blending_mode", NODE + "get_opacity"):
        args["channel"] = CHANNEL
    return args


def sequence() -> Sequence:
    s = start(MESH)
    s.add("substance_painter.layerstack.delete_node", initial_root=True, expected_type="PaintLayer")
    fill_import = s.add(ps.IMPORT_RESOURCE, input=FILL_INPUT, usage="TEXTURE")
    map_import = s.add(ps.IMPORT_RESOURCE, input=MESH_MAP_INPUT, usage="TEXTURE")
    s.add(ps.SET_MESH_MAP, usage=CHANNEL, resource_step=map_import)
    node = s.fill([CHANNEL], position="top", texture_set=TEXTURE_SET)
    s.add(NODE + "set_name", node_step=node, name=LAYER_NAME)
    s.add(NODE + "set_visible", node_step=node, visible=True)
    s.blend(node, CHANNEL, "Normal", 1.0)
    s.add(LAYER + "set_geometry_mask", node_step=node, inclusion_list=False, meshes=[])
    s.add(FILL + "set_projection_mode", node_step=node, projection_mode="UV")
    s.add(FILL + "set_projection_parameters", node_step=node, **UV)
    s.add(ps.SET_SOURCE, node_step=node, channel=CHANNEL, resource_step=fill_import)
    for call in fixed_readbacks():
        s.add(call, **readback_args(call, node))
    s.add(PROJECT_UUID, owned_project=True)
    for imported in (fill_import, map_import):
        query = s.add(RESOURCE_FROM_PROJECT, import_step=imported)
        s.add(RESOURCE_RETRIEVE, resource_step=query)
    s.add(ps.GET_SOURCE, node_step=node, channel=CHANNEL)
    s.add(ps.GET_MESH_MAP, usage=CHANNEL)
    for maps, file_format, bit_depth, padding in CAPTURES:
        for _ in range(2):
            s.add(
                EXPORT,
                maps=list(maps),
                file_format=file_format,
                bit_depth=bit_depth,
                padding=padding,
                dithering=False,
                key_by_step=True,
            )
    return s


DESCRIPTION = (
    "Decision 245 section 2's recording (phase1.25_pilot-wand item 2.7): a virtual Normal on a "
    "UV-islanded set whose Height has no layer, with a bound Normal mesh map, under Legacy at "
    "256 px, OpenGL. API probe golden on the authored sphere (one set uzp_sphere, pole rows "
    "half covered): the initial Paint root is deleted by the guarded one-shot cleanup (step 2, "
    "owned create, exactly one PaintLayer, no root left); the authored 16-bit normal-b is bound "
    "as the Normal mesh map; one visible Split fill with only Normal active carries the authored "
    "16-bit normal-a, Normal at opacity 1, neutral geometry mask, identity Nearest Repeat UV. "
    "Fresh getters read the full root tree, the fill state, both resource joins, the fill source "
    "and the mesh map in same_session and after Full save/reopen, with no setter replayed. "
    "Captures in both recordings: Normal_OpenGL at PNG 16 and OpenEXR 32f with infinite and "
    "passthrough padding, and an OpenEXR 32f infinite control of Height, the Normal channel and "
    "normal_base, each export done twice in a row, keyed by step, no dithering. Expected bits, "
    "void rules and predictions are declared in "
    "parity/reports/phase1/normal-empty-height-freeze.md before capture; the Height control is "
    "an observation, not proof of the virtual normal's internal Height."
)


def request(root: Path = REPO_ROOT) -> dict[str, Any]:
    golden = Golden(NAME, DOMAIN, DESCRIPTION, MESH, list(INPUTS), sequence())
    hashes = {
        name: hashlib.sha256((root / rr.fixture(name)[1]).read_bytes()).hexdigest()
        for name in INPUTS
    }
    result = rr.request_manifest(golden, hashes, current_envelope(root))
    result["golden_id"] = DOMAIN
    return result


def request_path(root: Path = REPO_ROOT) -> Path:
    return rr.request_root(root) / "tier0" / "api-probes" / f"{NAME}.json"


def readback(outputs: list[dict[str, Any]], step: dict[str, Any]) -> Any:
    """The one clean readback output of an authored getter step."""
    call = step["call"]
    found = [
        o
        for o in outputs
        if o.get("kind") == "api_readback"
        and o.get("output_id") == f"s{step['step']}/{call.rsplit('.', 1)[1]}"
    ]
    require(len(found) == 1, f"readback identity of step {step['step']}")
    output = found[0]
    require(
        "raised" not in output
        and output.get("call") == call
        and canonical_json(output.get("args")) == canonical_json(step["args"]),
        f"readback context of step {step['step']}",
    )
    return output.get("value")


def nonempty(value: Any) -> bool:
    return type(value) is str and bool(value)


def channel_descriptor(value: Any, name: str) -> dict[str, Any]:
    """A channel as `template_capture` describes it, typed exactly; its values are measured."""
    require(
        type(value) is dict
        and set(value) == {"format", "bit_depth", "is_color", "is_floating", "label"}
        and nonempty(value["format"])
        and type(value["bit_depth"]) is int
        and value["bit_depth"] > 0
        and type(value["is_color"]) is bool
        and type(value["is_floating"]) is bool
        and type(value["label"]) is str,
        f"{name} channel descriptor",
    )
    result: dict[str, Any] = value
    return result


def validate_cleanup(receipt: Any, created_project_uuid: str) -> None:
    """The initial Paint cleanup's receipt (the r1 outcome of step 2, verified by the caller):
    the created project, one PaintLayer with a positive uid before, no root after."""
    require(nonempty(created_project_uuid), "created UUID")
    require(
        type(receipt) is dict
        and set(receipt)
        == {"created_project_uuid", "current_project_uuid", "before", "after_root_count"}
        and receipt["created_project_uuid"] == created_project_uuid
        and receipt["current_project_uuid"] == created_project_uuid
        and type(receipt["before"]) is dict
        and set(receipt["before"]) == {"uid", "node_type"}
        and type(receipt["before"]["uid"]) is int
        and receipt["before"]["uid"] > 0
        and receipt["before"]["node_type"] == "PaintLayer"
        and type(receipt["after_root_count"]) is int
        and receipt["after_root_count"] == 0,
        "initial Paint cleanup receipt",
    )


def validate_observed_state(
    recording: dict[str, Any],
    manifest: dict[str, Any],
    imported: dict[str, dict[str, str]],
    created_project_uuid: str,
) -> dict[str, Any]:
    """Pure void gate of one recording, not admission; returns what it measured.

    The caller verifies that `manifest` is the committed request and that `imported` maps
    normal-a and normal-b to their full identities from the verified import receipt, never
    inferred from a name. The cleanup receipt is checked separately (`validate_cleanup`), since
    only r1 holds it. The recording is void unless the root tree is exactly the authored fill,
    every authored getter reads back its literal, the fill source joins normal-a with a named
    colour space, the Normal mesh map joins normal-b, the owned project is the created one and
    the single texture set holds typed Normal and Height channels at 256 px.
    """
    require(recording["condition"] in CONDITIONS, "recording condition")
    require(set(imported) == {FILL_INPUT, MESH_MAP_INPUT}, "import identities")
    for identity in imported.values():
        require(set(identity) == {"context", "name", "version"}, "import identity fields")
        require(all(nonempty(v) for v in identity.values()), "import identity values")
    require(nonempty(created_project_uuid), "created UUID")
    outputs = recording["outputs"]
    steps = manifest["instruction_sequence"]["steps"]
    reads = [step for step in steps if is_read(step["call"], step["args"])]
    imports = {
        step["step"]: step["args"]["input"] for step in steps if step["call"] == ps.IMPORT_RESOURCE
    }
    require(sorted(imports.values()) == sorted(imported), "authored imports")

    expected = fixed_readbacks()
    for call in (*expected, ps.GET_SOURCE, ps.GET_MESH_MAP, PROJECT_UUID):
        require(sum(step["call"] == call for step in reads) == 1, f"authored readback {call}")
    queries: dict[str, Any] = {}
    color_space: Any = None
    for step in reads:
        call = step["call"]
        value = readback(outputs, step)
        if call in expected:
            require(
                canonical_json(value) == canonical_json(expected[call]),
                f"authored readback differs: {call}",
            )
        elif call == PROJECT_UUID:
            require(
                canonical_json(value)
                == canonical_json(
                    {
                        "created_project_uuid": created_project_uuid,
                        "current_project_uuid": created_project_uuid,
                    }
                ),
                "owned project identity",
            )
        elif call == RESOURCE_FROM_PROJECT:
            name = imports[step["args"]["import_step"]]
            require(type(value) is dict and set(value) == {"resource"}, "project resource query")
            resource = value["resource"]
            require(
                type(resource) is dict
                and set(resource) == {"context", "name", "version"}
                and all(nonempty(v) for v in resource.values())
                and resource["name"] == imported[name]["name"]
                and resource["version"] == imported[name]["version"],
                f"project resource of {name}",
            )
            queries[name] = value
            queries[f"step{step['step']}"] = value
        elif call == RESOURCE_RETRIEVE:
            query = queries.get(f"step{step['args']['resource_step']}")
            require(
                query is not None and canonical_json(value) == canonical_json([query]),
                "unique retrieved project resource",
            )
        elif call == ps.GET_SOURCE:
            require(
                type(value) is dict
                and set(value) == {"bitmap", "color_space"}
                and FILL_INPUT in queries
                and canonical_json(value["bitmap"]) == canonical_json(queries[FILL_INPUT]),
                "fill source joins normal-a",
            )
            color_space = value["color_space"]
            require(nonempty(color_space), "fill source colour space")
        elif call == ps.GET_MESH_MAP:
            require(
                MESH_MAP_INPUT in queries
                and canonical_json(value) == canonical_json(queries[MESH_MAP_INPUT]),
                "Normal mesh map joins normal-b",
            )

    templates = [
        o
        for o in outputs
        if o.get("kind") == "template_capture" and o.get("output_id") == "template/texture-sets"
    ]
    require(len(templates) == 1, "template identity")
    sets = templates[0]["values"]["texture_sets"]
    require(set(sets) == {TEXTURE_SET}, "texture set identity")
    texture = sets[TEXTURE_SET]
    require(canonical_json(texture["resolution"]) == canonical_json([256, 256]), "resolution")
    require(len(texture["stacks"]) == 1, "stack count")
    channels = next(iter(texture["stacks"].values()))
    require(type(channels) is dict, "stack channels")
    return {
        "channels": {
            name: channel_descriptor(channels.get(name), name) for name in (CHANNEL, "Height")
        },
        "source_color_space": color_space,
    }


def validate_pair(
    recordings: list[dict[str, Any]],
    manifest: dict[str, Any],
    imported: dict[str, dict[str, str]],
    created_project_uuid: str,
    cleanup: Any,
) -> dict[str, Any]:
    """The cleanup receipt holds, both recordings pass the gate, one per condition, and they
    measure the same channels and the same fill source colour space; returns those values."""
    validate_cleanup(cleanup, created_project_uuid)
    require(sorted(r["condition"] for r in recordings) == sorted(CONDITIONS), "one recording each")
    measured = [
        validate_observed_state(r, manifest, imported, created_project_uuid) for r in recordings
    ]
    require(canonical_json(measured[0]) == canonical_json(measured[1]), "r1 and r2 disagree")
    return measured[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    path = request_path()
    require(path.parent.is_dir(), "request parent must already exist")
    path.write_text(json.dumps(request(), indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
