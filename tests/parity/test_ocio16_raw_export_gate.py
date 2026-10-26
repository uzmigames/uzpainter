"""Authored capability receipts and in-memory store; no Painter or real private evidence."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.parity.test_ocio16_raw_readout_admission import authored_record
from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_export_gate as gate
from tools.parity.envelope import ocio
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def authored_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests, records = [], []
    for state in control.STATES:
        _, record = authored_record(monkeypatch)
        manifest = control.request(state)
        job = probe_job_from_manifest(manifest)
        record["golden_id"] = manifest["golden_id"]
        record["key"]["inputs"] = job.input_hashes()
        record["key"]["instruction_sequence_sha256"] = job.instruction_sequence_sha256
        by_id = {o["output_id"]: o for o in record["recordings"][0]["outputs"]}
        for step in job.state_steps:
            by_id[step.output_id]["args"] = step.args
        record["environment"]["recorder_version"] = "authored-" + state
        # Independently created captures need not share project/resource/process identities.
        encoded = json.dumps(record)
        for marker in ("public-project", "public-synthetic", "public-session"):
            encoded = encoded.replace(marker, marker + "-" + state)
        manifests.append(manifest)
        records.append(json.loads(encoded))
    environment = deepcopy(records[0]["environment"])
    monkeypatch.setattr(ocio, "ocio_identities", lambda *args: ([environment], [environment]))
    monkeypatch.setattr(
        replay, "recorded_request_environment_matches", ocio.recorded_request_environment_matches
    )
    return manifests, records


def sealed(manifests: list[dict[str, Any]], records: list[dict[str, Any]]) -> Mock:
    entries: dict[tuple[str, str, str], Any] = {}
    blobs: dict[str, bytes] = {}
    for manifest, record in zip(manifests, records, strict=True):
        refs = []
        for identity, kind, document in (
            (GOLDEN_RECORD_ID, "private_oracle_record", record),
            (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND, record["environment"]),
        ):
            data = canonical_json(document)
            sha = hashlib.sha256(data).hexdigest()
            ref = {"record_id": identity, "kind": kind, "sha256": sha, "size_bytes": len(data)}
            refs.append(ref)
            entries[
                (manifest["software"]["painter"]["build_id"], manifest["golden_id"], identity)
            ] = SimpleNamespace(**ref)
            blobs[sha] = data
        manifest["private_records"] = refs
    store = Mock()
    store.entry.side_effect = lambda build, golden, identity: entries.get((build, golden, identity))
    store.load.side_effect = (
        lambda sha, size: blobs.get(sha) if len(blobs.get(sha, b"")) == size else None
    )
    return store


@pytest.mark.parametrize("state", control.STATES)
def test_three_fresh_capabilities_authorize_only_exact_collection(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    manifests, records = authored_bundle(monkeypatch)
    store = sealed(manifests, records)
    request = control.request(state, exports=True)
    report = gate.authorize_collection(request, state, list(reversed(manifests)), store)
    assert report["collection_authorized"] and report["status"] == "authorized"
    assert report["request_canonical_sha256"] == gate.digest(request)
    assert report["readout_identity"] == report["parity"] == "not_established"
    assert report["export_bytes_validated"] is False
    for prerequisite, manifest, record in zip(
        report["prerequisites"], manifests, records, strict=True
    ):
        assert prerequisite["manifest_canonical_sha256"] == gate.digest(manifest)
        assert prerequisite["record_sha256"] == gate.digest(record)
        assert prerequisite["private_records"] == sorted(
            manifest["private_records"], key=lambda r: r["record_id"]
        )
    assert store.entry.call_count >= 6 and store.load.call_count >= 6


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "legacy",
        "reference",
        "unadmitted",
        "envelope",
        "configuration",
        "build",
        "capability",
        "request",
        "export_refs",
        "prior_audit",
    ],
)
def test_gate_refuses_missing_or_changed_evidence(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifests, records = authored_bundle(monkeypatch)
    request = control.request("calibration-float", exports=True)
    if mutation == "envelope":
        records[1]["environment"]["gpu_model"] = "different-host"
    elif mutation == "configuration":
        records[1]["environment"]["colour_configuration_sha256"] = "2" * 64
    elif mutation == "build":
        records[1]["environment"]["painter_build"] = "different-build"
    elif mutation == "capability":
        template = next(
            output
            for output in records[1]["recordings"][1]["outputs"]
            if output["kind"] == "template_capture"
        )
        template["values"]["texture_sets"]["uzp_plane"]["resolution"] = [128, 128]
    store = sealed(manifests, records)
    if mutation == "missing":
        manifests.pop()
    elif mutation == "extra":
        manifests.append(deepcopy(manifests[0]))
    elif mutation == "duplicate":
        manifests[1] = deepcopy(manifests[0])
    elif mutation == "legacy":
        manifests[1]["golden_id"] = manifests[1]["golden_id"].replace("-v3", "-v2")
    elif mutation == "reference":
        manifests[1]["private_records"].append(deepcopy(manifests[1]["private_records"][0]))
    elif mutation == "unadmitted":
        store.entry.side_effect = lambda *args: None
    elif mutation == "request":
        request["instruction_sequence"]["steps"][-1]["args"]["bit_depth"] = "16f"
    elif mutation == "export_refs":
        request["private_records"] = manifests[0]["private_records"]
    elif mutation == "prior_audit":
        manifests[0] = {"status": "authorized", "collection_authorized": True}
    with pytest.raises(ValueError):
        gate.authorize_collection(request, "calibration-float", manifests, store)


def test_previous_authorization_never_skips_live_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    manifests, records = authored_bundle(monkeypatch)
    store = sealed(manifests, records)
    request = control.request("calibration-float", exports=True)
    assert gate.authorize_collection(request, "calibration-float", manifests, store)[
        "collection_authorized"
    ]
    store.entry.side_effect = lambda *args: None
    with pytest.raises(ValueError, match="not admitted"):
        gate.authorize_collection(request, "calibration-float", manifests, store)


def test_export_environment_join_is_checked_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    manifests, records = authored_bundle(monkeypatch)
    store = sealed(manifests, records)
    monkeypatch.setattr(gate, "recorded_request_environment_matches", lambda *args: False)
    with pytest.raises(ValueError, match="export request envelope"):
        gate.authorize_collection(
            control.request("calibration-float", exports=True),
            "calibration-float",
            manifests,
            store,
        )
