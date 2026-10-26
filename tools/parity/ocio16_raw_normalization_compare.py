"""Compare observable Raw PNG16/FLOAT transfers at fixed EXR coordinates.

Equal outputs do not identify an internal normalization, decoder or identity readout.
No tolerance, channel permutation, orientation search or color transform is applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import traceback
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity import ocio16_raw_export_admission as admission
from tools.parity import ocio16_raw_readout_admission as receipt
from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import current_envelope, registry_path
from tools.parity.feasibility import png
from tools.parity.ocio16_raw_identity import checked_pixels
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.environment import ENVELOPE_FIELDS, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository
from tools.parity.recorder.probes import is_read
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control

STATES = ("normalization-float", "normalization-png16")
INPUT_PINS = {
    "normalization-float": "79972acbd621f5c70ebac1dd87e0b881d2bc732683f0e9fab9d678c4a289ab3b",
    "normalization-png16": "60a6ea30c4c97b455f0fc74ec0157529afeb844292e707abcc925c34e9f320d1",
}


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def verified_bytes(store: OracleStore, ref: dict[str, Any]) -> bytes:
    raw = load_oracle(store, ref)
    receipt.require(raw is not None, "comparison evidence unavailable")
    assert raw is not None
    receipt.equal(
        [hashlib.sha256(raw).hexdigest(), len(raw)],
        [ref["sha256"], ref["size_bytes"]],
        "comparison evidence receipt differs",
    )
    return raw


def authored_input(authored: dict[str, Any], state: str) -> dict[str, Any]:
    source = next(row for row in authored["inputs"] if row["input_id"] == state)
    receipt.equal(source["sha256"], INPUT_PINS[state], "authored input pin differs")
    path = REPO_ROOT / source["path"]
    data = path.read_bytes()
    receipt.equal(
        hashlib.sha256(data).hexdigest(), INPUT_PINS[state], "authored input bytes differ"
    )
    expected = control.authored_values(state)
    if state == "normalization-float":
        values = checked_pixels(path, data)
        receipt.require(
            np.array_equal(values.view(np.uint32), expected.view(np.uint32)),
            "FLOAT authored formula differs",
        )
    else:
        # The closed SHA pin binds every byte, including CRCs and the compressed stream.
        chunks = png.chunks(data)
        receipt.equal(
            [kind.decode("ascii") for kind, _ in chunks],
            ["IHDR", "IDAT", "IEND"],
            "PNG chunk domain",
        )
        receipt.equal(
            list(struct.unpack(">IIBBBBB", chunks[0][1])),
            [256, 256, 16, 2, 0, 0, 0],
            "PNG native format",
        )
        values = png.decode(data)
        receipt.require(
            values.dtype == np.uint16
            and values.shape == (256, 256, 3)
            and np.array_equal(values, expected),
            "PNG authored formula differs",
        )
    return {"sha256": INPUT_PINS[state], "size_bytes": len(data), "formula_verified": True}


def common_recipe(authored: dict[str, Any], state: str) -> dict[str, Any]:
    sequence = json.loads(canonical_json(authored["instruction_sequence"]))
    imports = [step for step in sequence["steps"] if step["call"] == ps.IMPORT_RESOURCE]
    receipt.require(len(imports) == 1, "single authored input import")
    receipt.equal(imports[0]["args"]["input"], state, "imported authored input")
    imports[0]["args"]["input"] = "paired-authored-input"
    return {
        "instruction_sequence": sequence,
        "inputs": [row for row in authored["inputs"] if row["input_id"] != state],
        **{
            key: authored[key]
            for key in (
                "schema",
                "record_class",
                "tier",
                "domain",
                "applied_settings",
                "expectations",
                "software",
            )
        },
    }


def observed_context(record: dict[str, Any]) -> dict[str, Any]:
    contexts = []
    calls = set(control.fixed_readbacks()) | {control.BITMAP + "list_available_color_spaces"}
    for recording in record["recordings"]:
        readbacks = {}
        for call in sorted(calls):
            found = [
                output
                for output in recording["outputs"]
                if output.get("call") == call and is_read(call, output["args"])
            ]
            receipt.require(len(found) == 1, "common context readback inventory")
            readbacks[call] = {key: found[0][key] for key in ("kind", "args", "value")}
        exports = [output for output in recording["outputs"] if output["kind"] == "exported_map"]
        receipt.require(len(exports) == 1, "common context export inventory")
        contexts.append(
            {
                "condition": recording["condition"],
                "readbacks": readbacks,
                "template": receipt.output(recording, "template/texture-sets")["values"],
                "export_settings": exports[0]["export_settings"],
            }
        )
    return {
        "key": {
            key: value
            for key, value in record["key"].items()
            if key not in ("inputs", "instruction_sequence_sha256")
        },
        "rounds": contexts,
    }


def compare(
    float_manifest: dict[str, Any], png_manifest: dict[str, Any], store: OracleStore
) -> dict[str, Any]:
    manifests = json.loads(canonical_json([float_manifest, png_manifest]))
    registry = registry_path().read_bytes()
    envelope = current_envelope()
    common = None
    experiments = []
    pixels = []
    for state, manifest in zip(STATES, manifests, strict=True):
        validation = admission.inspect_export(manifest, state, store)
        authored = control.request(state, exports=True)
        inputs = authored_input(authored, state)
        refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
        record = json.loads(verified_bytes(store, refs[GOLDEN_RECORD_ID]))
        environment = json.loads(verified_bytes(store, refs[ENVIRONMENT_RECORD_ID]))
        receipt.require(
            recorded_request_environment_matches(environment, authored, envelope, store),
            "comparison envelope is not current",
        )
        context = {
            "environment": {field: environment[field] for field in ENVELOPE_FIELDS},
            "recipe": common_recipe(authored, state),
            "observed": observed_context(record),
        }
        if common is None:
            common = context
        receipt.equal(context, common, "paired capture contexts differ")
        rounds = []
        for sha in validation["map_sha256"]:
            ref = next(
                ref
                for ref in refs.values()
                if ref["kind"] == "exported_map" and ref["sha256"] == sha
            )
            rounds.append(checked_pixels(store.blob_path(sha), verified_bytes(store, ref)))
        pixels.append(rounds)
        experiments.append(
            {
                "state": state,
                "manifest_canonical_sha256": digest(manifest),
                "input": inputs,
                "admission": validation,
                # Recorder version is provenance, never part of the envelope match.
                "recorder_version": environment["recorder_version"],
            }
        )
    comparisons = []
    for index, (left, right) in enumerate(zip(pixels[0], pixels[1], strict=True), 1):
        difference = left.view(np.uint32) != right.view(np.uint32)
        comparisons.append(
            {
                "round": index,
                "samples": int(difference.size),
                "different_samples": int(np.count_nonzero(difference)),
                "different_samples_rgb": [
                    int(np.count_nonzero(difference[..., channel])) for channel in range(3)
                ],
            }
        )
    receipt.equal(current_envelope(), envelope, "comparison registry entry changed")
    receipt.require(registry_path().read_bytes() == registry, "comparison registry changed")
    return {
        "schema": "uzpainter/raw-normalization-comparison/1",
        "status": "measured",
        "comparison": "different"
        if any(row["different_samples"] for row in comparisons)
        else "equal",
        "experiments": experiments,
        "rounds": comparisons,
        "common_context": common,
        "common_context_sha256": digest(common),
        "registry_sha256": hashlib.sha256(registry).hexdigest(),
        "registry_entry_sha256": digest(envelope),
        "decoder": {
            "name": "OpenEXR",
            "version": version("OpenEXR"),
            "numpy_version": np.__version__,
        },
        "comparison_basis": "uint32 EXR [y,x,RGB]; windows (0,0)-(255,255); no transformations",
        "scope": "paired observable transfer in this recorded context only",
        "internal_normalization": "not_established",
        "readout_identity": "not_established",
        "color_channel_flag": "unobserved",
        "difference_cause": "not_inferred",
        "parity": "not_established",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--float-manifest", type=Path, required=True)
    parser.add_argument("--png-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = None
    stage = "destination"
    try:
        destination = ensure_outside_repository(args.output)
        receipt.require(
            destination.parent.is_dir() and not destination.exists(), "private output destination"
        )
        stage = "store"
        store = locate()
        receipt.require(store is not None, "store unavailable")
        assert store is not None
        stage = "comparison"
        report = compare(
            json.loads(args.float_manifest.read_bytes()),
            json.loads(args.png_manifest.read_bytes()),
            store,
        )
        encoded = canonical_json(report) + b"\n"
        stage = "publication"
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {
                    "status": "measured",
                    "comparison": report["comparison"],
                    "report_sha256": hashlib.sha256(encoded).hexdigest(),
                }
            )
        )
        return 0
    except Exception:
        summary = {"status": "refused"}
        failure = (
            canonical_json(
                {"status": "refused", "stage": stage, "traceback": traceback.format_exc()}
            )
            + b"\n"
        )
        if destination is not None and destination.parent.is_dir():
            try:
                with destination.with_name(destination.stem + "-failure.json").open("xb") as stream:
                    stream.write(failure)
                summary["report_sha256"] = hashlib.sha256(failure).hexdigest()
            except Exception:
                pass
        print(json.dumps(summary))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
