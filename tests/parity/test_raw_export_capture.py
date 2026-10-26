"""Real export gate over authored in-memory evidence; mocked Painter/process boundaries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_ocio16_raw_export_gate import authored_bundle, sealed
from tests.parity.test_ocio16_raw_readout_admission import authored_record
from tests.parity.test_raw_capability_capture import boundaries
from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_export_gate as gate
from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.recorder import raw_export_capture as capture
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import private_record_refs
from tools.parity.recorder.probes import ProbeJob
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def setup_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[capture.Request, Any, dict[str, Any]]:
    manifests, records = authored_bundle(monkeypatch)
    store = sealed(manifests, records)
    paths = []
    for index, manifest in enumerate(manifests):
        path = tmp_path / f"capability-{index}.json"
        path.write_bytes(canonical_json(manifest))
        paths.append(path)
    request_path = tmp_path / "export.json"
    request_path.write_bytes(canonical_json(control.request("normalization-png16", exports=True)))
    executable = tmp_path / "authored.exe"
    executable.write_bytes(b"not executable")
    request = capture.Request(
        "normalization-png16", request_path, executable, tmp_path / "capture", tuple(paths)
    )
    monkeypatch.setattr(capture, "locate", lambda: store)
    # Get the receipt template first; restore the real environment join installed by the bundle.
    _, record = authored_record(monkeypatch)
    monkeypatch.setattr(
        replay, "recorded_request_environment_matches", recorded_request_environment_matches
    )
    return request, store, record


def write_ready(run: Path, job: ProbeJob, template: dict[str, Any], mutation: str = "") -> None:
    record = deepcopy(template)
    record["golden_id"] = job.manifest["golden_id"]
    record["key"]["instruction_sequence_sha256"] = job.instruction_sequence_sha256
    record["key"]["inputs"] = job.input_hashes()
    data = b"authored opaque export bytes; decoding belongs to the later pixel gate"
    sha = hashlib.sha256(data).hexdigest()
    for recording in record["recordings"]:
        recording["outputs"].append(
            {
                "output_id": f"uzp_plane/user0/step{job.exports[0].step}",
                "kind": "exported_map",
                "texture_set": "uzp_plane",
                "map": "user0",
                "blob": {"sha256": sha, "size_bytes": len(data), "media_type": "image/x-exr"},
                "storage_format": {
                    "container": "exr",
                    "sample_type": "float",
                    "bits_per_channel": 32,
                    "channels": 3,
                    "encoding": "linear",
                },
                "export_settings": {
                    **job.exports[0].parameters,
                    "step": job.exports[0].step,
                    "map_type": "documentMap",
                    "map_channels": "RGB",
                    "encoding_basis": "source_channel_format",
                },
            }
        )
    if mutation == "round":
        record["recordings"][1]["condition"] = "same_session"
    elif mutation == "extra_map":
        extra = deepcopy(record["recordings"][1]["outputs"][-1])
        extra["output_id"] += "-extra"
        record["recordings"][1]["outputs"].append(extra)
    elif mutation == "map_id":
        record["recordings"][1]["outputs"][-1]["output_id"] = "foreign/user0/step34"
    raw = canonical_json(record)
    environment = canonical_json(record["environment"])
    environment_sha = hashlib.sha256(environment).hexdigest()
    manifest = deepcopy(job.manifest)
    refs = private_record_refs(raw, record, {sha: len(data)})
    refs.append(
        {
            "record_id": ENVIRONMENT_RECORD_ID,
            "kind": ENVIRONMENT_KIND,
            "sha256": environment_sha,
            "size_bytes": len(environment),
        }
    )
    if mutation == "missing_ref":
        refs.pop(1)
    elif mutation == "aliased_ref":
        refs[2]["record_id"] = refs[1]["record_id"]
    manifest["private_records"] = refs
    (run / "record.json").write_bytes(raw)
    (run / "manifest.json").write_bytes(canonical_json(manifest))
    blobs = run / "blobs"
    blobs.mkdir()
    (blobs / sha).write_bytes(b"corrupted" if mutation == "blob" else data)
    (blobs / environment_sha).write_bytes(environment)


def test_export_gate_inside_lock_before_launch_and_private_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, store, template = setup_capture(tmp_path, monkeypatch)
    state = boundaries(
        monkeypatch,
        request,
        export=True,
        ready_writer=lambda run, job: write_ready(run, job, template),
    )
    real_gate = gate.authorize_collection

    def checked_gate(*args: Any) -> dict[str, Any]:
        assert "lock" in state.calls and "start" not in state.calls
        state.calls.append("gate")
        return real_gate(*args)

    monkeypatch.setattr(gate, "authorize_collection", checked_gate)
    result = capture.capture(request)
    assert (
        result["status"] == "complete"
        and result["captures"] == 1
        and result["exports"] == 2
        and result["admissions"] == 0
    )
    assert state.calls.index("lock") < state.calls.index("gate") < state.calls.index("start")
    assert state.calls[-2:] == ["stop", "release"] and not state.running
    report = json.loads(request.output_prefix.with_suffix(".report.json").read_bytes())
    audit = Path(report["authorization_path"]).read_bytes()
    assert report["authorization_sha256"] == hashlib.sha256(audit).hexdigest()
    assert len(report["private_records"]) == 4 and report["export_bytes_validated"] is False
    assert json.loads(audit)["collection_authorized"] is True
    assert store.entry.call_count >= 6
    assert {call[0] for call in store.method_calls} <= {"entry", "load"}
    assert "run" not in result and "authorization_path" not in result


@pytest.mark.parametrize(
    "failure", ["unadmitted", "duplicate", "cached_audit", "audit_exists", "capability_recipe"]
)
def test_gate_or_request_refusal_never_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    request, store, _ = setup_capture(tmp_path, monkeypatch)
    state = boundaries(monkeypatch, request, export=True)
    if failure == "unadmitted":
        store.entry.side_effect = lambda *args: None
    elif failure == "duplicate":
        request = replace(request, capability_manifests=(request.capability_manifests[0],) * 3)
    elif failure == "cached_audit":
        request.capability_manifests[0].write_bytes(
            canonical_json({"status": "authorized", "collection_authorized": True})
        )
    elif failure == "audit_exists":
        request.output_prefix.with_suffix(".authorization.json").write_bytes(b"existing")
    else:
        request.manifest.write_bytes(canonical_json(control.request(request.state)))
    result = capture.capture(request)
    assert (
        result["status"] == "refused"
        and result["captures"] == result["exports"] == result["admissions"] == 0
    )
    assert "start" not in state.calls and "capture" not in state.calls
    if failure == "audit_exists":
        assert request.output_prefix.with_suffix(".authorization.json").read_bytes() == b"existing"


@pytest.mark.parametrize(
    "failure",
    [
        "remote_pid",
        "marker",
        "marker_ipc",
        "create_swap",
        "reopen_uuid",
        "project_swap",
        "lock_loss",
        "process_start",
        "after_ready",
    ],
)
def test_export_ownership_loss_preserves_process_and_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    request, _, template = setup_capture(tmp_path, monkeypatch)
    state = boundaries(
        monkeypatch,
        request,
        failure,
        export=True,
        ready_writer=lambda run, job: write_ready(run, job, template),
    )
    result = capture.capture(request)
    assert result["status"] == "refused" and state.running
    assert not {"stop", "terminate", "release"}.intersection(state.calls)
    if failure == "after_ready":
        report = json.loads(request.output_prefix.with_suffix(".report.json").read_bytes())
        assert result["captures"] == 1 and result["exports"] == 2
        assert (Path(report["run"]) / "READY").is_file()


@pytest.mark.parametrize(
    "mutation", ["round", "extra_map", "map_id", "missing_ref", "aliased_ref", "blob"]
)
def test_ready_inventory_refuses_and_preserves_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    request, _, template = setup_capture(tmp_path, monkeypatch)
    state = boundaries(
        monkeypatch,
        request,
        export=True,
        ready_writer=lambda run, job: write_ready(run, job, template, mutation),
    )
    result = capture.capture(request)
    assert result["status"] == "refused" and result["captures"] == 1
    assert state.calls[-2:] == ["stop", "release"] and not state.running
    report = json.loads(request.output_prefix.with_suffix(".report.json").read_bytes())
    assert (Path(report["run"]) / "READY").is_file() and result["admissions"] == 0


def test_export_capture_failure_closes_only_owned_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _, _ = setup_capture(tmp_path, monkeypatch)
    state = boundaries(monkeypatch, request, "capture", export=True)
    result = capture.capture(request)
    assert result["status"] == "refused" and not state.running and not state.opened
    assert state.closes == 1 and state.calls[-2:] == ["stop", "release"]
