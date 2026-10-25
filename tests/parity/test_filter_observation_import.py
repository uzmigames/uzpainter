"""Authored-only coverage of the observation preflight's typed wire boundary."""

from __future__ import annotations

import ast
import dataclasses
import datetime
import enum
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tools.parity import filter_observation_import as importer
from tools.parity.envelope import ocio
from tools.parity.envelope.registry import current_envelope
from tools.parity.filter_observation_import import (
    ImportRefused,
    build_payload,
    digest,
    parameters,
    parse,
    resource_id,
    typed_json,
)
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.probes import PAINTER_PROBES, probe_job_from_manifest
from tools.parity.schemas import REPO_ROOT, record_problems
from tools.parity.store.store import OracleStore
from tools.parity.tier0_semantics import filter_observation_control as control

SYNTHETIC_STORE: OracleStore = Mock(spec=OracleStore)


def test_hash_preserves_types_and_zero() -> None:
    assert len({digest({"p": value}) for value in (1, 1.0, 0, 0.0, -0.0)}) == 5
    assert typed_json({"z": "é", "a": 1.0}) == '{"a":1.0,"z":"é"}'.encode()


@pytest.mark.parametrize("value", [True, [], {}, None, float("inf"), float("nan"), 1 << 63])
def test_parameters_refuse_unsupported_types(value: object) -> None:
    with pytest.raises(ImportRefused):
        parameters({"p": value})


@pytest.mark.parametrize(
    "data", [b'{"p":1,"p":2}', b'{"p":NaN}', b'{"p":9223372036854775808}', b"[]"]
)
def test_json_refuses_ambiguous_or_unsupported_values(data: bytes) -> None:
    with pytest.raises(ImportRefused):
        parse(data)


def test_complete_resource_identity_keeps_observed_url() -> None:
    value: dict[str, Any] = {
        "resource_id": {"resource": {"context": "synthetic", "name": "host", "version": "v1"}},
        "url": "resource://synthetic/host?version=v1",
    }
    assert resource_id(value) == {
        "context": "synthetic",
        "name": "host",
        "version": "v1",
        "url": value["url"],
    }
    value["resource_id"]["resource"].pop("version")
    with pytest.raises(ImportRefused):
        resource_id(value)


def synthetic_environment() -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        "painter_build": current_envelope()["painter_build"],
        "gpu_model": "synthetic",
        "driver_version": "synthetic",
        "os_build": "synthetic",
        "colour_configuration_sha256": "1" * 64,
        "recorder_version": "synthetic-recorder/1",
    }


def install_authored_envelope(monkeypatch: pytest.MonkeyPatch) -> OracleStore:
    """Synthetic anchors and references; the request-specific policy itself stays real."""
    legacy = {**synthetic_environment(), "colour_configuration_sha256": "2" * 64}
    envelope = {
        **current_envelope(),
        "envelope_sha256": envelope_sha256(legacy),
        "equivalent_envelopes": [],
    }
    monkeypatch.setattr(importer, "current_envelope", lambda: envelope)
    monkeypatch.setattr(
        ocio,
        "ocio_identities",
        lambda current, store, configuration, repo_root: (
            [legacy],
            [synthetic_environment()]
            if configuration == ocio.named_ocio(control.request())
            else [],
        ),
    )
    return SYNTHETIC_STORE


@pytest.fixture(autouse=True)
def authored_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    install_authored_envelope(monkeypatch)


