"""Synthetic full recordings exercise frozen AO verification without private oracle pixels."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit import ao_operand_control as verifier
from tools.parity.fit.decode import Decoded
from tools.parity.fit.oracle import Golden, Recording
from tools.parity.recorder.job import EXPORT, canonical_json
from tools.parity.tier0_semantics import ao_operand_control as authored
from tools.parity.tier0_semantics import recording_requests as requests


@pytest.fixture
def golden() -> Golden:
    control = authored.request()
    inputs = []
    for name in control.inputs:
        generate = requests.fixture(name)[2]
        assert generate is not None
        inputs.append({"input_id": name, "sha256": verifier.digest(generate())})
    result = Golden(
        verifier.GOLDEN,
        Path("synthetic.json"),
        {"instruction_sequence": {"steps": control.sequence.steps}, "inputs": inputs},
        "a" * 64,
        {},
        None,
    )
    result.manifest["applied_settings"] = requests.request_manifest(
        control, {i["input_id"]: i["sha256"] for i in inputs}, current_envelope()
    )["applied_settings"]
    mesh, channel = authored.operands()
    product, codes = verifier.prediction()
    for recording, condition in (("r1", "same_session"), ("r2", "after_save_reopen")):
        outputs = {}
        for step in (s for s in control.sequence.steps if s["call"] == EXPORT):
            number, fmt = step["step"], step["args"]["file_format"]
            floating = fmt == "exr"
            for texture_set in verifier.SETS:
                for name, kind in verifier.MAPS.items():
                    if name == "AO_Mixed":
                        values = codes.astype(np.float32) / np.float32(255)
                    elif name == "ambient_occlusion":
                        values = mesh if texture_set in ("s0", "s1") else product
                    else:
                        values = channel if texture_set in ("s0", "s1") else np.ones_like(channel)
                    stored = values if floating else np.rint(values * 255).astype(np.uint8)
                    sha = verifier.digest(stored.tobytes())
                    output_id = f"{texture_set}/{name}/step{number}"
                    outputs[output_id] = {
                        "kind": "exported_map",
                        "texture_set": texture_set,
                        "map": name,
                        "blob": {"sha256": sha},
                        "storage_format": {
                            "container": fmt,
                            "channels": 1,
                            "sample_type": "float" if floating else "uint",
                            "bits_per_channel": 32 if floating else 8,
                        },
                        "export_settings": {
                            "step": number,
                            "map_type": kind,
                            "map_channels": "L",
                            "paddingAlgorithm": "passthrough",
                            "dithering": False,
                        },
                    }
                    result._decoded[sha] = Decoded(
                        stored[..., None], not floating, 32 if floating else 8
                    )
        result.recordings[recording] = Recording(recording, condition, outputs)
        outputs["template/texture-sets"] = {
            "kind": "template_capture",
            "values": {
                "texture_sets": {
                    texture_set: {
                        "resolution": [256, 256],
                        "stacks": {
                            "": {
                                "AO": {
                                    "format": "L32F",
                                    "bit_depth": 32,
                                    "is_floating": True,
                                }
                            }
                        },
                    }
                    for texture_set in verifier.SETS
                }
            },
        }
    return result


def test_full_control_scores_every_repeat_and_reopen(golden: Golden) -> None:
    report = verifier.verify(golden)
    assert len(report["output_hashes"]) == 96
    assert len(report["preconditions"]) == 32
    assert len(report["stability"]) == 96
    assert len(report["conditional_png_prediction"]) == 16
    assert report["precondition_failures"] == report["stability_failures"] == 0
    assert all(c["differences"] == 0 for c in report["conditional_png_prediction"].values())
    encoded = json.dumps(report)
    assert "coordinate" not in encoded and "pixels" not in encoded and "values" not in encoded


def test_wrong_operand_in_reopened_repeat_is_retained(golden: Golden) -> None:
    output = next(
        o
        for o in golden.recordings["r2"].outputs.values()
        if o["texture_set"] == "s3"
        and o["map"] == "ambient_occlusion"
        and o["storage_format"]["container"] == "exr"
    )
    altered = golden._decoded[output["blob"]["sha256"]].values.copy()
    altered[7, 19, 0] = np.nextafter(altered[7, 19, 0], np.float32(1))
    sha = verifier.digest(altered.tobytes())
    output["blob"]["sha256"] = sha
    golden._decoded[sha] = Decoded(altered, False, 32)
    report = verifier.verify(golden)
    assert report["precondition_failures"] == 2
    assert report["stability_failures"] == 2
    assert len(report["conditional_png_prediction"]) == 16


def test_stable_quantizer_residual_does_not_change_frozen_prediction(golden: Golden) -> None:
    for recording in golden.recordings.values():
        for output in recording.outputs.values():
            if output["kind"] != "exported_map":
                continue
            if output["map"] != "AO_Mixed" or output["storage_format"]["container"] != "png":
                continue
            old = golden._decoded[output["blob"]["sha256"]]
            values = old.values.copy()
            values[0, 0, 0] = 1
            sha = verifier.digest(values.tobytes())
            golden._decoded[sha] = Decoded(values, True, 8)
            output["blob"]["sha256"] = sha
    report = verifier.verify(golden)
    assert report["precondition_failures"] == report["stability_failures"] == 0
    assert report["prediction_sha256"] == verifier.PREDICTION_SHA256
    assert report["comparison_failures"] == 16
    assert all(c["differences"] == 1 for c in report["conditional_png_prediction"].values())


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "precision", "processing", "reopen", "sequence", "input"]
)
def test_incomplete_or_different_protocol_refuses(golden: Golden, change: str) -> None:
    outputs = golden.recordings["r2"].outputs
    name = next(iter(outputs))
    if change == "missing":
        del outputs[name]
    elif change == "duplicate":
        outputs["duplicate"] = copy.deepcopy(outputs[name])
    elif change == "precision":
        outputs[name]["storage_format"]["bits_per_channel"] = 16
    elif change == "processing":
        outputs[name]["export_settings"]["dithering"] = True
    elif change == "reopen":
        golden.recordings["r2"].condition = "same_session"
    elif change == "sequence":
        golden.manifest["instruction_sequence"]["steps"] = []
    else:
        golden.manifest["inputs"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError):
        verifier.verify(golden)


@pytest.mark.parametrize("change", ["missing", "format", "resolution", "set", "stack"])
def test_effective_template_is_required_in_reopened_recording(golden: Golden, change: str) -> None:
    outputs = golden.recordings["r2"].outputs
    sets = outputs["template/texture-sets"]["values"]["texture_sets"]
    if change == "missing":
        del outputs["template/texture-sets"]
    elif change == "format":
        sets["s3"]["stacks"][""]["AO"]["format"] = "L16"
    elif change == "resolution":
        sets["s2"]["resolution"] = [128, 128]
    elif change == "set":
        del sets["s1"]
    else:
        sets["s0"]["stacks"]["other"] = {}
    with pytest.raises(ValueError):
        verifier.verify(golden)


def test_raw_schema_is_checked_before_identity(golden: Golden) -> None:
    with pytest.raises(ValueError, match="schema"):
        verifier.validate_record({}, golden.manifest)


def test_changed_authored_mesh_is_not_refrozen(
    golden: Golden, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = requests.fixture

    def changed(name: str) -> Any:
        value = fixture(name)
        return (value[0], value[1], lambda: b"changed") if name == authored.MESH_VALUES else value

    monkeypatch.setattr(requests, "fixture", changed)
    with pytest.raises(ValueError, match="frozen AO mesh or product"):
        verifier.verify(golden)


def test_duplicate_record_reference_fails_before_loading(
    golden: Golden, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = {"private_records": [{"record_id": "golden-record"}, {"record_id": "golden-record"}]}
    monkeypatch.setattr(
        verifier, "resolve_golden", lambda _: SimpleNamespace(manifest_path=Path("x"))
    )
    monkeypatch.setattr(verifier, "load_json", lambda _: manifest)
    monkeypatch.setattr(verifier, "locate", lambda: None)

    def forbidden(*args: Any) -> Any:
        raise AssertionError("duplicate references must fail before loading")

    monkeypatch.setattr(verifier, "load", forbidden)
    monkeypatch.setattr(verifier, "load_oracle", forbidden)
    assert verifier.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_or_unavailable_control"


@pytest.mark.parametrize(
    "change", ["golden", "tier", "build", "envelope", "sequence", "inputs", "duplicate"]
)
def test_raw_identity_and_duplicates_are_not_hidden_by_loader(
    golden: Golden, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate identity checks; the schema's own gate is exercised separately.
    monkeypatch.setattr(verifier, "record_problems", lambda record: [])
    monkeypatch.setattr(verifier, "envelope_sha256", lambda environment: environment["digest"])
    envelope = current_envelope()
    record: dict[str, Any] = {
        "golden_id": verifier.GOLDEN,
        "tier": "0",
        "environment": {"digest": envelope["envelope_sha256"]},
        "key": {
            "painter_build": {"build_id": envelope["painter_build"]},
            "instruction_sequence_sha256": verifier.digest(
                canonical_json(golden.manifest["instruction_sequence"])
            ),
            "inputs": golden.manifest["inputs"],
        },
        "recordings": [
            {"recording_id": "r1", "outputs": []},
            {"recording_id": "r2", "outputs": []},
        ],
    }
    verifier.validate_record(record, golden.manifest)
    if change == "golden":
        record["golden_id"] = "other"
    elif change == "tier":
        record["tier"] = "1"
    elif change == "build":
        record["key"]["painter_build"]["build_id"] = "other"
    elif change == "envelope":
        record["environment"]["digest"] = "b" * 64
    elif change == "sequence":
        record["key"]["instruction_sequence_sha256"] = "b" * 64
    elif change == "inputs":
        record["key"]["inputs"] = []
    else:
        record["recordings"][0]["outputs"] = [{"output_id": "x"}, {"output_id": "x"}]
    with pytest.raises(ValueError):
        verifier.validate_record(record, golden.manifest)
