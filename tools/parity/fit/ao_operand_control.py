"""Verify frozen four-set AO controls; public output contains only hashes and counts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.oracle import Golden, OracleUnavailable, load
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.job import EXPORT, canonical_json
from tools.parity.schemas import load_json, record_problems
from tools.parity.store.store import load_oracle, locate
from tools.parity.tier0_semantics import ao_operand_control as authored
from tools.parity.tier0_semantics import recording_requests as requests
from tools.parity.verdict import resolve_golden

GOLDEN = "tier0/semantics/ao-mixed-mesh-float-product"
PREDICTION_SHA256 = "816dd547a054cb453d601556db7f36ca7e8fa257931582963026542c1022134c"
PROTOCOL_SHA256 = "2961757c5df30fd45fdf084bb33bd8837800b8633b9e70376ee60bbe26c5969d"
INPUT_COMMITMENTS = {
    authored.MESH_VALUES: "f4ce3fe428bd313dce7169eb84d8b565428aa6dd100232213ab1949a05c2e200",
    authored.PRODUCT_VALUES: "c15bc094abab6ed5d9c8b29b3688877245801b532611d06f596d9df1f64772a1",
}
MAPS = {"AO_Mixed": "virtualMap", "ambientOcclusion": "documentMap", "ambient_occlusion": "meshMap"}
SETS = ("s0", "s1", "s2", "s3")
Array = npt.NDArray[Any]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prediction() -> tuple[Array, Array]:
    mesh, channel = authored.operands()
    product = mesh * channel
    fixed = np.floor(product.astype(np.float64) * 4096).astype(np.int64)
    codes = ((fixed * 255 + 2047) >> 12).astype(np.uint8)
    if digest(codes.tobytes()) != PREDICTION_SHA256:
        raise ValueError("frozen AO prediction changed")
    return product, codes


def bits(values: Array, floating: bool) -> Array:
    return values.astype("<f4").view("<u4") if floating else values.astype(np.uint8)


def comparison(left: Array, right: Array) -> dict[str, Any]:
    return {
        "samples": int(left.size),
        "differences": int(np.count_nonzero(left != right)),
        "left_sha256": digest(left.tobytes()),
        "right_sha256": digest(right.tobytes()),
    }


def validate_record(record: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Validate the private envelope before the generic loader's indexed view is trusted."""
    if record_problems(record):
        raise ValueError("private record schema or cross-field rules failed")
    envelope = current_envelope()
    key = record["key"]
    if (
        record["golden_id"] != GOLDEN
        or record["tier"] != "0"
        or key["painter_build"]["build_id"] != envelope["painter_build"]
        or envelope_sha256(record.get("environment", {})) != envelope["envelope_sha256"]
        or key["instruction_sequence_sha256"]
        != digest(canonical_json(manifest["instruction_sequence"]))
        or key["inputs"]
        != [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in manifest["inputs"]]
    ):
        raise ValueError("private record identity or envelope differs from frozen control")
    recordings = record["recordings"]
    if len(recordings) != len({r["recording_id"] for r in recordings}) or any(
        len(r["outputs"]) != len({o["output_id"] for o in r["outputs"]}) for r in recordings
    ):
        raise ValueError("duplicate recording or output ids")


def validate_template(recording: Any) -> None:
    captures = [o for o in recording.outputs.values() if o["kind"] == "template_capture"]
    if len(captures) != 1:
        raise ValueError("AO control requires one effective template capture per recording")
    sets = captures[0]["values"]["texture_sets"]
    if set(sets) != set(SETS):
        raise ValueError("AO effective texture sets differ from frozen control")
    for texture_set in sets.values():
        if texture_set["resolution"] != [256, 256] or set(texture_set["stacks"]) != {""}:
            raise ValueError("AO effective resolution or stack differs from frozen control")
        ao = texture_set["stacks"][""]["AO"]
        if ao["format"] != "L32F" or ao["bit_depth"] != 32 or ao["is_floating"] is not True:
            raise ValueError("AO effective channel must be L32F")