def synthetic_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = control.request()
    job = probe_job_from_manifest(manifest)
    record = json.loads(
        (REPO_ROOT / "parity/schema/samples/private/api-readback-record.json").read_bytes()
    )
    record["golden_id"] = manifest["golden_id"]
    record["key"]["inputs"] = job.input_hashes()
    record["key"]["instruction_sequence_sha256"] = job.instruction_sequence_sha256
    record["key"]["painter_build"] = deepcopy(manifest["software"]["painter"])
    colour = {
        "mode": "ocio",
        "OCIO": "synthetic/resources/ocio/substance/config.ocio",
        "PAINTER_ACE_CONFIG": None,
    }
    record["key"]["project_settings"] = {
        "create": job.project_settings(),
        "colour_management": colour,
    }
    record["key"]["effective_defaults"]["colour_management"] = deepcopy(colour)
    record["environment"] = synthetic_environment()
    for recording in record["recordings"]:
        outputs = []
        for step in job.probe_steps:
            getter = step.call.rsplit(".", 1)[1]
            effect = step.args.get("effect", False) or "FilterEffectNode" in step.call
            node = step.args["node_step"]
            host = next(s.step for s in job.state_steps if s.call.endswith(".insert_fill"))
            role = "host" if node == host else "filter"
            query = control.HOST_QUERY if role == "host" else control.FILTER_QUERY
            values: dict[str, Any] = {
                "get_name": "Observation " + role,
                "is_visible": True,
                "get_blending_mode": "Normal",
                "get_opacity": 1.0,
                "get_geometry_mask": deepcopy(control.GEOMETRY),
                "source_mode": "Split",
                "active_channels": [control.CHANNEL],
                "get_projection_mode": "UV",
                "is_symmetry_enabled": False,
                "get_parameters": {"seed": 3, "gain": -0.0},
                "resource_id": {
                    "resource_id": {
                        "resource": {
                            "context": query["resource_context"],
                            "name": query.get("resource_name", "synthetic/internal/" + role),
                            "version": "synthetic-v1",
                        }
                    },
                    "url": "resource://synthetic/" + role + "?version=synthetic-v1",
                },
                "image_outputs": ["height", "color"] if not effect else [],
                "active_output": "color",
                "resolution": {
                    "mode": "Custom",
                    "value": [256, 256],
                    "value_kind": "tuple",
                    "log2_offset": 0,
                },
                "image_inputs": [],
                "get_projection_parameters": {
                    "class": "UVProjectionParams",
                    "filtering_mode": "Nearest",
                    "uv_wrapping_mode": "Repeat",
                    "uv_transformation": {
                        **{k: control.UV[k] for k in ("scale_mode", "scale", "rotation", "offset")},
                    },
                },
            }
            outputs.append(
                {
                    "output_id": step.output_id,
                    "kind": "api_readback",
                    "call": step.call,
                    "args": step.args,
                    "value": values[getter],
                }
            )
        if recording["condition"] == "same_session":
            outputs = [
                {
                    "output_id": s.output_id,
                    "kind": "api_readback",
                    "call": s.call,
                    "args": s.args,
                    "value": None,
                }
                for s in job.state_steps
            ] + outputs
        recording["outputs"] = outputs
    assert record_problems(record) == []
    plane = job.inputs["plane"].read_bytes()
    mesh = {
        "sha256": hashlib.sha256(plane).hexdigest(),
        "size_bytes": len(plane),
        "mime": "model/obj",
    }
    projection = {
        "next_id": 10,
        "mesh": {"resource": mesh["sha256"]},
        "resources": {mesh["sha256"]: [{"mime": mesh["mime"], "size": len(plane)}]},
        "settings": {
            "normal_map_format": "OpenGL",
            "default_resolution": {"width": 256, "height": 256},
            "color_management": {"mode": "ocio", "config_hash": PAINTER_OCIO_CONFIG_SHA256},
        },
        "texture_sets": [
            {
                "id": 1,
                "name": "uzp_plane",
                "resolution": {"width": 256, "height": 256},
                "mesh_maps": {},
                "stacks": [
                    {"id": 2, "channels": {control.CHANNEL: {"format": "L32F"}}, "root_layers": []}
                ],
            }
        ],
        "display": {"environment": {"resource": None}, "color_lut": None},
        "authored_extra": "preserved",
    }
    base = {
        "schema": "uzpainter/filter-observation-base/1",
        "project_uuid": "synthetic-project",
        "projection": projection,
        "projection_sha256": digest(projection),
        "mesh": mesh,
    }
    return manifest, record, base


