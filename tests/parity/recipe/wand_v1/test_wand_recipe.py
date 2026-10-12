"""Recipe and diagnostics on Wand v1 (phase2.2_recipe-and-diagnostics items 3.1, 3.2; P2-RECIPE).

3.1 rebuilds Wand v1 from its recipe dump (`runner.py`) and compares the two projects' digests and
exports; the report goes to `UZP_RECIPE_REBUILD_REPORT` when that is set. 3.2 runs the diagnostics
on the wand: `isolate` on each root group, and `material_views` on each material group of the
stack, compared with OpenEXR 32f exports of the same project (padding `passthrough`).

Local run on the owner's machine (decision 028): it needs the UzmiGames asset repository
(`UZP_TEST_ASSETS3D`, default `E:\\UzmiGames\\Assets3D`) and `zig` for a fresh `zig build
painter`. No Painter golden is read: UzPainter is compared with itself. CPU only: the export and
the diagnostics run on the CPU evaluator. A comparison whose evaluation UzPainter refuses before
writing (`NotYetSupported`: an export processing or a source that is still a gap) is skipped with
the refusal as the reason; the refusal must be the same on both sides of the rebuild.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT, Wand
from tests.parity.recipe.wand_v1.runner import Scenario, job_manifest, run
from tests.parity.tier1.wand_v1.runner import built
from tools.parity.fit.decode import decode
from tools.parity.recipe_rebuild import write_report
from tools.parity.schemas import Schema, validation_errors

REPORT_ENV = "UZP_RECIPE_REBUILD_REPORT"  # repository-relative path of the report to write
F32 = npt.NDArray[np.float32]

pytestmark = pytest.mark.skipif(
    not (ASSETS3D / "AGENTS.md").is_file(),
    reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
)


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


@pytest.fixture(scope="module")
def scenario(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Scenario:
    return run(painter, tmp_path_factory.mktemp("rebuild"))


@pytest.fixture(scope="module")
def synced(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Wand:
    """Wand v1 created and synced through the adapter, left as the session's project."""
    return built(painter, tmp_path_factory.mktemp("diagnostics") / "wand", job_manifest())


# ── 3.1 Rebuild from the dump ───────────────────────────────────────────────────────────────────


def test_wand_rebuilt_from_its_dump_has_the_same_recipe(scenario: Scenario) -> None:
    """3.1: the project rebuilt from the dump and the bundle's resources dumps the same body,
    rebuild block and digest; an export refused before writing is refused alike on both sides."""
    report, original, rebuilt = scenario.report, scenario.original, scenario.rebuilt
    assert validation_errors(report, Schema.RECIPE_REBUILD_REPORT) == []
    assert rebuilt["digest"] == original["digest"]
    assert rebuilt["recipe"] == original["recipe"]
    assert rebuilt["rebuild"] == original["rebuild"]
    assert report["equality"]["digests_equal"] is True
    assert report["equality"]["outcome"] in ("pass", "export_refused"), report["equality"]
    if scenario.refusals:
        assert len(scenario.refusals) == 2 and len(set(scenario.refusals)) == 1, scenario.refusals


def test_wand_rebuilt_from_its_dump_exports_byte_identical_files(scenario: Scenario) -> None:
    """3.1, 4.1: every file of the wand's export configuration is byte-identical."""
    if scenario.refusals:
        pytest.skip(f"UzPainter refuses the wand's export before writing: {scenario.refusals[0]}")
    report = scenario.report
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    files = report["original"]["export"]["files"]
    assert len(files) == 5
    assert report["rebuilt"]["export"]["files"] == files
    assert report["equality"]["outcome"] == "pass", report["equality"]


# ── 3.2 Diagnostics ─────────────────────────────────────────────────────────────────────────────

# The documentMap of each material view's channel, and its components.
DOCUMENT_MAPS = {
    "BaseColor": ("basecolor", 3),
    "Height": ("height", 1),
    "Normal": ("normal", 3),
    "Roughness": ("roughness", 1),
    "Metallic": ("metallic", 1),
}

PROBE = """
import substance_painter.textureset as ts
import substance_painter.layerstack as ls
import uzpainter
from uzpainter import diagnostics, export

WORK = __WORK__
DOCUMENT_MAPS = __MAPS__
stack = ts.get_active_stack()

def save(name, m):
    path = WORK + "/" + name + ".bin"
    with open(path, "wb") as out:
        out.write(m["values"])
    return {"path": path, "shape": [m["height"], m["width"], m["components"]]}

def groups(nodes):
    return [n for n in nodes if hasattr(n, "sub_layers")]

def visibility():
    return [(n["uid"], n["visible"]) for n in diagnostics.snapshot_layer_tree()["nodes"]]

roots = groups(ls.get_root_layer_nodes(stack))
"""

