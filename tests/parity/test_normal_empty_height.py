"""Decision 245 section 2's request (`tools/parity/tier0_semantics/normal_empty_height.py`).

Structure: the API probe loader accepts the request with the cleanup at step 2, setters before
getters before keyed final exports; the stack is one Normal-only fill over a bound normal-b, no
step names Height as a source or channel, the five captures are each done twice, and the
committed request is the generated one. The void gate: a synthetic recording built from the
manifest passes, and each void condition (a root left by create, a Height channel, a wrong
join, a foreign project, a missing channel, disagreeing recordings) is refused.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.recorder.probes import is_read, probe_job_from_manifest
from tools.parity.schemas import Schema, validation_errors
from tools.parity.tier0_semantics import normal_empty_height as m
from tools.parity.tier0_semantics.ocio16_raw_readout_control import (
    FILL,
    PROJECT_UUID,
    RESOURCE_FROM_PROJECT,
    RESOURCE_RETRIEVE,
    ROOT_LAYERS,
)

IMPORTED = {
    m.FILL_INPUT: {"context": "project", "name": "normal-a", "version": "va"},
    m.MESH_MAP_INPUT: {"context": "project", "name": "normal-b", "version": "vb"},
}
UUID = "owned-project"
# Synthetic stand-ins: the gate returns whatever formats Painter reports, it does not expect these.
CHANNELS = {
    name: {"format": f, "bit_depth": 16, "is_color": False, "is_floating": True, "label": ""}
    for name, f in (("Height", "L16F"), ("Normal", "RGB16F"))
}
CLEANUP = {
    "created_project_uuid": UUID,
    "current_project_uuid": UUID,
    "before": {"uid": 7, "node_type": "PaintLayer"},
    "after_root_count": 0,
}


def steps(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = manifest["instruction_sequence"]["steps"]
    return result


def test_probe_loader_accepts_the_request_in_its_phases() -> None:
    manifest = m.request()
    job = probe_job_from_manifest(manifest)
    sequence = steps(manifest)
    assert sequence[1] == {
        "step": 2,
        "call": "substance_painter.layerstack.delete_node",
        "args": {"initial_root": True, "expected_type": "PaintLayer"},
    }
    kinds = [
        "export" if s["call"] == EXPORT else "read" if is_read(s["call"], s["args"]) else "set"
        for s in sequence[1:]
    ]
    assert kinds == sorted(kinds, key=["set", "read", "export"].index)
    assert len(job.probe_steps) == kinds.count("read") == 19
    assert len(job.exports) == 10
    assert job.keyed_export_steps == {s["step"] for s in sequence if s["call"] == EXPORT}
    assert manifest["golden_id"] == m.DOMAIN == "tier0/api-probes/" + m.NAME
    assert [i["input_id"] for i in manifest["inputs"]] == list(m.INPUTS)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["private_records"] == []
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    assert m.request_path().parent.name == "api-probes"


def test_stack_is_one_normal_only_fill_over_the_bound_mesh_map() -> None:
    sequence = steps(m.request())
    imports = {s["step"]: s["args"]["input"] for s in sequence if s["call"] == ps.IMPORT_RESOURCE}
    assert sorted(imports.values()) == [m.FILL_INPUT, m.MESH_MAP_INPUT]
    assert [s["call"] for s in sequence].count(ps.INSERT_FILL) == 1
    setters = [s for s in sequence if not is_read(s["call"], s["args"])]
    (active,) = [s for s in setters if s["call"] == ps.SET_ACTIVE_CHANNELS]
    assert active["args"]["channels"] == ["Normal"]
    (source,) = [s for s in sequence if s["call"] == ps.SET_SOURCE]
    assert source["args"]["channel"] == "Normal"
    assert imports[source["args"]["resource_step"]] == m.FILL_INPUT
    (binding,) = [s for s in sequence if s["call"] == ps.SET_MESH_MAP]
    assert binding["args"]["usage"] == "Normal"
    assert imports[binding["args"]["resource_step"]] == m.MESH_MAP_INPUT
    for step in sequence:
        if step["call"] != EXPORT:
            assert "Height" not in json.dumps(step["args"])


def test_captures_cover_both_formats_and_paddings_twice() -> None:
    exports = [s["args"] for s in steps(m.request()) if s["call"] == EXPORT]
    configs = [(a["maps"], a["file_format"], a["bit_depth"], a["padding"]) for a in exports]
    assert configs == [tuple(c) for c in m.CAPTURES for _ in range(2)]
    assert all(a["dithering"] is False and a["key_by_step"] is True for a in exports)
    assert "probe" not in json.dumps(exports)


def test_committed_request_is_the_generated_one() -> None:
    committed = json.loads(m.request_path().read_text(encoding="utf-8"))
    assert committed == m.request()


def recording(manifest: dict[str, Any], condition: str = "same_session") -> dict[str, Any]:
    """What a clean recording of the authored state reads, built from the manifest."""
    sequence = steps(manifest)
    imports = {s["step"]: s["args"]["input"] for s in sequence if s["call"] == ps.IMPORT_RESOURCE}
    fixed = m.fixed_readbacks()
    queries: dict[int, Any] = {}
    outputs: list[dict[str, Any]] = [
        {
            "output_id": "template/texture-sets",
            "kind": "template_capture",
            "values": {
                "texture_sets": {
                    m.TEXTURE_SET: {
                        "resolution": [256, 256],
                        "stacks": {"": copy.deepcopy(CHANNELS)},
                    }
                }
            },
        }
    ]
    for step in sequence:
        call, args = step["call"], step["args"]
        if not is_read(call, args):
            continue
        if call in fixed:
            value: Any = fixed[call]
        elif call == PROJECT_UUID:
            value = {"created_project_uuid": UUID, "current_project_uuid": UUID}
        elif call == RESOURCE_FROM_PROJECT:
            value = {"resource": dict(IMPORTED[imports[args["import_step"]]])}
            queries[step["step"]] = value
        elif call == RESOURCE_RETRIEVE:
            value = [queries[args["resource_step"]]]
        elif call == ps.GET_SOURCE:
            value = {"bitmap": {"resource": dict(IMPORTED[m.FILL_INPUT])}, "color_space": "sRGB"}
        else:
            assert call == ps.GET_MESH_MAP
            value = {"resource": dict(IMPORTED[m.MESH_MAP_INPUT])}
        outputs.append(
            {
                "output_id": f"s{step['step']}/{call.rsplit('.', 1)[1]}",
                "kind": "api_readback",
                "call": call,
                "args": copy.deepcopy(args),
                "value": copy.deepcopy(value),
            }
        )
    return {"condition": condition, "outputs": outputs}


def output(record: dict[str, Any], call: str) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = record["outputs"]
    (found,) = [o for o in outputs if o.get("call") == call]
    return found


def test_clean_recordings_pass_and_agree() -> None:
    manifest = m.request()
    pair = [recording(manifest, c) for c in m.CONDITIONS]
    measured = m.validate_pair(pair, manifest, IMPORTED, UUID, CLEANUP)
    assert measured == {"channels": CHANNELS, "source_color_space": "sRGB"}


def initial_paint_left(record: dict[str, Any]) -> None:
    paint = {"node_type": "PaintLayer", "name": "Layer 1", "visible": True, "has_mask": False}
    output(record, ROOT_LAYERS)["value"].append({**paint, "Content": [], "Mask": []})


def height_active(record: dict[str, Any]) -> None:
    output(record, FILL + "active_channels")["value"] = ["Height", "Normal"]


def mesh_map_is_normal_a(record: dict[str, Any]) -> None:
    output(record, ps.GET_MESH_MAP)["value"] = {"resource": dict(IMPORTED[m.FILL_INPUT])}


def source_is_normal_b(record: dict[str, Any]) -> None:
    output(record, ps.GET_SOURCE)["value"]["bitmap"] = {"resource": dict(IMPORTED["normal-b"])}


def foreign_project(record: dict[str, Any]) -> None:
    output(record, PROJECT_UUID)["value"]["current_project_uuid"] = "other"


def no_height_channel(record: dict[str, Any]) -> None:
    del record["outputs"][0]["values"]["texture_sets"][m.TEXTURE_SET]["stacks"][""]["Height"]


def getter_raised(record: dict[str, Any]) -> None:
    output(record, ROOT_LAYERS)["raised"] = "RuntimeError"


def resource_context_none(record: dict[str, Any]) -> None:
    """normal-a's context is None the same way in its query, its retrieval and the fill source,
    so every join still agrees and only the context's type is wrong."""
    (query,) = [
        o
        for o in record["outputs"]
        if o.get("call") == RESOURCE_FROM_PROJECT
        and o["value"]["resource"]["name"] == IMPORTED[m.FILL_INPUT]["name"]
    ]
    query["value"]["resource"]["context"] = None
    for retrieved in [o for o in record["outputs"] if o.get("call") == RESOURCE_RETRIEVE]:
        if retrieved["value"][0]["resource"]["name"] == IMPORTED[m.FILL_INPUT]["name"]:
            retrieved["value"][0]["resource"]["context"] = None
    output(record, ps.GET_SOURCE)["value"]["bitmap"]["resource"]["context"] = None


