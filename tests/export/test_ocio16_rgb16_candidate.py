"""Test-only RGB16 hypothesis; nine authored candidates, no fit or production-domain change."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.evaluator.test_compositor_tile_dag import TEMPLATES_DIR
from tests.export import test_ocio16_bitmap_controls as baseline
from tests.export.tier0 import export_spec
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import recording_requests as rr

MODEL = control.RGB16_CANDIDATE_MODEL
OBSERVED = {
    "source_bits": 16,
    "source_channels": 3,
    "source_width": 256,
    "source_height": 256,
    "srgb_decode": True,
}
OUTSIDE_DOMAIN = (
    "resolution",
    "mesh_missing",
    "mesh_partial_uv",
    "hidden",
    "opacity",
    "blend",
    "second_hidden_fill",
    "group",
    "mask",
    "content_effect",
    "inactive_source",
    "inactive_basecolor",
    "projection_mode",
    "filtering",
    "wrapping",
    "scale",
    "rotation",
    "offset",
    "padding",
    "dithering",
    "resize",
    "rgb_order",
    "rgb_duplicate",
    "document_format",
)


def candidates(work: Path) -> list[baseline.Candidate]:
    planned = []
    for source in control.RGB16_CANDIDATES:
        request_path = (
            rr.request_root(REPO_ROOT) / "tier0/api-probes" / f"{control.request_name(source)}.json"
        )
        authored = json.loads(request_path.read_text(encoding="utf-8"))
        plan = control.native_rgb16_candidate(
            authored, source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
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
            planned.append(
                baseline.Candidate(
                    source,
                    authored,
                    spec,
                    spec_dir,
                    export.config(output, ["uzp_plane"]),
                    work / source / f"run-{export.step}",
                    output / f"uzp_plane_basecolor.{export.parameters['fileFormat']}",
                    f"uzp_plane/basecolor/step{export.step}",
                    export.step,
                )
            )
    return planned


def write_candidate(exe: Path, candidate: baseline.Candidate) -> dict[str, Any]:
    ensure_outside_repository(candidate.run_dir)
    candidate.run_dir.mkdir(parents=True, exist_ok=True)
    spec = candidate.spec_dir / "spec.json"
    config = candidate.run_dir / "config.json"
    spec.write_text(json.dumps(candidate.spec), encoding="utf-8")
    config.write_text(json.dumps(candidate.config), encoding="utf-8")

    def retain(stdout: str | bytes | None, stderr: str | bytes | None) -> None:
        for name, text in (("stdout", stdout), ("stderr", stderr)):
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            (candidate.run_dir / f"native.{name}.txt").write_text(text or "", encoding="utf-8")

    try:
        process = subprocess.run(
            [str(exe), "ocio16-input-candidate", str(TEMPLATES_DIR), str(spec), str(config)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        retain(error.stdout, error.stderr)
        raise ValueError("RGB16 candidate timed out") from None
    retain(process.stdout, process.stderr)
    if process.returncode != 0:
        raise ValueError("RGB16 candidate process failed")
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise ValueError("RGB16 candidate report shape")
    return value


def checked_output(candidate: baseline.Candidate, result: dict[str, Any]) -> tuple[bytes, int]:
    if result.get("model") != MODEL or result.get("non_conformant") is not True:
        raise ValueError("RGB16 candidate model differs")
    if "error" in result or len(result.get("written", [])) != 1:
        raise ValueError("RGB16 candidate export refused")
    observed = result.get("observed")
    if not isinstance(observed, dict) or set(observed) != {*OBSERVED, "bitmap_fetches"}:
        raise ValueError("RGB16 observed report shape")
    if any(type(observed[k]) is not type(v) or observed[k] != v for k, v in OBSERVED.items()):
        raise ValueError("RGB16 source domain differs")
    fetches = observed["bitmap_fetches"]
    if type(fetches) is not int or fetches <= 0:
        raise ValueError("RGB16 bitmap was not fetched")
    written = result["written"][0]
    if written["relativePath"] != candidate.path.name or not candidate.path.is_file():
        raise ValueError("RGB16 output identity differs")
    data = candidate.path.read_bytes()
    if written["sha256"] != hashlib.sha256(data).hexdigest():
        raise ValueError("RGB16 output hash differs")
    return data, fetches


def replay(exe: Path, work: Path, report: dict[str, Any]) -> None:
    report["stage"] = "authored_inputs"
    planned = candidates(work)
    if len(planned) != 9 or len({c.path for c in planned}) != 9:
        raise ValueError("RGB16 candidate matrix differs")
    produced = []
    report["stage"] = "native_export"
    for candidate in planned:
        report["attempted"] += 1
        result = write_candidate(exe, candidate)
        report["returned"] += 1
        data, fetches = checked_output(candidate, result)
        produced.append((candidate, data))
        report["candidates"] += 1
        report["bitmap_fetches"] += fetches
    # Shared receipt/configuration checks and exact decoded-pixel comparator, after all writes.
    baseline.compare_produced(produced, report)
    if report["comparisons"] != 18:
        raise ValueError("RGB16 comparison matrix incomplete")


def new_report() -> dict[str, Any]:
    return {
        **baseline.new_report(),
        "schema": "ocio16-rgb16-candidate/1",
        "model": MODEL,
        "non_conformant": True,
        "returned": 0,
        "bitmap_fetches": 0,
    }


def outside_domain(candidate: baseline.Candidate, mutation: str) -> None:
    """Change public authored inputs only; exercise parsed fields of the native test hook."""
    spec, config = candidate.spec, candidate.config
    layer = spec["layers"][0]
    projection = layer["projection"]
    parameters = config["exportParameters"][0]["parameters"]
    channels = config["exportPresets"][0]["maps"][0]["channels"]
    if mutation == "resolution":
        spec["resolution"] = [128, 256]
    elif mutation == "mesh_missing":
        del spec["mesh"]
    elif mutation == "mesh_partial_uv":
        original = Path(spec["mesh"]).read_text(encoding="utf-8")
        assert "vt 1.0 1.0" in original
        mesh = candidate.spec_dir / "partial-uv.obj"
        mesh.write_text(original.replace("vt 1.0", "vt 0.5"), encoding="utf-8")
        spec["mesh"] = str(mesh)
    elif mutation == "hidden":
        layer["visible"] = False
    elif mutation == "opacity":
        layer["blending"]["BaseColor"]["opacity"] = 0.5
    elif mutation == "blend":
        layer["blending"]["BaseColor"]["mode"] = "Multiply"
    elif mutation == "second_hidden_fill":
        extra = deepcopy(layer)
        extra.update(uid=999, visible=False)
        spec["layers"].append(extra)
    elif mutation == "group":
        spec["layers"] = [{"kind": "group", "uid": 999, "children": [layer]}]
    elif mutation == "mask":
        layer["mask"] = {"background": "White", "effects": []}
    elif mutation == "content_effect":
        layer["effects"] = [{"kind": "fill", "uid": 999, "sources": {}}]
    elif mutation == "inactive_source":
        layer["sources"]["Roughness"] = deepcopy(layer["sources"]["BaseColor"])
        layer["active_channels"] = ["BaseColor"]
    elif mutation == "inactive_basecolor":
        layer["active_channels"] = []
    elif mutation in ("projection_mode", "filtering", "wrapping", "scale", "rotation", "offset"):
        key, value = {
            "projection_mode": ("mode", "Triplanar"),
            "filtering": ("filtering_mode", "BilinearHQ"),
            "wrapping": ("uv_wrapping_mode", "RepeatNone"),
            "scale": ("scale", [2.0, 1.0]),
            "rotation": ("rotation", 45.0),
            "offset": ("offset", [0.25, 0.0]),
        }[mutation]
        projection[key] = value
    elif mutation == "padding":
        parameters["paddingAlgorithm"] = "infinite"
    elif mutation == "dithering":
        parameters["dithering"] = True
    elif mutation == "resize":
        parameters["sizeLog2"] = 7
    elif mutation == "rgb_order":
        channels[0]["srcChannel"], channels[1]["srcChannel"] = "G", "R"
    elif mutation == "rgb_duplicate":
        channels[1]["srcChannel"] = "R"
    elif mutation == "document_format":
        next(c for c in spec["channels"] if c["type"] == "BaseColor")["format"] = "RGB16"
    else:
        raise ValueError("unknown RGB16 domain mutation")


@pytest.mark.parametrize("mutation", OUTSIDE_DOMAIN)
def test_ocio16_rgb16_native_refuses_outside_domain(tmp_path: Path, mutation: str) -> None:
    supplied = os.environ.get("UZP_OCIO16_EXPORT_TESTS_EXE")
    if not supplied:
        pytest.skip("set UZP_OCIO16_EXPORT_TESTS_EXE to an approved binary; no build here")
    exe = Path(supplied)
    assert exe.is_file(), "RGB16 executable unavailable"
    candidate = candidates(ensure_outside_repository(tmp_path))[0]
    outside_domain(candidate, mutation)
    result = write_candidate(exe, candidate)
    assert result.get("model") == MODEL and result.get("non_conformant") is True
    assert type(result.get("error")) is str and result["error"]
    assert "written" not in result or result["written"] == []
    assert not candidate.path.exists()
    assert not candidate.path.parent.exists() or not any(candidate.path.parent.rglob("*"))


def test_ocio16_rgb16_diagnostic(tmp_path: Path) -> None:
    supplied = os.environ.get("UZP_OCIO16_EXPORT_TESTS_EXE")
    if not supplied:
        pytest.skip("set UZP_OCIO16_EXPORT_TESTS_EXE to an approved binary; no build here")
    report = new_report()
    failed = False
    try:
        exe = Path(supplied)
        if not exe.is_file():
            raise ValueError("RGB16 executable unavailable")
        report["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
        replay(exe, ensure_outside_repository(tmp_path), report)
    except Exception:
        failed = True
        report["status"] = "failed"
    try:
        path = ensure_outside_repository(
            Path(os.environ["LOCALAPPDATA"]) / "UzPainter" / "ocio16-rgb16-candidate-private.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except Exception:
        failed = True
    if failed:
        pytest.fail(
            "RGB16 diagnostic operation failed; inspect private count report", pytrace=False
        )
    if report["comparisons"] != 18 or report["pixels_different"]:
        pytest.fail("RGB16 hypothesis differs; inspect private count report", pytrace=False)


def fake_result(candidate: baseline.Candidate) -> dict[str, Any]:
    """Authored harness data, never a decoder or a substitute for the native hypothesis."""
    data = b"authored-candidate"
    candidate.path.parent.mkdir(parents=True, exist_ok=True)
    candidate.path.write_bytes(data)
    return {
        "model": MODEL,
        "non_conformant": True,
        "observed": {**OBSERVED, "bitmap_fetches": 1},
        "written": [
            {"relativePath": candidate.path.name, "sha256": hashlib.sha256(data).hexdigest()}
        ],
    }


def test_public_rgb16_matrix(tmp_path: Path) -> None:
    planned = candidates(tmp_path)
    assert len(planned) == len({c.path for c in planned}) == 9
    assert {c.source for c in planned} == set(control.RGB16_CANDIDATES)
    assert [c.config["exportParameters"][0]["parameters"]["bitDepth"] for c in planned] == [
        "8",
        "16",
        "32f",
    ] * 3
    for candidate in planned:
        assert candidate.spec["color_management"] == "ocio"
        assert candidate.spec["config_hash"] == PAINTER_OCIO_CONFIG_SHA256
        parameters = candidate.config["exportParameters"][0]["parameters"]
        assert parameters["paddingAlgorithm"] == "passthrough" and parameters["dithering"] is False


def test_negative_specs_are_distinct_authored_inputs(tmp_path: Path) -> None:
    variants = set()
    for mutation in OUTSIDE_DOMAIN:
        candidate = candidates(tmp_path / mutation)[0]
        before = json.dumps([candidate.spec, candidate.config], sort_keys=True)
        outside_domain(candidate, mutation)
        after = json.dumps([candidate.spec, candidate.config], sort_keys=True)
        assert after != before
        assert candidate.authored["private_records"] == candidate.authored["expectations"] == []
        assert not candidate.path.exists()
        variants.add(mutation)
    assert len(variants) == len(OUTSIDE_DOMAIN)


@pytest.mark.parametrize("bad", ["model", "flag", "raw", "bits", "fetch", "bool", "extra"])
def test_native_contract_refuses_unobserved_decoder(tmp_path: Path, bad: str) -> None:
    candidate = candidates(tmp_path)[0]
    result = fake_result(candidate)
    if bad == "model":
        result["model"] = "ordinary-export"
    elif bad == "flag":
        result["non_conformant"] = False
    elif bad == "extra":
        result["observed"]["decoder16_called"] = True
    else:
        key, value = {
            "raw": ("srgb_decode", False),
            "bits": ("source_bits", 8),
            "fetch": ("bitmap_fetches", 0),
            "bool": ("bitmap_fetches", True),
        }[bad]
        result["observed"][key] = value
    with pytest.raises(ValueError):
        checked_output(candidate, result)


def test_all_nine_candidates_precede_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = new_report()
    calls = 0

    def write(exe: Path, candidate: baseline.Candidate) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        assert report["comparisons"] == 0
        return fake_result(candidate)

    def compare(produced: list[tuple[baseline.Candidate, bytes]], result: dict[str, Any]) -> None:
        assert calls == len(produced) == result["candidates"] == 9
        for _, data in produced:
            for _ in range(2):
                baseline.compare_bytes(data, data, result)
        result.update(stage="complete", status="equal")

    monkeypatch.setattr(__name__ + ".write_candidate", write)
    monkeypatch.setattr(baseline, "compare_produced", compare)
    replay(Path("never-executed"), tmp_path, report)
    assert report["comparisons"] == report["encoded_equal"] == report["pixels_equal"] == 18
    assert report["attempted"] == report["returned"] == report["bitmap_fetches"] == 9


@pytest.mark.parametrize("kind", ["operation", "mismatch"])
def test_failure_and_mismatch_remain_distinct_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    exe = tmp_path / "authored.exe"
    exe.write_bytes(b"not executable")
    monkeypatch.setenv("UZP_OCIO16_EXPORT_TESTS_EXE", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def run(exe: Path, work: Path, result: dict[str, Any]) -> None:
        if kind == "operation":
            result.update(attempted=2, returned=1, candidates=1)
            raise RuntimeError("PRIVATE_SENTINEL_MUST_NOT_LEAK")
        result.update(
            stage="complete",
            status="different",
            attempted=9,
            returned=9,
            candidates=9,
            comparisons=18,
            pixels_different=18,
        )

    monkeypatch.setattr(__name__ + ".replay", run)
    with pytest.raises(pytest.fail.Exception) as caught:
        test_ocio16_rgb16_diagnostic(tmp_path)
    text = (tmp_path / "UzPainter/ocio16-rgb16-candidate-private.json").read_text()
    assert "PRIVATE_SENTINEL" not in str(caught.value) + text
    report = json.loads(text)
    assert report["status"] == ("failed" if kind == "operation" else "different")
    assert report["model"] == MODEL and report["non_conformant"] is True
    assert ("operation failed" if kind == "operation" else "hypothesis differs") in str(
        caught.value
    )
