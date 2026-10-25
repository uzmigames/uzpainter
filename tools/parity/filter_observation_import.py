"""Private Filter observation preflight (decision 362); never evaluates a procedural asset."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder.environment import ENVELOPE_FIELDS, envelope_sha256
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.probes import ProbeJob, probe_job_from_manifest
from tools.parity.schemas import record_problems
from tools.parity.store.manifest import verify
from tools.parity.store.store import OracleStore, load_oracle
from tools.parity.tier0_semantics import filter_observation_control as control


class ImportRefused(ValueError):
    """A public, value-free reason for refusing a private capture."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ImportRefused(reason)


def closed(value: Any, keys: set[str], reason: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == keys, reason)
    return cast(dict[str, Any], value)


def typed_json(value: Any) -> bytes:
    """Core WriteCanonical domain, including int64 and distinct double/signed zero."""
    if value is None or type(value) is bool:
        pass
    elif type(value) is int:
        require(-(1 << 63) <= value < (1 << 63), "integer outside int64")
    elif type(value) is float:
        require(math.isfinite(value), "non-finite JSON number")
    elif type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ImportRefused("invalid Unicode") from None
    elif type(value) is list:
        for item in value:
            typed_json(item)
    elif type(value) is dict:
        for key, item in value.items():
            require(type(key) is str, "non-string JSON key")
            typed_json(key)
            typed_json(item)
    else:
        raise ImportRefused("unsupported JSON type")
    return canonical_json(value)


def digest(value: Any) -> str:
    return hashlib.sha256(typed_json(value)).hexdigest()


