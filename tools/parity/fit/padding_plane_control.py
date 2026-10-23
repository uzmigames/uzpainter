"""CPU scoring of the pre-capture endpoint-plane commitments (decision 358).

Run with --manifest and --predictions. Private maps remain in memory; stdout
contains only identifiers, hashes and counts. No hypothesis is regenerated.
The freeze contains final mixtures, not ordered tap lists: discovery-channel
and support-class differences are reported, but tap order is not certified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.common import channel_format
from tools.parity.fit.decode import Decoded, decode
from tools.parity.fit.oracle import Golden, OracleUnavailable, load
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.job import canonical_json
from tools.parity.schemas import REPO_ROOT, load_json, record_problems
from tools.parity.store.store import load_oracle, locate

GOLDEN = "tier0/semantics/export-padding-plane-control"
MATERIAL = "uzp_padding_plane_control"
PREDICTIONS_SHA256 = "5b98e22a8d9c288a7b14e8dbe08c3216b7fb90b18fed2950d022bb5a5339224e"
REFERENCE_SHA256 = "c36795882a04c6ee6ff956f4280e4e58a5e605451039dc4f3b0df732e82e546a"
PROTOCOL_SHA256 = "527241df061429c71ca960740cecfd8bbac35042c40880c80d7274c37a8cde04"
EXPORT_STEPS = {45: "infinite", 46: "infinite", 47: "passthrough", 48: "passthrough"}
INPUTS = {
    "padding-plane-control": "3e406f3fae528e122b62e93ecb1db63214455d0dc9951d73a1b74d890201b7bb",
    "kernel-onehot-a-n512": "1ba87cecae8ccd225fbb81399bd9793a1402fdb364f791bd23a94ecf3db77ffb",
    "kernel-onehot-b-n512": "25e13933fbb7db49cf753003d2d6102e175fba74de9f7408961a4db07b999bd8",
    "kernel-onehot-c-n512": "54ff12bf20effb2a342f3b7b042f56852e6c33445be4128af1006bc7dbba0d1f",
    "uv-ramp-512": "44d56e0f653a199d8fa2c23451891b4ee4bcf8d4a64d3369186f77f87fda78f5",
    "kernel-code-d-n512": "2179f688faa4c54d30b4ff80c1e2051501a66e634608aca759b3fc2dcc8a7d05",
    "kernel-code-e-n512": "0495ca8fd1375a62e09de392b5031cf5787391f635fc03d57f4170b33d74d89b",
    "kernel-code-f-n512": "161e2e7dbfbcb673333d0652f0fbe1c10256e41790d988d18a46d4c14b5d892a",
    "kernel-code-g-n512": "71f3940346d39eeec29fcba3cd25beb771661541d765dc494130b610e0721aa3",
}
Bits = npt.NDArray[np.uint32]
Mask = npt.NDArray[np.bool_]


def checked_bytes(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("frozen artifact hash mismatch")
    return data


def bits_of(image: Decoded) -> Bits:
    if image.integer or image.bits != 32 or image.values.shape != (512, 512, 3):
        raise ValueError("control requires 512x512 RGB float32 maps")
    if not np.isfinite(image.values).all():
        raise ValueError("control contains nonfinite samples")
    return np.ascontiguousarray(image.values, dtype=np.float32).view(np.uint32)


def frozen_inputs(golden: Golden, repository: Path) -> tuple[Bits, Mask]:
    inputs = {row["input_id"]: row for row in golden.manifest["inputs"]}
    if (
        len(golden.manifest["inputs"]) != len(INPUTS)
        or {key: row["sha256"] for key, row in inputs.items()} != INPUTS
    ):
        raise ValueError("control authored inputs differ from commitments")
    paths = {key: repository / row["path"] for key, row in inputs.items()}
    data = {key: checked_bytes(paths[key], digest) for key, digest in INPUTS.items()}
    source = np.concatenate([bits_of(decode(data[key])) for key in list(INPUTS)[1:]], axis=2)
    reference = repository / "tests/export/padding_reference.py"
    checked_bytes(reference, REFERENCE_SHA256)
    spec = importlib.util.spec_from_file_location("padding_plane_frozen_coverage", reference)
    if spec is None or spec.loader is None:
        raise ValueError("frozen coverage reference unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    triangles, _, _ = module.obj_mesh(paths["padding-plane-control"], MATERIAL)
    covered = np.zeros((512, 512), dtype=np.bool_)
    for _, uv in triangles:
        for x, y in module.covered_texels(uv, 512, 512):
            covered[y, x] = True
    if not covered.any():
        raise ValueError("empty authored coverage")
    return source, covered


def validate_protocol(manifest: dict[str, Any]) -> None:
    protocol = {key: manifest[key] for key in ("instruction_sequence", "applied_settings")}
    if hashlib.sha256(canonical_json(protocol)).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("control protocol differs from frozen request")


def validate_record(record: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Check raw lists before the generic loader indexes and collapses their IDs."""
    recordings = record["recordings"]
    if len(recordings) != len({r["recording_id"] for r in recordings}) or any(
        len(r["outputs"]) != len({o["output_id"] for o in r["outputs"]}) for r in recordings
    ):
        raise ValueError("duplicate recording or output ids")
    if record_problems(record):
        raise ValueError("private record schema or cross-field rules failed")
    validate_protocol(manifest)
    envelope, key = current_envelope(), record["key"]
    if (
        record["golden_id"] != GOLDEN
        or record["tier"] != "0"
        or key["painter_build"]["build_id"] != envelope["painter_build"]
        or envelope_sha256(record.get("environment", {})) != envelope["envelope_sha256"]
        or key["instruction_sequence_sha256"]
        != hashlib.sha256(canonical_json(manifest["instruction_sequence"])).hexdigest()
        or key["inputs"]
        != [{"input_id": row["input_id"], "sha256": row["sha256"]} for row in manifest["inputs"]]
    ):
        raise ValueError("private record identity or envelope mismatch")


