"""Private RGB8/uniform baseline replay; an explicitly supplied binary, never an implicit build."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.export.encoders_tier0 import write_export
from tests.export.tier0 import export_spec
from tools.parity.envelope import ocio
from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.recorder.environment import ENVELOPE_FIELDS, envelope_sha256
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository, slug
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, record_problems
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import recording_requests as rr


@dataclass(frozen=True)
class Candidate:
    source: str
    authored: dict[str, Any]
    spec: dict[str, Any]
    spec_dir: Path
    config: dict[str, Any]
    run_dir: Path
    path: Path
    output_id: str
    step: int


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


def decoded_exact(left: bytes, right: bytes, report: dict[str, Any] | None = None) -> bool:
    a, b = decode(left), decode(right)
    if report is not None:
        report["decoded_non_finite_candidate"] += int(np.count_nonzero(~np.isfinite(a.values)))
        report["decoded_non_finite_reference"] += int(np.count_nonzero(~np.isfinite(b.values)))
    return (
        a.integer == b.integer
        and a.bits == b.bits
        and a.values.shape == b.values.shape
        and a.values.dtype == b.values.dtype
        and np.array_equal(a.values, b.values, equal_nan=True)
    )


def compare_bytes(data: bytes, expected: bytes, report: dict[str, Any]) -> None:
    report["comparisons"] += 1
    if hashlib.sha256(data).digest() == hashlib.sha256(expected).digest():
        report["encoded_equal"] += 1
        report["pixels_equal"] += 1
    else:
        report["encoded_different"] += 1
        report["pixels_equal" if decoded_exact(data, expected, report) else "pixels_different"] += 1


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


def require_admitted_refs(store: OracleStore, manifest: dict[str, Any]) -> None:
    build = manifest["software"]["painter"]["build_id"]
    for ref in manifest["private_records"]:
        entry = store.entry(build, manifest["golden_id"], ref["record_id"])
        if entry is None or canonical_json(
            [entry.kind, entry.sha256, entry.size_bytes]
        ) != canonical_json([ref["kind"], ref["sha256"], ref["size_bytes"]]):
            raise ValueError("oracle reference not admitted")


def validate_receipt_context(
    record: dict[str, Any], authored: dict[str, Any], store: OracleStore
) -> None:
    job = probe_job_from_manifest(authored)
    key = record["key"]
    settings = key["project_settings"]
    if (
        key["instruction_sequence_sha256"] != job.instruction_sequence_sha256
        or canonical_json(key["inputs"]) != canonical_json(job.input_hashes())
        or canonical_json(key["painter_build"]) != canonical_json(authored["software"]["painter"])
        or set(settings) != {"create", "colour_management"}
        or canonical_json(settings["create"]) != canonical_json(job.project_settings())
    ):
        raise ValueError("oracle receipt recipe differs")
    colour = settings["colour_management"]
    if (
        set(colour) != {"mode", "OCIO", "PAINTER_ACE_CONFIG"}
        or colour["mode"] != "ocio"
        or type(colour["OCIO"]) is not str
        or not colour["OCIO"].replace("\\", "/").endswith("resources/ocio/substance/config.ocio")
        or colour["PAINTER_ACE_CONFIG"] is not None
        or canonical_json(key["effective_defaults"].get("colour_management"))
        != canonical_json(colour)
    ):
        raise ValueError("oracle receipt colour context differs")
    environment = record.get("environment")
    envelope = current_envelope()
    if (
        type(environment) is not dict
        or environment.get("basis") != "recorded"
        or any(environment.get(field) in (None, "", "unknown") for field in ENVELOPE_FIELDS)
        or canonical_json(environment["painter_build"]) != canonical_json(envelope["painter_build"])
        or not recorded_request_environment_matches(environment, authored, envelope, store)
    ):
        raise ValueError("oracle receipt envelope differs")


def compare_produced(produced: list[tuple[Candidate, bytes]], report: dict[str, Any]) -> None:
    """Compare completed authored candidates against the same admitted export identities."""
    # Reference bytes cannot reach setup or any native invocation.
    report["stage"] = "oracle_comparison"
    store = locate()
    if store is None:
        raise ValueError("oracle unavailable")
    base = manifest_root(current_envelope()) / "tier0/api-probes"
    loaded: dict[str, tuple[dict[str, Any], list[dict[str, Any]], str]] = {}
    for candidate, data in produced:
        if candidate.source not in loaded:
            manifest = json.loads(
                (base / f"{control.request_name(candidate.source)}.json").read_text()
            )
            if any(
                canonical_json(manifest[k]) != canonical_json(candidate.authored[k])
                for k in (
                    "golden_id",
                    "inputs",
                    "instruction_sequence",
                    "applied_settings",
                    "software",
                )
            ):
                raise ValueError("oracle authored context differs")
            refs = manifest["private_records"]
            records = [r for r in refs if r["kind"] == "private_oracle_record"]
            if len(records) != 1 or not records[0]["record_id"].endswith(GOLDEN_RECORD_ID):
                raise ValueError("oracle record identity")
            require_admitted_refs(store, manifest)
            raw = load_oracle(store, records[0])
            if raw is None:
                raise ValueError("oracle record unavailable")
            record = json.loads(raw)
            if record_problems(record) or record["golden_id"] != manifest["golden_id"]:
                raise ValueError("oracle record schema")
            validate_receipt_context(record, candidate.authored, store)
            if len(record["recordings"]) != 2 or [r["condition"] for r in record["recordings"]] != [
                "same_session",
                "after_save_reopen",
            ]:
                raise ValueError("oracle recording conditions")
            loaded[candidate.source] = (
                record,
                refs,
                records[0]["record_id"][: -len(GOLDEN_RECORD_ID)],
            )
        record, refs, prefix = loaded[candidate.source]
        for recording in record["recordings"]:
            matches = [
                o
                for o in recording["outputs"]
                if o["kind"] == "exported_map" and o["output_id"] == candidate.output_id
            ]
            if len(matches) != 1:
                raise ValueError("oracle output identity")
            output = matches[0]
            parameters = candidate.config["exportParameters"][0]["parameters"]
            settings = output["export_settings"]
            if (
                any(
                    canonical_json(settings.get(k)) != canonical_json(v)
                    for k, v in parameters.items()
                )
                or canonical_json(settings.get("step")) != canonical_json(candidate.step)
                or settings.get("map_type") != "documentMap"
                or settings.get("map_channels") != "RGB"
                or output["texture_set"] != "uzp_plane"
            ):
                raise ValueError("oracle export settings differ")
            key = prefix + slug(recording["recording_id"]) + "-" + slug(candidate.output_id)
            references = [r for r in refs if r["record_id"] == key]
            if len(references) != 1 or any(
                references[0][k] != output["blob"][k] for k in ("sha256", "size_bytes")
            ):
                raise ValueError("oracle reference mismatch")
            expected = load_oracle(store, references[0])
            if expected is None:
                raise ValueError("oracle output unavailable")
            compare_bytes(data, expected, report)
    report["stage"] = "complete"
    report["status"] = "equal" if report["pixels_different"] == 0 else "different"


def new_report() -> dict[str, Any]:
    return {
        "schema": "ocio16-native-baselines/1",
        "status": "incomplete",
        "stage": "setup",
        "attempted": 0,
        "candidates": 0,
        "comparisons": 0,
        "encoded_equal": 0,
        "encoded_different": 0,
        "pixels_equal": 0,
        "pixels_different": 0,
        "decoded_non_finite_candidate": 0,
        "decoded_non_finite_reference": 0,
    }


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
    monkeypatch.setattr(__name__ + ".locate", no_store)
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

    monkeypatch.setattr(__name__ + ".decode", fake_decode)
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
        __name__ + ".decode",
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
    monkeypatch.setattr(__name__ + ".current_envelope", lambda: envelope)
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
    monkeypatch.setattr(__name__ + ".locate", lambda: store)
    monkeypatch.setattr(__name__ + ".manifest_root", lambda _: tmp_path)
    report = new_report()
    with pytest.raises(ValueError, match="not admitted"):
        compare_produced([(candidate, b"authored-native-output")], report)
    store.load.assert_not_called()
    assert report["comparisons"] == 0