def parse(data: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate JSON member")
            result[key] = value
        return result

    try:

        def floating(token: str) -> float:
            value = float(token)
            require(value != 0.0 or Decimal(token).is_zero(), "floating-point underflow")
            return value

        result = json.loads(data, object_pairs_hook=pairs, parse_float=floating)
    except (UnicodeError, json.JSONDecodeError):
        raise ImportRefused("invalid JSON") from None
    require(type(result) is dict, "JSON root must be an object")
    typed_json(result)
    return cast(dict[str, Any], result)


def parameters(value: Any) -> dict[str, Any]:
    require(type(value) is dict, "parameters must be an object")
    for item in value.values():
        require(type(item) in (int, float, str), "parameter outside decision 361 codec")
    typed_json(value)
    return cast(dict[str, Any], value)


def resource_id(value: Any) -> dict[str, str]:
    outer = closed(value, {"resource_id", "url"}, "resource readback shape")
    wrapped = closed(outer["resource_id"], {"resource"}, "resource readback wrapper")
    parts = closed(wrapped["resource"], {"context", "name", "version"}, "resource parts")
    result = {"url": outer["url"], **parts}
    require(
        all(type(v) is str and bool(v) for v in result.values()), "resource identity incomplete"
    )
    return result


def recipe_body(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "uzpainter/filter-observation-recipe/1",
        "instruction_sequence": manifest["instruction_sequence"],
        "applied_settings": manifest["applied_settings"],
        "inputs": [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in manifest["inputs"]],
    }


def paired_readbacks(record: dict[str, Any], job: ProbeJob) -> dict[str, dict[int, Any]]:
    """Select complete recorder outputs, never old expected replay values."""
    require(not record_problems(record), "private record schema")
    require(record["golden_id"] == job.manifest["golden_id"], "record golden mismatch")
    recordings = record["recordings"]
    require(len(recordings) == 2, "exactly two recordings required")
    result: dict[str, dict[int, Any]] = {}
    for recording in recordings:
        condition = recording["condition"]
        require(
            condition in ("same_session", "after_save_reopen") and condition not in result,
            "paired conditions required",
        )
        values = {}
        if condition == "same_session":
            for state in job.state_steps:
                outcomes = [o for o in recording["outputs"] if o["output_id"] == state.output_id]
                require(
                    len(outcomes) == 1
                    and outcomes[0]["kind"] == "api_readback"
                    and outcomes[0]["call"] == state.call
                    and typed_json(outcomes[0]["args"]) == typed_json(state.args)
                    and "raised" not in outcomes[0]
                    and "value" in outcomes[0],
                    "state operation did not succeed",
                )
        for step in job.probe_steps:
            outputs = [o for o in recording["outputs"] if o["output_id"] == step.output_id]
            require(len(outputs) == 1, "missing or duplicate readback")
            output = outputs[0]
            require(
                output["kind"] == "api_readback"
                and output["call"] == step.call
                and typed_json(output["args"]) == typed_json(step.args)
                and "raised" not in output
                and "value" in output,
                "readback contract differs",
            )
            values[step.step] = output["value"]
        result[condition] = values
    # Integer keys are local indexing, never part of the canonical wire body.
    require(
        typed_json(list(result["same_session"].values()))
        == typed_json(list(result["after_save_reopen"].values())),
        "paired readbacks differ",
    )
    return result


def admitted_record(store: OracleStore, manifest: dict[str, Any]) -> tuple[bytes, ProbeJob]:
    """Require every admitted reference and authored input to resolve before deriving anything."""
    build = manifest["software"]["painter"]["build_id"]
    for ref in manifest["private_records"]:
        entry = store.entry(build, manifest["golden_id"], ref["record_id"])
        require(entry is not None, "record not admitted")
        assert entry is not None
        require(
            entry.kind == ref["kind"]
            and entry.sha256 == ref["sha256"]
            and entry.size_bytes == ref["size_bytes"],
            "admission differs",
        )
    resolutions = verify(store, manifest)
    require(
        bool(resolutions) and all(r.path is not None for r in resolutions), "oracle unavailable"
    )
    refs = [r for r in manifest["private_records"] if r["kind"] == "private_oracle_record"]
    require(len(refs) == 1, "unique private record required")
    data = load_oracle(store, refs[0])
    require(data is not None, "private record unavailable")
    assert data is not None
    return data, probe_job_from_manifest(manifest)


def build_payload(
    manifest: dict[str, Any],
    record_bytes: bytes,
    base: dict[str, Any],
    *,
    texture_set: int,
    stack: int,
) -> dict[str, Any]:
    """One derivation for synthetic receipts and verified own-Painter records; no native calls."""
    authored = control.request()
    for key in ("golden_id", "instruction_sequence", "inputs", "applied_settings", "software"):
        require(typed_json(manifest[key]) == typed_json(authored[key]), "authored recipe differs")
    job = probe_job_from_manifest(manifest)
    record = parse(record_bytes)
    refs = [r for r in manifest["private_records"] if r["kind"] == "private_oracle_record"]
    record_hash = hashlib.sha256(record_bytes).hexdigest()
    require(
        len(refs) == 1
        and refs[0]["sha256"] == record_hash
        and refs[0]["size_bytes"] == len(record_bytes),
        "record receipt differs",
    )
    paired = paired_readbacks(record, job)
    key = record["key"]
    require(
        key["instruction_sequence_sha256"] == job.instruction_sequence_sha256
        and typed_json(key["inputs"]) == typed_json(job.input_hashes()),
        "record recipe key differs",
    )
    require(
        typed_json(key["painter_build"]) == typed_json(manifest["software"]["painter"]),
        "record Painter build differs",
    )
    environment = record.get("environment")
    current = current_envelope()
    require(
        type(environment) is dict
        and environment.get("basis") == "recorded"
        and all(environment.get(k) not in (None, "unknown", "") for k in ENVELOPE_FIELDS),
        "recorded environment required",
    )
    environment = cast(dict[str, Any], environment)
    require(
        environment["painter_build"] == current["painter_build"]
        and envelope_sha256(environment)
        in {current["envelope_sha256"], *current["equivalent_envelopes"]},
        "recorded envelope differs",
    )
    project_settings = closed(
        key["project_settings"], {"create", "colour_management"}, "record project settings"
    )
    require(
        typed_json(project_settings["create"]) == typed_json(job.project_settings()),
        "record create settings differ",
    )
    colour = closed(
        project_settings["colour_management"],
        {"mode", "OCIO", "PAINTER_ACE_CONFIG"},
        "record colour settings",
    )
    require(
        colour["mode"] == "ocio"
        and type(colour["OCIO"]) is str
        and colour["OCIO"].replace("\\", "/").endswith("resources/ocio/substance/config.ocio")
        and typed_json(key["effective_defaults"].get("colour_management")) == typed_json(colour),
        "record colour context differs",
    )
    closed(
        base, {"schema", "project_uuid", "projection", "projection_sha256", "mesh"}, "base fields"
    )
    require(
        base["schema"] == "uzpainter/filter-observation-base/1"
        and type(base["project_uuid"]) is str
        and bool(base["project_uuid"]),
        "base identity",
    )
    projection = deepcopy(base["projection"])
    require(
        type(projection) is dict
        and "filter_source_observations" not in projection
        and digest(projection) == base["projection_sha256"],
        "base projection hash",
    )
    require(
        type(texture_set) is int and texture_set > 0 and type(stack) is int and stack > 0,
        "target IDs",
    )
    mesh = closed(base["mesh"], {"sha256", "size_bytes", "mime"}, "base mesh fields")
    mesh_bytes = job.inputs["plane"].read_bytes()
    require(
        mesh["sha256"] == hashlib.sha256(mesh_bytes).hexdigest()
        and type(mesh["size_bytes"]) is int
        and mesh["size_bytes"] == len(mesh_bytes)
        and type(mesh["mime"]) is str
        and bool(mesh["mime"]),
        "base mesh differs",
    )
    require(
        projection["mesh"]["resource"] == mesh["sha256"]
        and set(projection["resources"]) == {mesh["sha256"]},
        "mesh census differs",
    )
    metadata = projection["resources"][mesh["sha256"]]
    require(
        len(metadata) == 1
        and metadata[0]["mime"] == mesh["mime"]
        and metadata[0]["size"] == mesh["size_bytes"],
        "mesh metadata differs",
    )
    settings = projection["settings"]
    require(
        settings["normal_map_format"] == "OpenGL"
        and settings["default_resolution"] == {"width": 256, "height": 256}
        and settings["color_management"]["mode"] == "ocio"
        and settings["color_management"]["config_hash"] == PAINTER_OCIO_CONFIG_SHA256,
        "base project settings differ",
    )
    sets = projection["texture_sets"]
    selected = [s for s in sets if s["id"] == texture_set]
    require(
        len(selected) == 1
        and selected[0]["name"] == "uzp_plane"
        and selected[0]["resolution"] == {"width": 256, "height": 256},
        "target texture set differs",
    )
    stacks = [s for s in selected[0]["stacks"] if s["id"] == stack]
    require(
        len(stacks) == 1 and stacks[0]["channels"][control.CHANNEL]["format"] == "L32F",
        "target stack differs",
    )
    require(
        all(not s["mesh_maps"] and all(not k["root_layers"] for k in s["stacks"]) for s in sets),
        "base must have no layers or mesh maps",
    )
    require(projection.get("procedural_snapshots", {}) == {}, "snapshots outside V1")
    require(
        projection["display"]["environment"]["resource"] is None
        and projection["display"]["color_lut"] is None,
        "external display resources outside V1",
    )
    next_id = projection["next_id"]
    require(type(next_id) is int and 0 < next_id < (1 << 63) - 2, "base allocation ID")
    host_step = next(s.step for s in job.state_steps if s.call.endswith(".insert_fill"))
    filter_step = next(s.step for s in job.state_steps if s.call.endswith(".insert_filter_effect"))

    def observed(call: str, node: int) -> Any:
        matches = [s for s in job.probe_steps if s.call == call and s.args.get("node_step") == node]
        require(len(matches) == 1, "unique authored getter required")
        return paired["same_session"][matches[0].step]

    def equal(call: str, node: int, expected: Any) -> None:
        require(typed_json(observed(call, node)) == typed_json(expected), "setter readback differs")

    for node, name in ((host_step, "Observation host"), (filter_step, "Observation filter")):
        for getter, value in (
            ("get_name", name),
            ("is_visible", True),
            ("get_blending_mode", "Normal"),
            ("get_opacity", 1.0),
        ):
            equal(control.NODE + getter, node, value)
    equal(control.LAYER + "get_geometry_mask", host_step, control.GEOMETRY)
    equal(control.FILL + "source_mode", host_step, "Split")
    equal(control.FILL + "active_channels", host_step, [control.CHANNEL])
    equal(control.FILL + "get_projection_mode", host_step, "UV")
    equal(
        "substance_painter.layerstack.FilterEffectNode.active_channels",
        filter_step,
        [control.CHANNEL],
    )
    uv: dict[str, Any] = {
        "class": "UVProjectionParams",
        "filtering_mode": control.UV["filtering_mode"],
        "uv_wrapping_mode": control.UV["uv_wrapping_mode"],
        "uv_transformation": {
            "class": "UVTransformationParams",
            **{k: control.UV[k] for k in ("scale_mode", "scale", "rotation", "offset")},
        },
    }
    equal(control.FILL + "get_projection_parameters", host_step, uv)
    equal(control.SOURCE + "image_inputs", host_step, [])
    equal(control.SOURCE + "image_inputs", filter_step, [])
    descriptors = {}
    references = {}
    filter_readback = {}
    for role, node, query in (
        ("host", host_step, control.HOST_QUERY),
        ("filter", filter_step, control.FILTER_QUERY),
    ):
        params = parameters(observed(control.SOURCE + "get_parameters", node))
        identity = resource_id(observed(control.SOURCE + "resource_id", node))
        require(
            identity["context"] == query["resource_context"]
            and identity["name"] == query["resource_name"],
            "selected resource differs",
        )
        outputs = observed(control.SOURCE + "image_outputs", node)
        require(
            type(outputs) is list
            and all(type(o) is str and bool(o) for o in outputs)
            and len(set(outputs)) == len(outputs),
            "image outputs invalid",
        )
        descriptors[role] = {"resource_id": identity, "parameters": deepcopy(params)}
        descriptor = {
            "schema": "uzpainter/filter-observation-descriptor/1",
            "role": role,
            **descriptors[role],
        }
        core_params = {
            k: int(v) if type(v) is float and v.is_integer() and -(1 << 63) <= v < (1 << 63) else v
            for k, v in params.items()
        }
        mapping = {}
        resolution = None
        if role == "host":
            active = observed(control.SOURCE + "active_output", node)
            require(
                type(active) is str and active in outputs,
                "active output missing from observed outputs",
            )
            mapping[control.CHANNEL] = active
            raw_resolution = closed(
                observed(control.SOURCE + "resolution", node),
                {"mode", "value", "value_kind", "log2_offset"},
                "source resolution fields",
            )
            require(
                raw_resolution["mode"]
                in ("Auto", "Asset", "Custom", "TextureSet", "UVTile", "Document", "Manual")
                and raw_resolution["value_kind"] in ("tuple", "list")
                and type(raw_resolution["value"]) is list
                and len(raw_resolution["value"]) == 2
                and all(type(v) is int for v in raw_resolution["value"])
                and type(raw_resolution["log2_offset"]) is int,
                "source resolution invalid",
            )
            resolution = {k: raw_resolution[k] for k in ("mode", "value", "log2_offset")}
        else:
            filter_readback = {
                "parameters": deepcopy(params),
                "resource_id": identity,
                "image_outputs": outputs,
            }
        references[role] = {
            "asset": "uzasset://observation/" + digest(descriptor) + "@1",
            "params": core_params,
            "preset": None,
            "image_inputs": {},
            "output_mapping": mapping,
            "mask_output": None,
            "resolution_override": resolution,
        }
    blending = {control.CHANNEL: {"mode": "Normal", "opacity": 1.0}}
    effect = {
        "uid": next_id + 1,
        "kind": "filter",
        "name": "Observation filter",
        "visible": True,
        "blending": deepcopy(blending),
        "active_channels": [control.CHANNEL],
        "preset_ref": None,
        "procedural": references["filter"],
    }
    core_uv = deepcopy(uv)
    del core_uv["class"]
    del core_uv["uv_transformation"]["class"]
    host = {
        "uid": next_id,
        "kind": "fill",
        "name": "Observation host",
        "visible": True,
        "blending": blending,
        "content_effects": [effect],
        "mask": None,
        "geometry_mask": deepcopy(control.GEOMETRY),
        "preset_ref": None,
        "fill": {
            "source_mode": "Split",
            "sources": {control.CHANNEL: {"type": "procedural", **references["host"]}},
            "material_source": None,
            "active_channels": [control.CHANNEL],
            "projection": {"mode": "UV", "uv": core_uv, "params": {}},
            # A-PYDOC 12.2 fill.html: symmetry is available only for 3D projections.
            "symmetry": {"enabled": False, "params": {}},
        },
    }
    stacks[0]["root_layers"] = [host]
    projection["next_id"] += 2
    body = recipe_body(manifest)
    return {
        "schema": "uzpainter/filter-observation-import/2",
        "target": {
            "project_uuid": base["project_uuid"],
            "preimport_projection_sha256": base["projection_sha256"],
            "texture_set": texture_set,
            "stack": stack,
            "mesh": deepcopy(mesh),
        },
        "recipe": {"sha256": digest(body), "body": body},
        "host_state": host,
        "filter_state": effect,
        "descriptors": descriptors,
        "expected_projection": projection,
        "capture": {
            "recorder": environment["recorder_version"],
            "envelope_id": current_envelope()["envelope_id"],
            "painter_build_id": manifest["software"]["painter"]["build_id"],
            "recipe_sha256": digest(body),
            "resource_query": str(control.HOST_QUERY["search"])
            + ";"
            + str(control.FILTER_QUERY["search"]),
            "authored_inputs": body["inputs"],
            "receipts": [{"condition": condition, "sha256": record_hash} for condition in paired],
        },
        "readbacks": {condition: deepcopy(filter_readback) for condition in paired},
    }


def admitted_payload(
    store: OracleStore,
    manifest: dict[str, Any],
    base: dict[str, Any],
    *,
    texture_set: int,
    stack: int,
) -> dict[str, Any]:
    data, _ = admitted_record(store, manifest)
    return build_payload(manifest, data, base, texture_set=texture_set, stack=stack)


def write_private(path: Path, payload: dict[str, Any]) -> None:
    from tools.parity.recorder.output import ensure_outside_repository

    target = ensure_outside_repository(path)
    data = typed_json(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data + b"\n")


def main() -> int:
    import argparse
    import sys

    from tools.parity.recorder.output import ensure_outside_repository
    from tools.parity.store.store import locate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--texture-set", type=int, required=True)
    parser.add_argument("--stack", type=int, required=True)
    args = parser.parse_args()
    try:
        store = locate()
        require(store is not None, "oracle unavailable")
        assert store is not None
        base_path = ensure_outside_repository(args.base)
        payload = admitted_payload(
            store,
            parse(args.manifest.read_bytes()),
            parse(base_path.read_bytes()),
            texture_set=args.texture_set,
            stack=args.stack,
        )
        write_private(args.output, payload)
    except Exception:
        sys.stderr.write("Filter observation preflight refused; no payload accepted.\n")
        return 2
    sys.stdout.write('{"status":"written","observations":2}\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
