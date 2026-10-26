"""Private RGB8/uniform baseline replay; an explicitly supplied binary, never an implicit build."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.export.encoders_tier0 import write_export
from tests.export.tier0 import export_spec
from tools.parity import ocio16_bitmap_replay as baseline
from tools.parity.envelope import ocio
from tools.parity.envelope.registry import current_envelope
from tools.parity.ocio16_bitmap_replay import (
    Candidate as Candidate,
)
from tools.parity.ocio16_bitmap_replay import (
    compare_bytes as compare_bytes,
)
from tools.parity.ocio16_bitmap_replay import (
    compare_produced as compare_produced,
)
from tools.parity.ocio16_bitmap_replay import (
    decoded_exact as decoded_exact,
)
from tools.parity.ocio16_bitmap_replay import (
    new_report as new_report,
)
from tools.parity.ocio16_bitmap_replay import (
    validate_receipt_context as validate_receipt_context,
)
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import recording_requests as rr


def candidates(work: Path) -> list[Candidate]:
    """Build every native input before any private-store access."""
    result = []
    for source in control.NATIVE_BASELINES:
        request_path = (
            rr.request_root(REPO_ROOT) / "tier0/api-probes" / f"{control.request_name(source)}.json"
        )
        authored = json.loads(request_path.read_text())
        plan = control.native_baseline(
            authored,
            source,
            configuration_sha256=PAINTER_OCIO_CONFIG_SHA256,
        )
        spec_dir = work / source / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec = export_spec(plan.manifest, "uzp_plane", spec_dir)
        create = authored["instruction_sequence"]["steps"][0]["args"]
        spec.update(
            template="default",
            mesh=str(plan.inputs[create["mesh"]]),
            normal_map_format=create["normal_map_format"],
            color_management="ocio",
            config_hash=PAINTER_OCIO_CONFIG_SHA256,
        )
        for export in plan.exports:
            output = work / source / f"output-{export.step}"
            config = export.config(output, ["uzp_plane"])
            result.append(
                Candidate(
                    source,
                    authored,
                    spec,
                    spec_dir,
                    config,
                    work / source / f"run-{export.step}",
                    output / f"uzp_plane_basecolor.{export.parameters['fileFormat']}",
                    f"uzp_plane/basecolor/step{export.step}",
                    export.step,
                )
            )
    return result


def replay(exe: Path, work: Path, report: dict[str, Any]) -> None:
    report["stage"] = "authored_inputs"
    planned = candidates(work)
    if len(planned) != 6:
        raise ValueError("native baseline candidate count")
    produced: list[tuple[Candidate, bytes]] = []
    report["stage"] = "native_export"
    for candidate in planned:
        report["attempted"] += 1
        result = write_export(
            exe, candidate.spec, candidate.spec_dir, candidate.config, candidate.run_dir
        )
        if "error" in result or len(result.get("written", [])) != 1:
            raise ValueError("native baseline export refused")
        written = result["written"][0]
        if written["relativePath"] != candidate.path.name or not candidate.path.is_file():
            raise ValueError("native baseline output identity")
        data = candidate.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != written["sha256"]:
            raise ValueError("native baseline output hash")
        produced.append((candidate, data))
        report["candidates"] += 1
    compare_produced(produced, report)


def test_candidates_public_contract(tmp_path: Path) -> None:
    planned = candidates(tmp_path)
    assert len(planned) == 6
    for candidate in planned:
        assert candidate.spec["color_management"] == "ocio"
        assert candidate.spec["config_hash"] == PAINTER_OCIO_CONFIG_SHA256
        assert candidate.spec["template"] == "default"
        assert candidate.config["exportParameters"][0]["parameters"]["dithering"] is False
    assert len({c.path for c in planned}) == 6
    assert [c.config["exportParameters"][0]["parameters"]["bitDepth"] for c in planned] == [
        "8",
        "16",
        "32f",
    ] * 2


def test_replay_finishes_candidates_before_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = new_report()
    calls = 0

    def fake_export(
        exe: Path, spec: dict[str, Any], spec_dir: Path, config: dict[str, Any], run_dir: Path
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        extension = config["exportParameters"][0]["parameters"]["fileFormat"]
        path = Path(config["exportPath"]) / f"uzp_plane_basecolor.{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"public-mock")
        return {
            "written": [
                {"relativePath": path.name, "sha256": hashlib.sha256(b"public-mock").hexdigest()}
            ]
        }

    def no_store() -> None:
        assert calls == report["candidates"] == 6
        return None

    monkeypatch.setattr(__name__ + ".write_export", fake_export)
    monkeypatch.setattr(baseline, "locate", no_store)
    with pytest.raises(ValueError, match="oracle unavailable"):
        replay(Path("never-executed"), tmp_path, report)
    assert report["attempted"] == 6
    assert report["comparisons"] == 0


def test_ocio16_native_baselines(tmp_path: Path) -> None:
    supplied = os.environ.get("UZP_OCIO16_EXPORT_TESTS_EXE")
    if not supplied:
        pytest.skip("set UZP_OCIO16_EXPORT_TESTS_EXE to an existing approved binary; no build here")
    report = new_report()
    failed = False
    try:
        path = ensure_outside_repository(
            Path(os.environ["LOCALAPPDATA"]) / "UzPainter" / "ocio16-native-baselines-private.json"
        )
        exe = Path(supplied)
        if not exe.is_file():
            raise ValueError("native baseline executable unavailable")
        report["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
        replay(exe, ensure_outside_repository(tmp_path), report)
    except Exception:
        failed = True
        report["status"] = "failed"
    try:
        path = ensure_outside_repository(
            Path(os.environ["LOCALAPPDATA"]) / "UzPainter" / "ocio16-native-baselines-private.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except Exception:
        failed = True
    if failed:
        pytest.fail(
            "OCIO baseline diagnostic failed; inspect private count-only report", pytrace=False
        )
    if report["comparisons"] != 12 or report["pixels_different"]:
        pytest.fail("OCIO baseline pixels differ; inspect private count-only report", pytrace=False)


@pytest.mark.parametrize(
    "other,equal",
    [
        (0.0, True),
        (-0.0, True),
        (1.0, False),
        (np.nextafter(0.0, 1.0), False),
        (float("nan"), False),
    ],
)
def test_decoded_exact_uses_numeric_equality(
    monkeypatch: pytest.MonkeyPatch,
    other: float,
    equal: bool,
) -> None:
    def fake_decode(data: bytes) -> SimpleNamespace:
        return SimpleNamespace(
            integer=False,
            bits=32,
            values=np.array([0.0 if data == b"left" else other], dtype=np.float64),
        )

    monkeypatch.setattr(baseline, "decode", fake_decode)
    assert decoded_exact(b"left", b"right") is equal


def test_different_png_headers_preserve_pixel_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = (REPO_ROOT / rr.fixture("srgb8-ramp")[1]).read_bytes()
    chunk = b"tEXt" + b"Comment\x00public synthetic header"
    different = (
        data[:-12]
        + struct.pack(">I", len(chunk) - 4)
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
        + data[-12:]
    )
    report = new_report()
    for _ in range(12):
        compare_bytes(data, different, report)
    assert report["encoded_equal"] == 0 and report["encoded_different"] == 12
    assert report["pixels_equal"] == 12 and report["pixels_different"] == 0
    exe = tmp_path / "mock.exe"
    exe.write_bytes(b"not executable")
    monkeypatch.setenv("UZP_OCIO16_EXPORT_TESTS_EXE", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def compared(exe: Path, work: Path, result: dict[str, Any]) -> None:
        result.update(report)

    monkeypatch.setattr(__name__ + ".replay", compared)
    test_ocio16_native_baselines(tmp_path)


def test_decoded_nan_matches_only_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        baseline,
        "decode",
        lambda data: SimpleNamespace(integer=False, bits=32, values=np.array([np.nan, np.inf])),
    )
    report = new_report()
    assert decoded_exact(b"left", b"right", report)
    assert report["decoded_non_finite_candidate"] == report["decoded_non_finite_reference"] == 2


def test_native_failure_report_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "mock.exe"
    exe.write_bytes(b"not executable")
    monkeypatch.setenv("UZP_OCIO16_EXPORT_TESTS_EXE", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def failure(exe: Path, work: Path, report: dict[str, Any]) -> None:
        report["attempted"] = 2
        raise RuntimeError("PRIVATE_SENTINEL_MUST_NOT_LEAK")

    monkeypatch.setattr(__name__ + ".replay", failure)
    with pytest.raises(pytest.fail.Exception) as caught:
        test_ocio16_native_baselines(tmp_path)
    assert "PRIVATE_SENTINEL" not in str(caught.value)
    raw = (tmp_path / "UzPainter/ocio16-native-baselines-private.json").read_text()
    assert "PRIVATE_SENTINEL" not in raw
    report = json.loads(raw)
    assert report["status"] == "failed" and report["attempted"] == 2


@pytest.fixture
def authored_receipt(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    authored = control.request("uniform")
    job = probe_job_from_manifest(authored)
    colour = {
        "mode": "ocio",
        "OCIO": "synthetic/resources/ocio/substance/config.ocio",
        "PAINTER_ACE_CONFIG": None,
    }
    environment = {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        "painter_build": deepcopy(current_envelope()["painter_build"]),
        "gpu_model": "synthetic",
        "driver_version": "synthetic",
        "os_build": "synthetic",
        "colour_configuration_sha256": "1" * 64,
        "recorder_version": "synthetic/1",
    }
    anchor = {**environment, "colour_configuration_sha256": "2" * 64}
    envelope = {
        **current_envelope(),
        "envelope_sha256": envelope_sha256(anchor),
        "equivalent_envelopes": [],
    }
    references = deepcopy([environment])
    monkeypatch.setattr(ocio, "ocio_identities", lambda *args, **kwargs: ([anchor], references))
    monkeypatch.setattr(baseline, "current_envelope", lambda: envelope)
    return authored, {
        "key": {
            "instruction_sequence_sha256": job.instruction_sequence_sha256,
            "inputs": job.input_hashes(),
            "painter_build": deepcopy(authored["software"]["painter"]),
            "project_settings": {"create": job.project_settings(), "colour_management": colour},
            "effective_defaults": {"colour_management": deepcopy(colour)},
        },
        "environment": environment,
    }


def test_receipt_accepts_exact_authored_context(
    authored_receipt: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    authored, record = authored_receipt
    assert envelope_sha256(record["environment"]) != current_envelope()["envelope_sha256"]
    validate_receipt_context(record, authored, Mock())


@pytest.mark.parametrize(
    "mutation",
    [
        "sequence",
        "inputs",
        "build",
        "create",
        "create_type",
        "colour",
        "defaults",
        "environment_missing",
        "environment_unknown",
        "environment_changed",
        "environment_build",
    ],
)
def test_receipt_rejects_other_context_before_comparison(
    authored_receipt: tuple[dict[str, Any], dict[str, Any]], mutation: str
) -> None:
    authored, record = authored_receipt
    key = record["key"]
    if mutation == "sequence":
        key["instruction_sequence_sha256"] = "0" * 64
    elif mutation == "inputs":
        key["inputs"] = []
    elif mutation == "build":
        key["painter_build"]["build_id"] = "synthetic-other"
    elif mutation in ("create", "create_type"):
        key["project_settings"]["create"]["default_texture_resolution"] = (
            128 if mutation == "create" else 256.0
        )
    elif mutation == "colour":
        key["project_settings"]["colour_management"]["OCIO"] = "other/config.ocio"
    elif mutation == "defaults":
        key["effective_defaults"]["colour_management"]["mode"] = "legacy"
    elif mutation == "environment_missing":
        del record["environment"]
    elif mutation == "environment_unknown":
        record["environment"]["gpu_model"] = "unknown"
    elif mutation == "environment_changed":
        record["environment"]["colour_configuration_sha256"] = "2" * 64
    elif mutation == "environment_build":
        record["environment"]["painter_build"] = "synthetic-other"
    with pytest.raises(ValueError, match="oracle receipt"):
        validate_receipt_context(record, authored, Mock())


@pytest.mark.parametrize(
    "mutation", ["missing_anchor", "missing_reference", "split", "foreign_host", "unreadable"]
)
def test_receipt_refuses_unproved_ocio_reference(
    authored_receipt: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    authored, record = authored_receipt
    reference = deepcopy(record["environment"])
    anchor = {**reference, "colour_configuration_sha256": "2" * 64}
    anchors, references = [anchor], [reference]
    if mutation == "missing_anchor":
        anchors = []
    elif mutation == "missing_reference":
        references = []
    elif mutation == "split":
        references.append({**reference, "colour_configuration_sha256": "3" * 64})
    elif mutation == "foreign_host":
        anchor["gpu_model"] = "other"

    def identities(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if mutation == "unreadable":
            raise RecorderError("synthetic unreadable reference")
        return anchors, references

    monkeypatch.setattr(ocio, "ocio_identities", identities)
    with pytest.raises(ValueError):
        validate_receipt_context(record, authored, Mock())


@pytest.mark.parametrize("mutation", ["missing", "kind", "sha256", "size_bytes", "size_type"])
def test_unadmitted_receipt_is_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    candidate = candidates(tmp_path)[0]
    manifest = deepcopy(candidate.authored)
    ref = {
        "record_id": GOLDEN_RECORD_ID,
        "kind": "private_oracle_record",
        "sha256": "1" * 64,
        "size_bytes": 1,
    }
    manifest["private_records"] = [ref]
    directory = tmp_path / "tier0/api-probes"
    directory.mkdir(parents=True)
    (directory / f"{control.request_name(candidate.source)}.json").write_text(json.dumps(manifest))
    store = Mock()
    entry = SimpleNamespace(kind=ref["kind"], sha256=ref["sha256"], size_bytes=1)
    if mutation == "missing":
        store.entry.return_value = None
    else:
        setattr(
            entry,
            "size_bytes" if mutation == "size_type" else mutation,
            True if mutation == "size_type" else "different",
        )
        store.entry.return_value = entry
    monkeypatch.setattr(baseline, "locate", lambda: store)
    monkeypatch.setattr(baseline, "manifest_root", lambda _: tmp_path)
    report = new_report()
    with pytest.raises(ValueError, match="not admitted"):
        compare_produced([(candidate, b"authored-native-output")], report)
    store.load.assert_not_called()
    assert report["comparisons"] == 0
