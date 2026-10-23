"""Authored bit patterns only; no oracle pixels or candidate refitting."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit import padding_plane_control as control
from tools.parity.fit.decode import Decoded
from tools.parity.fit.oracle import Golden, Recording
from tools.parity.tier0_semantics import padding_plane_control as authored
from tools.parity.tier0_semantics import recording_requests as requests


def golden() -> Golden:
    records = {}
    for rec, condition in (("r1", "same_session"), ("r2", "after_save_reopen")):
        outputs = {
            "template/texture-sets": {
                "kind": "template_capture",
                "values": {
                    "texture_sets": {
                        control.MATERIAL: {
                            "resolution": [512, 512],
                            "stacks": {
                                "": {
                                    f"User{i}": {
                                        "format": "RGB32F",
                                        "bit_depth": 32,
                                        "is_floating": True,
                                    }
                                    for i in range(8)
                                }
                            },
                        }
                    }
                },
            }
        }
        for step, mode in enumerate(("infinite", "infinite", "passthrough", "passthrough")):
            for i in range(8):
                outputs[f"{step}/{i}"] = {
                    "kind": "exported_map",
                    "texture_set": control.MATERIAL,
                    "map": f"user{i}",
                    "storage_format": {
                        "container": "exr",
                        "sample_type": "float",
                        "bits_per_channel": 32,
                        "channels": 3,
                        "encoding": "linear",
                    },
                    "export_settings": {
                        "step": step + 45,
                        "paddingAlgorithm": mode,
                        "map_type": "documentMap",
                        "map_channels": "RGB",
                        "encoding_basis": "source_channel_format",
                        "fileFormat": "exr",
                        "bitDepth": "32f",
                        "dithering": False,
                    },
                }
        records[rec] = Recording(rec, condition, outputs)
    result = Mock(
        spec=Golden, wraps=Golden(control.GOLDEN, Path("unused"), {}, "a" * 64, records, None)
    )
    result.golden_id = control.GOLDEN
    result.manifest = requests.request_manifest(
        authored.request(), control.INPUTS, current_envelope()
    )
    result.recordings = records
    result.map.return_value = Decoded(np.zeros((512, 512, 3), np.float64), False, 32)
    return result


def test_capture_requires_complete_repeated_reopened_domain() -> None:
    samples = control.captured_samples(golden())
    assert set(samples) == {"r1", "r2"}
    assert samples["r2"]["infinite"][1].shape == (512, 512, 24)


@pytest.mark.parametrize("failure", ["missing", "condition", "format", "channel", "integer"])
def test_capture_refuses_wrong_or_partial_domain(failure: str) -> None:
    record = golden()
    if failure == "missing":
        del record.recordings["r2"].outputs["3/7"]
    elif failure == "condition":
        record.recordings["r2"].condition = "same_session"
    elif failure == "format":
        record.recordings["r1"].outputs["0/0"]["storage_format"]["bits_per_channel"] = 16
    elif failure == "channel":
        record.recordings["r1"].outputs["template/texture-sets"]["values"]["texture_sets"][
            control.MATERIAL
        ]["stacks"][""]["User7"]["format"] = "RGB16F"
    else:
        record.map.return_value = Decoded(np.zeros((512, 512, 3), np.int64), True, 32)  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        control.captured_samples(record)


def test_scoring_counts_bits_coverage_repeats_groups_and_verification() -> None:
    source = np.full((2, 3, 24), np.float32(0.5)).view(np.uint32)
    covered = np.array([[True, True, False], [True, False, False]])
    samples = {
        rec: {mode: [source.copy(), source.copy()] for mode in ("infinite", "passthrough")}
        for rec in ("r1", "r2")
    }
    rows = {
        "2,0": {"bits": source[0, 2].tolist(), "region": "0-h1-w4-flat-q0", "taps": 2},
        "1,1": {"bits": source[1, 1].tolist(), "region": "1-h2-w16-flat-q0", "taps": 4},
    }
    predictions = {name: copy.deepcopy(rows) for name in ("baseline", "generic", "conservative")}
    clean = control.score(samples, source, covered, predictions)
    assert clean["domain_pass"] == 1
    assert clean["policies"]["baseline"]["r1_0"]["all"]["differing"] == 0
    predictions["generic"]["2,0"]["bits"][12] += 1
    report = control.score(samples, source, covered, predictions)
    assert report["policies"]["generic"]["r1_0"]["h1-w4"]["verification_differing"] == 1
    assert report["policies"]["generic"]["r1_0"]["all"]["discovery_differing"] == 0
    samples["r2"]["infinite"][1][0, 0, 0] += 1
    invalid = control.score(samples, source, covered, predictions)
    assert invalid["coverage_mismatches"] == 1 and invalid["domain_pass"] == 0
    assert invalid["stability"]["infinite_reopen_1"] == 1
    assert "2,0" not in json.dumps(report) and "bits" not in json.dumps(report)
    assert report["ordered_tap_lists_absent"] == 2


def test_passthrough_uncovered_instability_is_reported_separately() -> None:
    source = np.zeros((1, 2, 24), dtype=np.uint32)
    covered = np.array([[True, False]])
    samples = {
        rec: {mode: [source.copy(), source.copy()] for mode in ("infinite", "passthrough")}
        for rec in ("r1", "r2")
    }
    samples["r2"]["passthrough"][1][0, 1, 0] = 0x80000000
    rows = {"1,0": {"bits": [0] * 24, "region": "0-h1-w4-flat-q0", "taps": 2}}
    report = control.score(
        samples, source, covered, {name: rows for name in ("baseline", "generic", "conservative")}
    )
    assert report["domain_pass"] == 1
    assert report["stability"]["r2_uncovered_passthrough_repeat"] == 1


def test_changed_frozen_predictions_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "predictions.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        control.validate(golden(), path)


def test_changed_authored_inputs_are_refused() -> None:
    record = golden()
    record.manifest = {"inputs": []}
    with pytest.raises(ValueError, match="authored inputs"):
        control.frozen_inputs(record, Path("unused"))


def test_duplicate_authored_input_is_not_hidden_by_indexing() -> None:
    record = golden()
    record.manifest["inputs"].append(copy.deepcopy(record.manifest["inputs"][0]))
    with pytest.raises(ValueError, match="authored inputs"):
        control.frozen_inputs(record, Path("unused"))


@pytest.mark.parametrize("change", ["sequence", "settings", "step", "dithering"])
def test_changed_capture_protocol_is_refused(change: str) -> None:
    record = golden()
    if change == "sequence":
        record.manifest["instruction_sequence"]["steps"][-1]["args"]["dithering"] = True
    elif change == "settings":
        record.manifest["applied_settings"] = []
    elif change == "step":
        record.recordings["r1"].outputs["0/0"]["export_settings"]["step"] = 100
    else:
        record.recordings["r1"].outputs["0/0"]["export_settings"]["dithering"] = True
    with pytest.raises(ValueError):
        control.captured_samples(record)


@pytest.mark.parametrize("duplicate", ["recording", "output"])
def test_raw_duplicate_ids_are_refused_before_indexing(duplicate: str) -> None:
    recording: dict[str, Any] = {"recording_id": "r1", "outputs": [{"output_id": "sample"}]}
    record = {"recordings": [recording]}
    if duplicate == "recording":
        record["recordings"].append(copy.deepcopy(recording))
    else:
        recording["outputs"].append({"output_id": "sample"})
    with pytest.raises(ValueError, match="duplicate"):
        control.validate_record(record, {})


def test_cli_missing_blob_reports_no_private_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["padding-plane-control", "--manifest", "unused", "--predictions", "unused"]
    )
    monkeypatch.setattr(
        control, "load_json", lambda _: {"private_records": [{"record_id": "golden-record"}]}
    )
    monkeypatch.setattr(control, "locate", lambda: None)
    monkeypatch.setattr(control, "load_oracle", lambda *_: None)
    assert control.main() == 2
    result = capsys.readouterr()
    assert json.loads(result.out) == {"status": "oracle_unavailable", "golden_id": control.GOLDEN}
    assert result.err == ""


@pytest.mark.parametrize("failure", ["dimensions", "nonfinite"])
def test_decoded_domain_is_checked_independently_of_metadata(failure: str) -> None:
    values = np.zeros((512, 512, 3), dtype=np.float64)
    if failure == "dimensions":
        values = values[:256]
    else:
        values[0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        control.bits_of(Decoded(values, False, 32))


def test_source_coverage_cannot_overlap_frozen_ring() -> None:
    source = np.zeros((1, 1, 24), dtype=np.uint32)
    samples = {
        rec: {mode: [source, source] for mode in ("infinite", "passthrough")}
        for rec in ("r1", "r2")
    }
    rows = {"0,0": {"bits": [0] * 24, "region": "0-h1-w4-flat-q0", "taps": 2}}
    with pytest.raises(ValueError, match="overlaps"):
        control.score(samples, source, np.ones((1, 1), dtype=bool), {"baseline": rows})