ISOLATE = """
revision = uzpainter.project.revision()
before = diagnostics.snapshot_layer_tree()
visible = visibility()
isolated = [{k: v for k, v in diagnostics.isolate(n.uid(), "BaseColor").items()
             if k in ("source", "revision", "node")} for n in roots]
after = diagnostics.snapshot_layer_tree()
result = {"revision": [revision, uzpainter.project.revision()],
          "visible": [visible, visibility()], "diff": diagnostics.diff_snapshots(before, after),
          "roots": [n.uid() for n in roots], "isolated": isolated}
"""

# Each material group's views, or the refusal of its evaluation; then, when none was refused,
# the documentMap exports the views are compared with.
MATERIALS = """
materials = {}
refusals = {}
for root in roots:
    for group in groups(root.sub_layers()):
        if not group.has_mask():
            continue
        try:
            views = diagnostics.material_views(group.uid())
        except uzpainter.NotYetSupported as error:
            refusals[group.get_name()] = str(error)
            continue
        materials[group.get_name()] = {
            "uid": group.uid(), "inside": views["inside"], "missing": views["missing"],
            "refused": views["refused"], "mask": save("mask-%d" % group.uid(), views["mask"]),
            "views": {name: save("%s-%d" % (name, group.uid()), v["values"])
                      for name, v in views["views"].items()}}
files = {}
if not refusals:
    maps = [{"fileName": name, "channels": [
                {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap",
                 "srcMapName": source}
                for c in (["R", "G", "B"] if components == 3 else ["L"])]}
            for name, (source, components) in DOCUMENT_MAPS.items()]
    config = {"exportPath": WORK + "/document", "exportShaderParams": False,
              "defaultExportPreset": "d", "exportPresets": [{"name": "d", "maps": maps}],
              "exportList": [{"rootPath": stack.material().name()}],
              "exportParameters": [{"parameters": {"fileFormat": "exr", "bitDepth": "32f",
                                                   "dithering": False,
                                                   "paddingAlgorithm": "passthrough"}}]}
    exported = export.export_project_textures(config)["files"]
    files = {f["relative_path"]: f["path"] for f in exported}
result = {"materials": materials, "refusals": refusals, "files": files}
"""


def probe(wand: Wand, name: str, body: str) -> Any:
    """`body` run on the synced wand after the shared helpers, in a folder of its own."""
    work = wand.work / name
    work.mkdir()
    script = (PROBE + body).replace("__WORK__", repr(work.as_posix()))
    return wand.probe(name, script.replace("__MAPS__", repr(DOCUMENT_MAPS)))


def values(saved: dict[str, Any]) -> F32:
    """A diagnostic map the script saved: float32, shape (height, width, components)."""
    data = np.frombuffer(Path(saved["path"]).read_bytes(), dtype="<f4")
    return data.reshape(saved["shape"])


def exr(path: str) -> F32:
    """An OpenEXR 32f export as float32, shape (height, width, channels)."""
    decoded = decode(Path(path).read_bytes())
    assert not decoded.integer and decoded.bits == 32
    as_float: F32 = decoded.values.astype(np.float32)
    return as_float


def test_wand_isolate_on_each_root_group_restores_the_state(synced: Wand) -> None:
    """3.2: `isolate` on each root group leaves the revision, every visibility flag and the
    layer tree unchanged, and names its source and the revision it read."""
    r = probe(synced, "isolate", ISOLATE)
    assert r["roots"], "the wand has no root group"
    assert r["revision"][0] == r["revision"][1]
    assert r["visible"][0] == r["visible"][1]
    empty: dict[str, list[Any]] = {"added": [], "removed": [], "modified": []}
    assert {k: r["diff"][k] for k in empty} == empty and r["diff"]["stacks"] == empty, r["diff"]
    for uid, isolated in zip(r["roots"], r["isolated"], strict=True):
        assert isolated == {
            "source": f"isolated/BaseColor/{uid}",
            "revision": r["revision"][0],
            "node": uid,
        }


def test_wand_material_views_match_the_exported_maps(synced: Wand) -> None:
    """3.2: each material view of each material group equals the exported documentMap inside the
    group's effective mask and is 0 outside it."""
    r = probe(synced, "materials", MATERIALS)
    if r["refusals"]:
        pytest.skip(f"UzPainter refuses the wand's material views: {r['refusals']}")
    materials = r["materials"]
    assert len(materials) == 4  # wood, leather, iron, gem: the stack's material groups
    document = {name: exr(r["files"][f"{name}.exr"]) for name in DOCUMENT_MAPS}
    for material, found in materials.items():
        assert found["refused"] == {}, (material, found["refused"])
        assert found["missing"] == ["ID"], (material, found["missing"])  # no ID mesh map
        assert sorted(found["views"]) == sorted(DOCUMENT_MAPS), material
        inside = values(found["mask"])[..., 0] >= 0.5
        assert int(inside.sum()) == found["inside"] > 0, material
        for name, saved in found["views"].items():
            got = values(saved)
            expected = document[name]
            assert got.shape == expected.shape, (material, name)
            same = np.array_equal(got[inside].view(np.uint32), expected[inside].view(np.uint32))
            assert same, (material, name)
            assert np.all(got[~inside] == 0.0), (material, name)
