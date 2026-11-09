"""glTF PBR Metal Roughness on the pilots (phase3.1_unreal-gltf-pbr-preset items 3.1, 3.2).

Item 3.1: each pilot's glTF golden (`phase3/tier1/<pilot>-gltf`, written by
`tools/parity/recorder/gltf_pilots.py`) is the pilot's admitted Tier 1 golden closed by Painter's
own export of its predefined glTF preset (`export-preset-generator://gltf`, PNG 16, the pilot's
size, `infinite` padding, no dithering).
UzPainter rebuilds it twice through the Wand's runner, every export the production export: the
Wand and the Sash run their pinned `painter_export.py` and then the same configuration as a
closing export (`Wand.closing_export`), the Tunic its native job with the configuration as its
one export. UzPainter resolves the URL to the authored `gltf-pbr-metal-roughness` preset
(`src/export/preset_aliases.cpp`). Every map, the glTF files and the script's five, is compared in
decoded values with Painter's r1, each judged with the exceptions its receipt names (EXC-013 for
the padding, EXC-014 for the Normal's island edge; decisions 414, 417). A pass is a pass under
those, never exact.

Item 3.2: the Wand's first rebuild's published glTF generation is consumed by the pinned fastgltf
0.9.1 (`tools/consumers/gltf.py`): base colour, metallic-roughness and occlusion (one ORM file),
normal; emissive bound only when the preset wrote it (glTF 2.0: `emissiveTexture` optional,
`emissiveFactor` default [0, 0, 0]), else the receipt must report it skipped. The packing
references are the same rebuild's independent Roughness and Metallic PNG 16 files.

It runs only when `UZP_TIER1_PRODUCTION=1` (six GPU rebuilds, never part of the suite), on the
owner's machine, and prints per-map counts (`GLTF_<PILOT>:`) and the consumer report summary
(`GLTF_CONSUMER:`). With `UZP_GLTF_REPORTS=1` it writes each comparison report to
`parity/reports/phase3/tier1-<pilot>-gltf.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d.client import GPU_DEADLINE_ENV
from tests.adapters.assets3d.wand import ASSETS3D
from tests.export.test_gltf_consumer import gltf_consumer  # noqa: F401  (the fixture)
from tests.parity.tier1.test_mcp_round import (
    fast_painter,  # noqa: F401  (the fixture)
    painter_ocio,
)
from tests.parity.tier1.tunic_recipe import GPU_DEADLINE_MS
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tests.parity.tier1.wand_v1.test_wand_production import PRODUCTION_ENV, counts
from tools.consumers.gltf import run_fixture
from tools.parity.coverage import obj_materials
from tools.parity.recorder.gltf_pilots import PILOT_GOLDENS
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import CandidateRun, write_report
from tools.parity.verdict import resolve_golden

PRODUCTION_EXCEPTIONS = frozenset({"EXC-013", "EXC-014"})
GLTF_MAPS = ("baseColor", "occlusionRoughnessMetallic", "normal")
CONSUMER_MANIFEST = REPO_ROOT / "parity/manifests/consumers/gltf/wand-v1.json"

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]


def golden_id(pilot: str) -> str:
    found = PILOT_GOLDENS[pilot][1]
    if resolve_golden(found) is None:
        pytest.skip(f"{found} is not admitted")
    return found


def compared(
    painter: Path, work: Path, pilot: str
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun]]:
    """The report and the two production rebuilds, under each pilot's own conditions: the Wand
    as its Tier 1 runs, the Sash under the manifest's `OCIO`, the Tunic under `OCIO` with its
    GPU deadline (its 4096 px exports outlast the default)."""
    found = golden_id(pilot)
    with pytest.MonkeyPatch.context() as patch:
        if pilot != "wand-v1":
            patch.setenv("OCIO", str(painter_ocio()))
        if pilot == "tunic-v10":
            patch.setenv(GPU_DEADLINE_ENV, str(GPU_DEADLINE_MS))
        report, runs = wand_runner.compared(painter, work, found, Path("unused"))
    print(f"GLTF_{pilot.upper()}: " + json.dumps(counts(report) if not runs[0].refused else {}))
    if os.environ.get("UZP_GLTF_REPORTS") == "1":
        write_report(report, REPO_ROOT / f"parity/reports/phase3/tier1-{pilot}-gltf.json")
    return report, runs


def check(report: dict[str, Any], runs: tuple[CandidateRun, CandidateRun]) -> None:
    """Neither rebuild refused; the glTF preset wrote exactly baseColor, the ORM and normal; every
    file relies on EXC-013 and only a Normal on EXC-014; equal to Painter under those;
    byte-identical rebuilds."""
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    gltf = {key for key in runs[0].files if key[1].rsplit("_", 1)[-1] in GLTF_MAPS}
    assert sorted(key[1].rsplit("_", 1)[-1] for key in gltf) == sorted(GLTF_MAPS), gltf
    for run in runs:
        for key, relied in run.exceptions.items():
            normal = key[1].lower().endswith("_normal")
            assert relied <= PRODUCTION_EXCEPTIONS and ("EXC-014" in relied) <= normal, (
                key,
                relied,
            )
    equality = report["equality_to_painter"]
    assert equality["structural"] == [], equality["structural"]
    assert equality["outcome"] == "pass", (equality["outcome"], counts(report))
    assert {e["exception_id"] for e in equality["exceptions_relied_on"]} <= PRODUCTION_EXCEPTIONS
    assert report["uzpainter_repeatability"]["status"] == "repeatable"


def test_wand_v1_gltf_export_equals_painter_and_loads_in_fastgltf(
    fast_painter: Path,  # noqa: F811
    gltf_consumer: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    report, runs = compared(fast_painter, tmp_path / "wand", "wand-v1")
    check(report, runs)
    root = tmp_path / "wand" / "run-1" / "closing-export"
    by_suffix = {key[1].rsplit("_", 1)[-1]: path for key, path in runs[0].files.items()}
    orm = by_suffix["occlusionRoughnessMetallic"].name
    bindings = {
        "baseColor": by_suffix["baseColor"].name,
        "metallicRoughness": orm,
        "normal": by_suffix["normal"].name,
        "occlusion": orm,
    }
    references = {
        name: {"path": str(path), "sha256": wand_runner.sha256_of(path)}
        for name, path in (
            ("roughness", by_suffix["Roughness"]),
            ("metallic", by_suffix["Metallic"]),
        )
    }
    mesh = next((tmp_path / "wand" / "run-1" / "assets").rglob("*_low.obj"))
    [material] = obj_materials(mesh)
    consumer = run_fixture(
        root,
        mesh,
        bindings,
        references,
        tmp_path / "consumer",
        gltf_consumer,
        CONSUMER_MANIFEST,
        mesh_material=material,
    )
    summary = {
        "status": consumer["status"],
        "generation": consumer["generation"],
        "receipt_sha256": consumer["receipt_sha256"],
        "mesh": consumer["consumer"]["mesh"],
        "material": consumer["consumer"]["material"],
        "bindings": {s: b["sha256"] for s, b in consumer["consumer"]["bindings"].items()},
        "packing": consumer["packing"],
        "consumer_gaps": [g.get("slot", g.get("gap")) for g in consumer["consumer_gaps"]],
    }
    print("GLTF_CONSUMER: " + json.dumps(summary, sort_keys=True))
    assert consumer["status"] == "pass"
    assert consumer["consumer"]["material"]["emissiveFactor"] == [0, 0, 0]
    assert any(g.get("slot") == "emissive" for g in consumer["consumer_gaps"])


def test_sash_v5_gltf_export_equals_painter(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    check(*compared(fast_painter, tmp_path, "sash-v5"))


def test_tunic_v10_gltf_export_equals_painter(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    check(*compared(fast_painter, tmp_path, "tunic-v10"))
