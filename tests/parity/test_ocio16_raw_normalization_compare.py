"""Two authored export captures; no real oracle access or Painter process."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import numpy as np
import OpenEXR
import pytest

from tests.parity.test_ocio16_raw_export_admission import authored_export, sealed
from tools.parity import ocio16_bitmap_replay as replay
from tools.parity import ocio16_raw_export_admission as admission
from tools.parity import ocio16_raw_normalization_compare as comparison
from tools.parity.envelope import ocio
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str = "equal"
) -> tuple[list[dict[str, Any]], Mock]:
    manifests, stores, records = [], [], []
    for index, state in enumerate(comparison.STATES):
        manifest, record, _ = authored_export(tmp_path, monkeypatch, state)
        # Separate projects, resource contexts and sessions must remain independently valid.
        encoded = json.dumps(record)
        for marker in ("public-project", "public-synthetic", "public-session"):
            encoded = encoded.replace(marker, marker + state)
        record = json.loads(encoded)
        if index and mutation in ("driver_version", "recorder_version"):
            record["environment"][mutation] = "different"
        if index and mutation == "context":
            # Extra recorded template context is accepted individually, but cannot be ignored.
            for recording in record["recordings"]:
                template = next(o for o in recording["outputs"] if o["kind"] == "template_capture")
                template["values"]["context_marker"] = "different"
        if index and mutation == "receipt":
            record["key"]["instruction_sequence_sha256"] = "0" * 64
        paths = {}
        for r, recording in enumerate(record["recordings"]):
            values = np.zeros((256, 256, 3), dtype=np.float32)
            values[0, 0, 2] = np.nextafter(np.float32(0), np.float32(1))
            values[100, 150, 1] = np.float32(0.75)
            if index and mutation == "value":
                values[25, 23, 0] = np.float32(0.5)
            if index and mutation == "subnormal":
                values[0, 0, 2] = 0
            if index and mutation == "signedzero":
                values[0, 0, 0] = -0.0
            if index and mutation == "flip":
                values = values[::-1].copy()
            header: dict[str, Any] = {
                "compression": OpenEXR.ZIP_COMPRESSION,
                "comments": f"{index}-{r}",
            }
            if index and mutation == "window":
                header["displayWindow"] = (
                    np.array([1, 0], np.int32),
                    np.array([256, 255], np.int32),
                )
            path = tmp_path / f"paired-{index}-{r}.exr"
            OpenEXR.File(
                header, {name: np.ascontiguousarray(values[..., c]) for c, name in enumerate("RGB")}
            ).write(str(path))
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            paths[sha] = path
            output = next(o for o in recording["outputs"] if o["kind"] == "exported_map")
            output["blob"] = {"sha256": sha, "size_bytes": len(raw), "media_type": "image/x-exr"}
        manifests.append(manifest)
        records.append(record)
        stores.append(sealed(manifest, record, paths))
    environments = [deepcopy(record["environment"]) for record in records]
    monkeypatch.setattr(ocio, "ocio_identities", lambda *args: (environments, environments))
    monkeypatch.setattr(
        replay, "recorded_request_environment_matches", ocio.recorded_request_environment_matches
    )
    if mutation == "driver_version":
        # Model two independently accepted environments: the pair must still reject their join.
        monkeypatch.setattr(replay, "recorded_request_environment_matches", lambda *args: True)
        monkeypatch.setattr(comparison, "recorded_request_environment_matches", lambda *args: True)
    store = Mock()
    store.entry.side_effect = lambda build, golden, identity: next(
        (found for child in stores if (found := child.entry(build, golden, identity)) is not None),
        None,
    )
    store.load.side_effect = lambda sha, size: next(
        (found for child in stores if (found := child.load(sha, size)) is not None), None
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


def test_equal_observable_outputs_do_not_claim_internal_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests, store = pair(tmp_path, monkeypatch)
    report = comparison.compare(manifests[0], manifests[1], store)
    assert report["status"] == "measured" and report["comparison"] == "equal"
    assert all(
        row["samples"] == 196608 and row["different_samples"] == 0 for row in report["rounds"]
    )
    assert (
        report["internal_normalization"]
        == report["readout_identity"]
        == report["parity"]
        == "not_established"
    )
    assert report["color_channel_flag"] == "unobserved"
    assert (
        report["experiments"][0]["admission"]["map_sha256"]
        != report["experiments"][1]["admission"]["map_sha256"]
    )
    assert report["common_context_sha256"] == comparison.digest(report["common_context"])
    store.entry.side_effect = lambda *_: None
    with pytest.raises(ValueError):
        comparison.compare(manifests[0], manifests[1], store)


@pytest.mark.parametrize("mutation,channel", [("value", 0), ("signedzero", 0), ("subnormal", 2)])
def test_one_native_bit_difference_is_a_valid_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, channel: int
) -> None:
    manifests, store = pair(tmp_path, monkeypatch, mutation)
    report = comparison.compare(manifests[0], manifests[1], store)
    assert report["comparison"] == "different"
    for row in report["rounds"]:
        assert row["different_samples"] == 1
        assert row["different_samples_rgb"] == [int(c == channel) for c in range(3)]


def test_recorder_versions_are_preserved_as_provenance_not_equated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests, store = pair(tmp_path, monkeypatch, "recorder_version")
    report = comparison.compare(manifests[0], manifests[1], store)
    assert report["comparison"] == "equal"
    assert [row["recorder_version"] for row in report["experiments"]] == [
        "synthetic/1",
        "different",
    ]
    assert "recorder_version" not in report["common_context"]["environment"]
    assert report["readout_identity"] == report["internal_normalization"] == "not_established"


@pytest.mark.parametrize("mutation", ["driver_version", "context", "receipt", "window"])
def test_noncomparable_captures_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifests, store = pair(tmp_path, monkeypatch, mutation)
    if mutation in ("driver_version", "context"):
        for state, manifest in zip(comparison.STATES, manifests, strict=True):
            assert admission.inspect_export(manifest, state, store)["status"] == "validated"
    with pytest.raises(ValueError):
        comparison.compare(manifests[0], manifests[1], store)


def test_flip_is_not_repaired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifests, store = pair(tmp_path, monkeypatch, "flip")
    report = comparison.compare(manifests[0], manifests[1], store)
    assert report["comparison"] == "different"
    assert all(row["different_samples"] == 4 for row in report["rounds"])


def test_registry_change_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifests, store = pair(tmp_path, monkeypatch)
    registry = Mock()
    registry.read_bytes.side_effect = [b"original", b"changed"]
    monkeypatch.setattr(comparison, "registry_path", lambda: registry)
    with pytest.raises(ValueError, match="registry changed"):
        comparison.compare(manifests[0], manifests[1], store)


def test_recipe_difference_refuses_even_when_authored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests, store = pair(tmp_path, monkeypatch)
    original = comparison.common_recipe

    def altered(authored: dict[str, Any], state: str) -> dict[str, Any]:
        recipe = original(authored, state)
        if state == comparison.STATES[1]:
            recipe["applied_settings"] = []
        return recipe

    monkeypatch.setattr(comparison, "common_recipe", altered)
    with pytest.raises(ValueError, match="contexts differ"):
        comparison.compare(manifests[0], manifests[1], store)


@pytest.mark.parametrize("state", comparison.STATES)
def test_input_formula_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    authored = control.request(state, exports=True)
    original = control.authored_values
    monkeypatch.setattr(control, "authored_values", lambda s: np.zeros_like(original(s)))
    with pytest.raises(ValueError, match="formula differs"):
        comparison.authored_input(authored, state)


def test_cli_valid_difference_and_failure_evidence_are_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifests, store = pair(tmp_path, monkeypatch, "value")
    files = [tmp_path / "float.json", tmp_path / "png.json"]
    for path, manifest in zip(files, manifests, strict=True):
        path.write_text(json.dumps(manifest), encoding="utf-8")
    destination = tmp_path / "comparison.json"
    monkeypatch.setattr(comparison, "locate", lambda: store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--float-manifest",
            str(files[0]),
            "--png-manifest",
            str(files[1]),
            "--output",
            str(destination),
        ],
    )
    assert comparison.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {"status", "comparison", "report_sha256"}
    assert summary["comparison"] == "different"
    original = destination.read_bytes()
    assert summary["report_sha256"] == hashlib.sha256(original).hexdigest()
    assert comparison.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    failure = tmp_path / "comparison-failure.json"
    evidence = failure.read_bytes()
    assert "traceback" in json.loads(evidence)
    assert comparison.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    assert destination.read_bytes() == original and failure.read_bytes() == evidence


def test_cli_repository_destination_refuses_before_loading_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = REPO_ROOT / "tmp" / "scratch" / "paired-forbidden.json"
    store = Mock(side_effect=AssertionError("must not load"))
    monkeypatch.setattr(comparison, "locate", store)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--float-manifest",
            "unused",
            "--png-manifest",
            "unused",
            "--output",
            str(destination),
        ],
    )
    assert comparison.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    store.assert_not_called()
    assert not destination.exists()
