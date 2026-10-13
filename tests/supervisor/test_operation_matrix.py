"""The requirement-to-typed-operation matrix through `UzPainter.exe --mcp` (task
phase2.7_mcp-operation-matrix; decision 182; `docs/architecture/11-mcp-server.md` §2, §6, §7).

- `tools/capabilities/mcp-tools.json`, the build's registered MCP tools the matrix generator reads,
  equals what a real worker lists (without and with `--allow-python`) and the supervisor's own
  tools. `UZP_UPDATE_MCP_TOOLS=1` rewrites it from the live listing.
- The matrix is published in `uzpainter://capabilities` as the shipped `capabilities.json` holds it.
- The Python-disabled conformance fixtures of the `available` rows no other test settles with Python
  disabled: an export with an inline configuration to OpenEXR, `isolate_layer`, the compare-mask
  and colour-selection effects, and the display, shader and camera tools.

Every supervisor runs on Vulkan with Python disabled, so no device is created and every call is
GPU-free.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from python.uzpainter_supervisor.registry import SUPERVISOR_TOOLS, _value_maps
from tests.supervisor.conftest import REPO_ROOT, Mcp, Pipe, make_project

BASE = ("--gpu-backend", "vulkan")
TOOLS_PATH = REPO_ROOT / "tools" / "capabilities" / "mcp-tools.json"
UPDATE_ENV = "UZP_UPDATE_MCP_TOOLS"
DESCRIPTION = (
    "The MCP tools the build registers (decision 182): the supervisor's own (served_by supervisor; "
    "opt_in --mcp-http for the HTTP-only lease tools) and the worker's (served_by worker; opt_in "
    "--allow-python for run_python), each with the capability-manifest operations it declares and "
    "the operations of each argument value it gates (values, by JSON pointer: "
    "x-uzpainter-capability). The worker's Debug-only --test-faults tools and the --preview tool "
    "preview_status are not listed. tests/supervisor/test_operation_matrix.py keeps it equal to a "
    "live worker's listing (UZP_UPDATE_MCP_TOOLS=1 rewrites it); the capability manifest generator "
    "reads it to check and derive the operation matrix (11-mcp-server.md §2)."
)


def snapshot(default: list[dict[str, Any]], allowed: list[dict[str, Any]]) -> dict[str, Any]:
    """`mcp-tools.json` of a worker's listings without and with `--allow-python`."""
    tools: list[dict[str, Any]] = [
        {
            "name": name,
            "served_by": "supervisor",
            "opt_in": "--mcp-http" if http_only else None,
            "operations": [],
            "values": {},
        }
        for name, (_, _, _, http_only) in SUPERVISOR_TOOLS.items()
    ]
    always = {tool["name"] for tool in default}
    for tool in allowed:
        tools.append(
            {
                "name": tool["name"],
                "served_by": "worker",
                "opt_in": None if tool["name"] in always else "--allow-python",
                "operations": tool["capability"],
                "values": dict(_value_maps(tool["inputSchema"])),
            }
        )
    tools.sort(key=lambda tool: str(tool["name"]))
    return {"description": DESCRIPTION, "tools": tools}


def render(document: dict[str, Any]) -> str:
    """One tool per line, as the other generator inputs."""
    lines = ",\n".join(
        "    " + json.dumps(tool, sort_keys=True, ensure_ascii=False) for tool in document["tools"]
    )
    description = json.dumps(document["description"], ensure_ascii=False)
    return f'{{\n  "description": {description},\n  "tools": [\n{lines}\n  ]\n}}\n'


def listing(painter: Path, tmp_path: Path, *args: str) -> list[dict[str, Any]]:
    pipe = Pipe(painter, tmp_path, *BASE, *args)
    try:
        tools: list[dict[str, Any]] = pipe.request({"method": "tools/list"})["result"]["tools"]
        return tools
    finally:
        pipe.close()