def receipt(manifest: dict[str, Any], record: dict[str, Any]) -> bytes:
    data = typed_json(record)
    manifest["private_records"] = [
        {
            "record_id": "golden",
            "kind": "private_oracle_record",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
    ]
    return data


def recorder_uv_description() -> dict[str, Any]:
    tree = ast.parse(PAINTER_PROBES.read_text())
    functions: list[ast.stmt] = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"describe", "class_name"}
    ]
    assert len(functions) == 2
    other = type("OtherPainterValue", (), {})
    namespace: dict[str, Any] = {
        "Any": Any,
        "enum": enum,
        "dataclasses": dataclasses,
        "datetime": datetime,
        "json": json,
        "substance_painter": SimpleNamespace(
            colormanagement=SimpleNamespace(Color=other),
            resource=SimpleNamespace(ResourceID=other, Shelf=other, Resource=other),
            source=SimpleNamespace(
                SourceBitmap=other, SourceUniformColor=other, SourceSubstance=other
            ),
            layerstack=SimpleNamespace(Node=other),
        ),
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(PAINTER_PROBES), "exec"), namespace
    )
    transformation = dataclasses.make_dataclass(
        "UVTransformationParams",
        [(key, Any) for key in ("scale_mode", "scale", "rotation", "offset")],
    )
    projection = dataclasses.make_dataclass(
        "UVProjectionParams",
        [(key, Any) for key in ("filtering_mode", "uv_wrapping_mode", "uv_transformation")],
    )

    def member(name: str, value: object) -> enum.Enum:
        entry = str(value)
        factory: Any = enum.Enum
        kind: type[enum.Enum] = factory(name, {entry: 1})
        result: enum.Enum = kind[entry]
        return result

    value = projection(
        filtering_mode=member("FilteringMode", control.UV["filtering_mode"]),
        uv_wrapping_mode=member("UVWrapMode", control.UV["uv_wrapping_mode"]),
        uv_transformation=transformation(
            scale_mode=member("ScaleMode", control.UV["scale_mode"]),
            scale=deepcopy(control.UV["scale"]),
            rotation=control.UV["rotation"],
            offset=deepcopy(control.UV["offset"]),
        ),
    )
    result: dict[str, Any] = namespace["describe"](value)
    return result


@pytest.mark.parametrize("mutation", [None, "nested_class", "offset", "extra_field", "outer_class"])
def test_uv_readback_uses_real_recorder_dataclass_shape_and_refuses_drift(
    mutation: str | None,
) -> None:
    manifest, record, base = synthetic_inputs()
    described = recorder_uv_description()
    assert described["class"] == "UVProjectionParams"
    assert "class" not in described["uv_transformation"]
    assert described["filtering_mode"] == "Nearest"
    if mutation == "nested_class":
        described["uv_transformation"]["class"] = "UVTransformationParams"
    elif mutation == "offset":
        described["uv_transformation"]["offset"][0] = 0.25
    elif mutation == "extra_field":
        described["uv_transformation"]["private-marker"] = "private-marker"
    elif mutation == "outer_class":
        described.pop("class")
    for recording in record["recordings"]:
        output = next(
            o
            for o in recording["outputs"]
            if o["call"] == control.FILL + "get_projection_parameters"
        )
        if mutation is None:
            assert typed_json(output["value"]) == typed_json(described)
        output["value"] = deepcopy(described)
    data = receipt(manifest, record)
    if mutation is None:
        payload = build_payload(manifest, data, base, texture_set=1, stack=2, store=SYNTHETIC_STORE)
        assert (
            payload["host_state"]["fill"]["projection"]["uv"]["uv_transformation"]
            == (described["uv_transformation"])
        )
    else:
        with pytest.raises(ImportRefused) as error:
            build_payload(manifest, data, base, texture_set=1, stack=2, store=SYNTHETIC_STORE)
        assert str(error.value) == (
            f"setter readback differs: {control.FILL}get_projection_parameters "
            f"(step {output['args']['node_step']})"
        )


def test_builder_derives_same_payload_without_mutating_inputs() -> None:
    manifest, record, base = synthetic_inputs()
    data = receipt(manifest, record)
    before = deepcopy((manifest, base))
    payload = build_payload(manifest, data, base, texture_set=1, stack=2, store=SYNTHETIC_STORE)
    assert (manifest, base) == before
    assert payload["host_state"]["uid"] == 10 and payload["filter_state"]["uid"] == 11
    ref = payload["host_state"]["fill"]["sources"][control.CHANNEL]
    assert ref["output_mapping"] == {control.CHANNEL: "color"}
    assert ref["params"]["gain"] == 0 and type(ref["params"]["gain"]) is int
    assert typed_json(payload["descriptors"]["host"]["parameters"]["gain"]) == b"-0.0"
    assert payload["expected_projection"]["next_id"] == 12
    assert payload["expected_projection"]["authored_extra"] == "preserved"
    assert payload["capture"]["recipe_sha256"] == digest(payload["recipe"]["body"])
    assert payload["readbacks"]["same_session"] == payload["readbacks"]["after_save_reopen"]


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy",
        "configuration",
        "build",
        "gpu",
        "os",
        "missing_store",
        "foreign_request",
    ],
)
def test_builder_requires_request_specific_ocio_relation(mutation: str) -> None:
    manifest, record, base = synthetic_inputs()
    store = None if mutation == "missing_store" else SYNTHETIC_STORE
    if mutation in ("legacy", "configuration"):
        record["environment"]["colour_configuration_sha256"] = (
            "2" if mutation == "legacy" else "3"
        ) * 64
    elif mutation in ("build", "gpu", "os"):
        field = {"build": "painter_build", "gpu": "gpu_model", "os": "os_build"}[mutation]
        record["environment"][field] = "foreign"
    elif mutation == "foreign_request":
        next(s for s in manifest["applied_settings"] if s["name"] == "OCIO")["value"] = "foreign"
    reason = (
        "private record schema"
        if mutation == "build"
        else r"authored recipe differs|recorded envelope differs"
    )
    with pytest.raises(ImportRefused, match=reason):
        build_payload(
            manifest, receipt(manifest, record), base, texture_set=1, stack=2, store=store
        )


