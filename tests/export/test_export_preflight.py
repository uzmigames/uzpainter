"""SUP-035 (decision 091, amended): the dry run's preflight (`src/export/guards.h`).

`uzp-export-tests.exe preflight` runs `PreflightExport` on a spec's plan, counting every resource
read, then the export itself (`WriteExport`), so each case compares the preflight with what the
export does on the same plan:
- a refused file is `blocked` with the export's own NotYetSupported message, and the whole
  preflight is `blocked` when any file is (the export is all or nothing);
- a file whose UV coverage is not available is `needs_evaluation`;
- an admitted file is `no_known_blocker`;
- the preflight reads no image, leaves the plan as it was and writes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.export.test_export_encoders import (
    GRID,
    SPHERE,
    TEMPLATES,
    chan,
    config,
    files_under,
    run,
    spec,
)

INFINITE = 'the padding "infinite" on a texture set whose UV islands do not cover the whole tile'
ISLAND_NORMAL = "reads the combined virtual normal on a texture set whose UV islands do not cover"


def preflight(exe: Path, spec_path: Path, cfg: dict[str, Any], tmp: Path) -> dict[str, Any]:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    [result] = run(exe, "preflight", str(TEMPLATES), str(spec_path), str(tmp / "config.json"))
    # Side-effect free: no image read, the plan unchanged, nothing written before the export.
    assert result["resource_reads"] == 0, result
    assert result["plan_after"] == result["plan"]
    assert result["written_before_export"] is False
    return result


def statuses(result: dict[str, Any]) -> dict[str, str]:
    return {f["relative_path"]: f["status"] for f in result["preflight"]["files"]}


def test_an_admitted_plan_has_no_known_blocker(export_tests: Path, tmp_path: Path) -> None:
    """On the grid (complete coverage) every file is `no_known_blocker`, one per planned file in
    plan order, and the export writes them; the preflight read none of the bitmaps the export
    evaluates."""
    out = tmp_path / "out"
    result = preflight(export_tests, spec(tmp_path / "spec", GRID), config(out), tmp_path / "run")
    planned = [f["relativePath"] for f in result["plan"]["files"]]
    assert [f["relative_path"] for f in result["preflight"]["files"]] == planned
    assert set(statuses(result).values()) == {"no_known_blocker"}
    assert result["preflight"]["status"] == "no_known_blocker"
    assert all("reason" not in f for f in result["preflight"]["files"])
    assert sorted(result["export"]["written"]) == sorted(planned) == sorted(files_under(out))


def test_infinite_padding_on_islands_is_blocked_with_the_exports_reason(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 259: on the sphere, whose UV islands leave texels uncovered, `infinite` padding is
    `blocked` for every file with exactly the message the export then raises, naming its owner,
    recording and decisions; nothing is written."""
    out = tmp_path / "out"
    sphere = spec(tmp_path / "spec", SPHERE, "uzp_sphere")
    result = preflight(export_tests, sphere, config(out, root="uzp_sphere"), tmp_path / "run")
    files = result["preflight"]["files"]
    assert result["preflight"]["status"] == "blocked"
    assert {f["status"] for f in files} == {"blocked"}
    assert all(INFINITE in f["reason"] and f["type"] == "NotYetSupported" for f in files), files
    assert files[0]["references"] == [
        "decision 220",
        "phase1.25_pilot-wand",
        "R-090",
        "decision 090",
        "decision 259",
    ], files[0]
    assert result["export"] == {"error": "NotYetSupported", "message": files[0]["reason"]}
    assert files_under(out) == {}


