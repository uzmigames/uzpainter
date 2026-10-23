"""SUP-035 (decision 091, amended): the MCP `export` dry run's `preflight`, beside the unchanged
`plan` and `textures`, through `UzPainter.exe --mcp` with Python disabled.

The worker runs on Vulkan, where it has no device (`gpu_status` "unavailable"): a dry run that
needed the GPU could not answer at all.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tests.supervisor.conftest import REPO_ROOT, Mcp

SPHERE = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes" / "sphere.obj"
BASE = ("--gpu-backend", "vulkan", "--test-gpu-unavailable")


def rgb(kind: str, name: str) -> list[dict[str, str]]:
    return [
        {"destChannel": c, "srcChannel": c, "srcMapType": kind, "srcMapName": name} for c in "RGB"
    ]


def islands_config(out: Path) -> dict[str, Any]:
    """The sphere's BaseColor (a documentMap, admitted under passthrough on UV islands) and its
    Normal_OpenGL (refused on UV islands, decision 245)."""
    return {
        "exportPath": str(out),
        "defaultExportPreset": "p",
        "exportPresets": [
            {
                "name": "p",
                "maps": [
                    {
                        "fileName": "$textureSet_BaseColor",
                        "channels": rgb("documentMap", "baseColor"),
                    },
                    {
                        "fileName": "$textureSet_Normal",
                        "channels": rgb("virtualMap", "Normal_OpenGL"),
                    },
                ],
            }
        ],
        "exportList": [{"rootPath": "uzp_sphere"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "16",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }


def tree(root: Path) -> dict[str, str]:
    """The SHA-256 of every file under `root`; the open project's lock file, which the worker
    holds exclusively, by its presence only."""
    return {
        p.relative_to(root).as_posix(): "held"
        if p.suffix == ".lock"
        else hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_the_dry_run_preflight_blocks_a_mixed_plan_and_changes_nothing(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """On the sphere, whose UV islands leave texels uncovered: the dry run keeps `{dry_run,
    revision, plan, textures}` as they were and adds `preflight`. BaseColor has no known blocker
    and Normal_OpenGL is `blocked` with the reason and references of the real export's
    `capability_gap`, so the whole preflight is `blocked`. The dry run commits nothing, writes no
    file and changes no file of the project, on a worker without a GPU device."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    assert session.status()["gpu_status"] == "unavailable"
    created = session.call(
        "project_create",
        {"mesh": str(SPHERE), "settings": {"default_texture_resolution": 256}, "wait": True},
    )
    assert created["result"]["status"] == "committed", created
    fill = session.call(
        "layer_insert", {"kind": "fill", "params": {"active_channels": ["BaseColor", "Height"]}}
    )
    assert fill["result"]["status"] == "committed", fill
    project = tmp_path / "project" / "sphere.uzp"
    project.parent.mkdir()
    saved = session.call("project_save_as", {"path": str(project), "wait": True})
    assert "error" not in saved, saved
    revision = session.call("status")["result"]["revision"]
    files_before = tree(project.parent)
    out = tmp_path / "out" / "islands"
    config = islands_config(out)

    dry = session.call("export", {"config": config, "dry_run": True, "wait": True})
    result = dry["result"]
    assert set(result) == {"dry_run", "revision", "plan", "textures", "preflight"}, result
    assert result["dry_run"] is True and result["revision"] == revision
    # The legacy fields: the plan and Painter's list shape, unchanged.
    plan = result["plan"]
    planned = [f["relativePath"] for f in plan["files"]]
    assert {"exportPath", "files", "skipped", "hash"} <= set(plan), plan
    [listed] = result["textures"]
    assert set(listed) == {"texture_set", "stack", "files"}
    assert listed["texture_set"] == "uzp_sphere" and len(listed["files"]) == len(planned) == 2

    preflight = result["preflight"]
    assert set(preflight) == {"status", "note", "files"}
    assert preflight["status"] == "blocked" and "all or nothing" in preflight["note"]
    by_path = {f["relative_path"]: f for f in preflight["files"]}
    assert list(by_path) == planned
    base, normal = by_path["uzp_sphere_BaseColor.png"], by_path["uzp_sphere_Normal.png"]
    assert base["status"] == "no_known_blocker" and "reason" not in base, base
    assert normal["status"] == "blocked" and normal["type"] == "NotYetSupported", normal
    assert "reads the combined virtual normal" in normal["reason"], normal
    assert "decision 245" in normal["references"], normal

    # Side-effect free: no commit, no file written, the project's files as they were.
    assert session.call("status")["result"]["revision"] == revision
    assert not out.exists()
    assert tree(project.parent) == files_before

    # The real export refuses the whole batch with the same reason, and writes nothing.
    refused = session.call("export", {"config": config, "wait": True})
    assert refused["error"]["code"] == "capability_gap", refused
    assert refused["error"]["details"]["reason"] == normal["reason"]
    assert not out.exists() or not any(out.rglob("*.png"))
    assert session.call("status")["result"]["revision"] == revision
