"""Independent structural checks of the UzEngine material writer, without an engine mock."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def material_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zig = shutil.which("zig")
    assert zig is not None, "zig is required for material writer acceptance"
    prefix = tmp_path_factory.mktemp("material-tests")
    result = subprocess.run(
        [zig, "build", "uzp-material-tests", "--prefix", str(prefix)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return prefix / "bin" / "uzp-material-tests.exe"


def authored_spec() -> dict[str, Any]:
    return {
        "name": "Authored material",
        "materialPath": "authored.uzmat",
        "albedo": "maps/colour.uztexture",
        "normal": "maps/surface.uztexture",
        "orm": "maps/packed.uztexture",
        "emissive": "maps/light.uztexture",
    }


def write(exe: Path, tmp: Path, spec: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = tmp / "request.json"
    request.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [str(exe), str(request)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode in (0, 1), (result.stdout, result.stderr)
    return result.returncode, json.loads(result.stdout)


def test_material_graph_pins_and_inline_match(material_tests: Path, tmp_path: Path) -> None:
    spec = authored_spec()
    code, result = write(material_tests, tmp_path, spec)
    assert code == 0, result
    graph = json.loads(result["bytes"])
    scene = json.loads(result["inlineMaterial"])
    assert graph["version"] == 1 and graph["domain"] == "Surface"
    assert graph["shadingModel"] == "DefaultLit" and graph["name"] == spec["name"]
    expressions = {expression["id"]: expression for expression in graph["expressions"]}
    outputs = [
        expression for expression in expressions.values() if expression["type"] == "PBROutput"
    ]
    assert len(outputs) == 1 and len(expressions) == 5
    expected = {
        0: ("Albedo", "albedo", 0),
        1: ("ORM", "orm", 3),
        2: ("ORM", "orm", 2),
        3: ("Normal", "normal", 0),
        4: ("Emissive", "emissive", 0),
        5: ("Albedo", "albedo", 4),
        6: ("ORM", "orm", 1),
    }
    inputs = outputs[0]["inputs"]
    assert len(inputs) == 7 and {link["pin"] for link in inputs} == set(range(7))
    for link in inputs:
        name, slot, sample_pin = expected[link["pin"]]
        sample = expressions[link["srcExpr"]]
        assert sample["type"] == "TextureSample" and sample["name"] == name
        assert link["srcPin"] == sample_pin
        assert sample["stringParams"]["texturePath"] == scene[slot] == spec[slot]
    assert scene["material_graph"] == result["materialPath"] == spec["materialPath"]
    assert scene["orm"] == spec["orm"]
    assert graph["params"]["baseColorTint"] == [1, 1, 1]
    for factor in (
        "roughnessMultiplier",
        "metallicMultiplier",
        "normalStrength",
        "emissiveMultiplier",
        "specularMultiplier",
        "aoMultiplier",
    ):
        assert graph["params"][factor] == 1
    for factor in (
        "baseColorR",
        "baseColorG",
        "baseColorB",
        "roughnessMultiplier",
        "metallicMultiplier",
        "normalIntensity",
        "aoIntensity",
        "emissiveColorR",
        "emissiveColorG",
        "emissiveColorB",
        "emissiveIntensity",
    ):
        assert scene[factor] == 1
    assert scene["specular"] == 0.5
    assert result["gaps"] == []


@pytest.mark.parametrize(
    "blend,name", [(0, "Opaque"), (1, "Masked"), (2, "Translucent"), (3, "Additive")]
)
def test_blend_and_height_gap(material_tests: Path, tmp_path: Path, blend: int, name: str) -> None:
    spec = authored_spec() | {
        "height": "maps/displacement.uztexture",
        "blend": blend,
        "twoSided": True,
    }
    code, result = write(material_tests, tmp_path, spec)
    assert code == 0, result
    graph, scene = json.loads(result["bytes"]), json.loads(result["inlineMaterial"])
    assert graph["blendMode"] == scene["blendMode"] == name
    assert graph["twoSided"] is True
    assert "height" not in scene and "heightmap" not in scene
    assert spec["height"] not in result["bytes"] + result["inlineMaterial"]
    gaps = {gap["binding"]: gap for gap in result["gaps"]}
    assert set(gaps) == ({"height"} if blend == 0 else {"height", "opacity"})
    assert gaps["height"]["path"] == spec["height"] and gaps["height"]["reason"]
    if blend:
        assert gaps["opacity"]["path"] == spec["albedo"]
        assert "SM5" in gaps["opacity"]["reason"]


def test_unicode_escapes_and_determinism(material_tests: Path, tmp_path: Path) -> None:
    spec = authored_spec() | {
        "name": 'Madeira \u00e7 \U0001f332 "quoted" \\ tab\t newline\n',
        "albedo": "maps/cor-\u00e7.uztexture",
    }
    first = write(material_tests, tmp_path, spec)
    second = write(material_tests, tmp_path, spec)
    assert first == second and first[0] == 0
    for key in ("bytes", "inlineMaterial"):
        text = first[1][key]
        parsed = json.loads(text)
        assert (
            text
            == json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )
    assert json.loads(first[1]["bytes"])["name"] == spec["name"]
    assert json.loads(first[1]["inlineMaterial"])["albedo"] == spec["albedo"]


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../escape.uztexture",
        "/absolute.uztexture",
        "C:/absolute.uztexture",
        "maps\\wrong.uztexture",
        "maps//empty.uztexture",
        "maps/./dot.uztexture",
        "maps/../up.uztexture",
        "https://x/map.uztexture",
        "maps/%2e%2e.uztexture",
        "maps/query?.uztexture",
        "maps/hash#.uztexture",
        "maps/control\n.uztexture",
        "maps/trailing./map.uztexture",
        "maps/trailing /map.uztexture",
        "maps/wrong.png",
        "aux.uztexture",
        "dir/COM1.uztexture",
        "NUL/maps/file.uztexture",
        "NUL .uztexture",
        "dir/COM1 .uztexture",
    ],
)
def test_unsafe_texture_references_rejected(
    material_tests: Path, tmp_path: Path, path: str
) -> None:
    code, result = write(material_tests, tmp_path, authored_spec() | {"normal": path})
    assert code == 1 and result["error"]


@pytest.mark.parametrize(
    "changes",
    [
        {"materialPath": "nested/material.uzmat"},
        {"materialPath": "../escape.uzmat"},
        {"materialPath": "material.json"},
        {"name": ""},
        {"name": "bad\0name"},
        {"blend": 99},
        {"invalidUtf8Name": True},
        {"invalidUtf8Height": True},
        {"height": "../height.uztexture"},
        {"materialPath": "CON.uzmat"},
        {"materialPath": "CON .uzmat"},
        {"normal": "maps/colour.uztexture"},
        {"orm": "maps/light.uztexture"},
    ],
)
def test_invalid_material_rejected(
    material_tests: Path, tmp_path: Path, changes: dict[str, Any]
) -> None:
    code, result = write(material_tests, tmp_path, authored_spec() | changes)
    assert code == 1 and result["error"]
