"""Forge one receipt field at a time; no Painter process or private store."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.parity.test_ocio16_raw_readout_control import synthetic
from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_readout_admission as admission
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.environment import (
    ENVELOPE_FIELDS,
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
)
from tools.parity.recorder.output import GOLDEN_RECORD_ID
from tools.parity.recorder.probes import GET_NODE_BY_UID, probe_job_from_manifest
from tools.parity.schemas import record_problems
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def authored_record(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, first, resource = synthetic()
    job = probe_job_from_manifest(manifest)
    node = next(s.step for s in job.state_steps if s.call == ps.INSERT_FILL)
    first.update(recording_id="r1", session_id="public-session", recorded_at="2026-10-25T12:00:00Z")
    identity = {
        "output_id": f"identity/s{node}",
        "kind": "api_readback",
        "call": GET_NODE_BY_UID,
        "args": {"node_step": node},
        "value": {"present": True, "uid_same_as_recorded": True, "uid_resolves_to_node": True},
    }
    first["outputs"].append(identity)
    second = deepcopy(first)
    second.update(recording_id="r2", condition="after_save_reopen")
    second["outputs"].append(
        {
            "output_id": "identity/reopen",
            "kind": "api_readback",
            "call": GET_NODE_BY_UID,
            "args": {},
            "value": {"found_by": {str(node): "location"}},
        }
    )
    for step in job.state_steps:
        value: Any = None
        if step.call == ps.IMPORT_RESOURCE:
            value = {"resource": resource}
        if step.args.get("initial_root"):
            value = {
                "created_project_uuid": "public-project",
                "current_project_uuid": "public-project",
                "before": {"uid": 17, "node_type": "PaintLayer"},
                "after_root_count": 0,
            }
        first["outputs"].append(
            {
                "output_id": step.output_id,
                "kind": "api_readback",
                "call": step.call,
                "args": step.args,
                "value": value,
            }
        )
    colour = {
        "mode": "ocio",
        "OCIO": "public/resources/ocio/substance/config.ocio",
        "PAINTER_ACE_CONFIG": None,
    }
    environment = {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        **{field: "public" for field in ENVELOPE_FIELDS},
        "painter_build": current_envelope()["painter_build"],
    }
    environment["colour_configuration_sha256"] = "1" * 64
    environment["recorder_version"] = "synthetic/1"
    monkeypatch.setattr(
        replay,
        "recorded_request_environment_matches",
        lambda env, *args: env.get("gpu_model") == "public",
    )
    return manifest, {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": manifest["golden_id"],
        "tier": "0",
        "environment": environment,
        "key": {
            "inputs": job.input_hashes(),
            "instruction_sequence_sha256": job.instruction_sequence_sha256,
            "effective_defaults": {"colour_management": colour},
            "painter_build": manifest["software"]["painter"],
            "project_settings": {"create": job.project_settings(), "colour_management": colour},
            "resource_hashes": [],
            "bake_backend": None,
            "render_state": None,
        },
        "recordings": [first, second],
    }


def admitted(manifest: dict[str, Any], record: dict[str, Any]) -> tuple[bytes, bytes, Mock]:
    raw = json.dumps(record, sort_keys=True).encode()
    environment = json.dumps(record["environment"], sort_keys=True).encode()
    manifest["private_records"] = [
        {
            "record_id": identity,
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        for identity, kind, data in (
            (GOLDEN_RECORD_ID, "private_oracle_record", raw),
            (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND, environment),
        )
    ]
    entries = {
        ref["record_id"]: SimpleNamespace(
            kind=ref["kind"], sha256=ref["sha256"], size_bytes=ref["size_bytes"]
        )
        for ref in manifest["private_records"]
    }
    store = Mock()
    store.entry.side_effect = lambda build, golden, identity: entries.get(identity)
    return raw, environment, store


def test_complete_capability_receipt_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, record = authored_record(monkeypatch)
    assert record_problems(record) == []
    raw, environment, store = admitted(manifest, record)
    report = admission.validate_capability(
        manifest, raw, "normalization-png16", store, environment_bytes=environment
    )
    assert report["status"] == "validated" and report["rounds"] == 2
    assert report["color_channel_flag"] == "unobserved"
    assert report["readout_identity"] == "not_established" and not report["exports_authorized"]


@pytest.mark.parametrize(
    "mutation",
    [
        "binding",
        "missing",
        "foreign_environment",
        "topology",
        "condition",
        "session",
        "setter_r2",
        "key",
        "input_hash",
        "ocio",
        "space",
        "uid",
        "rebind",
        "cleanup_project",
        "cleanup_type",
        "cleanup_count",
        "state_args",
        "domain",
        "unadmitted",
        "receipt_hash",
    ],
)
def test_forged_receipts_refuse(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    manifest, record = authored_record(monkeypatch)
    first, second = record["recordings"]
    by_call = {o.get("call"): o for o in first["outputs"]}
    if mutation == "binding":
        by_call[ps.IMPORT_RESOURCE]["value"]["resource"] = {
            "context": "foreign",
            "name": "other",
            "version": "v2",
        }
    elif mutation == "missing":
        first["outputs"].pop(0)
    elif mutation == "foreign_environment":
        record["environment"]["gpu_model"] = "foreign"
    elif mutation == "topology":
        by_call[control.ROOT_LAYERS]["value"].append({"node_type": "PaintLayer"})
    elif mutation == "condition":
        second["condition"] = "same_session"
    elif mutation == "session":
        second["session_id"] = "foreign"
    elif mutation == "setter_r2":
        second["outputs"].append(deepcopy(by_call[ps.SET_SOURCE]))
    elif mutation == "key":
        record["key"]["instruction_sequence_sha256"] = "0" * 64
    elif mutation == "input_hash":
        record["key"]["inputs"][1]["sha256"] = "0" * 64
    elif mutation == "ocio":
        record["key"]["project_settings"]["colour_management"]["mode"] = "legacy"
    elif mutation == "space":
        by_call[control.BITMAP + "get_color_space"]["value"] = {
            "class": "DataColorSpace",
            "name": "Data",
        }
    elif mutation == "uid":
        next(o for o in first["outputs"] if o["output_id"].startswith("identity/s"))["value"][
            "uid_resolves_to_node"
        ] = False
    elif mutation == "rebind":
        second["outputs"][-1]["value"]["found_by"] = {"999": "location"}
    elif mutation.startswith("cleanup_"):
        value = by_call["substance_painter.layerstack.delete_node"]["value"]
        if mutation == "cleanup_project":
            value["current_project_uuid"] = "foreign"
        elif mutation == "cleanup_type":
            value["before"]["node_type"] = "FillLayer"
        else:
            value["after_root_count"] = False
    elif mutation == "state_args":
        by_call[ps.IMPORT_RESOURCE]["args"] = {"input": "other", "usage": "TEXTURE"}
    elif mutation == "domain":
        manifest["instruction_sequence"]["steps"].pop()
    raw, environment, store = admitted(manifest, record)
    if mutation == "unadmitted":
        store.entry.side_effect = lambda *args: None
    if mutation == "receipt_hash":
        raw += b" "
    with pytest.raises((ValueError, KeyError)):
        admission.validate_capability(
            manifest, raw, "normalization-png16", store, environment_bytes=environment
        )


def test_unadmitted_bytes_are_never_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, record = authored_record(monkeypatch)
    _, _, store = admitted(manifest, record)
    store.entry.side_effect = lambda *args: None
    load = Mock()
    monkeypatch.setattr(admission, "load_oracle", load)
    with pytest.raises(ValueError, match="not admitted"):
        admission.inspect_capability(manifest, "normalization-png16", store)
    load.assert_not_called()


def test_other_recipe_is_refused_before_private_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, record = authored_record(monkeypatch)
    _, _, store = admitted(manifest, record)
    manifest["instruction_sequence"]["steps"].pop()
    load = Mock()
    monkeypatch.setattr(admission, "load_oracle", load)
    with pytest.raises(ValueError, match="authored capability"):
        admission.inspect_capability(manifest, "normalization-png16", store)
    load.assert_not_called()
    store.entry.assert_not_called()


def test_runtime_pair_is_loaded_by_identity_not_position(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, record = authored_record(monkeypatch)
    raw, environment, store = admitted(manifest, record)
    manifest["private_records"].reverse()
    blobs = {GOLDEN_RECORD_ID: raw, ENVIRONMENT_RECORD_ID: environment}
    load = Mock(side_effect=lambda store, ref: blobs[ref["record_id"]])
    monkeypatch.setattr(admission, "load_oracle", load)
    assert admission.inspect_capability(manifest, "normalization-png16", store)["status"] == (
        "validated"
    )
    assert load.call_count == 2


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "foreign_id", "unknown_kind", "unadmitted", "unrelated", "hash"],
)
def test_environment_pair_refuses(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    manifest, record = authored_record(monkeypatch)
    raw, environment, store = admitted(manifest, record)
    ref = manifest["private_records"][1]
    if mutation == "missing":
        manifest["private_records"].pop()
    elif mutation == "duplicate":
        manifest["private_records"].append(deepcopy(ref))
    elif mutation == "foreign_id":
        ref["record_id"] = "foreign-oracle-environment"
    elif mutation == "unknown_kind":
        ref["kind"] = "private_oracle_record"
    elif mutation == "unadmitted":
        original = store.entry.side_effect
        store.entry.side_effect = lambda build, golden, identity: (
            None if identity == ENVIRONMENT_RECORD_ID else original(build, golden, identity)
        )
    elif mutation == "unrelated":
        foreign = deepcopy(record["environment"])
        foreign["gpu_model"] = "unrelated"
        environment = json.dumps(foreign, sort_keys=True).encode()
        ref.update(sha256=hashlib.sha256(environment).hexdigest(), size_bytes=len(environment))
        original = store.entry.side_effect
        store.entry.side_effect = lambda build, golden, identity: (
            SimpleNamespace(kind=ref["kind"], sha256=ref["sha256"], size_bytes=ref["size_bytes"])
            if identity == ENVIRONMENT_RECORD_ID
            else original(build, golden, identity)
        )
    else:
        environment += b" "
    blobs = {GOLDEN_RECORD_ID: raw, ENVIRONMENT_RECORD_ID: environment}
    load = Mock(side_effect=lambda store, ref: blobs[ref["record_id"]])
    monkeypatch.setattr(admission, "load_oracle", load)
    with pytest.raises(ValueError):
        admission.inspect_capability(manifest, "normalization-png16", store)
    if mutation not in {"unrelated", "hash"}:
        load.assert_not_called()