def color_space_raised(record: dict[str, Any]) -> None:
    output(record, ps.GET_SOURCE)["value"]["color_space"] = {"raised": "RuntimeError"}


def color_space_missing(record: dict[str, Any]) -> None:
    del output(record, ps.GET_SOURCE)["value"]["color_space"]


def color_space_none(record: dict[str, Any]) -> None:
    output(record, ps.GET_SOURCE)["value"]["color_space"] = None


def stack(record: dict[str, Any]) -> dict[str, Any]:
    stacks: dict[str, Any] = record["outputs"][0]["values"]["texture_sets"][m.TEXTURE_SET]["stacks"]
    channels: dict[str, Any] = stacks[""]
    return channels


def bit_depth_bool(record: dict[str, Any]) -> None:
    stack(record)["Normal"]["bit_depth"] = True


def format_none(record: dict[str, Any]) -> None:
    stack(record)["Height"]["format"] = None


def flag_missing(record: dict[str, Any]) -> None:
    del stack(record)["Normal"]["is_floating"]


def channel_null(record: dict[str, Any]) -> None:
    stack(record)["Height"] = None


@pytest.mark.parametrize(
    "void",
    [
        initial_paint_left,
        height_active,
        mesh_map_is_normal_a,
        source_is_normal_b,
        foreign_project,
        no_height_channel,
        getter_raised,
        resource_context_none,
        color_space_raised,
        color_space_missing,
        color_space_none,
        bit_depth_bool,
        format_none,
        flag_missing,
        channel_null,
    ],
)
def test_each_void_condition_is_refused(void: Any) -> None:
    manifest = m.request()
    record = recording(manifest)
    void(record)
    with pytest.raises(ValueError):
        m.validate_observed_state(record, manifest, IMPORTED, UUID)