def test_an_island_normal_is_blocked_with_and_without_a_height(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 245: a Normal_OpenGL file on the sphere is `blocked` under `passthrough` and
    `infinite`, with a layer writing the Height and with none, with the export's own message."""
    for height in (True, False):
        sphere = spec(tmp_path / f"spec-{height}", SPHERE, "uzp_sphere", height=height)
        for padding in ("passthrough", "infinite"):
            out = tmp_path / f"out-{height}-{padding}"
            cfg = config(out, root="uzp_sphere", paddingAlgorithm=padding)
            cfg["exportPresets"][0]["maps"] = [
                {
                    "fileName": "$textureSet_n",
                    "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
                }
            ]
            cfg["exportParameters"] = cfg["exportParameters"][:1]
            result = preflight(export_tests, sphere, cfg, tmp_path / f"run-{height}-{padding}")
            [file] = result["preflight"]["files"]
            assert file["status"] == "blocked" and ISLAND_NORMAL in file["reason"], file
            assert "decision 245" in file["references"], file
            assert result["export"] == {"error": "NotYetSupported", "message": file["reason"]}
            assert files_under(out) == {}


def test_unknown_coverage_needs_evaluation(export_tests: Path, tmp_path: Path) -> None:
    """Without a texturing mesh the coverage is not available: every file is `needs_evaluation`,
    never admitted (the export then fails for want of the coverage); a processing refusal, which
    needs no coverage, is still `blocked`."""
    bare = spec(tmp_path / "spec", None)
    result = preflight(export_tests, bare, config(tmp_path / "out"), tmp_path / "run")
    files = result["preflight"]["files"]
    assert result["preflight"]["status"] == "needs_evaluation"
    assert {f["status"] for f in files} == {"needs_evaluation"}
    assert all("the spec has no mesh" in f["reason"] and "references" not in f for f in files)
    assert (
        result["export"]["error"] == "Failure"
        and "no texturing mesh" in result["export"]["message"]
    )

    dithered = config(
        tmp_path / "out-dithered",
        [
            {
                "filter": {"outputMaps": ["maps/$textureSet_Roughness"]},
                "parameters": {"bitDepth": "8", "dithering": True},
            }
        ],
    )
    result = preflight(export_tests, bare, dithered, tmp_path / "run-dithered")
    assert statuses(result)["maps/s0_Roughness.png"] == "blocked"
    assert result["preflight"]["status"] == "blocked"


def test_a_mixed_plan_blocks_the_whole_batch(export_tests: Path, tmp_path: Path) -> None:
    """One refused file blocks the export of every file: the preflight is `blocked` while the
    other files have no known blocker, and the export raises that file's message and writes
    none of them."""
    out = tmp_path / "out"
    cfg = config(
        out,
        [
            {
                "filter": {"outputMaps": ["maps/$textureSet_Roughness"]},
                "parameters": {"bitDepth": "8", "dithering": True},
            }
        ],
    )
    result = preflight(export_tests, spec(tmp_path / "spec", GRID), cfg, tmp_path / "run")
    assert statuses(result) == {
        "s0_User0.png": "no_known_blocker",
        "maps/s0_Roughness.png": "blocked",
        "s0_Height.exr": "no_known_blocker",
    }
    assert result["preflight"]["status"] == "blocked"
    [blocked] = [f for f in result["preflight"]["files"] if f["status"] == "blocked"]
    assert "dithering at PNG 8 bits" in blocked["reason"]
    assert blocked["references"] == [
        "R-090",
        "decision 103",
        "decision 349",
        "phase3.2_unreal-ue56-packed-preset",
    ], blocked
    assert result["export"] == {"error": "NotYetSupported", "message": blocked["reason"]}
    assert files_under(out) == {}


def test_normal_statistics_without_coverage_need_evaluation(
    export_tests: Path, tmp_path: Path
) -> None:
    """SUP-039: a statistics file of the combined normal (regionStats/Normal_OpenGL) reads the
    island-edge texels, so it needs its set's UV coverage. When the project's texturing mesh does
    not re-derive (its bytes are not stored), it is `needs_evaluation` with the re-derive's own
    error, never `no_known_blocker`, while the export, which has the coverage, refuses it; when
    the mesh re-derives, the island check blocks it with the export's message. A statistics file
    of another map needs no coverage, and a project with no texturing mesh at all has no UV
    islands, as the export reads it."""

    def stats(name: str, mesh: Path | None, reference: str | None) -> tuple[Path, str]:
        root = "uzp_sphere" if mesh else "s0"
        path = spec(tmp_path / name, mesh, root)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["layers"][0]["uid"] = 501
        if reference is not None:
            document["mesh_reference"] = reference
        path.write_text(json.dumps(document), encoding="utf-8")
        return path, root

    def stats_config(out: Path, root: str) -> dict[str, Any]:
        cfg = config(out, root=root, paddingAlgorithm="passthrough")
        cfg["exportPresets"][0]["maps"] = [
            {"fileName": f"$textureSet_{name}", "channels": [chan("L", "diagnosticMap", source)]}
            for name, source in (
                ("n", "regionStats/Normal_OpenGL/501"),
                ("b", "regionStats/BaseColor/501"),
            )
        ]
        cfg["exportParameters"] = cfg["exportParameters"][:1]
        return cfg

    def by_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {f["map"]: f for f in result["preflight"]["files"]}

    missing, root = stats("missing", SPHERE, "missing")
    out = tmp_path / "out-missing"
    result = preflight(export_tests, missing, stats_config(out, root), tmp_path / "run-missing")
    files = by_map(result)
    normal, base = files["$textureSet_n"], files["$textureSet_b"]
    assert result["mesh_reads"] >= 1, result
    assert normal["status"] == "needs_evaluation", normal
    assert "the texturing mesh does not re-derive" in normal["reason"], normal
    assert "is not stored" in normal["reason"], normal
    assert base["status"] == "no_known_blocker", base
    assert result["preflight"]["status"] == "needs_evaluation"
    assert result["export"]["error"] == "NotYetSupported", result["export"]
    assert ISLAND_NORMAL in result["export"]["message"]
    assert files_under(out) == {}

    stored, root = stats("stored", SPHERE, "stored")
    result = preflight(
        export_tests, stored, stats_config(tmp_path / "out-stored", root), tmp_path / "run-stored"
    )
    normal = by_map(result)["$textureSet_n"]
    assert result["mesh_reads"] >= 1, result
    assert normal["status"] == "blocked" and ISLAND_NORMAL in normal["reason"], normal
    assert result["export"] == {"error": "NotYetSupported", "message": normal["reason"]}

    absent, root = stats("absent", None, None)
    result = preflight(
        export_tests, absent, stats_config(tmp_path / "out-absent", root), tmp_path / "run-absent"
    )
    assert {f["status"] for f in result["preflight"]["files"]} == {"no_known_blocker"}, result
