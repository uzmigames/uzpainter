"""Validate admitted Raw V3 export receipts and native FLOAT32 stability, offline.

The recorded EXR encoding label is format metadata, not proof of an identity transform.
No input/output equality, Color flag, fit, tolerance or production parity is inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_readout_admission as receipt
from tools.parity.fit.decode import Array
from tools.parity.preserve_diagnostic_evidence import file_fingerprint
from tools.parity.recorder.capture import exr_format
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import (
    GOLDEN_RECORD_ID,
    ensure_outside_repository,
    private_record_refs,
)
from tools.parity.recorder.probes import ProbeJob, probe_job_from_manifest
from tools.parity.recorder.resource_qualification import exr_fields
from tools.parity.recorder.texture import output_safe
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def validate_manifest(manifest: dict[str, Any], state: str) -> dict[str, Any]:
    authored = control.request(state, exports=True)
    receipt.require(not validation_errors(manifest, Schema.GOLDEN_PUBLIC), "public export schema")
    receipt.equal(
        {k: v for k, v in manifest.items() if k != "private_records"},
        {k: v for k, v in authored.items() if k != "private_records"},
        "authored export request differs",
    )
    refs = manifest["private_records"]
    receipt.require(
        len(refs) == 4 and len({r["record_id"] for r in refs}) == 4,
        "four export references required",
    )
    fixed = {(r["kind"], r["record_id"]) for r in refs if r["kind"] != "exported_map"}
    receipt.require(
        fixed
        == {("private_oracle_record", GOLDEN_RECORD_ID), (ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID)}
        and sum(r["kind"] == "exported_map" for r in refs) == 2,
        "export reference kinds",
    )
    return authored


def export_outputs(record: dict[str, Any], job: ProbeJob) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt.require(len(record["recordings"]) == 2 and len(job.exports) == 1, "export round domain")
    outputs = []
    for recording in record["recordings"]:
        maps = [o for o in recording["outputs"] if o["kind"] == "exported_map"]
        receipt.require(len(maps) == 1, "one export per round")
        template = receipt.output(recording, "template/texture-sets")
        receipt.require(template["kind"] == "template_capture", "export template kind")
        sets = template["values"]["texture_sets"]
        receipt.require(
            set(sets) == {"uzp_plane"} and len(sets["uzp_plane"]["stacks"]) == 1,
            "export stack inventory",
        )
        stack = next(iter(sets["uzp_plane"]["stacks"]))
        identity = "/".join(
            [
                "uzp_plane",
                *([output_safe(stack)] if stack else []),
                "user0",
                f"step{job.exports[0].step}",
            ]
        )
        receipt.equal(
            [maps[0]["output_id"], maps[0]["texture_set"], maps[0]["map"]],
            [identity, "uzp_plane" + ("/" + stack if stack else ""), "user0"],
            "export map identity",
        )
        receipt.equal(
            maps[0]["export_settings"],
            {
                **job.exports[0].parameters,
                "step": job.exports[0].step,
                "map_type": "documentMap",
                "map_channels": "RGB",
                "encoding_basis": "file",
            },
            "export settings differ",
        )
        receipt.equal(maps[0]["blob"]["media_type"], "image/x-exr", "export media type")
        outputs.append(maps[0])
    return outputs[0], outputs[1]


def decode_native(path: Path, data: bytes) -> Array:
    """Decode the verified blob with the existing OpenEXR binding, without a temporary copy."""
    import OpenEXR

    receipt.require(data[:4] == b"\x76\x2f\x31\x01", "EXR signature")
    measured = exr_fields(data)
    receipt.equal(
        [
            measured["width"],
            measured["height"],
            sorted(measured["channel_names"]),
            measured["sample_types"],
        ],
        [256, 256, ["B", "G", "R"], ["float"] * 3],
        "EXR native header differs",
    )
    expected = [hashlib.sha256(data).hexdigest(), len(data)]
    receipt.equal(list(file_fingerprint(path)), expected, "decode blob receipt differs")
    with OpenEXR.File(str(path), separate_channels=True) as image:
        receipt.require(len(image.parts) == 1, "single EXR part required")
        channels = image.channels()
        receipt.require(set(channels) == {"R", "G", "B"}, "EXR channels differ")
        planes = []
        for name in "RGB":
            channel = channels[name]
            receipt.require(channel.xSampling == channel.ySampling == 1, "EXR channel sampling")
            plane = np.asarray(channel.pixels)
            receipt.require(
                plane.dtype == np.dtype(np.float32) and plane.shape == (256, 256),
                "native FLOAT32 plane required",
            )
            receipt.require(bool(np.isfinite(plane).all()), "non-finite export sample")
            planes.append(plane)
        values = np.stack(planes, axis=-1)
    receipt.equal(list(file_fingerprint(path)), expected, "decode blob changed")
    return values


def validate_export(
    manifest: dict[str, Any],
    record_bytes: bytes,
    state: str,
    store: OracleStore,
    *,
    environment_bytes: bytes,
) -> dict[str, Any]:
    authored = validate_manifest(manifest, state)
    record = receipt.validate_record_receipt(
        manifest, authored, record_bytes, store, environment_bytes=environment_bytes
    )
    job = probe_job_from_manifest(authored)
    maps = export_outputs(record, job)
    receipt.validate_rounds(
        record, authored, export_output_ids=(maps[0]["output_id"], maps[1]["output_id"])
    )
    refs = manifest["private_records"]
    map_refs = [r for r in refs if r["kind"] == "exported_map"]
    sizes = {ref["sha256"]: ref["size_bytes"] for ref in map_refs}
    environment_ref = next(r for r in refs if r["record_id"] == ENVIRONMENT_RECORD_ID)
    expected = [*private_record_refs(record_bytes, record, sizes), environment_ref]
    receipt.equal(
        sorted(refs, key=lambda r: r["record_id"]),
        sorted(expected, key=lambda r: r["record_id"]),
        "export references differ",
    )
    pixels = []
    hashes = []
    for output in maps:
        blob = output["blob"]
        raw = load_oracle(store, blob)
        receipt.require(raw is not None, "export blob unavailable")
        assert raw is not None
        receipt.equal(
            [hashlib.sha256(raw).hexdigest(), len(raw)],
            [blob["sha256"], blob["size_bytes"]],
            "export blob receipt differs",
        )
        measured = exr_format(raw)
        receipt.equal(
            output["storage_format"],
            measured.as_schema("linear"),
            "measured export storage differs",
        )
        pixels.append(decode_native(store.blob_path(blob["sha256"]), raw))
        hashes.append(blob["sha256"])
    receipt.require(
        np.array_equal(pixels[0].view(np.uint32), pixels[1].view(np.uint32)),
        "export rounds differ at native bits",
    )
    return {
        "schema": "uzpainter/raw-export-validation/1",
        "status": "validated",
        "state": state,
        "rounds": 2,
        "exports": 2,
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
        "request_canonical_sha256": hashlib.sha256(canonical_json(authored)).hexdigest(),
        "map_sha256": hashes,
        "decoded_rounds_bit_exact": True,
        "sample_type": "FLOAT32",
        "shape": [256, 256, 3],
        "all_finite": True,
        "color_channel_flag": "unobserved",
        "readout_identity": "not_established",
        "parity": "not_established",
    }


def inspect_export(manifest: dict[str, Any], state: str, store: OracleStore) -> dict[str, Any]:
    validate_manifest(manifest, state)
    replay.require_admitted_refs(store, manifest)
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    raw = load_oracle(store, refs[GOLDEN_RECORD_ID])
    environment = load_oracle(store, refs[ENVIRONMENT_RECORD_ID])
    receipt.require(raw is not None and environment is not None, "export receipt unavailable")
    assert raw is not None and environment is not None
    return validate_export(manifest, raw, state, store, environment_bytes=environment)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", choices=control.STATES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = None
    try:
        destination = ensure_outside_repository(args.output)
        receipt.require(
            destination.parent.is_dir() and not destination.exists(), "private output destination"
        )
        store = locate()
        receipt.require(store is not None, "store unavailable")
        assert store is not None
        report = inspect_export(json.loads(args.manifest.read_bytes()), args.state, store)
        encoded = canonical_json(report) + b"\n"
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {
                    "status": "validated",
                    "rounds": 2,
                    "exports": 2,
                    "report_sha256": hashlib.sha256(encoded).hexdigest(),
                }
            )
        )
        return 0
    except Exception:
        if destination is not None and destination.parent.is_dir():
            try:
                with destination.with_name(destination.stem + "-failure.json").open(
                    "x", encoding="utf-8"
                ) as stream:
                    json.dump({"status": "refused", "traceback": traceback.format_exc()}, stream)
            except Exception:
                pass
        print('{"status":"refused"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