def opened(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> tuple[Mcp, int]:
    """A Python-disabled session on a saved plane project; its revision."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    reply = session.call("project_open", {"path": str(project), "wait": True})
    revision = reply["result"]["revision"]
    assert isinstance(revision, int)
    return session, revision


def inserted(reply: dict[str, Any]) -> int:
    assert "error" not in reply, reply
    uid = reply["result"]["returned"]["node"]
    assert isinstance(uid, int)
    return uid


def test_the_registered_tools_are_the_snapshot(painter: Path, tmp_path: Path) -> None:
    """2.4: the registered tools the build check reads are the tools a worker lists and the
    supervisor serves, with the operations each declares and gates by argument value."""
    default = listing(painter, tmp_path)
    allowed = listing(painter, tmp_path, "--allow-python")
    assert {tool["name"] for tool in default} < {tool["name"] for tool in allowed}
    live = snapshot(default, allowed)
    if os.environ.get(UPDATE_ENV) == "1":
        TOOLS_PATH.write_text(render(live), encoding="utf-8")
    assert json.loads(TOOLS_PATH.read_text(encoding="utf-8")) == live, (
        f"{TOOLS_PATH.name} differs from the live listing; rerun with {UPDATE_ENV}=1"
    )
    [python] = [tool for tool in live["tools"] if tool["opt_in"] == "--allow-python"]
    assert python["name"] == "run_python"


def test_the_matrix_is_published_in_uzpainter_capabilities(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.3, 3.3, 4.1: `uzpainter://capabilities` carries the shipped manifest's matrix, every
    required operation once; the gap families are capability gaps there and no row is satisfied by
    `run_python`."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    [content] = session.request("resources/read", {"uri": "uzpainter://capabilities"})["contents"]
    published = json.loads(content["text"])["operation_matrix"]
    shipped = json.loads((painter.parent / "capabilities.json").read_text(encoding="utf-8"))
    assert published == shipped["operation_matrix"]
    rows = {row["operation"]: row for row in published}
    assert len(rows) == len(published)
    for operation in ("bake.start", "stack.smart_material", "stack.procedural", "anchor.list"):
        assert rows[operation]["status"] == "capability gap", operation
    assert rows["mesh.reload"]["status"] == "available"
    assert rows["capture.painter_iray"]["gaps"] == [
        {
            "symbol": "uzpainter.render.capture",
            "context": "mode:painter_iray",
            "status": "release-gap",
        }
    ]
    for row in published:
        assert row["tool"] != "run_python" or row["status"] == "needs Python", row
        assert row["status"] != "available" or row["fixture"], row


def test_export_with_an_inline_configuration(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Fixture of `export.config` and `export.format.exr`: Painter's json_config given inline
    exports the roughness map as a 32-bit float OpenEXR."""
    session, _ = opened(painter, tmp_path, sessions)
    folder = tmp_path / "out" / "inline"
    config = {
        "exportPath": str(folder),
        "exportShaderParams": False,
        "defaultExportPreset": "rough",
        "exportPresets": [
            {
                "name": "rough",
                "maps": [
                    {
                        "fileName": "rough",
                        "channels": [
                            {
                                "destChannel": "L",
                                "srcChannel": "L",
                                "srcMapType": "documentMap",
                                "srcMapName": "roughness",
                            }
                        ],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "exr",
                    "bitDepth": "32f",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }
    reply = session.call("export", {"config": config, "wait": True})
    assert "error" not in reply, reply
    files = [Path(file["path"]) for file in reply["result"]["files"]]
    assert [path.suffix for path in files] == [".exr"]
    assert files[0].is_file() and files[0].read_bytes()[:4] == bytes([0x76, 0x2F, 0x31, 0x01])


def test_isolate_layer_publishes_the_layer_alone(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Fixture of `diagnostics.isolate_layer`: the layer's contribution is published as an export
    generation and the stack's visibility is unchanged."""
    session, _ = opened(painter, tmp_path, sessions)
    fill = inserted(session.call("layer_insert", {"kind": "fill", "name": "Alone"}))
    before = session.call("project_inspect")["result"]["revision"]
    reply = session.call("isolate_layer", {"uid": fill, "channels": ["BaseColor"], "path": "iso"})
    assert "error" not in reply, reply
    result = reply["result"]
    assert result["uid"] == fill and result["was_visible"] is True and result["export"]
    assert session.call("project_inspect")["result"]["revision"] == before


def test_compare_mask_and_color_selection_effects_are_gaps(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Fixture of the gap rows `effect.insert_compare_mask` and `effect.insert_color_selection`:
    the facade's insert is supported, but the typed tool performs the native insert
    (`uzpainter.layerstack.insert_*_effect`, a release gap owned by phase4.1_nodes-mask-effects),
    so each fails `capability_gap` before any mutation."""
    session, _ = opened(painter, tmp_path, sessions)
    fill = inserted(session.call("layer_insert", {"kind": "fill"}))
    masked = session.call("mask_set", {"uid": fill, "present": True, "background": "White"})
    assert masked["result"]["status"] == "committed", masked
    before = session.call("project_inspect")["result"]["revision"]
    for kind in ("compare_mask", "color_selection"):
        reply = session.call("effect_insert", {"uid": fill, "stack": "mask", "kind": kind})
        assert reply["error"]["code"] == "capability_gap", (kind, reply)
        [operation] = reply["error"]["details"]["operations"]  # refused before admission
        assert operation["symbol"] == f"uzpainter.layerstack.insert_{kind}_effect", reply
        assert (operation["argument"], operation["value"]) == ("/kind", kind), reply
        assert "phase4.1_nodes-mask-effects" in operation["notes"], reply
    assert session.call("project_inspect")["result"]["revision"] == before


def test_render_state_tools_without_python(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Fixtures of `display.*`, `shader.*` and `camera.*`: the reads, a refused display value
    (decision 038), the fixed pipeline's values accepted and a camera set in Blender's
    convention."""
    session, revision = opened(painter, tmp_path, sessions)
    assert session.call("display_get")["result"]["name"] == "common"
    assert session.call("shader_get")["result"]["shader"] == "open-pbr"
    assert session.call("camera_get")["result"] == {"camera": None, "blender": None}
    refused = session.call("display_set", {"exposure": 1.0})
    assert refused["error"]["details"]["type"] == "UnsupportedInUzPainter", refused
    same = session.call("display_set", {"exposure": 0.0, "background": [89, 89, 89]})
    assert same["result"]["status"] == "no_op", same
    shader = session.call("shader_set", {"parameters": {"double_sided": False}})
    assert "error" not in shader, shader
    blender = {
        "location": [0.0, -40.0, 1.0],
        "rotation_euler_degrees": [90.0, 0.0, 0.0],
        "type": "PERSP",
        "angle_degrees": 40.0,
        "lens_mm": 50.0,
        "ortho_scale": 2.5,
        "focus_distance": 40.0,
        "aperture_radius": 0.0,
    }
    camera = session.call("camera_set", {"blender": blender})
    assert (
        camera["result"]["status"] == "committed" and camera["committed_revision"] == revision + 1
    )
    assert session.call("camera_get")["result"]["blender"] == blender
