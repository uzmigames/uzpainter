"""Synthetic admitted captures and real authored EXRs; no private oracle or recorder run."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import numpy as np
import OpenEXR
import pytest

from tests.parity.test_ocio16_raw_export_admission import authored_export, sealed
from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_export_admission as admission
from tools.parity import ocio16_raw_transfer_diagnostics as diagnostic
from tools.parity.envelope import ocio
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str = ""
) -> tuple[list[dict[str, Any]], Mock]:
    manifests, stores, environments = [], [], []
    for index, state in enumerate(diagnostic.STATES):
        manifest, record, _ = authored_export(tmp_path, monkeypatch, state)
        for marker in ("public-project", "public-synthetic", "public-session"):
            record = json.loads(json.dumps(record).replace(marker, marker + state))
        record["environment"]["recorder_version"] = "authored-" + state
        if index and mutation == "envelope":
            record["environment"]["driver_version"] = "other"
        if index and mutation == "receipt":
            record["key"]["instruction_sequence_sha256"] = "0" * 64
        if index and mutation == "context":
            for recording in record["recordings"]:
                next(o for o in recording["outputs"] if o["kind"] == "template_capture")["values"][
                    "marker"
                ] = "different"
        paths = {}
        for round_index, recording in enumerate(record["recordings"]):
            values = control.authored_values(state).copy()
            if index and mutation == "value":
                values[9, 7, 0] = np.float32(0.75)
            if index and mutation == "signedzero":
                values[0, 0, 0] = -0.0
            if not index and mutation == "subnormal":
                values[0, 0, 2] = 0.0
            if index and mutation == "swap":
                values = values[..., [1, 0, 2]].copy()
            if index and mutation == "flip":
                values = values[::-1].copy()
            path = tmp_path / f"transfer-{index}-{round_index}.exr"
            header: dict[str, Any] = {
                "compression": OpenEXR.ZIP_COMPRESSION,
                "comments": f"{index}-{round_index}",
            }
            if index and mutation == "window":
                header["displayWindow"] = (
                    np.array([1, 0], np.int32),
                    np.array([256, 255], np.int32),
                )
            OpenEXR.File(
                header, {name: np.ascontiguousarray(values[..., c]) for c, name in enumerate("RGB")}
            ).write(str(path))
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            paths[sha] = path
            output = next(o for o in recording["outputs"] if o["kind"] == "exported_map")
            output["blob"] = {"sha256": sha, "size_bytes": len(raw), "media_type": "image/x-exr"}
        manifests.append(manifest)
        environments.append(record["environment"])
        stores.append(sealed(manifest, record, paths))
    monkeypatch.setattr(ocio, "ocio_identities", lambda *args: (environments, environments))
    monkeypatch.setattr(
        replay, "recorded_request_environment_matches", ocio.recorded_request_environment_matches
    )
    if mutation == "envelope":
        # Independently accepted environments must still fail the comparison's own join.
        monkeypatch.setattr(replay, "recorded_request_environment_matches", lambda *args: True)
        monkeypatch.setattr(diagnostic, "recorded_request_environment_matches", lambda *args: True)
    store = Mock()
    store.entry.side_effect = lambda *args: next(
        (value for child in stores if (value := child.entry(*args)) is not None), None
    )
    store.load.side_effect = lambda *args: next(
        (value for child in stores if (value := child.load(*args)) is not None), None
    )

    def blob_path(sha: str) -> Path:
        for child in stores:
            try:
                return Path(child.blob_path(sha))
            except KeyError:
                pass
        raise KeyError(sha)

    store.blob_path.side_effect = blob_path
    return manifests, store


def test_exact_authored_transfers_and_fixed_same_code_relation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests, store = captures(tmp_path, monkeypatch)
    report = diagnostic.inspect_transfer(manifests[0], manifests[1], store)
    assert report["status"] == "measured"
    for experiment in report["experiments"]:
        assert experiment["recorder_version"] == "authored-" + experiment["state"]
        for row in experiment["rounds"]:
            assert row["direct_identity"]["samples"] == 196608
            assert row["direct_identity"]["different_samples"] == 0
            classes = row["direct_identity"]["authored_classes"]
            assert sum(sum(value["samples_rgb"]) for value in classes.values()) == 196608
    assert all(row["different_samples"] == 0 for row in report["shared_r_same_coordinate"])
    for row in report["normalization_same_code_different_channel_position"]:
        assert all(pair["different_samples"] == 0 for pair in row["pairs"].values())
        assert all(pair["different_samples"] == 0 for pair in row["against_authored_center_rgb"])
    assert report["general_readout_identity"] == report["channel_invariance"] == "not_established"
    store.entry.side_effect = lambda *args: None
    with pytest.raises(ValueError):
        diagnostic.inspect_transfer(manifests[0], manifests[1], store)


def test_changed_r_is_localized_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests, store = captures(tmp_path, monkeypatch, "value")
    report = diagnostic.inspect_transfer(manifests[0], manifests[1], store)
    for row in report["experiments"][1]["rounds"]:
        metrics = row["direct_identity"]
        assert metrics["different_samples"] == 1
        assert metrics["different_samples_rgb"] == [1, 0, 0]
        assert metrics["different_samples_by_row_rgb"][9] == [1, 0, 0]
        assert metrics["different_samples_by_column_rgb"][7] == [1, 0, 0]
    assert all(row["different_samples"] == 1 for row in report["shared_r_same_coordinate"])
    for row in report["normalization_same_code_different_channel_position"]:
        assert row["pairs"]["RG"]["different_samples"] == 1
        assert row["pairs"]["RB"]["different_samples"] == 1
        assert row["pairs"]["GB"]["different_samples"] == 0


@pytest.mark.parametrize(
    "mutation,index,category,channel",
    [("subnormal", 0, "subnormal", 2), ("signedzero", 1, "zero", 0)],
)
def test_native_edge_bits_remain_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    index: int,
    category: str,
    channel: int,
) -> None:
    manifests, store = captures(tmp_path, monkeypatch, mutation)
    report = diagnostic.inspect_transfer(manifests[0], manifests[1], store)
    for row in report["experiments"][index]["rounds"]:
        metrics = row["direct_identity"]
        assert metrics["different_samples"] == 1
        assert metrics["authored_classes"][category]["different_samples_rgb"] == [
            int(c == channel) for c in range(3)
        ]


@pytest.mark.parametrize("mutation,total", [("swap", 131072), ("flip", 196608)])
def test_channel_or_coordinate_changes_are_not_corrected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, total: int
) -> None:
    manifests, store = captures(tmp_path, monkeypatch, mutation)
    report = diagnostic.inspect_transfer(manifests[0], manifests[1], store)
    assert all(
        row["direct_identity"]["different_samples"] == total
        for row in report["experiments"][1]["rounds"]
    )


@pytest.mark.parametrize("mutation", ["envelope", "context", "receipt", "window"])
def test_invalid_evidence_or_cross_capture_context_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifests, store = captures(tmp_path, monkeypatch, mutation)
    if mutation in ("envelope", "context"):
        for state, manifest in zip(diagnostic.STATES, manifests, strict=True):
            assert admission.inspect_export(manifest, state, store)["status"] == "validated"
    with pytest.raises(ValueError):
        diagnostic.inspect_transfer(manifests[0], manifests[1], store)


@pytest.mark.parametrize("state", diagnostic.STATES)
def test_input_formula_is_not_replaced_by_a_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    authored = control.request(state, exports=True)
    original = control.authored_values
    monkeypatch.setattr(control, "authored_values", lambda value: np.zeros_like(original(value)))
    with pytest.raises(ValueError, match="formula"):
        diagnostic.input_pixels(authored, state)


def test_registry_drift_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifests, store = captures(tmp_path, monkeypatch)
    registry = Mock()
    registry.read_bytes.side_effect = [b"before", b"after"]
    monkeypatch.setattr(diagnostic, "registry_path", lambda: registry)
    with pytest.raises(ValueError, match="registry changed"):
        diagnostic.inspect_transfer(manifests[0], manifests[1], store)


def test_cli_keeps_details_private_and_preserves_prior_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifests, store = captures(tmp_path, monkeypatch, "value")
    source = [tmp_path / "calibration.json", tmp_path / "normalization.json"]
    for path, manifest in zip(source, manifests, strict=True):
        path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "diagnostic.json"
    monkeypatch.setattr(diagnostic, "locate", lambda: store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnostic",
            "--calibration-manifest",
            str(source[0]),
            "--normalization-manifest",
            str(source[1]),
            "--output",
            str(output),
        ],
    )
    assert diagnostic.main() == 0
    report = output.read_bytes()
    assert json.loads(capsys.readouterr().out) == {
        "status": "measured",
        "report_sha256": hashlib.sha256(report).hexdigest(),
    }
    assert diagnostic.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    failure = tmp_path / "diagnostic-failure.json"
    preserved = failure.read_bytes()
    assert json.loads(preserved)["stage"] == "destination"
    assert diagnostic.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    assert output.read_bytes() == report and failure.read_bytes() == preserved


def test_repository_output_is_rejected_before_store_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = REPO_ROOT / "tmp" / "scratch" / "transfer-forbidden.json"
    store = Mock(side_effect=AssertionError("must not load"))
    monkeypatch.setattr(diagnostic, "locate", store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnostic",
            "--calibration-manifest",
            "unused",
            "--normalization-manifest",
            "unused",
            "--output",
            str(output),
        ],
    )
    assert diagnostic.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    store.assert_not_called()
    assert not output.exists()
