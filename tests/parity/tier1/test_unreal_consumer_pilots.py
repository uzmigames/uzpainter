"""UE 5.6 imports the pilots' Unreal Engine (Packed) production exports
(phase3.2_unreal-ue56-packed-preset items 2.8, 3.2 and 3.3; consumer-matrix row 8).

Each pilot is rebuilt and compared with Painter exactly as `test_unreal_pilots.py` does (item
3.1: equal under EXC-013 and EXC-014 only); the first rebuild's published generation of the
preset (PNG 16, Painter's own parameters for the pilot's golden) is then consumed by UE 5.6
through the generation-pinning adapter (`tools/consumers/unreal.py`). On the Wand v1, a third
build exports two more configurations of the same project: the DDS variant
(`unreal-engine-packed-dds`, the same parameters; each canonical PNG 16 must be byte-identical to
the compared PNG 16) and TGA 8 (dithering off: TGA 8 refuses it). UE imports the TGA 8 files with
their bindings and refuses every DDS (UE 5.6's DDS importer supports neither BC7 nor BC5; item
3.3's observation), then cooks the fixture for Windows, which compiles its materials and gives
each cooked texture's pixel format.

Runs only with `UZP_TIER1_PRODUCTION=1` and `UZP_UE_FIXTURE=1` on the owner's machine (GPU
rebuilds, UE 5.6 and the fixture project; decision 028). With `UZP_UE_CONSUMER_REPORTS=1` each
report is written to `tmp/scratch/unreal-consumer-<label>.json`, the material of the public
summary `parity/reports/phase3/unreal-consumer-wand-v1.md`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.export.test_unreal_consumer import DDS_REFUSALS
from tests.parity.tier1.test_mcp_round import fast_painter  # noqa: F401  (the fixture)
from tests.parity.tier1.test_unreal_pilots import check, compared, golden_id, unreal_map
from tests.parity.tier1.test_unreal_pilots import pytestmark as pilot_marks
from tests.parity.tier1.wand_v1.runner import built, sha256_of
from tools.consumers import unreal
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1.compare import CandidateRun
from tools.parity.verdict import resolve_golden

MANIFEST = REPO_ROOT / "parity/manifests/consumers/unreal/wand-v1.json"
UE_ENV = "UZP_UE_FIXTURE"

pytestmark = [
    *pilot_marks,
    pytest.mark.skipif(
        os.environ.get(UE_ENV) != "1" or not unreal.editor_cmd().is_file(),
        reason=f"opt-in local UE 5.6 run: set {UE_ENV}=1 on the owner's machine (decision 028)",
    ),
]

VARIANT_EXPORT_CODE = """import json

import substance_painter.export