def test_recordings_that_measure_different_formats_are_refused() -> None:
    manifest = m.request()
    first, second = (recording(manifest, c) for c in m.CONDITIONS)
    stack(second)["Normal"]["format"] = "RGB32F"
    with pytest.raises(ValueError):
        m.validate_pair([first, second], manifest, IMPORTED, UUID, CLEANUP)
    with pytest.raises(ValueError):
        m.validate_pair([first, first], manifest, IMPORTED, UUID, CLEANUP)


@pytest.mark.parametrize(
    "change",
    [
        {"created_project_uuid": "other"},
        {"current_project_uuid": "other"},
        {"before": {"uid": 0, "node_type": "PaintLayer"}},
        {"before": {"uid": True, "node_type": "PaintLayer"}},
        {"before": {"uid": 7, "node_type": "FillLayer"}},
        {"after_root_count": 1},
        {"after_root_count": False},
        {"extra": True},
    ],
)
def test_cleanup_receipt_is_checked_exactly(change: dict[str, Any]) -> None:
    manifest = m.request()
    pair = [recording(manifest, c) for c in m.CONDITIONS]
    with pytest.raises(ValueError):
        m.validate_cleanup({**CLEANUP, **change}, UUID)
    with pytest.raises(ValueError):
        m.validate_pair(pair, manifest, IMPORTED, UUID, {**CLEANUP, **change})