def captured_samples(golden: Golden) -> dict[str, dict[str, list[Bits]]]:
    validate_protocol(golden.manifest)
    if golden.golden_id != GOLDEN or set(golden.recordings) != {"r1", "r2"}:
        raise ValueError("control requires its original and save/reopen recordings")
    samples: dict[str, dict[str, list[Bits]]] = {}
    for recording, condition in (("r1", "same_session"), ("r2", "after_save_reopen")):
        if golden.recordings[recording].condition != condition:
            raise ValueError("control recording condition mismatch")
        template = golden.output(recording, "template/texture-sets")
        sets = template["values"]["texture_sets"]
        if template["kind"] != "template_capture" or set(sets) != {MATERIAL}:
            raise ValueError("control effective texture sets mismatch")
        texture_set = sets[MATERIAL]
        if texture_set["resolution"] != [512, 512] or set(texture_set["stacks"]) != {""}:
            raise ValueError("control effective resolution or stack mismatch")
        channels = {name.lower(): value for name, value in texture_set["stacks"][""].items()}
        if any(
            channels[f"user{i}"]["bit_depth"] != 32
            or channels[f"user{i}"]["is_floating"] is not True
            for i in range(8)
        ):
            raise ValueError("control effective channel precision mismatch")
        if any(
            channel_format(golden, MATERIAL, f"user{i}", recording) != "RGB32F" for i in range(8)
        ):
            raise ValueError("control template channels must be RGB32F")
        steps: dict[int, dict[int, Bits]] = {}
        modes: dict[int, str] = {}
        for output_id in golden.maps(recording):
            output = golden.output(recording, output_id)
            settings, storage = output["export_settings"], output["storage_format"]
            if output["texture_set"] != MATERIAL or output["map"] not in [
                f"user{i}" for i in range(8)
            ]:
                raise ValueError("unexpected control map")
            if storage != {
                "container": "exr",
                "sample_type": "float",
                "bits_per_channel": 32,
                "channels": 3,
                "encoding": "linear",
            }:
                raise ValueError("control storage domain mismatch")
            if settings.get("map_type") != "documentMap" or settings.get("map_channels") != "RGB":
                raise ValueError("control map binding mismatch")
            mode, step = settings.get("paddingAlgorithm"), settings.get("step")
            if type(step) is not int or EXPORT_STEPS.get(step) != mode:
                raise ValueError("control export step mismatch")
            if settings != {
                "paddingAlgorithm": mode,
                "step": step,
                "map_type": "documentMap",
                "map_channels": "RGB",
                "encoding_basis": "source_channel_format",
                "fileFormat": "exr",
                "bitDepth": "32f",
                "dithering": False,
            }:
                raise ValueError("control export configuration mismatch")
            index = int(output["map"][4:])
            if index in steps.setdefault(step, {}) or modes.setdefault(step, mode) != mode:
                raise ValueError("duplicate or mixed control export step")
            steps[step][index] = bits_of(golden.map(recording, output_id))
        if len(steps) != 4 or any(set(values) != set(range(8)) for values in steps.values()):
            raise ValueError("control requires four complete eight-map exports")
        samples[recording] = {
            mode: [
                np.concatenate([steps[s][i] for i in range(8)], axis=2)
                for s in sorted(steps)
                if modes[s] == mode
            ]
            for mode in ("infinite", "passthrough")
        }
        if any(len(values) != 2 for values in samples[recording].values()):
            raise ValueError("control requires two exports of each padding mode")
    return samples