def test_admitted_builder_passes_store_to_ocio_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, record, base = synthetic_inputs()
    data = receipt(manifest, record)
    monkeypatch.setattr(
        importer, "admitted_record", lambda store, value: (data, probe_job_from_manifest(value))
    )
    payload = importer.admitted_payload(SYNTHETIC_STORE, manifest, base, texture_set=1, stack=2)
    assert payload["target"]["project_uuid"] == base["project_uuid"]


@pytest.mark.parametrize(
    "mutation",
    [
        "getter_missing",
        "getter_duplicate",
        "getter_error",
        "pair_type",
        "geometry",
        "source_inputs",
        "active_output",
        "recipe",
        "base_hash",
        "target",
        "receipt",
    ],
)
def test_builder_refuses_incomplete_or_changed_evidence(mutation: str) -> None:
    manifest, record, base = synthetic_inputs()
    outputs = record["recordings"][0]["outputs"]
    if mutation == "getter_missing":
        outputs.pop()
    elif mutation == "getter_duplicate":
        outputs.append(deepcopy(outputs[-1]))
    elif mutation == "getter_error":
        outputs[-1]["raised"] = {"type": "ValueError", "message": "synthetic"}
    elif mutation == "pair_type":
        next(o for o in outputs if o["call"].endswith(".get_parameters"))["value"]["seed"] = 3.0
    elif mutation in ("geometry", "source_inputs", "active_output"):
        getter, value = {
            "geometry": (
                "get_geometry_mask",
                {"type": "Mesh", "inclusion_list": True, "items": []},
            ),
            "source_inputs": ("image_inputs", ["external"]),
            "active_output": ("active_output", "absent"),
        }[mutation]
        for recording in record["recordings"]:
            next(o for o in recording["outputs"] if o["call"].endswith("." + getter))["value"] = (
                value
            )
    elif mutation == "recipe":
        manifest["instruction_sequence"]["steps"][1]["call"] = "unapproved.operation"
    elif mutation == "base_hash":
        base["projection"]["next_id"] += 1
    elif mutation == "target":
        base["projection"]["texture_sets"][0]["name"] = "wrong"
        base["projection_sha256"] = digest(base["projection"])
    data = receipt(manifest, record)
    if mutation == "receipt":
        data += b" "
    with pytest.raises((ImportRefused, ValueError)):
        build_payload(manifest, data, base, texture_set=1, stack=2, store=SYNTHETIC_STORE)


@pytest.mark.parametrize(
    "mutation",
    [
        "state_raised",
        "environment_missing",
        "environment_changed",
        "painter_version",
        "create_settings",
        "colour_defaults",
    ],
)
def test_builder_refuses_setup_or_environment_changes(mutation: str) -> None:
    manifest, record, base = synthetic_inputs()
    if mutation == "state_raised":
        record["recordings"][0]["outputs"][0]["raised"] = {
            "type": "ValueError",
            "message": "synthetic",
        }
    elif mutation == "environment_missing":
        del record["environment"]
    elif mutation == "environment_changed":
        record["environment"]["driver_version"] = "different"
    elif mutation == "painter_version":
        record["key"]["painter_build"]["version"] = "0.0.0"
    elif mutation == "create_settings":
        record["key"]["project_settings"]["create"]["default_texture_resolution"] = 128
    elif mutation == "colour_defaults":
        record["key"]["effective_defaults"]["colour_management"]["mode"] = "legacy"
    with pytest.raises(ImportRefused):
        build_payload(
            manifest, receipt(manifest, record), base, texture_set=1, stack=2, store=SYNTHETIC_STORE
        )


