"""Fixed-coordinate measurements over authored EXRs and fully validated synthetic receipts."""

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
from tools.parity import ocio16_raw_identity as identity
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str = "equal"
) -> tuple[dict[str, Any], Mock]:
    manifest, record, _ = authored_export(tmp_path, monkeypatch, identity.STATE)
    paths = {}
    for index, recording in enumerate(record["recordings"]):
        values = control.authored_values(identity.STATE).copy()
        header: dict[str, Any] = {"compression": OpenEXR.ZIP_COMPRESSION, "comments": str(index)}
        if mutation == "subnormal":
            values[0, 0, 2] = 0.0
        elif mutation == "signedzero":
            values[0, 0, 0] = -0.0
        elif mutation == "value":
            values[19, 23, 1] = np.float32(0.75)
        elif mutation == "flip":
            values = values[::-1].copy()
        elif mutation in ("dataWindow", "displayWindow"):
            header[mutation] = (
                np.array([1, 0], dtype=np.int32),
                np.array([256, 255], dtype=np.int32),
            )
        path = tmp_path / f"identity-{index}.exr"
        OpenEXR.File(
            header, {name: np.ascontiguousarray(values[..., c]) for c, name in enumerate("RGB")}
        ).write(str(path))
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        paths[sha] = path
        output = next(o for o in recording["outputs"] if o["kind"] == "exported_map")
        output["blob"] = {"sha256": sha, "size_bytes": len(data), "media_type": "image/x-exr"}
    if mutation == "receipt":
        record["key"]["instruction_sequence_sha256"] = "0" * 64
    return manifest, sealed(manifest, record, paths)


def test_equal_pixels_with_distinct_encoded_bytes_and_fresh_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, store = experiment(tmp_path, monkeypatch)
    report = identity.inspect_identity(manifest, store)
    assert report["status"] == "measured" and report["comparison"] == "equal"
    assert len({r["map_sha256"] for r in report["rounds"]}) == 2
    assert all(r["samples"] == 196608 and r["different_samples"] == 0 for r in report["rounds"])
    assert report["decoder"]["version"]
    assert report["general_readout_identity"] == report["parity"] == "not_established"
    assert report["negative_zero_input_coverage"] is False
    store.entry.side_effect = lambda *_: None
    with pytest.raises(ValueError):
        identity.inspect_identity(manifest, store)


@pytest.mark.parametrize("mutation,channel", [("subnormal", 2), ("signedzero", 0), ("value", 1)])
def test_one_changed_native_sample_is_a_valid_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, channel: int
) -> None:
    manifest, store = experiment(tmp_path, monkeypatch, mutation)
    report = identity.inspect_identity(manifest, store)
    assert report["status"] == "measured" and report["comparison"] == "different"
    for row in report["rounds"]:
        assert row["different_samples"] == 1
        assert row["different_samples_rgb"] == [int(c == channel) for c in range(3)]


def test_orientation_is_not_searched_or_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, store = experiment(tmp_path, monkeypatch, "flip")
    report = identity.inspect_identity(manifest, store)
    assert report["comparison"] == "different"
    assert all(row["different_samples"] == 196608 for row in report["rounds"])


@pytest.mark.parametrize("mutation", ["dataWindow", "displayWindow", "receipt"])
def test_invalid_domain_or_receipt_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifest, store = experiment(tmp_path, monkeypatch, mutation)
    with pytest.raises(ValueError):
        identity.inspect_identity(manifest, store)


def test_authored_formula_mismatch_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, store = experiment(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "authored_values", lambda _: np.zeros((256, 256, 3), np.float32))
    with pytest.raises(ValueError, match="formula"):
        identity.inspect_identity(manifest, store)


@pytest.mark.parametrize("mutation", ["equal", "value"])
def test_cli_writes_private_report_once_and_stdout_has_no_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    manifest, store = experiment(tmp_path, monkeypatch, mutation)
    source, destination = tmp_path / "manifest.json", tmp_path / "report.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(identity, "locate", lambda: store)
    monkeypatch.setattr(
        sys, "argv", ["identity", "--manifest", str(source), "--output", str(destination)]
    )
    assert identity.main() == 0
    stdout = json.loads(capsys.readouterr().out)
    assert set(stdout) == {"status", "comparison", "report_sha256"}
    assert stdout["comparison"] == ("equal" if mutation == "equal" else "different")
    original = destination.read_bytes()
    assert stdout["report_sha256"] == hashlib.sha256(original).hexdigest()
    assert identity.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    assert destination.read_bytes() == original


def test_failure_evidence_is_private_and_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "result.json"
    monkeypatch.setattr(identity, "locate", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["identity", "--manifest", "unused", "--output", str(destination)]
    )
    assert identity.main() == 2
    summary = json.loads(capsys.readouterr().out)
    failure = tmp_path / "result-failure.json"
    original = failure.read_bytes()
    assert summary == {"status": "refused", "report_sha256": hashlib.sha256(original).hexdigest()}
    evidence = json.loads(original)
    assert evidence["stage"] == "store" and "store unavailable" in evidence["traceback"]
    assert not destination.exists()
    assert identity.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    assert failure.read_bytes() == original


def test_repository_destination_refuses_before_store_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forbidden = REPO_ROOT / "tmp" / "scratch" / "identity-forbidden.json"
    store = Mock(side_effect=AssertionError("must not access store"))
    monkeypatch.setattr(identity, "locate", store)
    monkeypatch.setattr(
        sys, "argv", ["identity", "--manifest", "unused", "--output", str(forbidden)]
    )
    assert identity.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused"}
    store.assert_not_called()
    assert not forbidden.exists()
    assert not forbidden.with_name("identity-forbidden-failure.json").exists()
