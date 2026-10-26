"""Frozen Raw transfer diagnostics; no corrective mapping, fit or identity promotion.

Direct coordinate comparisons are primary. The separate same-code comparisons use only
indices derived from the public input formula; channel and position remain confounded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity import ocio16_raw_export_admission as admission
from tools.parity import ocio16_raw_identity as identity
from tools.parity import ocio16_raw_normalization_compare as paired
from tools.parity import ocio16_raw_readout_admission as receipt
from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import current_envelope, registry_path
from tools.parity.fit.decode import Array
from tools.parity.recorder.environment import ENVELOPE_FIELDS, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control

STATES = ("calibration-float", "normalization-float")
INPUT_PINS = {
    STATES[0]: identity.INPUT_SHA256,
    STATES[1]: paired.INPUT_PINS[STATES[1]],
}


def input_pixels(authored: dict[str, Any], state: str) -> tuple[Array, dict[str, Any]]:
    source = next(row for row in authored["inputs"] if row["input_id"] == state)
    receipt.equal(source["sha256"], INPUT_PINS[state], "authored input pin differs")
    path = REPO_ROOT / source["path"]
    raw = path.read_bytes()
    receipt.equal(hashlib.sha256(raw).hexdigest(), INPUT_PINS[state], "input bytes differ")
    pixels = identity.checked_pixels(path, raw)
    receipt.require(
        np.array_equal(pixels.view(np.uint32), control.authored_values(state).view(np.uint32)),
        "authored formula differs",
    )
    return pixels, {"sha256": INPUT_PINS[state], "size_bytes": len(raw), "formula_verified": True}


def counts(left: Array, right: Array) -> dict[str, int]:
    receipt.require(
        left.dtype == right.dtype == np.float32 and left.shape == right.shape,
        "comparison sample domain",
    )
    return {
        "samples": int(left.size),
        "different_samples": int(np.count_nonzero(left.view(np.uint32) != right.view(np.uint32))),
    }


def direct_metrics(expected: Array, actual: Array) -> dict[str, Any]:
    difference = expected.view(np.uint32) != actual.view(np.uint32)
    bits = expected.view(np.uint32)
    magnitude = bits & np.uint32(0x7FFFFFFF)
    exponent = magnitude & np.uint32(0x7F800000)
    classes = {
        "zero": magnitude == 0,
        "subnormal": (exponent == 0) & (magnitude != 0),
        "endpoint_one": bits == np.uint32(0x3F800000),
        "normal_except_one": (exponent != 0) & (bits != np.uint32(0x3F800000)),
    }
    return {
        **counts(expected, actual),
        "different_samples_rgb": np.count_nonzero(difference, axis=(0, 1)).tolist(),
        "different_samples_by_row_rgb": np.count_nonzero(difference, axis=1).tolist(),
        "different_samples_by_column_rgb": np.count_nonzero(difference, axis=0).tolist(),
        "authored_classes": {
            name: {
                "samples_rgb": np.count_nonzero(mask, axis=(0, 1)).tolist(),
                "different_samples_rgb": np.count_nonzero(mask & difference, axis=(0, 1)).tolist(),
            }
            for name, mask in classes.items()
        },
    }


def same_code_metrics(expected: Array, actual: Array) -> dict[str, Any]:
    # Fixed public formula offsets, never chosen from an output or used to repair identity.
    n = np.arange(65536, dtype=np.int64)
    offsets = (0, 21845, 43690)
    inputs = expected.reshape(65536, 3)
    outputs = actual.reshape(65536, 3)
    aligned = [outputs[(n - offset) % 65536, channel] for channel, offset in enumerate(offsets)]
    for channel, offset in enumerate(offsets):
        receipt.require(
            np.array_equal(
                inputs[(n - offset) % 65536, channel].view(np.uint32), inputs[:, 0].view(np.uint32)
            ),
            "authored same-code relation differs",
        )
    return {
        "indices": ["R[n]", "G[(n-21845)%65536]", "B[(n-43690)%65536]"],
        "against_authored_center_rgb": [counts(inputs[:, 0], values) for values in aligned],
        "pairs": {
            name: counts(aligned[a], aligned[b])
            for name, a, b in (("RG", 0, 1), ("RB", 0, 2), ("GB", 1, 2))
        },
        "limitation": (
            "same authored value at different channel/position combinations; not channel invariance"
        ),
    }


def inspect_transfer(
    calibration_manifest: dict[str, Any], normalization_manifest: dict[str, Any], store: OracleStore
) -> dict[str, Any]:
    manifests = json.loads(canonical_json([calibration_manifest, normalization_manifest]))
    registry = registry_path().read_bytes()
    envelope = current_envelope()
    common = None
    experiments = []
    all_pixels = []
    all_inputs = []
    for state, manifest in zip(STATES, manifests, strict=True):
        validation = admission.inspect_export(manifest, state, store)
        authored = control.request(state, exports=True)
        expected, source = input_pixels(authored, state)
        refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
        record = json.loads(paired.verified_bytes(store, refs[GOLDEN_RECORD_ID]))
        environment = json.loads(paired.verified_bytes(store, refs[ENVIRONMENT_RECORD_ID]))
        receipt.require(
            recorded_request_environment_matches(environment, authored, envelope, store),
            "diagnostic envelope is not current",
        )
        context = {
            "environment": {field: environment[field] for field in ENVELOPE_FIELDS},
            "recipe": paired.common_recipe(authored, state),
            "observed": paired.observed_context(record),
        }
        if common is None:
            common = context
        receipt.equal(context, common, "diagnostic capture contexts differ")
        pixels = []
        rounds = []
        for round_index, sha in enumerate(validation["map_sha256"], 1):
            ref = next(
                ref
                for ref in refs.values()
                if ref["kind"] == "exported_map" and ref["sha256"] == sha
            )
            actual = identity.checked_pixels(
                store.blob_path(sha), paired.verified_bytes(store, ref)
            )
            pixels.append(actual)
            rounds.append(
                {
                    "round": round_index,
                    "map_sha256": sha,
                    "direct_identity": direct_metrics(expected, actual),
                }
            )
        all_pixels.append(pixels)
        all_inputs.append(expected)
        experiments.append(
            {
                "state": state,
                "input": source,
                "manifest_canonical_sha256": paired.digest(manifest),
                "admission": validation,
                "recorder_version": environment["recorder_version"],
                "rounds": rounds,
            }
        )
    receipt.require(
        np.array_equal(
            all_inputs[0][..., 0].view(np.uint32), all_inputs[1][..., 0].view(np.uint32)
        ),
        "shared authored R differs",
    )
    shared_r = []
    same_code = []
    for index, (calibration, normalization) in enumerate(
        zip(all_pixels[0], all_pixels[1], strict=True), 1
    ):
        shared_r.append({"round": index, **counts(calibration[..., 0], normalization[..., 0])})
        same_code.append({"round": index, **same_code_metrics(all_inputs[1], normalization)})
    receipt.equal(current_envelope(), envelope, "diagnostic registry entry changed")
    receipt.require(registry_path().read_bytes() == registry, "diagnostic registry changed")
    return {
        "schema": "uzpainter/raw-transfer-diagnostics/1",
        "status": "measured",
        "experiments": experiments,
        "shared_r_same_coordinate": shared_r,
        "normalization_same_code_different_channel_position": same_code,
        "common_context": common,
        "common_context_sha256": paired.digest(common),
        "registry_sha256": hashlib.sha256(registry).hexdigest(),
        "registry_entry_sha256": paired.digest(envelope),
        "decoder": {
            "name": "OpenEXR",
            "version": version("OpenEXR"),
            "numpy_version": np.__version__,
        },
        "comparison_basis": "native FLOAT32 uint32 bits; direct EXR [y,x,RGB]; no correction",
        "shared_r_limitation": (
            "other RGB inputs differ; dependence or an unisolated condition, "
            "not a causal attribution"
        ),
        "general_readout_identity": "not_established",
        "channel_invariance": "not_established",
        "internal_normalization": "not_established",
        "color_channel_flag": "unobserved",
        "difference_cause": "not_inferred",
        "parity": "not_established",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--normalization-manifest", type=Path, required=True)
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
        stage = "measurement"
        report = inspect_transfer(
            json.loads(args.calibration_manifest.read_bytes()),
            json.loads(args.normalization_manifest.read_bytes()),
            store,
        )
        encoded = canonical_json(report) + b"\n"
        stage = "publication"
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps({"status": "measured", "report_sha256": hashlib.sha256(encoded).hexdigest()})
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
