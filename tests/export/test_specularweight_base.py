"""Recorded empty SpecularWeight bases, bounded by template and channel format."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.conftest import REPO_ROOT
from tests.export.test_export_encoders import TEMPLATES, chan, export, files_under
from tests.export.test_uze_preset import gaps, header, publish, published, shipped_config
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import load
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

TEMPLATE_IDS = {"default": "default", "alpha-blend": "pbr-metallic-roughness-alpha-blend"}
FORMATS = ("L8", "L16", "L32F")


def empty_spec(path: Path, template: str, fmt: str, *, present: bool = True) -> Path:
    document = {
        "name": "uzp_plane",
        "template": template,
        "resolution": [256, 256],
        "mesh": str(REPO_ROOT / "parity/fixtures/meshes/plane.obj"),
        "channels": [{"type": "SpecularWeight", "format": fmt}]
        if present
        else [{"type": "BaseColor", "format": "sRGB8"}],
        "resources": [],
        "layers": [],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def config(out: Path, file_format: str) -> dict[str, Any]:
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "weight",
        "exportPresets": [
            {
                "name": "weight",
                "maps": [
                    {
                        "fileName": "$textureSet_specularweight",
                        "channels": [chan("L", "documentMap", "specularweight")],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": file_format,
                    "bitDepth": "32f" if file_format == "exr" else "16",
                    "dithering": False,
                    "paddingAlgorithm": "infinite",
                }
            }
        ],
    }


@pytest.mark.parametrize("template", TEMPLATE_IDS.values())
@pytest.mark.parametrize("fmt", FORMATS)
def test_empty_channel_exports_observed_base(
    export_tests: Path, tmp_path: Path, template: str, fmt: str
) -> None:
    spec = empty_spec(tmp_path / "spec.json", template, fmt)
    for file_format in ("exr", "png"):
        outputs = []
        for repeat in range(2):
            out = tmp_path / f"{file_format}-{repeat}"
            result = export(export_tests, spec, config(out, file_format), out / "request")
            assert "error" not in result, result
            raw = (out / f"uzp_plane_specularweight.{file_format}").read_bytes()
            image = decode(raw)
            assert image.values.shape == (256, 256, 1)
            assert image.bits == (32 if file_format == "exr" else 16)
            assert np.all(image.values == (1.0 if file_format == "exr" else 65535))
            outputs.append(raw)
        assert outputs[0] == outputs[1]


@pytest.mark.parametrize("template", TEMPLATE_IDS)
@pytest.mark.parametrize("fmt", FORMATS)
def test_empty_channel_matches_current_oracle(
    export_tests: Path, tmp_path: Path, template: str, fmt: str
) -> None:
    store = locate()
    if store is None:
        pytest.skip("private oracle store unavailable on this machine (decision 028)")
    golden_id = f"tier0/semantics/specularweight-empty-base-{template}-{fmt.lower()}"
    resolved = resolve_golden(golden_id)
    assert resolved is not None and not resolved.stale
    golden = load(store, resolved.manifest_path)
    assert set(golden.recordings) == {"r1", "r2"}
    spec = empty_spec(tmp_path / "spec.json", TEMPLATE_IDS[template], fmt)
    for file_format, steps in (("exr", (3, 4)), ("png", (5, 6))):
        out = tmp_path / file_format
        result = export(export_tests, spec, config(out, file_format), out / "request")
        assert "error" not in result, result
        candidate = decode((out / f"uzp_plane_specularweight.{file_format}").read_bytes())
        for recording in ("r1", "r2"):
            for step in steps:
                oracle = golden.map(recording, f"uzp_plane/specularweight/step{step}")
                assert (candidate.bits, candidate.integer) == (oracle.bits, oracle.integer)
                assert np.array_equal(candidate.values, oracle.values), (recording, step)


@pytest.mark.parametrize(
    "template,fmt",
    [
        ("pbr-metallic-roughness-alpha-test", "L8"),
        ("unreal-engine", "L16"),
        ("default", "L16F"),
        ("pbr-metallic-roughness-alpha-blend", "RGB16"),
    ],
)
def test_unrecorded_combination_remains_refused(
    export_tests: Path, tmp_path: Path, template: str, fmt: str
) -> None:
    spec = empty_spec(tmp_path / "spec.json", template, fmt)
    out = tmp_path / "out"
    result = export(export_tests, spec, config(out, "png"), tmp_path / "request")
    assert result["error"] == "Failure"
    assert result["message"].startswith("evaluator:missing_base_value"), result
    assert files_under(out) == {}


def test_missing_channel_remains_skipped(export_tests: Path, tmp_path: Path) -> None:
    spec = empty_spec(tmp_path / "spec.json", "default", "L8", present=False)
    out = tmp_path / "out"
    result = export(export_tests, spec, config(out, "png"), tmp_path / "request")
    assert "error" not in result, result
    assert files_under(out) == {}


def test_published_specularweight_keeps_consumer_gap(export_tests: Path, tmp_path: Path) -> None:
    spec = empty_spec(tmp_path / "spec.json", "default", "L16")
    out = tmp_path / "out"
    cfg = shipped_config(out.as_posix(), ["$textureSet_specularweight"])
    cfg["exportList"][0]["rootPath"] = "uzp_plane"
    code, lines, err = publish(export_tests, spec, cfg, tmp_path)
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    generation, receipt = published(export_tests, out)
    entries = {entry["path"]: entry for entry in receipt["files"]}
    assert set(entries) == {"uzp_plane_specularweight.png", "uzp_plane_specularweight.uztexture"}
    canonical = entries["uzp_plane_specularweight.png"]
    assert (canonical["bit_depth"], canonical["colour_space"]) == ("16", "linear")
    assert gaps(canonical) == {"SpecularWeight"}
    derivative = entries["uzp_plane_specularweight.uztexture"]
    assert derivative["uztexture"]["binding"] is None
    assert derivative["uztexture"]["format"] == "BC4"
    assert gaps(derivative) == {"SpecularWeight"}
    files = generation / "files"
    assert np.all(decode((files / canonical["path"]).read_bytes()).values == 65535)
    assert header((files / derivative["path"]).read_bytes())[5] == 5


@pytest.mark.parametrize("scope", [[], ["default", "default"], ["missing"], [5], "default"])
def test_malformed_template_scope_is_rejected(
    export_tests: Path, tmp_path: Path, scope: Any
) -> None:
    templates = tmp_path / "templates"
    shutil.copytree(TEMPLATES, templates)
    path = templates / "channel-defaults.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    next(c for c in table["channels"] if c["type"] == "SpecularWeight")["project_templates"] = scope
    path.write_text(json.dumps(table), encoding="utf-8")
    spec = empty_spec(tmp_path / "spec.json", "default", "L8")
    out = tmp_path / "out"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config(out, "png")), encoding="utf-8")
    result = subprocess.run(
        [str(export_tests), "export", str(templates), str(spec), str(cfg)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "template" in result.stderr, result.stderr
    assert files_under(out) == {}
