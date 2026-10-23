"""Native resolution manifest/recipe roundtrips; legacy fixture bytes stay pinned."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.uzp_core.test_document_model import FIXTURE_PATH, REPO_ROOT, output, rejection
from tests.uzp_core.test_document_model import core_tests as _core_tests
from tests.uzp_core.test_recipe import walk

core_tests = _core_tests


def manifest_with(override: Any) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # The recipe rebuild supports structural sources, not stored paint content.
    stack = value["texture_sets"][0]["stacks"][0]
    stack["root_layers"] = [layer for layer in stack["root_layers"] if layer["kind"] != "paint"]
    base = stack["root_layers"][-1]
    base["content_effects"] = [
        effect for effect in base["content_effects"] if effect["kind"] != "paint"
    ]
    base["mask"]["effects"] = [
        effect for effect in base["mask"]["effects"] if effect["kind"] != "paint"
    ]
    reference = next(
        obj for obj in walk(value) if "asset" in obj and obj.get("resolution_override") is not None
    )
    reference["resolution_override"] = override
    return value


def validate_schema(kind: str, value: dict[str, Any]) -> None:
    path = REPO_ROOT / "src" / "uzp_core" / "schema" / f"{kind}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    "mode", ["Auto", "Asset", "Custom", "TextureSet", "UVTile", "Document", "Manual"]
)
def test_mode_fields_roundtrip_manifest_recipe_and_rebuild(
    core_tests: Path, tmp_path: Path, mode: str
) -> None:
    override = {"mode": mode, "value": [256, 512], "log2_offset": -2, "future": {"keep": 7}}
    manifest = manifest_with(override)
    validate_schema("manifest", manifest)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads(output(core_tests, "canonical", str(path)))
    assert loaded == manifest
    recipe = json.loads(output(core_tests, "recipe", str(path)))
    validate_schema("recipe", recipe)
    expected = {key: value for key, value in override.items() if key != "future"}
    assert any(obj.get("resolution_override") == expected for obj in walk(recipe))
    assert not any("future" in obj for obj in walk(recipe))
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    rebuilt = json.loads(output(core_tests, "rebuild", str(recipe_path)))
    validate_schema("manifest", rebuilt)
    assert any(obj.get("resolution_override") == expected for obj in walk(rebuilt))


@pytest.mark.parametrize(
    "override",
    [
        {"mode": "Auto", "value": [128, 128], "log2_offset": 0, "width": 128},
        {"width": 128, "height": 128, "log2_offset": 0},
        {"mode": "Auto", "value": [128, 128]},
        {"mode": "invalid", "value": [128, 128], "log2_offset": 0},
        {"mode": "Custom", "value": [64, 128], "log2_offset": 0},
        {"mode": "Custom", "value": [8192, 8192], "log2_offset": 0},
        {"mode": "Custom", "value": [129, 128], "log2_offset": 0},
        {"mode": "Auto", "value": [128], "log2_offset": 0},
        {"mode": "Auto", "value": [128, 128, 128], "log2_offset": 0},
        {"mode": "Auto", "value": [True, 128], "log2_offset": 0},
        {"mode": "Auto", "value": [128, 128], "log2_offset": True},
        {"mode": "Auto", "value": [128, 128], "log2_offset": 2**31},
        {"mode": "Auto", "value": [128, 128], "log2_offset": -(2**31) - 1},
    ],
)
def test_invalid_resolution_refused_by_schema_and_native(
    core_tests: Path, tmp_path: Path, override: dict[str, Any]
) -> None:
    from jsonschema import ValidationError

    manifest = manifest_with(override)
    with pytest.raises(ValidationError):
        validate_schema("manifest", manifest)
    assert rejection(core_tests, json.dumps(manifest), tmp_path) in ("ManifestError", "ValueError")


@pytest.mark.parametrize("offset", [-(2**31), 2**31 - 1])
def test_offset_extremes_persist_without_early_clamping(
    core_tests: Path, tmp_path: Path, offset: int
) -> None:
    manifest = manifest_with({"mode": "Auto", "value": [128, 128], "log2_offset": offset})
    validate_schema("manifest", manifest)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert json.loads(output(core_tests, "canonical", str(path))) == manifest


def test_recipe_digest_tracks_resolution_fields(core_tests: Path, tmp_path: Path) -> None:
    signatures = []
    for mode, value, offset in [
        ("Auto", [256, 256], 0),
        ("Custom", [256, 256], 0),
        ("Auto", [512, 512], 0),
        ("Auto", [256, 256], 1),
    ]:
        manifest = manifest_with({"mode": mode, "value": value, "log2_offset": offset})
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        recipe = json.loads(output(core_tests, "recipe", str(path)))
        signatures.append(recipe["digest"])
    assert len(set(signatures)) == len(signatures)