def verify(golden: Golden) -> dict[str, Any]:
    """Retain every failed precondition and comparison; never emit sample values or locations."""
    control = authored.request()
    if (
        golden.golden_id != GOLDEN
        or golden.manifest["instruction_sequence"]["steps"] != control.sequence.steps
    ):
        raise ValueError("record does not use the frozen AO control sequence")
    expected_inputs = {}
    for name in control.inputs:
        generator = requests.fixture(name)[2]
        if generator is None:
            raise ValueError("AO authored input is not reproducible")
        expected_inputs[name] = digest(generator())
    if any(expected_inputs[name] != pinned for name, pinned in INPUT_COMMITMENTS.items()):
        raise ValueError("frozen AO mesh or product input changed")
    inputs = golden.manifest["inputs"]
    if (
        len(inputs) != len(expected_inputs)
        or {i["input_id"]: i["sha256"] for i in inputs} != expected_inputs
    ):
        raise ValueError("record does not use the frozen authored inputs")
    expected = requests.request_manifest(control, expected_inputs, current_envelope())
    protocol = {
        "steps": control.sequence.steps,
        "inputs": expected_inputs,
        "settings": expected["applied_settings"],
    }
    if digest(canonical_json(protocol)) != PROTOCOL_SHA256:
        raise ValueError("frozen AO protocol or authored inputs changed")
    if golden.manifest.get("applied_settings") != expected["applied_settings"]:
        raise ValueError("record settings differ from the frozen AO control")
    if {name: rec.condition for name, rec in golden.recordings.items()} != {
        "r1": "same_session",
        "r2": "after_save_reopen",
    }:
        raise ValueError("AO control needs both same-session and save/reopen recordings")
    exports = [s for s in control.sequence.steps if s["call"] == EXPORT]
    formats = {s["step"]: s["args"]["file_format"] for s in exports}
    steps = {fmt: [step for step, kind in formats.items() if kind == fmt] for fmt in ("png", "exr")}
    samples: dict[tuple[str, int, str, str], Array] = {}
    hashes: dict[str, str] = {}
    for recording in golden.recordings:
        validate_template(golden.recordings[recording])
        for output_id in golden.maps(recording):
            output = golden.output(recording, output_id)
            settings, storage = output["export_settings"], output["storage_format"]
            step, texture_set, map_name = settings["step"], output["texture_set"], output["map"]
            key = (recording, step, texture_set, map_name)
            if (
                step not in formats
                or texture_set not in SETS
                or map_name not in MAPS
                or key in samples
            ):
                raise ValueError("unexpected or duplicate AO control output")
            fmt = formats[step]
            floating = fmt == "exr"
            if (
                storage["container"] != fmt
                or storage["channels"] != 1
                or storage["bits_per_channel"] != (32 if floating else 8)
                or storage["sample_type"] != ("float" if floating else "uint")
                or settings["map_type"] != MAPS[map_name]
                or settings["map_channels"] != "L"
                or settings["paddingAlgorithm"] != "passthrough"
                or settings["dithering"] is not False
            ):
                raise ValueError("AO output storage or processing differs from frozen control")
            decoded = golden.map(recording, output_id)
            if (
                decoded.values.shape != (256, 256, 1)
                or decoded.integer == floating
                or decoded.bits != (32 if floating else 8)
            ):
                raise ValueError("AO decoded shape or precision differs from frozen control")
            if not np.isfinite(decoded.values).all():
                raise ValueError("AO output contains nonfinite values")
            samples[key] = bits(decoded.values[..., 0], floating)
            hashes[f"{recording}/{step}/{texture_set}/{map_name}"] = golden.map_sha256(
                recording, output_id
            )
    if len(samples) != 96:
        raise ValueError("AO control requires all 96 outputs, including every repeat")
    product, codes = prediction()
    preconditions: dict[str, Any] = {}
    scores: dict[str, Any] = {}
    stability: dict[str, Any] = {}
    cross_sets: dict[str, Any] = {}
    for recording in golden.recordings:
        for repeat, step in enumerate(steps["exr"]):

            def value(
                texture_set: str, name: str, recording: str = recording, step: int = step
            ) -> Array:
                return samples[recording, step, texture_set, name]

            prefix = f"{recording}/repeat{repeat + 1}"
            for name in ("ambientOcclusion", "ambient_occlusion"):
                preconditions[f"{prefix}/s0-s1/{name}"] = comparison(
                    value("s0", name), value("s1", name)
                )
            exported_product = value("s1", "ambientOcclusion").view("<f4") * value(
                "s1", "ambient_occlusion"
            ).view("<f4")
            for texture_set in ("s2", "s3"):
                preconditions[f"{prefix}/{texture_set}/white"] = comparison(
                    value(texture_set, "ambientOcclusion"), bits(np.ones((256, 256)), True)
                )
                preconditions[f"{prefix}/{texture_set}/authored-product"] = comparison(
                    value(texture_set, "ambient_occlusion"), bits(product, True)
                )
                preconditions[f"{prefix}/{texture_set}/exported-product"] = comparison(
                    value(texture_set, "ambient_occlusion"), bits(exported_product, True)
                )
        for fmt, pair in steps.items():
            for step in pair:
                for texture_set in SETS:
                    if fmt == "png":
                        scores[f"{recording}/{step}/{texture_set}"] = comparison(
                            samples[recording, step, texture_set, "AO_Mixed"], codes
                        )
                    if texture_set != "s0":
                        cross_sets[f"{recording}/{step}/s0-{texture_set}"] = comparison(
                            samples[recording, step, "s0", "AO_Mixed"],
                            samples[recording, step, texture_set, "AO_Mixed"],
                        )
            for texture_set in SETS:
                for name in MAPS:
                    stability[f"{recording}/{fmt}/{texture_set}/{name}"] = comparison(
                        samples[recording, pair[0], texture_set, name],
                        samples[recording, pair[1], texture_set, name],
                    )
    for step in formats:
        for texture_set in SETS:
            for name in MAPS:
                stability[f"reopen/{step}/{texture_set}/{name}"] = comparison(
                    samples["r1", step, texture_set, name], samples["r2", step, texture_set, name]
                )
    return {
        "schema": "uzpainter/ao-operand-control-verification/1",
        "record_sha256": golden.record_sha256,
        "prediction_sha256": PREDICTION_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
        "output_hashes": hashes,
        "preconditions": preconditions,
        "precondition_failures": sum(c["differences"] != 0 for c in preconditions.values()),
        "stability": stability,
        "stability_failures": sum(c["differences"] != 0 for c in stability.values()),
        "conditional_png_prediction": scores,
        "cross_set_ao_mixed": cross_sets,
        "comparison_failures": sum(
            c["differences"] != 0 for c in (*scores.values(), *cross_sets.values())
        ),
        "scope": "Frozen diagnostic only; prediction inference requires all preconditions "
        "and stability. No acceptance.",
    }


def main() -> int:
    resolved = resolve_golden(GOLDEN)
    if resolved is None:
        print(json.dumps({"status": "oracle_unavailable", "golden_id": GOLDEN}))
        return 2
    store = locate()
    try:
        manifest = load_json(resolved.manifest_path)
        # Validate raw identity and duplicates before the loader indexes by id.
        refs = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
        if len(refs) != 1:
            raise ValueError("AO control requires exactly one golden-record reference")
        raw = load_oracle(
            store,
            refs[0],
        )
        if raw is None:
            raise OracleUnavailable("record unavailable")
        validate_record(json.loads(raw), manifest)
        golden = load(store, resolved.manifest_path)
        report = verify(golden)
    except (OracleUnavailable, ValueError, KeyError, TypeError, StopIteration):
        print(json.dumps({"status": "invalid_or_unavailable_control", "golden_id": GOLDEN}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        1
        if any(
            report[k]
            for k in ("precondition_failures", "stability_failures", "comparison_failures")
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