def differing_texels(a: Bits, b: Bits) -> int:
    return int(np.count_nonzero(np.any(a != b, axis=-1)))


def score(
    samples: dict[str, dict[str, list[Bits]]],
    source: Bits,
    covered: Mask,
    predictions: dict[str, Any],
) -> dict[str, Any]:
    """Count every committed ring texel; no samples or coordinates escape this function."""
    stability: dict[str, int] = {}
    coverage_errors = 0
    for recording in ("r1", "r2"):
        for mode in ("infinite", "passthrough"):
            a, b = samples[recording][mode]
            coverage_errors += differing_texels(a[covered], source[covered])
            coverage_errors += differing_texels(b[covered], source[covered])
            stability[f"{recording}_{mode}_repeat"] = differing_texels(a, b)
            if mode == "passthrough":
                stability[f"{recording}_uncovered_passthrough_repeat"] = differing_texels(
                    a[~covered], b[~covered]
                )
    for mode in ("infinite", "passthrough"):
        for repeat in range(2):
            a, b = samples["r1"][mode][repeat], samples["r2"][mode][repeat]
            stability[f"{mode}_reopen_{repeat}"] = differing_texels(a, b)
            if mode == "passthrough":
                stability[f"uncovered_passthrough_reopen_{repeat}"] = differing_texels(
                    a[~covered], b[~covered]
                )
    policies: dict[str, Any] = {}
    for policy, rows in predictions.items():
        counts: dict[str, Any] = {}
        for recording in ("r1", "r2"):
            for repeat, image in enumerate(samples[recording]["infinite"]):
                groups: dict[str, dict[str, int]] = {}
                for key, row in rows.items():
                    x, y = map(int, key.split(","))
                    if covered[y, x]:
                        raise ValueError("frozen ring overlaps authored coverage")
                    expected = np.asarray(row["bits"], dtype=np.uint32)
                    actual = image[y, x]
                    parts = row["region"].split("-")
                    group = "-".join(parts[1:3])
                    for name in ("all", group, f"frozen_taps_{row['taps']}"):
                        result = groups.setdefault(
                            name,
                            dict(
                                texels=0,
                                differing=0,
                                discovery_differing=0,
                                verification_differing=0,
                                support_class_differing=0,
                            ),
                        )
                        result["texels"] += 1
                        result["differing"] += int(np.any(actual != expected))
                        result["discovery_differing"] += int(np.any(actual[:12] != expected[:12]))
                        result["verification_differing"] += int(
                            np.any(actual[12:] != expected[12:])
                        )
                        result["support_class_differing"] += int(
                            np.any(
                                (actual[:9].view(np.float32) > 0)
                                != (expected[:9].view(np.float32) > 0)
                            )
                        )
                counts[f"{recording}_{repeat}"] = groups
        policies[policy] = counts
    return {
        "covered_texels": int(covered.sum()),
        "coverage_mismatches": coverage_errors,
        "stability": stability,
        "policies": policies,
        "ordered_tap_lists_absent": len(predictions["baseline"]),
        "domain_pass": int(
            coverage_errors == 0
            and all(value == 0 for name, value in stability.items() if "infinite" in name)
        ),
    }


def validate(
    golden: Golden, predictions_path: Path, repository: Path = REPO_ROOT
) -> dict[str, Any]:
    predictions = json.loads(checked_bytes(predictions_path, PREDICTIONS_SHA256))
    if set(predictions) != {"baseline", "generic", "conservative"} or any(
        len(rows) != 1280 for rows in predictions.values()
    ):
        raise ValueError("frozen prediction population mismatch")
    source, covered = frozen_inputs(golden, repository)
    report = score(captured_samples(golden), source, covered, predictions)
    report["record_sha256"] = golden.record_sha256
    report["predictions_sha256"] = PREDICTIONS_SHA256
    report["protocol_sha256"] = PROTOCOL_SHA256
    report["input_sha256"] = list(INPUTS.values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, store = load_json(args.manifest), locate()
        refs = [row for row in manifest["private_records"] if row["record_id"] == "golden-record"]
        if not refs:
            raise OracleUnavailable("record unavailable")
        if len(refs) != 1:
            raise ValueError("duplicate private record reference")
        raw = load_oracle(store, refs[0])
        if raw is None:
            raise OracleUnavailable("record unavailable")
        validate_record(json.loads(raw), manifest)
        report = validate(load(store, args.manifest), args.predictions)
    except (OracleUnavailable, FileNotFoundError):
        print(json.dumps({"status": "oracle_unavailable", "golden_id": GOLDEN}))
        return 2
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "invalid_control", "golden_id": GOLDEN}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["domain_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
