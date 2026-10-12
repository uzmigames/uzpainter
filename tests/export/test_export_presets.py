"""Tests of phase1.17_export-presets (P1-EXPORT, `docs/architecture/08-export.md` §4,
`docs/licensing-and-clean-room.md` §6; `assets/export-presets/`, `src/export/preset_aliases.h`;
decision 095).

The CPU cases run `uzp-export-tests.exe` (`presets`, `aliases`, `plan`, `export`) on every lane,
with the shipped presets installed beside it: the provenance record of every preset, the alias
table, the refusal of the presets whose layout no recording confirms (recording R-095), and the
Assets3D five-map preset planning what the pipeline's own inline configuration plans. The Tier 0
case reads the private oracle store and skips, saying so, on a machine without it (decision 028):
the five-map preset's normal map, written on the recorded plane goldens, is byte-identical to
Painter's files.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.export.conftest import REPO_ROOT
from tests.export.encoders_tier0 import _mesh_of, _painter_files, write_export
from tests.export.test_export_encoders import GRID, export, files_under, spec
from tests.export.test_export_plan import (
    FULL_CHANNELS,
    pipeline_inline_preset,
    plan_many,
    project,
    refused,
    texture_set,
)
from tests.export.tier0 import export_spec, needs_store
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.oracle import load
from tools.parity.guard.guard import content_hashes, load_index, run_guard, worktree_snapshot
from tools.parity.store.store import default_root, locate

PRESETS = REPO_ROOT / "assets" / "export-presets"
SCHEMA = REPO_ROOT / "src" / "export" / "preset-provenance.schema.json"
FIVE_MAP = "assets3d-inline-five-map"
UNCONFIRMED = {
    "PBR Metallic Roughness": "pbr-metallic-roughness",
    "Blender (Principled BSDF)": "blender-principled-bsdf",
}
BLENDER_URL = "resource://starter_assets/Blender (Principled BSDF)"
BLENDER_VERSION = "13120355637414252359"


def run(exe: Path, *args: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def resolve(exe: Path, directory: Path, references: list[str], tmp: Path) -> list[dict[str, Any]]:
    """`uzp-export-tests presets`: each reference resolved and its shipped preset loaded."""
    path = tmp / "references.json"
    path.write_text(json.dumps({"references": references}), encoding="utf-8")
    return run(exe, "presets", str(directory), str(path))


def preset_ids() -> list[str]:
    return sorted(
        p.name[: -len(".json")]
        for p in PRESETS.glob("*.json")
        if not p.name.endswith(".provenance.json")
    )


def shipped_config(reference: str, **extra: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "exportPath": "C:/export",
        "defaultExportPreset": reference,
        "exportList": [{"rootPath": "s0"}],
    }
    c.update(extra)
    return c


ONE_SET = project(texture_set("s0", FULL_CHANNELS))


# ── 3.2 Provenance ───────────────────────────────────────────────────────────


def test_provenance_records_are_complete(export_tests: Path) -> None:
    """3.2: every shipped preset has a `.provenance.json` valid under its schema, naming the
    preset, one packing entry per map in the preset's order, the Painter names the alias table
    resolves to it, and parity tests that exist; an exact status names its private records."""
    [table] = run(export_tests, "aliases")
    ids = preset_ids()
    assert ids == sorted(table["shipped"])
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    tests_here = {
        n.name
        for n in ast.parse(Path(__file__).read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    }
    for preset_id in ids:
        preset = json.loads((PRESETS / f"{preset_id}.json").read_text(encoding="utf-8"))
        record_path = PRESETS / f"{preset_id}.provenance.json"
        assert record_path.is_file(), f"{preset_id}: no provenance record"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        problems = [e.message for e in validator.iter_errors(record)]
        assert problems == [], f"{preset_id}: {problems}"
        assert record["preset"] == preset["name"] == preset_id
        maps = [e["fileName"] for e in record["packing"] if e["fileName"] != "(all)"]
        assert maps == [m["fileName"] for m in preset["maps"]], preset_id
        aliases = sorted(name for name, target, _ in table["aliases"] if target == preset_id)
        assert sorted(record["answersTo"]) == aliases, preset_id
        parity = record["parity"]
        if parity["status"] == "exact":
            assert record["privateRecords"], f"{preset_id}: exact parity without private records"
        for test in parity["tests"]:
            path, _, name = test.partition("::")
            assert path == "tests/export/test_export_presets.py" and name in tests_here, test
        if parity["layout"] == "unconfirmed":
            assert any(p["recording"] == "R-095" for p in parity["pending"]), preset_id


def test_a_preset_without_provenance_fails_naming_it(export_tests: Path, tmp_path: Path) -> None:
    """Spec scenario "Preset without provenance": loading a preset whose record is missing fails
    naming the preset; so does a record of another preset."""
    copy = tmp_path / "presets"
    shutil.copytree(PRESETS, copy)
    (copy / f"{FIVE_MAP}.provenance.json").unlink()
    [missing] = resolve(export_tests, copy, [FIVE_MAP], tmp_path)
    assert missing["error"] == "ManifestError", missing
    assert FIVE_MAP in missing["message"] and "provenance record" in missing["message"]
    shutil.copy(
        PRESETS / "pbr-metallic-roughness.provenance.json", copy / f"{FIVE_MAP}.provenance.json"
    )
    [other] = resolve(export_tests, copy, [FIVE_MAP], tmp_path)
    assert other["error"] == "ManifestError" and "records another preset" in other["message"]


# ── 3.3 Aliases ──────────────────────────────────────────────────────────────


def test_painter_names_resolve_to_shipped_presets(export_tests: Path, tmp_path: Path) -> None:
    """3.3: Painter's preset names, and their `resource://starter_assets/` URLs without a query or
    with the recorded version, resolve to the shipped presets (UzPainter ids); an unrecorded
    version is refused naming R-095; other text names no shipped preset."""
    installed = export_tests.parent / "assets" / "export-presets"
    references = [
        "Blender (Principled BSDF)",
        BLENDER_URL,
        f"{BLENDER_URL}?version={BLENDER_VERSION}",
        "PBR Metallic Roughness",
        "resource://starter_assets/PBR Metallic Roughness",
        FIVE_MAP,
        f"{BLENDER_URL}?version=1",
        "resource://starter_assets/PBR Metallic Roughness?version=1",
        "blender (principled bsdf)",
        "resource://my_shelf/Blender (Principled BSDF)",
    ]
    r = resolve(export_tests, installed, references, tmp_path)
    assert [x.get("id") for x in r[:6]] == [
        "blender-principled-bsdf",
        "blender-principled-bsdf",
        "blender-principled-bsdf",
        "pbr-metallic-roughness",
        "pbr-metallic-roughness",
        FIVE_MAP,
    ]
    assert all(x["name"] == x["id"] for x in r[:6])
    for x in r[6:8]:
        assert x["error"] == "NotYetSupported" and "R-095" in x["message"], x
    assert r[8]["id"] is None and r[9]["id"] is None

    # defaultExportPreset "Blender (Principled BSDF)" reaches the shipped preset via ParseConfig.
    [planned] = plan_many(
        export_tests, [(ONE_SET, shipped_config("Blender (Principled BSDF)"))], tmp_path
    )
    refused(planned, "NotYetSupported", '(shipped preset "blender-principled-bsdf")', "R-095")


def test_unconfirmed_presets_are_refused_naming_r095(export_tests: Path, tmp_path: Path) -> None:
    """Decision 095: a preset written from public sources whose layout no recording confirms is
    refused before anything is planned, whether named by `defaultExportPreset` or by an
    `exportList` entry, by its Painter name, its URL or its id."""
    cases = []
    for painter_name, preset_id in UNCONFIRMED.items():
        for reference in (painter_name, f"resource://starter_assets/{painter_name}", preset_id):
            cases.append((ONE_SET, shipped_config(reference)))
            cases.append(
                (
                    ONE_SET,
                    shipped_config(
                        FIVE_MAP, exportList=[{"rootPath": "s0", "exportPreset": reference}]
                    ),
                )
            )
    for result in plan_many(export_tests, cases, tmp_path):
        refused(
            result,
            "NotYetSupported",
            "no recording of Painter's output confirms its layout",
            "R-095",
            "decision 095",
        )


def test_preset_references_resolve_inline_first(export_tests: Path, tmp_path: Path) -> None:
    """Decision 095: an inline preset of the referenced name wins (Painter's documented
    behaviour); an inline preset that a shipped preset's id would collide with is refused; an
    unknown name lists the inline presets, the shipped ids and the Painter names; a shelf or
    predefined preset UzPainter does not ship is NotYetSupported."""
    inline_map = {
        "fileName": "$textureSet_x",
        "channels": [
            {
                "destChannel": "L",
                "srcChannel": "L",
                "srcMapType": "documentMap",
                "srcMapName": "height",
            }
        ],
        "parameters": {
            "fileFormat": "png",
            "bitDepth": "16",
            "dithering": False,
            "paddingAlgorithm": "infinite",
        },
    }
    cases = [
        (
            ONE_SET,
            shipped_config(
                "Blender (Principled BSDF)",
                exportPresets=[{"name": "Blender (Principled BSDF)", "maps": [inline_map]}],
            ),
        ),
        (
            ONE_SET,
            shipped_config(
                "PBR Metallic Roughness",
                exportPresets=[{"name": "pbr-metallic-roughness", "maps": [inline_map]}],
            ),
        ),
        (ONE_SET, shipped_config("Blender")),
        (ONE_SET, shipped_config("resource://my_shelf/Mine")),
        (ONE_SET, shipped_config("export-preset-generator://gltf")),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    assert [f["relativePath"] for f in r[0]["plan"]["files"]] == ["s0_x.png"]
    refused(r[1], "ValueError", "an inline preset of that name would shadow")
    message = refused(r[2], "ValueError", 'unknown export preset "Blender"')
    assert "Blender (Principled BSDF)" in message and FIVE_MAP in message
    for x in r[3:]:
        refused(x, "NotYetSupported", "UzPainter does not ship", "decision 095")


# ── The Assets3D five-map preset ─────────────────────────────────────────────


def strip_preset(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{k: v for k, v in f.items() if k not in ("preset", "path")} for f in plan["files"]]


def test_five_map_preset_plans_the_pipeline_maps(export_tests: Path, tmp_path: Path) -> None:
    """2.1, 4.1: the shipped five-map preset plans, file for file (names, channels, sources,
    parameters), what the pipeline's inline configuration (`painter_export.py`, its prefix the
    texture set's name and its sizeLog2 the set's size) plans; the hat v8 SpecularWeight map is
    not in it."""
    pipeline = pipeline_inline_preset("$textureSet", False)
    pipeline["exportList"] = [{"rootPath": "s0"}]
    pipeline["exportParameters"][0]["parameters"].pop("sizeLog2")
    shipped = shipped_config(FIVE_MAP, exportPath=pipeline["exportPath"])
    theirs, ours = plan_many(export_tests, [(ONE_SET, pipeline), (ONE_SET, shipped)], tmp_path)
    assert [f["relativePath"] for f in ours["plan"]["files"]] == [
        "s0_BaseColor.png",
        "s0_Roughness.png",
        "s0_Metallic.png",
        "s0_Height.png",
        "s0_Normal.png",
    ]
    assert strip_preset(ours["plan"]) == strip_preset(theirs["plan"])
    assert ours["list"] == theirs["list"]
    assert {f["preset"] for f in ours["plan"]["files"]} == {FIVE_MAP}


def test_five_map_preset_refuses_basecolor_naming_r090(export_tests: Path, tmp_path: Path) -> None:
    """Decisions 090 and 103: BaseColor's sRGB export encoding is not fitted, so an export through
    the five-map preset that writes BaseColor is refused before anything is written, naming
    recording R-090 and decision 103; the same export without BaseColor writes its files."""
    spec_path = spec(tmp_path / "spec", GRID)
    out = tmp_path / "out"
    result = export(
        export_tests,
        spec_path,
        shipped_config(FIVE_MAP, exportPath=out.as_posix()),
        tmp_path / "run",
    )
    assert result.get("error") == "NotYetSupported", result
    for fragment in ("sRGB8 channel BaseColor", "R-090", "decision 103"):
        assert fragment in result["message"], result["message"]
    assert files_under(out) == {}
    no_basecolor = shipped_config(
        FIVE_MAP,
        exportPath=out.as_posix(),
        exportList=[
            {
                "rootPath": "s0",
                "filter": {"outputMaps": ["$textureSet_Roughness", "$textureSet_Height"]},
            }
        ],
    )
    written = export(export_tests, spec_path, no_basecolor, tmp_path / "run2")
    assert "error" not in written, written
    assert sorted(files_under(out)) == ["s0_Height.png", "s0_Roughness.png"]


# ── Tier 0 (owner's machine) ─────────────────────────────────────────────────

PLANE_GOLDEN = "semantics/height-normal-plane-amplitudes"


def test_five_map_preset_normal_equals_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """3.1 (the part the current envelope records): the five-map preset's Normal map, written by
    WriteExport on the rebuilt plane goldens (s0-s3), is byte-identical to the Normal_OpenGL PNG 16
    file Painter exported (r1, and r2 where it equals r1, decision 032). The preset's other maps
    have no Painter record on a UzmiGames fixture yet (recording R-095)."""
    needs_store()
    golden = load(locate(), manifest_root(current_envelope()) / "tier0" / f"{PLANE_GOLDEN}.json")
    manifest = golden.manifest
    [step] = [
        s["step"]
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"].endswith("export_project_textures")
        and "virtualMap/Normal_OpenGL:RGB" in s["args"]["maps"]
        and s["args"].get("file_format", "png") == "png"
    ]
    compared = 0
    for texture_set_name in ("s0", "s1", "s2", "s3"):
        workdir = tmp_path / texture_set_name
        built = export_spec(manifest, texture_set_name, workdir / "spec")
        built["mesh"] = str(_mesh_of(manifest))
        out = workdir / "out"
        config = shipped_config(
            FIVE_MAP,
            exportPath=out.as_posix(),
            exportList=[
                {"rootPath": texture_set_name, "filter": {"outputMaps": ["$textureSet_Normal"]}}
            ],
        )
        result = write_export(export_tests, built, workdir / "spec", config, workdir / "run")
        assert "error" not in result, result
        [written] = result["written"]
        assert written["relativePath"] == f"{texture_set_name}_Normal.png"
        r1 = _painter_files(golden, "r1", step, texture_set_name)
        painter_name = f"{texture_set_name}_Normal_OpenGL.png"
        assert written["sha256"] == r1[painter_name], f"{texture_set_name}: differs from r1"
        r2 = _painter_files(golden, "r2", step, texture_set_name).get(painter_name)
        if r2 == r1[painter_name]:
            assert written["sha256"] == r2
        compared += 1
    assert compared == 4


# ── 3.4 Guard ────────────────────────────────────────────────────────────────


def test_shipped_presets_pass_the_guard() -> None:
    """3.4: no shipped preset file or record holds a private oracle record, and none matches a
    private-store hash (the repository guard of P0-STORE, with the owner's store index where it
    exists); the guard does see these files: an index holding a preset's hash blocks it."""
    snapshot = worktree_snapshot(REPO_ROOT, ["assets/export-presets/"])
    assert sorted(snapshot.checked) == sorted(
        f"assets/export-presets/{p.name}" for p in PRESETS.iterdir()
    )
    root = default_root()
    index_path = root / "index.json" if root is not None else None
    index = load_index(index_path) if index_path is not None and index_path.is_file() else None
    assert run_guard(REPO_ROOT, snapshot, index) == []
    planted = frozenset(content_hashes((PRESETS / f"{FIVE_MAP}.json").read_bytes()))
    findings = run_guard(REPO_ROOT, snapshot, planted)
    assert [(f.path, f.rule) for f in findings] == [
        (f"assets/export-presets/{FIVE_MAP}.json", "store-hash")
    ]
    if index is None:
        pytest.skip(
            "no private store index on this machine: the store-hash rule ran on a planted "
            "index only (hosted CI, decision 028)"
        )
