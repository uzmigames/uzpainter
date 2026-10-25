"""`uzp-export-tests tga-processing-candidate`: a TEST-ONLY diagnostic TGA8 candidate.

Authored inputs only (the grid mesh and ramp bitmap of `test_export_encoders`): no Painter file and
no oracle. The candidate encodes the spec's single PNG 8 file through the diagnostic measure export
in memory and writes its codes unchanged as RLE TGA8. These checks are independent of the encoder
under test: the native PNG bytes are compared with the ones `export-diagnostic` writes to disk, and
both images are decoded by Pillow. Nothing here is conformity or Painter parity; TGA stays refused
by the product.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from tests.export.test_export_encoders import TEMPLATES, chan, run, spec

PNG8 = {"fileFormat": "png", "bitDepth": "8", "dithering": False, "paddingAlgorithm": "infinite"}
MODEL = {"model": "native-png8-processing-candidate", "non_conformant": True}


def configuration(
    out: Path, maps: list[dict[str, Any]], parameters: dict[str, Any]
) -> dict[str, Any]:
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [{"parameters": parameters}],
    }


RGBA = {
    "fileName": "$textureSet_rgba",
    "channels": [chan(c, "documentMap", "user0") for c in "RGB"]
    + [
        {
            "destChannel": "A",
            "srcChannel": "L",
            "srcMapType": "documentMap",
            "srcMapName": "roughness",
        }
    ],
}
GREY = {"fileName": "$textureSet_grey", "channels": [chan("L", "documentMap", "roughness")]}


def candidate(
    exe: Path, tmp: Path, spec_path: Path, cfg: dict[str, Any], label: str
) -> dict[str, Any]:
    (tmp / f"{label}.json").write_text(json.dumps(cfg), encoding="utf-8")
    [report] = run(
        exe,
        "tga-processing-candidate",
        str(TEMPLATES),
        str(spec_path),
        str(tmp / f"{label}.json"),
        str(tmp / f"{label}.tga"),
    )
    return report


def test_candidate_writes_the_native_png8_codes_unchanged(
    export_tests: Path, tmp_path: Path
) -> None:
    spec_path = spec(tmp_path / "spec")
    for label, layout, mode in (("rgba", RGBA, "RGBA"), ("grey", GREY, "L")):
        cfg = configuration(tmp_path / f"out-{label}", [layout], PNG8)
        first = candidate(export_tests, tmp_path, spec_path, cfg, label)
        assert "error" not in first and "blocked" not in first, first.get("message")
        assert {k: first[k] for k in MODEL} == MODEL
        assert first["planned"]["parameters"] == PNG8 and first["planned"]["width"] == 256
        tga = (tmp_path / f"{label}.tga").read_bytes()
        assert first["tga"]["sha256"] == hashlib.sha256(tga).hexdigest()
        assert first["tga"]["size"] == len(tga)
        # Deterministic: the same inputs give the same native PNG and the same TGA.
        second = candidate(export_tests, tmp_path, spec_path, cfg, label + "-again")
        assert (second["png8_sha256"], second["tga"]) == (first["png8_sha256"], first["tga"])
        # Independent: export-diagnostic writes the same native PNG 8 bytes to disk.
        (tmp_path / f"{label}-diagnostic.json").write_text(json.dumps(cfg), encoding="utf-8")
        [written] = run(
            export_tests,
            "export-diagnostic",
            str(TEMPLATES),
            str(spec_path),
            str(tmp_path / f"{label}-diagnostic.json"),
        )
        [file] = written["written"]
        png = Path(file["path"]).read_bytes()
        assert hashlib.sha256(png).hexdigest() == first["png8_sha256"]
        assert file["bypassed"] == first["bypassed"] and file["undecided"] == first["undecided"]
        # Pillow decodes both: same size, layout, alpha and orientation, code for code.
        with (
            Image.open(tmp_path / f"{label}.tga") as decoded_tga,
            Image.open(Path(file["path"])) as decoded_png,
        ):
            assert decoded_tga.format == "TGA" and decoded_tga.mode == mode == decoded_png.mode
            assert decoded_tga.size == decoded_png.size == (256, 256)
            assert (first["tga"]["width"], first["tga"]["height"]) == decoded_tga.size
            assert first["tga"]["channels"] == len(mode)
            assert np.array_equal(np.asarray(decoded_tga), np.asarray(decoded_png))
        assert tga[2] in (10, 11), "an RLE true-colour or grey TGA"


def test_candidate_refusals_keep_the_model(export_tests: Path, tmp_path: Path) -> None:
    with_mesh = spec(tmp_path / "spec")
    without_mesh = spec(tmp_path / "spec-free", mesh=None)
    png16 = PNG8 | {"bitDepth": "16"}
    exr = {
        "fileFormat": "exr",
        "bitDepth": "32f",
        "dithering": False,
        "paddingAlgorithm": "infinite",
    }
    cases = {
        "no-mesh": (
            without_mesh,
            configuration(tmp_path / "o1", [GREY], PNG8),
            "parse_spec",
            "texturing mesh",
        ),
        "two-files": (
            with_mesh,
            configuration(tmp_path / "o2", [GREY, RGBA], PNG8),
            "compile_plan",
            "exactly one file",
        ),
        "png16": (
            with_mesh,
            configuration(tmp_path / "o3", [GREY], png16),
            "compile_plan",
            "bit depth 8",
        ),
        "exr": (
            with_mesh,
            configuration(tmp_path / "o4", [GREY], exr),
            "compile_plan",
            "bit depth 8",
        ),
    }
    for label, (spec_path, cfg, stage, message) in cases.items():
        report = candidate(export_tests, tmp_path, spec_path, cfg, label)
        assert {k: report[k] for k in MODEL} == MODEL, label
        assert (report["error"], report["stage"], report["blocked"]) == ("Setup", stage, False), (
            label
        )
        assert message in report["message"] and "reason_code" not in report, label
        assert "tga" not in report and not (tmp_path / f"{label}.tga").exists(), label
    # Every NotYetSupported of the plan compiler's call has one reason code; the release-gap
    # virtual maps the configuration names (AO_Mixed, decision 131) are context, not the cause.
    ao = {"fileName": "$textureSet_ao", "channels": [chan("L", "virtualMap", "AO_Mixed")]}
    tga = PNG8 | {"fileFormat": "tga"}
    for label, cfg, maps in (
        ("ao", configuration(tmp_path / "o5", [ao], PNG8), ["AO_Mixed"]),
        ("tga", configuration(tmp_path / "o6", [GREY], tga), None),
    ):
        report = candidate(export_tests, tmp_path, with_mesh, cfg, label)
        assert {k: report[k] for k in MODEL} == MODEL, label
        assert (report["error"], report["stage"]) == ("NotYetSupported", "compile_plan"), label
        assert report["reason_code"] == "compile_plan_not_yet_supported", label
        assert report["blocked"] is True and "tga" not in report, label
        assert report.get("release_gap_virtual_maps") == maps, label
    # A malformed configuration is an input error, never a blocked map.
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    [report] = run(
        export_tests,
        "tga-processing-candidate",
        str(TEMPLATES),
        str(with_mesh),
        str(tmp_path / "broken.json"),
        str(tmp_path / "broken.tga"),
    )
    assert {k: report[k] for k in MODEL} == MODEL
    assert (report["error"], report["stage"], report["blocked"]) == (
        "ValueError",
        "compile_plan",
        False,
    )
    assert "reason_code" not in report
    usage = subprocess.run(
        [str(export_tests), "tga-processing-candidate", str(TEMPLATES)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert usage.returncode == 2


def test_candidate_hydrates_insert_default_blending(export_tests: Path, tmp_path: Path) -> None:
    """Painter's insert defaults (decision 115: Height LinearDodge, Normal NormalMapDetail, both
    at opacity 1; every other channel the default Normal at 1, so absent) come first, and the
    spec's authored blending overrides them per channel."""
    defaults = {"Height": ["LinearDodge", 1.0], "Normal": ["NormalMapDetail", 1.0]}
    plain = spec(tmp_path / "plain")
    cfg = configuration(tmp_path / "o-plain", [GREY], PNG8)
    report = candidate(export_tests, tmp_path, plain, cfg, "plain")
    assert "error" not in report, report.get("message")
    assert [fill["blending"] for fill in report["fill_blending"]] == [defaults]
    authored = spec(tmp_path / "authored")
    document = json.loads(authored.read_text(encoding="utf-8"))
    document["layers"][0]["blending"] = {"Height": {"mode": "Normal", "opacity": 0.5}}
    authored.write_text(json.dumps(document), encoding="utf-8")
    cfg = configuration(tmp_path / "o-authored", [GREY], PNG8)
    report = candidate(export_tests, tmp_path, authored, cfg, "authored")
    assert "error" not in report, report.get("message")
    assert [fill["blending"] for fill in report["fill_blending"]] == [
        {"Height": ["Normal", 0.5], "Normal": ["NormalMapDetail", 1.0]}
    ]
