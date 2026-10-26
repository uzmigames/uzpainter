"""Admitted authored receipts and real OpenEXR files; no Painter, native build or private store."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import OpenEXR
import pytest

from tests.parity.test_ocio16_raw_readout_admission import authored_record
from tools.parity import ocio16_raw_export_admission as admission
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import private_record_refs
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def write_exr(
    path: Path,
    *,
    dtype: Any = np.float32,
    shape: tuple[int, int] = (256, 256),
    names: str = "RGB",
    mixed: bool = False,
    value: float = 0.25,
    comment: str = "authored",
) -> bytes:
    header = {
        "type": OpenEXR.scanlineimage,
        "compression": OpenEXR.ZIP_COMPRESSION,
        "comments": comment,
    }
    channels = {
        name: np.full(shape, value, dtype=np.float16 if mixed and name == "G" else dtype)
        for name in names
    }
    OpenEXR.File(header, channels).write(str(path))
    return path.read_bytes()


def authored_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str = "normalization-png16",
    *,
    different_encoding: bool = False,
    signed_zero: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    _, record = authored_record(monkeypatch)
    manifest = control.request(state, exports=True)
    job = probe_job_from_manifest(manifest)
    record["golden_id"] = manifest["golden_id"]
    record["key"]["inputs"] = job.input_hashes()
    record["key"]["instruction_sequence_sha256"] = job.instruction_sequence_sha256
    by_id = {o["output_id"]: o for o in record["recordings"][0]["outputs"]}
    for step in job.state_steps:
        by_id[step.output_id]["args"] = step.args
    paths = {}
    for index, recording in enumerate(record["recordings"]):
        path = tmp_path / f"round-{index}.exr"
        data = write_exr(
            path,
            value=(-0.0 if index else 0.0) if signed_zero else 0.25,
            comment=str(index) if different_encoding else "authored",
        )
        sha = hashlib.sha256(data).hexdigest()
        paths[sha] = path
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
                    "encoding_basis": "file",
                },
            }
        )
    return manifest, record, paths


def sealed(manifest: dict[str, Any], record: dict[str, Any], paths: dict[str, Path]) -> Mock:
    raw, environment = canonical_json(record), canonical_json(record["environment"])
    blobs = {sha: path.read_bytes() for sha, path in paths.items()}
    refs = private_record_refs(raw, record, {sha: len(data) for sha, data in blobs.items()})
    env_sha = hashlib.sha256(environment).hexdigest()
    refs.append(
        {
            "record_id": ENVIRONMENT_RECORD_ID,
            "kind": ENVIRONMENT_KIND,
            "sha256": env_sha,
            "size_bytes": len(environment),
        }
    )
    manifest["private_records"] = refs
    blobs[hashlib.sha256(raw).hexdigest()] = raw
    blobs[env_sha] = environment
    entries = {ref["record_id"]: SimpleNamespace(**ref) for ref in refs}
    store = Mock()
    store.entry.side_effect = (
        lambda build, golden, identity: entries.get(identity)
        if golden == manifest["golden_id"] and build == manifest["software"]["painter"]["build_id"]
        else None
    )
    store.load.side_effect = (
        lambda sha, size: blobs.get(sha) if len(blobs.get(sha, b"")) == size else None
    )
    store.blob_path.side_effect = lambda sha: paths[sha]
    return store


@pytest.mark.parametrize("state", control.STATES)
@pytest.mark.parametrize("different_encoding", [False, True])
def test_admitted_real_float_exports_pass_without_input_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, different_encoding: bool
) -> None:
    manifest, record, paths = authored_export(
        tmp_path, monkeypatch, state, different_encoding=different_encoding
    )
    store = sealed(manifest, record, paths)
    report = admission.inspect_export(manifest, state, store)
    assert report["status"] == "validated" and report["rounds"] == report["exports"] == 2
    assert report["decoded_rounds_bit_exact"] and report["all_finite"]
    assert report["readout_identity"] == report["parity"] == "not_established"
    assert report["color_channel_flag"] == "unobserved"
    assert (len(set(report["map_sha256"])) == 2) is different_encoding
    refs = [r for r in manifest["private_records"] if r["kind"] == "exported_map"]
    assert {r["record_id"] for r in refs} == {
        "r1-uzp_plane-user0-step34",
        "r2-uzp_plane-user0-step34",
    }


@pytest.mark.parametrize(
    "mutation",
    ["half", "uint", "mixed", "shape", "channels", "nan", "infinity", "signature", "path_receipt"],
)
def test_native_decoder_rejects_wrong_real_exr_domain(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "authored.exr"
    options: dict[str, Any] = {}
    if mutation in ("half", "uint"):
        options["dtype"] = np.float16 if mutation == "half" else np.uint32
    elif mutation == "mixed":
        options["mixed"] = True
    elif mutation == "shape":
        options["shape"] = (128, 256)
    elif mutation == "channels":
        options["names"] = "RGBA"
    elif mutation in ("nan", "infinity"):
        options["value"] = np.nan if mutation == "nan" else np.inf
    data = write_exr(path, **options)
    if mutation == "signature":
        data = b"not an EXR"
    elif mutation == "path_receipt":
        path.write_bytes(data + b"changed")
    with pytest.raises(ValueError):
        admission.decode_native(path, data)


def test_signed_zero_difference_is_not_numeric_equality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, record, paths = authored_export(tmp_path, monkeypatch, signed_zero=True)
    with pytest.raises(ValueError, match="native bits"):
        admission.inspect_export(manifest, "normalization-png16", sealed(manifest, record, paths))


@pytest.mark.parametrize(
    "mutation",
    [
        "settings",
        "basis",
        "storage",
        "map",
        "output_id",
        "media",
        "uuid",
        "resource",
        "setup_r2",
        "receipt_input",
        "environment",
        "round",
    ],
)
def test_forged_export_receipts_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifest, record, paths = authored_export(tmp_path, monkeypatch)
    second = record["recordings"][1]
    exported = second["outputs"][-1]
    if mutation == "settings":
        exported["export_settings"]["dithering"] = True
    elif mutation == "basis":
        exported["export_settings"]["encoding_basis"] = "source_channel_format"
    elif mutation == "storage":
        exported["storage_format"]["sample_type"] = "half"
    elif mutation == "map":
        exported["map"] = "basecolor"
    elif mutation == "output_id":
        exported["output_id"] = "foreign/user0/step34"
    elif mutation == "media":
        exported["blob"]["media_type"] = "image/png"
    elif mutation in ("uuid", "resource"):
        call = control.PROJECT_UUID if mutation == "uuid" else control.RESOURCE_RETRIEVE
        value = next(o["value"] for o in second["outputs"] if o.get("call") == call)
        if mutation == "uuid":
            value["current_project_uuid"] = "foreign-project"
        else:
            value[0]["resource"]["context"] = "foreign-resource"
    elif mutation == "setup_r2":
        first = record["recordings"][0]
        second["outputs"].append(
            deepcopy(next(o for o in first["outputs"] if o.get("args", {}).get("initial_root")))
        )
    elif mutation == "receipt_input":
        record["key"]["inputs"][0]["sha256"] = "0" * 64
    elif mutation == "environment":
        record["environment"]["gpu_model"] = "foreign-host"
    else:
        second["condition"] = "same_session"
    with pytest.raises(ValueError):
        admission.inspect_export(manifest, "normalization-png16", sealed(manifest, record, paths))


@pytest.mark.parametrize("mutation", ["missing", "extra", "alias", "kind", "legacy", "unadmitted"])
def test_public_ref_inventory_and_admission_precede_blob_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifest, record, paths = authored_export(tmp_path, monkeypatch)
    store = sealed(manifest, record, paths)
    refs = manifest["private_records"]
    if mutation == "missing":
        refs.pop(1)
    elif mutation == "extra":
        refs.append(deepcopy(refs[1]))
    elif mutation == "alias":
        refs[2]["record_id"] = refs[1]["record_id"]
    elif mutation == "kind":
        refs[1]["kind"] = "private_oracle_record"
    elif mutation == "legacy":
        manifest["golden_id"] = manifest["golden_id"].replace("-v3", "-v2")
    else:
        store.entry.side_effect = lambda *args: None
    with pytest.raises(ValueError):
        admission.inspect_export(manifest, "normalization-png16", store)
    store.load.assert_not_called()


def test_admitted_ref_id_must_match_producer_round_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, record, paths = authored_export(tmp_path, monkeypatch)
    store = sealed(manifest, record, paths)
    ref = manifest["private_records"][1]
    ref["record_id"] = "r1-unrelated-map"
    entries = {r["record_id"]: SimpleNamespace(**r) for r in manifest["private_records"]}
    store.entry.side_effect = lambda build, golden, identity: entries.get(identity)
    with pytest.raises(ValueError, match="export references differ"):
        admission.inspect_export(manifest, "normalization-png16", store)
