"""Read-only measurements of preserved rejected RGB16 candidates; never fits or runs a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import traceback
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tools.parity import ocio16_bitmap_replay as baseline
from tools.parity.fit.decode import Array, decode
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.vocabulary import SET_SOURCE
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import recording_requests as rr


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verified_file(root: Path, name: str, digest: str) -> bytes:
    path = Path(name)
    path = path if path.is_absolute() else root / path
    require(path.resolve().parent == root.resolve(), "preserved file outside evidence folder")
    data = path.read_bytes()
    require(sha(data) == digest, "preserved file hash differs")
    return data


def indexed_texts(entries: list[dict[str, Any]]) -> dict[Path, str]:
    texts = {}
    for item in entries:
        data = item["text"].encode("utf-8")
        require(sha(data) == item["sha256"] and len(data) == item["size"], "preserved text differs")
        origin = Path(item["origin"])
        require(origin not in texts, "duplicate text identity")
        texts[origin] = item["text"]
    return texts


def preserved(evidence: dict[str, Any], root: Path) -> list[tuple[baseline.Candidate, bytes]]:
    historical = json.loads(
        verified_file(root, evidence["report"]["file"], evidence["report"]["sha256"])
    )
    require(
        evidence["model"] == historical["model"] == control.RGB16_CANDIDATE_MODEL,
        "rejected model differs",
    )
    require(
        historical["comparisons"] == historical["pixels_different"] == 18
        and historical["candidates"] == 9
        and historical["status"] == "different",
        "historical rejection differs",
    )
    require(
        evidence["executable_sha256"] == historical["executable_sha256"], "binary identity differs"
    )
    texts = indexed_texts(evidence["texts"])
    result = []
    seen = set()
    for image in evidence["images"]:
        source, step = image["source"], image["step"]
        require(source in control.RGB16_CANDIDATES and type(step) is int, "candidate identity")
        require((source, step) not in seen, "duplicate candidate")
        seen.add((source, step))
        origin = Path(image["origin"])
        work = origin.parent.parent
        run = work / f"run-{step}"
        config = json.loads(texts[run / "config.json"])
        spec = json.loads(texts[work / "spec" / "spec.json"])
        native = json.loads(texts[run / "native.stdout.txt"])
        authored = json.loads(
            (
                rr.request_root(REPO_ROOT)
                / "tier0/api-probes"
                / f"{control.request_name(source)}.json"
            ).read_bytes()
        )
        plan = control.native_rgb16_candidate(
            authored, source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
        )
        steps = {item["step"]: item for item in plan.manifest["instruction_sequence"]["steps"]}
        sources = [
            item["args"]
            for item in steps.values()
            if item["call"] == SET_SOURCE and "resource_step" in item["args"]
        ]
        require(len(sources) == 1, "authored bitmap source count")
        imported = steps[sources[0]["resource_step"]]["args"]
        input_id = imported.get("input", imported.get("image"))
        bitmap_hash = sha(plan.inputs[input_id].read_bytes())
        require(
            len(spec["resources"]) == len(spec["layers"]) == 1
            and spec["resources"][0]["sha256"] == bitmap_hash
            and spec["layers"][0]["sources"]["BaseColor"]
            == {"bitmap": bitmap_hash, "color_space": "OcioColorSpace.sRGB"}
            and bitmap_hash in {item["sha256"] for item in evidence["public_inputs_by_hash"]},
            "preserved bitmap does not match authored source",
        )
        exports = [export for export in plan.exports if export.step == step]
        require(len(exports) == 1, "unrecognized export step")
        require(
            canonical_json(config)
            == canonical_json(exports[0].config(Path(config["exportPath"]), ["uzp_plane"])),
            "preserved export config differs",
        )
        require(
            native["model"] == evidence["model"] and native["non_conformant"] is True,
            "native model identity differs",
        )
        require(
            len(native["written"]) == 1
            and native["written"][0]["sha256"] == image["sha256"]
            and native["written"][0]["relativePath"] == origin.name,
            "native output receipt differs",
        )
        result.append(
            (
                baseline.Candidate(
                    source,
                    authored,
                    spec,
                    work / "spec",
                    config,
                    run,
                    root / Path(image["file"]).name,
                    f"uzp_plane/basecolor/step{step}",
                    step,
                ),
                verified_file(root, image["file"], image["sha256"]),
            )
        )
    require(len(result) == 9, "candidate matrix incomplete")
    return result


def quantiles(values: Array) -> list[float] | None:
    if not values.size:
        return None
    return [float(x) for x in np.percentile(values, [0, 50, 90, 99, 100], method="nearest")]


def different(a: Array, b: Array) -> Array:
    """Same numeric equality as the baseline, including matching NaNs and signed zeros."""
    result: Array = ~((a == b) | (np.isnan(a) & np.isnan(b)))
    return result


def measurements(a: Array, b: Array) -> dict[str, Any]:
    require(a.shape == b.shape == (256, 256, 3), "decoded image shape differs")
    unequal = different(a, b)
    channels = []
    for channel in range(3):
        finite = np.isfinite(a[..., channel]) & np.isfinite(b[..., channel])
        delta = a[..., channel].astype(np.float64) - b[..., channel].astype(np.float64)
        selected = delta[finite]
        nonzero_delta = delta[finite & unequal[..., channel]]
        channels.append(
            {
                "channel": "RGB"[channel],
                "samples": int(delta.size),
                "mismatches": int(np.count_nonzero(unequal[..., channel])),
                "signed_min": float(selected.min()) if selected.size else None,
                "signed_max": float(selected.max()) if selected.size else None,
                "abs_quantiles_all": quantiles(np.abs(selected)),
                "abs_quantiles_mismatches": quantiles(np.abs(nonzero_delta)),
            }
        )
    return {
        "pixels": int(a.shape[0] * a.shape[1]),
        "pixels_mismatched": int(np.count_nonzero(np.any(unequal, axis=-1))),
        "candidate_nonfinite": int(np.count_nonzero(~np.isfinite(a))),
        "reference_nonfinite": int(np.count_nonzero(~np.isfinite(b))),
        "channels": channels,
    }


def existing_tables() -> tuple[Array, Array, dict[str, str]]:
    arith_path, encode_path = (
        REPO_ROOT / "src/evaluator/arith.cpp",
        REPO_ROOT / "src/export/encode.cpp",
    )
    arith, encode = arith_path.read_text(), encode_path.read_text()
    operands = re.search(r"kSrgb8DecodeBits\[256\]\s*=\s*\{(.*?)\};", arith, re.S)
    codes = re.search(r"kOcioSrgbPng16\[256\]\s*=\s*\{(.*?)\};", encode, re.S)
    require(operands is not None and codes is not None, "existing table declarations changed")
    assert operands is not None and codes is not None
    bits = np.array(
        [int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]+)u", operands[1])], dtype=np.uint32
    )
    png16 = np.array([int(x) for x in re.findall(r"(\d+)u", codes[1])], dtype=np.int64)
    require(bits.size == png16.size == 256, "existing table lengths changed")
    values = bits.view(np.float32).astype(np.float64)
    require(bool(np.all(np.diff(values) > 0)), "existing operand order changed")
    return (
        values,
        png16,
        {str(p.relative_to(REPO_ROOT)): sha(p.read_bytes()) for p in (arith_path, encode_path)},
    )


def cross_format(images: dict[tuple[str, str, str], Array]) -> list[dict[str, Any]]:
    operands, png16, _ = existing_tables()
    result = []
    for source in control.RGB16_CANDIDATES:
        for condition in ("candidate", "same_session", "after_save_reopen"):
            floats = images[source, "exr32", condition]
            indices = np.minimum(np.searchsorted(operands, floats), 255)
            known = floats == operands[indices]
            row: dict[str, Any] = {
                "source": source,
                "condition": condition,
                "samples": int(floats.size),
                "outside_srgb8_operands": int(np.count_nonzero(~known)),
            }
            for format_, expected in (("png8", indices), ("png16", png16[indices])):
                row[format_ + "_known_samples_mismatched"] = int(
                    np.count_nonzero(known & (images[source, format_, condition] != expected))
                )
            result.append(row)
    return result


def permutation_checks(images: dict[tuple[str, str, str], Array]) -> list[dict[str, Any]]:
    permutations: list[dict[str, Any]] = []
    for source, inverse in (("field-a-brg", (1, 2, 0)), ("field-a-gbr", (2, 0, 1))):
        for format_ in ("png8", "png16", "exr32"):
            for condition in ("candidate", "same_session", "after_save_reopen"):
                unequal = different(
                    images[source, format_, condition][..., inverse],
                    images["field-a", format_, condition],
                )
                permutations.append(
                    {
                        "source": source,
                        "format": format_,
                        "condition": condition,
                        "samples_mismatched": int(np.count_nonzero(unequal)),
                        "pixels_mismatched": int(np.count_nonzero(np.any(unequal, axis=-1))),
                    }
                )
    return permutations


def analyze(evidence: dict[str, Any], root: Path, progress: dict[str, str]) -> dict[str, Any]:
    progress["stage"] = "preserved"
    produced = preserved(evidence, root)
    pairs: list[tuple[bytes, bytes]] = []

    def collect(data: bytes, expected: bytes, report: dict[str, Any]) -> None:
        # Reuse all existing admission/recipe/envelope/export checks, deferring every decode.
        pairs.append((data, expected))
        report["comparisons"] += 1

    progress["stage"] = "receipt_validation"
    with patch.object(baseline, "compare_bytes", collect):
        baseline.compare_produced(produced, baseline.new_report())
    require(len(pairs) == 18, "validated pair matrix incomplete")
    progress["stage"] = "measurements"
    rows = []
    images: dict[tuple[str, str, str], Array] = {}
    with patch.object(tempfile, "tempdir", str(root)):
        for index, (data, expected) in enumerate(pairs):
            candidate = produced[index // 2][0]
            condition = ("same_session", "after_save_reopen")[index % 2]
            a, b = decode(data), decode(expected)
            require(a.integer == b.integer and a.bits == b.bits, "decoded format differs")
            format_ = ("png" if a.integer else "exr") + str(a.bits)
            require(format_ in {"png8", "png16", "exr32"}, "unexpected decoded format")
            rows.append(
                {
                    "source": candidate.source,
                    "format": format_,
                    "condition": condition,
                    "candidate_sha256": sha(data),
                    "reference_sha256": sha(expected),
                    **measurements(a.values, b.values),
                }
            )
            images[candidate.source, format_, "candidate"] = a.values
            images[candidate.source, format_, condition] = b.values
    progress["stage"] = "aggregate_checks"
    permutations = permutation_checks(images)
    repeat = [
        {
            "source": source,
            "format": format_,
            "samples_mismatched": int(
                np.count_nonzero(
                    different(
                        images[source, format_, "same_session"],
                        images[source, format_, "after_save_reopen"],
                    )
                )
            ),
        }
        for source in control.RGB16_CANDIDATES
        for format_ in ("png8", "png16", "exr32")
    ]
    return {
        "schema": "uzpainter/ocio16-rejected-diagnostic/1",
        "status": "complete",
        "model": evidence["model"],
        "model_verdict": "rejected",
        "non_conformant": True,
        "historical_report_sha256": evidence["report"]["sha256"],
        "executable_sha256": evidence["executable_sha256"],
        "quantiles": [0, 50, 90, 99, 100],
        "error_direction": "candidate-minus-reference",
        "error_units": "native PNG code or EXR float",
        "comparisons": rows,
        "cross_format": cross_format(images),
        "permutations": permutations,
        "recording_repeatability": repeat,
        "existing_table_sources": existing_tables()[2],
        "receipt_validator_sha256": sha(Path(baseline.__file__).read_bytes()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    progress = {"stage": "preflight"}
    failure_path = None
    try:
        evidence_path = ensure_outside_repository(args.evidence).resolve()
        output = ensure_outside_repository(args.output).resolve()
        require(
            output.parent == evidence_path.parent and output != evidence_path,
            "output must use existing private evidence folder",
        )
        require(not output.exists(), "diagnostic output already exists")
        failure_path = output.with_name(output.stem + "-failure.json")
        data = evidence_path.read_bytes()
        require(sha(data) == args.evidence_sha256, "evidence index hash differs")
        report = analyze(json.loads(data), evidence_path.parent, progress)
        report["evidence_sha256"] = sha(data)
        report["diagnostic_code_sha256"] = sha(Path(__file__).read_bytes())
        progress["stage"] = "write_report"
        encoded = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        with output.open("xb") as stream:
            require(stream.write(encoded) == len(encoded), "short diagnostic write")
        print(
            json.dumps(
                {
                    "status": "complete",
                    "comparisons": len(report["comparisons"]),
                    "report_sha256": sha(encoded),
                }
            )
        )
    except Exception:
        if failure_path is not None:
            failure = {"status": "refused", **progress, "traceback": traceback.format_exc()}
            try:
                with failure_path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(failure, sort_keys=True, indent=2) + "\n")
            except Exception:
                pass
        print('{"status":"refused"}')
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