spec = json.loads(__SPEC__)
exported = substance_painter.export.export_project_textures(spec["config"])
result = {
    "status": str(exported.status),
    "message": exported.message,
    "files": {str(key): list(files) for key, files in exported.textures.items()},
}
"""


def written(report: dict[str, Any], label: str) -> None:
    if os.environ.get("UZP_UE_CONSUMER_REPORTS") == "1":
        path = REPO_ROOT / f"tmp/scratch/unreal-consumer-{label}.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: report.get(k) for k in ("status", "failures", "generation")}
    print(f"UE_CONSUMER_{label.upper()}: " + json.dumps(summary))


def unreal_root(run: CandidateRun) -> Path:
    """The export directory (its `current.json`) holding the run's Unreal files: the one whose
    ORM it wrote (a script job's own export also writes a `_Normal`)."""
    roots = set()
    for key, path in run.files.items():
        if unreal_map(key[1]) != "OcclusionRoughnessMetallic":
            continue
        found = next((p for p in path.parents if (p / "current.json").is_file()), None)
        assert found is not None, path
        roots.add(found)
    [root] = roots
    return root


def imported(painter: Path, work: Path, pilot: str) -> tuple[Path, dict[str, Any]]:
    report, runs = compared(painter, work, pilot)
    check(report, runs)
    root = unreal_root(runs[0])
    consumer = unreal.run_fixture(root, f"{pilot}-png16", "png", MANIFEST)
    written(consumer, f"{pilot}-png16")
    assert consumer["status"] == "pass", consumer["failures"]
    return root, consumer


def variant(wand: Any, name: str, **changes: Any) -> Path:
    """One more configuration of the pilot's closing export on the built project: `changes`
    replaces the preset or merges into the parameters."""
    base = wand.pipeline.config_export.config
    out: Path = wand.work / f"{name}-export"
    out.mkdir()
    parameters = {**base["exportParameters"][0]["parameters"], **changes.get("parameters", {})}
    config = {
        **base,
        "exportPath": out.as_posix(),
        "defaultExportPreset": changes.get("preset", base["defaultExportPreset"]),
        "exportParameters": [{"parameters": parameters}],
    }
    code = wand.work / f"{name}-export.py"
    spec = repr(json.dumps({"config": config}))
    code.write_text(VARIANT_EXPORT_CODE.replace("__SPEC__", spec), encoding="utf-8")
    call = wand.run_file(code)
    assert call.status == 0, call.stdout + call.stderr
    assert str(call.document()["status"]).endswith("Success"), call.document()
    return out


def test_wand_v1_png16_tga8_and_dds_import_and_cook(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    root, png16 = imported(fast_painter, tmp_path / "wand", "wand-v1")
    resolved = resolve_golden(golden_id("wand-v1"))
    assert resolved is not None
    wand = built(fast_painter, tmp_path / "variants", resolved.manifest_path)
    assert wand.export().status == 0
    dds_root = variant(wand, "dds", preset="unreal-engine-packed-dds")
    tga_root = variant(wand, "tga8", parameters={"fileFormat": "tga", "bitDepth": "8"})
    # The DDS variant's canonical PNG 16 files are the compared PNG 16 files, byte for byte.
    for slot, texture in png16["textures"].items():
        canonical = next(dds_root.glob(f"generations/*/files/{texture['file']}"))
        assert sha256_of(canonical) == texture["sha256"], slot
    reports = {"png16": png16}
    tga8 = unreal.run_fixture(tga_root, "wand-v1-tga8", "png", MANIFEST)
    written(tga8, "wand-v1-tga8")
    assert tga8["status"] == "pass", tga8["failures"]
    assert {t["format"] for t in tga8["textures"].values()} == {"tga"}
    reports["tga8"] = tga8
    # Item 3.3, observed: UE 5.6's DDS importer supports none of BC7_SRGB, BC7 and BC5.
    dds = unreal.run_fixture(dds_root, "wand-v1-dds", "dds", MANIFEST)
    written(dds, "wand-v1-dds")
    assert dds["status"] == "fail"
    assert {r["slot"] for r in dds["refused"]} == {
        "BaseColor",
        "OcclusionRoughnessMetallic",
        "Normal",
    }
    assert set(dds["ue_log_errors"]) >= DDS_REFUSALS, dds["ue_log_errors"]
    # The cook compiles the fixture's materials for Windows and gives each texture's format.
    cook = unreal.cook()
    cook["fixtures"] = {label: unreal.cooked_textures(report) for label, report in reports.items()}
    written(cook | {"status": "cooked" if cook["returncode"] == 0 else "failed"}, "wand-v1-cook")
    assert cook["returncode"] == 0 and cook["uzfixture_errors"] == [], cook
    for label, textures in cook["fixtures"].items():
        for slot, entry in textures["textures"].items():
            assert entry["files"] and entry["pixel_formats"], (label, slot, entry)
    print("UE_COOK: " + json.dumps(cook["fixtures"], sort_keys=True))
    assert root.is_dir()


def test_sash_v5_png16_imports(fast_painter: Path, tmp_path: Path) -> None:  # noqa: F811
    imported(fast_painter, tmp_path, "sash-v5")


def test_tunic_v10_png16_imports(fast_painter: Path, tmp_path: Path) -> None:  # noqa: F811
    imported(fast_painter, tmp_path, "tunic-v10")
