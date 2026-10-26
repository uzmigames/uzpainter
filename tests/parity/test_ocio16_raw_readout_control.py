"""Public authoring and synthetic readback gates; no Painter or private oracle."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity import ocio16_raw_readout_admission as admission
from tools.parity.feasibility import png
from tools.parity.fit.decode import decode
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.recorder.probes import is_read, manifest_symbol_problems, probe_job_from_manifest
from tools.parity.recorder.raw_capability_capture import Request, prepared
from tools.parity.recorder.resource_qualification import exr_fields
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control
from tools.parity.tier0_semantics import recording_requests as rr


@pytest.mark.parametrize("state", control.STATES)
def test_fixture_bytes_deterministic_and_native_samples_exact(tmp_path: Path, state: str) -> None:
    paths = [tmp_path / (str(i) + control.fixture_path(state).suffix) for i in range(2)]
    for path in paths:
        control.write_fixture(state, path)
    data = paths[0].read_bytes()
    assert data == paths[1].read_bytes() == (REPO_ROOT / control.fixture_path(state)).read_bytes()
    actual = decode(data)
    expected = control.authored_values(state)
    assert actual.values.shape == expected.shape == (256, 256, 3)
    assert np.array_equal(actual.values, expected.astype(np.float64))
    if state == "normalization-png16":
        assert actual.integer and actual.bits == 16
        assert [kind for kind, _ in png.chunks(data)] == [b"IHDR", b"IDAT", b"IEND"]
    else:
        assert not actual.integer and actual.bits == 32
        assert np.array_equal(
            actual.values.astype(np.float32).view(np.uint32), expected.view(np.uint32)
        )
        fields = exr_fields(data)
        assert fields["sample_types"] == ["float"] * 3
        assert fields["channel_names"] == ["B", "G", "R"]
        assert fields["compression"] == 0
        assert fields["attributes"] == sorted(
            [
                "channels",
                "compression",
                "dataWindow",
                "displayWindow",
                "lineOrder",
                "pixelAspectRatio",
                "screenWindowCenter",
                "screenWindowWidth",
                "type",
            ]
        )


def test_full_domain_and_calibration_endpoint_definition() -> None:
    codes = control.authored_values("normalization-png16")
    for channel in range(3):
        assert np.array_equal(np.sort(codes[..., channel], axis=None), np.arange(65536))
    floats = control.authored_values("normalization-float")
    assert np.array_equal(floats, (codes.astype(np.float64) / 65535).astype(np.float32))
    ladder = control.authored_values("calibration-float")
    assert np.isfinite(ladder).all() and (ladder >= 0).all() and (ladder <= 1).all()
    assert ladder[0, 0, 0] == ladder[0, 0, 1] == 0
    assert ladder[-1, -1, 0] == ladder[-1, -1, 2] == 1
    assert np.array_equal(ladder[..., 1], np.nextafter(ladder[..., 0], np.float32(0)))
    assert np.array_equal(ladder[..., 2], np.nextafter(ladder[..., 0], np.float32(1)))


@pytest.mark.parametrize("state", control.STATES)
@pytest.mark.parametrize("exports", [False, True])
def test_requests_use_existing_vocabulary_and_separate_setup(state: str, exports: bool) -> None:
    manifest = control.request(state, exports=exports)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(manifest) == []
    stored = (
        rr.request_root(REPO_ROOT)
        / "tier0/api-probes"
        / (manifest["golden_id"].rsplit("/", 1)[1] + ".json")
    )
    assert json.loads(stored.read_bytes()) == manifest
    job = probe_job_from_manifest(manifest)
    assert len(job.exports) == int(exports)
    assert all("set_" not in step.call for step in job.probe_steps)
    assert all(step.call != EXPORT for step in job.state_steps)
    assert sum(step.call == ps.SET_SOURCE for step in job.state_steps) == 1
    space = next(
        step for step in job.state_steps if step.call == control.BITMAP + "set_color_space"
    )
    assert space.args["color_space"] == "GenericColorSpace.Raw"
    assert "color_space_type" not in space.args
    assert manifest["golden_id"].endswith("-v3")
    previous = json.loads(
        stored.with_name(stored.name.replace("-v3.json", "-v2.json")).read_bytes()
    )
    assert previous["golden_id"].replace("-v2", "-v3") == manifest["golden_id"]
    assert previous["inputs"] == manifest["inputs"]
    assert (
        previous["instruction_sequence"]["steps"][:29]
        == manifest["instruction_sequence"]["steps"][:29]
    )
    if exports:
        capability = control.request(state)
        assert (
            manifest["instruction_sequence"]["steps"][:-1]
            == capability["instruction_sequence"]["steps"]
        )
        assert job.exports[0].parameters == {
            "fileFormat": "exr",
            "bitDepth": "32f",
            "dithering": False,
            "paddingAlgorithm": "passthrough",
        }
    assert manifest["private_records"] == []
    assert "flag remains unobserved" in manifest["description"]


@pytest.mark.parametrize("state", control.STATES)
@pytest.mark.parametrize("suffix", ["", "-v2"])
def test_current_runner_and_admission_refuse_historical_request(
    state: str, tmp_path: Path, suffix: str
) -> None:
    historical = (
        rr.request_root(REPO_ROOT)
        / "tier0/api-probes"
        / f"{control.PREFIX}-{state}-capability{suffix}.json"
    )
    with pytest.raises(ValueError, match="authored request differs"):
        prepared(Request(state, historical, REPO_ROOT / "pyproject.toml", tmp_path / "unused"))
    with pytest.raises(ValueError, match="authored capability request differs"):
        admission.validate_manifest(json.loads(historical.read_bytes()), state)


def synthetic() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    manifest = control.request("normalization-png16")
    resource = {"context": "public-synthetic", "name": "public-ramp", "version": "public-v1"}
    expected = control.fixed_readbacks()
    expected[control.PROJECT_UUID] = {
        "created_project_uuid": "public-project",
        "current_project_uuid": "public-project",
    }
    expected[control.RESOURCE_FROM_PROJECT] = {"resource": resource}
    expected[control.RESOURCE_RETRIEVE] = [{"resource": resource}]
    expected[ps.GET_SOURCE] = {"bitmap": {"resource": resource}, "color_space": "Raw"}
    expected[control.BITMAP + "list_available_color_spaces"] = ["Data", "Raw"]
    outputs = [
        {
            "kind": "api_readback",
            "output_id": f"s{s['step']}/{s['call'].rsplit('.', 1)[1]}",
            "call": s["call"],
            "args": deepcopy(s["args"]),
            "value": deepcopy(expected[s["call"]]),
        }
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"] in expected and is_read(s["call"], s["args"])
    ]
    outputs.append(
        {
            "kind": "template_capture",
            "output_id": "template/texture-sets",
            "subject": "texture sets, stacks and channel formats of the project",
            "values": {
                "texture_sets": {
                    "uzp_plane": {
                        "resolution": [256, 256],
                        "stacks": {
                            "": {
                                "User0": {
                                    "format": "RGB32F",
                                    "bit_depth": 32,
                                    "is_color": True,
                                    "is_floating": True,
                                    "label": "",
                                }
                            }
                        },
                    }
                }
            },
        }
    )
    return manifest, {"condition": "same_session", "outputs": outputs}, resource


@pytest.mark.parametrize("condition", ["same_session", "after_save_reopen"])
def test_state_gate_accepts_authored_synthetic_readbacks(condition: str) -> None:
    manifest, recording, resource = synthetic()
    recording["condition"] = condition
    control.validate_observed_state(recording, manifest, resource, "public-project")


@pytest.mark.parametrize(
    "mutation",
    [
        "resource",
        "data",
        "string",
        "enum",
        "format",
        "resolution_type",
        "uv",
        "active",
        "mask",
        "effect",
        "condition",
        "duplicate",
        "raised",
        "args",
        "missing_raw",
        "missing_getter",
    ],
)
def test_state_gate_refuses_changed_context(mutation: str) -> None:
    manifest, recording, resource = synthetic()
    outputs = recording["outputs"]
    by_call = {o.get("call"): o for o in outputs}
    if mutation == "missing_getter":
        manifest["instruction_sequence"]["steps"] = [
            step
            for step in manifest["instruction_sequence"]["steps"]
            if step["call"] != control.BITMAP + "get_color_space"
        ]
    elif mutation == "resource":
        by_call[ps.GET_SOURCE]["value"]["bitmap"]["resource"]["version"] = "other"
    elif mutation in ("data", "string", "enum"):
        by_call[control.BITMAP + "get_color_space"]["value"] = {
            "data": {"class": "DataColorSpace", "name": "Data"},
            "string": "Raw",
            "enum": {"class": "Other", "name": "Raw"},
        }[mutation]
    elif mutation in ("format", "resolution_type"):
        texture = outputs[-1]["values"]["texture_sets"]["uzp_plane"]
        if mutation == "format":
            texture["stacks"][""]["User0"]["format"] = "RGB16F"
        else:
            texture["resolution"] = [256.0, 256.0]
    elif mutation == "uv":
        by_call[control.FILL + "get_projection_parameters"]["value"]["uv_transformation"][
            "scale"
        ] = [2.0, 1.0]
    elif mutation == "active":
        by_call[control.FILL + "active_channels"]["value"].append("BaseColor")
    elif mutation == "mask":
        by_call[control.LAYER + "has_mask"]["value"] = True
    elif mutation == "effect":
        by_call[control.LAYER + "content_effects"]["value"] = [{}]
    elif mutation == "condition":
        recording["condition"] = "other"
    elif mutation == "duplicate":
        outputs.append(deepcopy(outputs[0]))
    elif mutation == "raised":
        outputs[0]["raised"] = {"message": "synthetic"}
    elif mutation == "args":
        by_call[control.NODE + "get_name"]["args"]["node_step"] += 1
    else:
        by_call[control.BITMAP + "list_available_color_spaces"]["value"] = ["Data"]
    with pytest.raises(ValueError):
        control.validate_observed_state(recording, manifest, resource, "public-project")


@pytest.mark.parametrize(
    "mutation",
    [
        "context",
        "retrieve_context",
        "empty",
        "multiple",
        "version",
        "name",
        "missing_version",
        "project",
        "marker",
    ],
)
def test_resource_evidence_refuses_unjoined_identity(mutation: str) -> None:
    manifest, recording, imported = synthetic()
    by_call = {o.get("call"): o for o in recording["outputs"]}
    query = by_call[control.RESOURCE_FROM_PROJECT]["value"]["resource"]
    retrieved = by_call[control.RESOURCE_RETRIEVE]["value"]
    if mutation == "context":
        query["context"] = "other-project"
    elif mutation == "retrieve_context":
        retrieved[0]["resource"]["context"] = "other-project"
    elif mutation == "empty":
        retrieved.clear()
    elif mutation == "multiple":
        retrieved.append(deepcopy(retrieved[0]))
    elif mutation in ("version", "name", "missing_version"):
        query["name" if mutation == "name" else "version"] = (
            "" if mutation == "missing_version" else "wrong"
        )
    else:
        key = "current_project_uuid" if mutation == "project" else "created_project_uuid"
        by_call[control.PROJECT_UUID]["value"][key] = "foreign-project"
    with pytest.raises(ValueError):
        control.validate_observed_state(recording, manifest, imported, "public-project")


def test_reopen_context_change_requires_independent_query_and_retrieval() -> None:
    manifest, recording, imported = synthetic()
    recording["condition"] = "after_save_reopen"
    by_call = {o.get("call"): o for o in recording["outputs"]}
    by_call[control.RESOURCE_FROM_PROJECT]["value"]["resource"]["context"] = (
        "reopened-project-context"
    )
    by_call[control.RESOURCE_RETRIEVE]["value"][0]["resource"]["context"] = (
        "reopened-project-context"
    )
    by_call[ps.GET_SOURCE]["value"]["bitmap"]["resource"]["context"] = "reopened-project-context"
    control.validate_observed_state(recording, manifest, imported, "public-project")
