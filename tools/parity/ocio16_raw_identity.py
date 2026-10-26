"""Measure fixed-coordinate Raw calibration equality; no transform or general identity claim.

The comparison is frozen before reading oracle pixels: EXR [y,x,R/G/B], no flips,
permutations, color conversion, fitting or tolerance. A valid difference is a result.
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
from tools.parity import ocio16_raw_readout_admission as receipt
from tools.parity.fit.decode import Array
from tools.parity.preserve_diagnostic_evidence import file_fingerprint
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control

STATE = "calibration-float"
INPUT_SHA256 = "8905ee16ed73963d9c0c6a6f4e98bba3632bc4546dbe890ebb036740d43b434d"


def checked_pixels(path: Path, data: bytes) -> Array:
    """Native decode plus an explicit common coordinate domain, bound to the same bytes."""
    import OpenEXR

    pixels = admission.decode_native(path, data)
    with OpenEXR.File(str(path), separate_channels=True, header_only=True) as image:
        header = image.header()
        for name in ("dataWindow", "displayWindow"):
            receipt.require(
                np.array_equal(np.asarray(header[name]), [[0, 0], [255, 255]]),
                "EXR coordinate window differs",
            )
    receipt.equal(
        list(file_fingerprint(path)),
        [hashlib.sha256(data).hexdigest(), len(data)],
        "EXR coordinate receipt changed",
    )
    return pixels


def inspect_identity(manifest: dict[str, Any], store: OracleStore) -> dict[str, Any]:
    """Revalidate admission each time; equal/different describe only this finite experiment."""
    validation = admission.inspect_export(manifest, STATE, store)
    authored = control.request(STATE, exports=True)
    source = next(row for row in authored["inputs"] if row["input_id"] == STATE)
    receipt.equal(source["sha256"], INPUT_SHA256, "authored input pin differs")
    path = REPO_ROOT / source["path"]
    data = path.read_bytes()
    receipt.equal(hashlib.sha256(data).hexdigest(), INPUT_SHA256, "input bytes differ")
    expected = checked_pixels(path, data)
    formula = control.authored_values(STATE)
    receipt.require(
        np.array_equal(expected.view(np.uint32), formula.view(np.uint32)),
        "authored formula differs",
    )
    rounds = []
    for index, sha in enumerate(validation["map_sha256"], 1):
        refs = [
            r
            for r in manifest["private_records"]
            if r["kind"] == "exported_map" and r["sha256"] == sha
        ]
        receipt.require(bool(refs), "export reference missing")
        raw = load_oracle(store, refs[0])
        receipt.require(raw is not None, "export bytes unavailable")
        assert raw is not None
        actual = checked_pixels(store.blob_path(sha), raw)
        difference = actual.view(np.uint32) != expected.view(np.uint32)
        rounds.append(
            {
                "round": index,
                "map_sha256": sha,
                "samples": int(difference.size),
                "different_samples": int(np.count_nonzero(difference)),
                "different_samples_rgb": [
                    int(np.count_nonzero(difference[..., c])) for c in range(3)
                ],
            }
        )
    return {
        "schema": "uzpainter/raw-identity-measurement/1",
        "status": "measured",
        "comparison": "different" if any(r["different_samples"] for r in rounds) else "equal",
        "state": STATE,
        "input_sha256": INPUT_SHA256,
        "input_size_bytes": len(data),
        "request_canonical_sha256": validation["request_canonical_sha256"],
        "admission": validation,
        "decoder": {
            "name": "OpenEXR",
            "version": version("OpenEXR"),
            "numpy_version": np.__version__,
        },
        "coordinates": "EXR [y,x,RGB]; windows (0,0)-(255,255); no transformations",
        "comparison_basis": "uint32 bits of native FLOAT32",
        "rounds": rounds,
        "domain": "authored calibration samples in this recorded context only",
        "negative_zero_input_coverage": False,
        "color_channel_flag": "unobserved",
        "general_readout_identity": "not_established",
        "difference_cause": "not_inferred",
        "parity": "not_established",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
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
        report = inspect_identity(json.loads(args.manifest.read_bytes()), store)
        encoded = canonical_json(report) + b"\n"
        stage = "publication"
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {
                    "status": report["status"],
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