def test_loader_refuses_blob_without_admission() -> None:
    from unittest.mock import Mock

    store = Mock()
    store.entry.return_value = None
    manifest, record, _ = synthetic_inputs()
    receipt(manifest, record)
    with pytest.raises(ImportRefused, match="not admitted"):
        importer.admitted_record(store, manifest)
    store.load.assert_not_called()


def test_json_refuses_underflow_without_changing_signed_zero() -> None:
    with pytest.raises(ImportRefused, match="underflow"):
        parse(b'{"p":1e-9999}')
    assert typed_json(parse(b'{"p":-0.0}')) == b'{"p":-0.0}'


@pytest.fixture
def gui_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    for role, usage in (("host", "PROCEDURAL"), ("filter", "FILTER")):
        monkeypatch.setattr(
            control,
            role.upper() + "_QUERY",
            {
                "search": "n:Synthetic " + role + "=",
                "require_unique": True,
                "resource_selection": "gui_name",
                "resource_context": "synthetic",
                "resource_gui_name": "Synthetic " + role,
                "resource_usage": usage,
            },
        )


def test_gui_builder_keeps_complete_observed_identity(gui_queries: None) -> None:
    manifest, record, base = synthetic_inputs()
    payload = build_payload(
        manifest, receipt(manifest, record), base, texture_set=1, stack=2, store=SYNTHETIC_STORE
    )
    for role in ("host", "filter"):
        assert payload["descriptors"][role]["resource_id"] == {
            "context": "synthetic",
            "name": "synthetic/internal/" + role,
            "version": "synthetic-v1",
            "url": "resource://synthetic/" + role + "?version=synthetic-v1",
        }


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
def test_gui_builder_refuses_identity_drift(gui_queries: None, field: str) -> None:
    manifest, record, base = synthetic_inputs()
    output = next(
        o for o in record["recordings"][1]["outputs"] if o["call"].endswith(".resource_id")
    )["value"]
    target = output if field == "url" else output["resource_id"]["resource"]
    target[field] += "-changed"
    with pytest.raises(ImportRefused, match="paired readbacks differ"):
        build_payload(
            manifest, receipt(manifest, record), base, texture_set=1, stack=2, store=SYNTHETIC_STORE
        )


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
def test_gui_selection_refuses_empty_identity(gui_queries: None, field: str) -> None:
    value: dict[str, Any] = {
        "resource_id": {"resource": {"context": "synthetic", "name": "internal", "version": "v1"}},
        "url": "resource://synthetic/internal?version=v1",
    }
    target: Any = value if field == "url" else value["resource_id"]["resource"]
    target[field] = ""
    with pytest.raises(ImportRefused, match="identity incomplete"):
        importer.selected_resource_identity(value, control.FILTER_QUERY, "filter")


@pytest.mark.parametrize(
    "mutation", ["mixed", "unknown", "usage", "not_unique", "empty_gui", "no_mode", "context"]
)
def test_gui_selection_refuses_wrong_contract(gui_queries: None, mutation: str) -> None:
    query = deepcopy(control.FILTER_QUERY)
    value = {
        "resource_id": {"resource": {"context": "synthetic", "name": "internal", "version": "v1"}},
        "url": "resource://synthetic/internal?version=v1",
    }
    if mutation == "mixed":
        query["resource_name"] = "internal"
    elif mutation == "unknown":
        query["resource_selection"] = "other"
    elif mutation == "usage":
        query["resource_usage"] = "PROCEDURAL"
    elif mutation == "not_unique":
        query["require_unique"] = False
    elif mutation == "empty_gui":
        query["resource_gui_name"] = ""
    elif mutation == "no_mode":
        del query["resource_selection"]
    elif mutation == "context":
        query["resource_context"] = "other"
    with pytest.raises(ImportRefused):
        importer.selected_resource_identity(value, query, "filter")


def test_exact_selection_still_requires_internal_name() -> None:
    query = {
        "search": "synthetic query",
        "require_unique": True,
        "resource_context": "synthetic",
        "resource_name": "authored-name",
    }
    value = {
        "resource_id": {"resource": {"context": "synthetic", "name": "other", "version": "v1"}},
        "url": "resource://synthetic/other?version=v1",
    }
    with pytest.raises(ImportRefused, match="selected resource differs"):
        importer.selected_resource_identity(value, query, "host")
