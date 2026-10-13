"""The worker's Diagnostics tools (docs/architecture/11-mcp-server.md §2; task
phase2.1_recipe-diagnostic-views item 2.6; decision 136), through the worker's pipe with the test
process as its supervisor.

CPU only: the worker runs `--gpu-backend vulkan` (no device), and the Diagnostics tools are
GPU-free. Each tool's output is compared with `uzpainter.diagnostics` on the same saved project
(`UzPainter.exe run`): the exported files hold the same float32 values as the Python views.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tests.supervisor.conftest import PLANE, Pipe, run_script
from tools.parity.fit.decode import decode

PROJECT = """
from uzpainter import colormanagement as cm, diagnostics, layerstack as ls, project, resource
from uzpainter import export, textureset as ts
CT = ts.ChannelType
project.create(PLANE, project.Settings(default_texture_resolution=256))
stack = ts.get_active_stack()
top = ls.InsertPosition.from_textureset_stack(stack)
half = resource.import_project_resource(IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE)
mat = ls.insert_fill(top)
mat.active_channels = {CT.SpecularRoughness, CT.BaseColor}
mat.set_source(CT.SpecularRoughness, cm.Color(0.2, 0.2, 0.2, "Raw"))
mat.set_source(CT.BaseColor, cm.Color(0.7, 0.3, 0.1, "Raw"))
mat.add_mask(ls.MaskBackground.Black)
mask_fill = ls.insert_fill(ls.InsertPosition.inside_node(mat, ls.NodeStack.Mask))
mask_fill.set_source(None, half.identifier())
leak = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
leak.active_channels = {CT.SpecularRoughness}
leak.set_source(CT.SpecularRoughness, cm.Color(0.6, 0.6, 0.6, "Raw"))
leak.set_opacity(0.5, CT.SpecularRoughness)
project.save_as(PATH)

def save(name, m):
    with open(WORK + "/" + name + ".bin", "wb") as out:
        out.write(m["values"])
    return [m["height"], m["width"], m["components"]]

iso = diagnostics.isolate(leak, CT.SpecularRoughness)
views = diagnostics.material_views(mat)

# The material's mask, views and leaks exported as sources, each computed by the export (B19).
sources = [(views["mask_source"], 1)]
for v in views["views"].values():
    sources += [(v["source"], v["values"]["components"]), (v["leaks_source"], 1)]
maps = [{"fileName": "$textureSet_" + name.replace("/", "_"), "channels": [
    {"destChannel": c, "srcChannel": c, "srcMapType": "diagnosticMap", "srcMapName": name}
    for c in ("RGB" if n == 3 else "L")]} for name, n in sources]
written = export.export_project_textures({
    "exportPath": WORK + "/views", "exportShaderParams": False, "defaultExportPreset": "d",
    "exportPresets": [{"name": "d", "maps": maps}], "exportList": [{"rootPath": "uzp_plane"}],
    "exportParameters": [{"parameters": {"fileFormat": "exr", "bitDepth": "32f",
                                         "dithering": False, "paddingAlgorithm": "passthrough"}}]})
result = {"mat": mat.uid(), "leak": leak.uid(), "revision": project.revision(),
          "snapshot": diagnostics.snapshot_layer_tree(),
          "iso": save("iso", iso["map"]), "mask": save("mask", views["mask"]),
          "rough": save("rough", views["views"]["Roughness"]["values"]),
          "leaks": {name: v["leak_count"] for name, v in views["views"].items()},
          "views_export": {f["relative_path"]: f["sha256"] for f in written["files"]},
          "stats": diagnostics.region_stats("BaseColor", mat)}
"""


def saved(work: Path, name: str, shape: list[int]) -> Any:
    return np.frombuffer((work / f"{name}.bin").read_bytes(), dtype="<f4").reshape(shape)


def exported(path: str) -> Any:
    decoded = decode(Path(path).read_bytes())
    assert not decoded.integer and decoded.bits == 32
    return decoded.values.astype(np.float32)


def test_diagnostics_tools_equal_the_python_views(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    project = tmp_path / "diag.uzp"
    images = Path(__file__).resolve().parents[2] / "parity" / "fixtures" / "api-probes"
    py = run_script(
        painter,
        tmp_path,
        f"PLANE = {PLANE.as_posix()!r}\nIMAGES = {images.as_posix()!r}\n"
        f"PATH = {project.as_posix()!r}\nWORK = {work.as_posix()!r}\n" + PROJECT,
    )
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    tools = {t["name"]: t for t in pipe.request({"method": "tools/list"})["result"]["tools"]}
    for name in (
        "snapshot_layer_tree",
        "diff_snapshots",
        "isolate_layer",
        "material_views",
        "region_stats",
    ):
        assert tools[name]["mutating"] is False and tools[name]["gpu"] is False, name
    revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
    assert revision == py["revision"]

    # snapshot_layer_tree and diff_snapshots.
    snapshot = pipe.call("snapshot_layer_tree")["result"]
    assert snapshot == py["snapshot"]
    diff = pipe.call("diff_snapshots", {"before": snapshot, "after": py["snapshot"]})["result"]
    assert (diff["added"], diff["removed"], diff["modified"]) == ([], [], [])
    bad = pipe.call("diff_snapshots", {"before": {"schema": "x"}, "after": snapshot})
    assert bad["error"]["code"] == "invalid_arguments"

    # isolate_layer: an export generation under the output root, equal to diagnostics.isolate.
    iso = pipe.call(
        "isolate_layer", {"uid": py["leak"], "channels": ["SpecularRoughness"], "path": "iso"}
    )
    result = iso["result"]
    assert iso["committed_revision"] == revision
    assert result["revision"] == revision and result["was_visible"] is True
    [file] = result["export"]["files"]
    assert file["source"] == f"isolated/SpecularRoughness/{py['leak']}"
    assert file["relative_path"] == f"uzp_plane_isolated_SpecularRoughness_{py['leak']}.exr"
    assert Path(file["path"]).is_relative_to((tmp_path / "out" / "iso").resolve())
    assert Path(result["export"]["receipt"]).is_file()
    assert np.array_equal(exported(file["path"]), saved(work, "iso", py["iso"]))

    # material_views: the mask, every view and its leaks exported; the summary is Python's.
    views = pipe.call("material_views", {"mask": py["mat"], "path": "views"})["result"]
    assert views["missing"] == ["ID"] and views["refused"] == {}
    assert {name: v["leak_count"] for name, v in views["views"].items()} == py["leaks"]
    assert py["leaks"]["Roughness"] == views["inside"] == 256 * 128
    files = {f["source"]: f["path"] for f in views["export"]["files"]}
    mat = py["mat"]
    assert list(files) == [f"materialMask/{mat}"] + [
        f"{kind}/{view}/{mat}"
        for view in ("BaseColor", "Height", "Normal", "Roughness", "Metallic")
        for kind in ("materialView", "materialLeaks")
    ]
    assert np.array_equal(exported(files[f"materialMask/{mat}"]), saved(work, "mask", py["mask"]))
    rough = exported(files[f"materialView/Roughness/{mat}"])
    assert np.array_equal(rough, saved(work, "rough", py["rough"]))
    # The tool writes the views its reply computed (B19, decision 246): the bytes an export that
    # computes every source writes.
    hashes = {f["relative_path"]: f["sha256"] for f in views["export"]["files"]}
    assert hashes == py["views_export"]

    # region_stats: Python's statistics.
    stats = pipe.call("region_stats", {"mask": mat, "map": "BaseColor"})["result"]
    assert stats == py["stats"] | {"revision": revision}

    # Refusals: a folder outside the output root, an unknown map, a node in no stack.
    outside = pipe.call(
        "isolate_layer", {"uid": mat, "channels": ["BaseColor"], "path": str(tmp_path)}
    )
    assert outside["error"]["code"] == "invalid_arguments"
    assert "output root" in outside["error"]["message"]
    unknown = pipe.call("region_stats", {"mask": mat, "map": "Bogus"})
    assert unknown["error"]["code"] == "invalid_arguments"
    missing = pipe.call("region_stats", {"mask": 999999, "map": "BaseColor"})
    assert missing["error"]["code"] == "call_failed"
    assert missing["error"]["details"]["type"] == "ValueError"
    assert pipe.call("project_inspect")["result"]["revision"] == revision
