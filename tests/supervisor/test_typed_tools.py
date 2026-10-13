"""The typed MCP tool families through `UzPainter.exe --mcp` (task phase2.6_mcp-typed-tool-families
items 3.1-3.6; decisions 164 and 165; `docs/architecture/11-mcp-server.md` §2, §3).

Every test drives the supervisor over stdio MCP with Python disabled, on synthetic UzmiGames
projects: the plane fixture made by `UzPainter.exe run` and the api-probes images. The worker runs
on Vulkan, so no device is created: every typed tool here is GPU-free (the capture's
`base_color` mode included).
"""

from __future__ import annotations

import base64
import json
import shutil
import zlib
from pathlib import Path
from typing import Any

from tests.supervisor.conftest import (
    OCIO_CONFIG,
    PLANE,
    REPO_ROOT,
    Mcp,
    Pipe,
    make_project,
    ocio_with_a_refused_bitmap,
    run_script,
)

PROBE_IMAGES = REPO_ROOT / "parity" / "fixtures" / "api-probes"
BASE = ("--gpu-backend", "vulkan")

# Every typed tool of 11 §2 the worker serves (the supervisor's own are listed separately).
TYPED = {
    "project_create",
    "project_open",
    "project_save",
    "project_save_as",
    "project_close",
    "project_inspect",
    "project_recipe",
    "project_revert",
    "set_list",
    "set_resolution",
    "set_rename",
    "set_channels",
    "set_mesh_maps",
    "resource_import",
    "resource_list",
    "resource_search",
    "resource_replace",
    "assets_search",
    "layer_list",
    "layer_insert",
    "layer_set",
    "layer_delete",
    "layer_instantiate",
    "effect_insert",
    "effect_set",
    "mask_set",
    "source_set",
    "fill_set",
    "procedural_set",
    "anchor_list",
    "smart_material_insert",
    "smart_mask_insert",
    "smart_export",
    "sync_stack",
    "apply_smart",
    "bake_inspect",
    "bake_configure",
    "bake_set_mesh_inputs",
    "bake_start",
    "bake_capture_preset",
    "bake_apply_preset",
    "export",
    "export_presets_list",
    "capture",
    "display_get",
    "display_set",
    "shader_get",
    "shader_set",
    "camera_get",
    "camera_set",
    "snapshot_layer_tree",
    "diff_snapshots",
    "isolate_layer",
    "material_views",
    "region_stats",
    "mesh_reload",
    "mesh_certificate",
}
OWN = {"status", "capabilities", "batch", "job_status", "job_result", "job_cancel", "job_list"}
# The families whose native implementation is not in this build (the tool itself is a gap).
GAP_CALLS: dict[str, dict[str, Any]] = {
    "resource_search": {"query": "rust"},
    "assets_search": {"query": "rust"},
    "layer_instantiate": {"source": 1},
    "procedural_set": {"uid": 1},
    "anchor_list": {},
    "smart_material_insert": {"asset": "uzasset://smart/rust@1"},
    "smart_mask_insert": {"uid": 1, "asset": "uzasset://smart/edges@1"},
    "smart_export": {"uid": 1, "kind": "material", "path": "smart.spsm"},
    "apply_smart": {"config_json": {"layers": []}},
    "bake_inspect": {},
    "bake_configure": {"texture_set": "uzp_plane"},
    "bake_set_mesh_inputs": {"texture_set": "uzp_plane"},
    "bake_start": {},
    "bake_capture_preset": {"path": "bake.json"},
    "bake_apply_preset": {"preset": {}},
}


def opened(painter: Path, tmp_path: Path, sessions: list[Mcp], *args: str) -> tuple[Mcp, int]:
    """A session on a saved plane project; its revision."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE, *args)
    sessions.append(session)
    reply = session.call("project_open", {"path": str(project), "wait": True})
    revision = reply["result"]["revision"]
    assert isinstance(revision, int)
    return session, revision


def revision_of(session: Mcp) -> Any:
    return session.call("status")["result"]["revision"]


def nodes(session: Mcp, **arguments: Any) -> dict[int, dict[str, Any]]:
    listed = session.call("layer_list", arguments)["result"]["nodes"]
    return {node["uid"]: node for node in listed}


def inserted(reply: dict[str, Any]) -> int:
    assert "error" not in reply, reply
    uid = reply["result"]["returned"]["node"]
    assert isinstance(uid, int)
    return uid


def png(width: int, height: int, grey: int) -> bytes:
    """An 8-bit grey PNG of one value."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    rows = b"".join(b"\x00" + bytes([grey]) * width for _ in range(height))
    signature = bytes([0x89]) + b"PNG\r\n\x1a\n"
    return (
        signature
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


# ── 3.1 per family ──────────────────────────────────────────────────────────────────────────────


def test_every_family_is_listed_with_its_capability_status(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.1-2.10, 3.5: every typed tool of 11 §2 is listed with its schema; the families whose
    native implementation is not in the build are listed as release gaps, and the values of an
    available tool that need a later family say so in `_meta`."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    tools = {tool["name"]: tool for tool in session.request("tools/list", {})["tools"]}
    assert set(tools) >= TYPED | OWN
    assert "run_python" not in tools and "lease_acquire" not in tools  # stdio, Python disabled
    status = {
        name: (tool.get("_meta") or {}).get("uzpainter/capability", {}).get("status")
        for name, tool in tools.items()
    }
    assert {name for name, value in status.items() if value == "release-gap"} == set(GAP_CALLS)
    values = {
        (v["argument"], v["value"]): v["status"]
        for v in tools["layer_insert"]["_meta"]["uzpainter/capability"]["values"]
    }
    assert values[("/kind", "fill")] == values[("/kind", "group")] == "available"
    assert values[("/kind", "paint")] == "release-gap"
    for name in ("project_create", "project_save_as", "mesh_reload", "export", "capture"):
        assert "wait" in tools[name]["inputSchema"]["properties"] or name == "capture", name
    assert tools["layer_set"]["inputSchema"]["required"] == ["uid"]
    assert tools["layer_set"]["inputSchema"]["properties"]["uid"]["x-uzpainter-ref"] == "node"


def test_stack_edit_with_python_disabled(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Spec scenario, 3.1 (Stack): `layer_insert` then `layer_set` commit, and their results and
    receipts carry the revision, the committed revision and the created and modified ids
    (INT-07)."""
    session, revision = opened(painter, tmp_path, sessions)
    reply = session.call("layer_insert", {"kind": "fill", "name": "Base"})
    uid = inserted(reply)
    assert reply["result"]["status"] == "committed" and reply["created"] == [uid]
    assert reply["revision"] == revision and reply["committed_revision"] == revision + 1
    receipt = reply["receipt"]
    assert receipt["project_uuid"] and receipt["job_id"] and receipt["admission"] == "executed"
    blending = {"BaseColor": {"mode": "Multiply", "opacity": 0.5}}
    changed = session.call("layer_set", {"uid": uid, "blending": blending, "visible": False})
    assert changed["result"]["status"] == "committed" and changed["changed"] == [uid]
    assert changed["revision"] == revision + 1 and changed["committed_revision"] == revision + 2
    node = nodes(session)[uid]
    assert node["visible"] is False and node["params"]["blending"]["BaseColor"] == {
        "mode": "Multiply",
        "opacity": 0.5,
    }


def test_project_and_texture_set_families(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.1 (Project, Texture sets): inspect a file without opening it, the recipe, revert, the
    texture sets' list, resolution, rename (another set's name refused, the same name a no-op),
    channels and mesh maps, save_as."""
    session, revision = opened(painter, tmp_path, sessions)
    file_report = session.call("project_inspect", {"path": str(tmp_path / "plane.uzp")})["result"]
    assert file_report["open"] is False and file_report["report"]["texture_sets"]
    recipe = session.call("project_recipe")["result"]
    assert recipe["revision"] == revision and len(recipe["digest"]) == 64

    [listed] = session.call("set_list")["result"]["texture_sets"]
    assert listed["name"] == listed["original_name"] == "uzp_plane"
    assert listed["resolution"] == {"width": 256, "height": 256}
    sized = session.call("set_resolution", {"width": 512, "height": 512})
    assert sized["result"]["status"] == "committed"
    renamed = session.call("set_rename", {"texture_set": "uzp_plane", "name": "body"})
    assert renamed["result"]["status"] == "committed"
    same = session.call("set_rename", {"texture_set": "body", "name": "body"})
    assert same["result"]["status"] == "no_op"
    [after] = session.call("set_list")["result"]["texture_sets"]
    assert (after["name"], after["original_name"]) == ("body", "uzp_plane")
    assert after["resolution"] == {"width": 512, "height": 512}

    channels = session.call(
        "set_channels",
        {
            "texture_set": "body",
            "add": [{"channel": "Emissive", "format": "sRGB8"}],
            "edit": [{"channel": "Height", "format": "L32F"}],
            "remove": ["BaseMetalness"],
        },
    )
    assert channels["result"]["status"] == "committed"
    [stack] = session.call("set_list")["result"]["texture_sets"][0]["stacks"]
    assert "Emissive" in stack["channels"] and "BaseMetalness" not in stack["channels"]
    assert stack["channels"]["Height"]["format"] == "L32F"
    duplicate = session.call(
        "set_channels", {"texture_set": "body", "add": [{"channel": "Emissive", "format": "L8"}]}
    )
    assert duplicate["error"]["code"] == "call_failed"
    assert revision_of(session) == revision + 3

    ao = tmp_path / "ao-white.png"
    shutil.copy(PROBE_IMAGES / "ao-white.png", ao)
    bound = session.call(
        "set_mesh_maps", {"texture_set": "body", "maps": {"AO": {"path": str(ao)}}}
    )
    assert bound["result"]["status"] == "committed" and bound["imported"]
    maps = session.call("set_list")["result"]["texture_sets"][0]["mesh_maps"]
    assert maps["AO"]["name"] == "ao-white"
    unbound = session.call("set_mesh_maps", {"texture_set": "body", "maps": {"AO": None}})
    assert unbound["result"]["status"] == "committed"
    assert session.call("set_list")["result"]["texture_sets"][0]["mesh_maps"] == {}

    reverted = session.call("project_revert", {"revision": revision})
    assert reverted["result"]["status"] == "committed"
    assert session.call("set_list")["result"]["texture_sets"][0]["name"] == "uzp_plane"
    both = session.call("project_revert", {"revision": 1, "checkpoint": "named"})
    assert both["error"]["code"] == "invalid_arguments"

    copy_path = tmp_path / "copy" / "plane-copy.uzp"
    saved = session.call("project_save_as", {"path": str(copy_path), "wait": True})
    assert saved["result"]["path"].endswith("plane-copy.uzp") and copy_path.is_file()
    assert session.call("status")["result"]["project"]["path"].endswith("plane-copy.uzp")


def test_resource_and_stack_families(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.1 (Resources, Stack): import, list and replace resources; effects in the content and
    mask stacks, masks, sources (uniform, bitmap, reset), fill settings and deletion."""
    session, _ = opened(painter, tmp_path, sessions)
    checker = tmp_path / "checker-16.png"
    shutil.copy(PROBE_IMAGES / "checker-16.png", checker)
    grey = tmp_path / "grey.png"
    grey.write_bytes(png(8, 8, 128))
    first = session.call(
        "resource_import", {"path": str(checker), "usage": "TEXTURE", "group": "g"}
    )
    resource = first["result"]["returned"]["resource"]
    assert resource["name"] == "checker-16" and resource["url"].startswith("resource://project/")
    again = session.call("resource_import", {"path": str(checker), "usage": "TEXTURE"})
    assert again["result"]["status"] == "no_op" and again["skipped"]
    second = session.call("resource_import", {"path": str(grey), "usage": "TEXTURE"})
    assert second["result"]["status"] == "committed"
    generator = session.call("resource_import", {"path": str(grey), "usage": "GENERATOR"})
    assert generator["error"]["code"] == "capability_gap"

    fill = inserted(
        session.call(
            "layer_insert",
            {"kind": "fill", "name": "Paint", "params": {"active_channels": ["BaseColor"]}},
        )
    )
    uniform = {"kind": "uniform_color", "color": [0.25, 0.5, 0.75], "color_space": "sRGB"}
    set_uniform = session.call(
        "source_set", {"uid": fill, "channel": "BaseColor", "source": uniform}
    )
    assert set_uniform["result"]["status"] == "committed"
    bitmap = {"kind": "bitmap", "resource": "checker-16", "color_space": "sRGB"}
    set_bitmap = session.call("source_set", {"uid": fill, "channel": "BaseColor", "source": bitmap})
    assert set_bitmap["result"]["status"] == "committed"
    source = nodes(session)[fill]["params"]["fill"]["sources"]["BaseColor"]
    assert source["type"] == "bitmap" and source["resource"]["sha256"] == resource["sha256"]
    no_channel = session.call("source_set", {"uid": fill, "source": uniform})
    assert no_channel["error"]["code"] == "call_failed"  # a content-stack fill needs its channel

    replaced = session.call("resource_replace", {"old": "checker-16", "new": "grey"})
    assert replaced["result"]["returned"]["nodes"] == [fill]
    projection = {"scale": [2.0, 2.0], "rotation": 45.0, "uv_wrapping_mode": "RepeatNone"}
    filled = session.call(
        "fill_set",
        {"uid": fill, "projection": projection, "active_channels": ["BaseColor", "Height"]},
    )
    assert filled["result"]["status"] == "committed"
    params = nodes(session)[fill]["params"]["fill"]
    assert params["active_channels"] == ["BaseColor", "Height"]
    assert params["projection"]["uv"]["uv_transformation"]["rotation"] == 45.0
    triplanar = session.call("fill_set", {"uid": fill, "projection_mode": "Triplanar"})
    assert triplanar["error"]["code"] == "capability_gap"

    levels = inserted(
        session.call("effect_insert", {"uid": fill, "stack": "content", "kind": "levels"})
    )
    assert nodes(session)[levels]["name"] == "Levels - Base color"
    components = [{"input_min": 0.1, "input_max": 0.9, "gamma": 1.2}] * 3
    tuned = session.call("effect_set", {"uid": levels, "levels": {"components": components}})
    assert tuned["result"]["status"] == "committed"
    no_mask = session.call("effect_insert", {"uid": fill, "stack": "mask", "kind": "fill"})
    assert no_mask["error"]["code"] == "call_failed"  # the layer has no mask yet
    masked = session.call("mask_set", {"uid": fill, "present": True, "background": "Black"})
    assert masked["result"]["status"] == "committed"
    mask_fill = inserted(
        session.call("effect_insert", {"uid": fill, "stack": "mask", "kind": "fill", "name": "M"})
    )
    mono = {"kind": "bitmap", "resource": "grey"}
    assert session.call("source_set", {"uid": mask_fill, "source": mono})["result"]["status"] == (
        "committed"
    )
    blended = session.call("effect_set", {"uid": mask_fill, "mono_blending": {"mode": "Multiply"}})
    assert blended["result"]["status"] == "committed"
    reset = session.call("source_set", {"uid": mask_fill, "source": None})
    assert reset["result"]["status"] == "committed"
    disabled = session.call("mask_set", {"uid": fill, "enabled": False})
    assert disabled["result"]["status"] == "committed"
    assert nodes(session)[fill]["params"]["mask"]["enabled"] is False
    generator_effect = session.call(
        "effect_insert", {"uid": fill, "stack": "content", "kind": "generator"}
    )
    assert generator_effect["error"]["code"] == "capability_gap"

    listed = session.call("resource_list", {"used_only": True})["result"]["resources"]
    assert {entry["name"] for entry in listed} == {"grey"}
    deleted = session.call("layer_delete", {"uid": fill})
    assert deleted["result"]["status"] == "committed" and fill not in nodes(session)
    group = session.call("resource_list")["result"]["resources"]
    assert {entry["name"]: entry["group"] for entry in group}["checker-16"] == "g"


def test_export_mesh_and_render_families(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.1 (Export, Mesh, Render): the shipped presets, a preset export's dry run (nothing
    written) and its export with overrides; the mesh certificate and a reload; a capture whose
    image block is the downscaled PNG."""
    session, revision = opened(painter, tmp_path, sessions)
    presets = session.call("export_presets_list")["result"]["presets"]
    ids = {preset["id"] for preset in presets}
    assert {"pbr-metallic-roughness", "assets3d-inline-five-map"} <= ids
    out = tmp_path / "out" / "export"
    arguments = {"preset": "assets3d-inline-five-map", "output_dir": str(out), "size_log2": 8}
    dry = session.call("export", {**arguments, "dry_run": True, "wait": True})
    assert dry["result"]["dry_run"] is True and dry["result"]["textures"]
    assert dry["result"]["plan"]["hash"] and not out.exists()
    exported = session.call("export", {**arguments, "file_format": "png", "wait": True})
    assert exported["result"]["files"] and Path(exported["result"]["directory"]).is_dir()
    both = session.call("export", {**arguments, "config": {}, "wait": True})
    assert both["error"]["code"] == "invalid_arguments"

    certificate = session.call("mesh_certificate")["result"]
    assert certificate["certificate"]["status"] in ("pass", "warn", "fail")
    assert len(certificate["mesh"]["sha256"]) == 64
    moved = tmp_path / "moved" / "plane.obj"
    moved.parent.mkdir()
    shutil.copy(PLANE, moved)
    reloaded = session.call("mesh_reload", {"path": str(moved), "wait": True})
    assert reloaded["result"]["status"] == "committed", reloaded
    assert reloaded["receipt"]["job"]["committed"] == {"revision": revision + 1}
    assert session.call("mesh_certificate")["result"]["mesh"]["source"].endswith("moved/plane.obj")

    shot = session.request(
        "tools/call", {"name": "capture", "arguments": {"mode": "base_color", "path": "shot.png"}}
    )
    body = shot["structuredContent"]
    assert "error" not in body, body
    image = body["image"]
    assert image["built"] is True and max(image["width"], image["height"]) <= 512
    [block] = [item for item in shot["content"] if item["type"] == "image"]
    data = base64.b64decode(block["data"])
    assert block["mimeType"] == "image/png" and data.startswith(bytes([0x89]) + b"PNG")
    assert int.from_bytes(data[16:20], "big") == image["width"]


def test_an_export_release_gap_is_a_capability_gap(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """phase2.9 (decision 192): an export setting the native code refuses before writing
    (`NotYetSupported`: dithering at PNG 8 bits is not fitted) fails `capability_gap {tool, type,
    reason}` like every typed tool's release gap, not a `RuntimeError`; nothing is written."""
    session, revision = opened(painter, tmp_path, sessions)
    out = tmp_path / "out" / "dithered"
    config = {
        "exportPath": str(out),
        "defaultExportPreset": "assets3d-inline-five-map",
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [{"parameters": {"bitDepth": "8", "dithering": True}}],
    }
    refused = session.call("export", {"config": config, "wait": True})
    assert refused["error"]["code"] == "capability_gap", refused
    details = refused["error"]["details"]
    assert details["tool"] == "export" and details["type"] == "NotYetSupported"
    assert "not fitted" in details["reason"]
    assert not out.exists() or not any(out.rglob("*.png"))
    assert revision_of(session) == revision


# ── 3.2 LAY-06 ──────────────────────────────────────────────────────────────────────────────────


def test_name_addressing_through_mcp(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.2 (LAY-06): repeating a named insert creates no duplicate; an ambiguous name fails before
    mutation listing the candidate ids; ids survive save, close and reopen."""
    session, _ = opened(painter, tmp_path, sessions)
    base = inserted(session.call("layer_insert", {"kind": "fill", "name": "Base"}))
    repeat = session.call("layer_insert", {"kind": "fill", "name": "Base"})
    assert inserted(repeat) == base and repeat["result"]["status"] == "no_op"
    assert repeat["result"]["returned"]["created"] is False
    group = session.call("layer_insert", {"kind": "group", "name": "Base"})
    assert group["error"]["code"] == "call_failed"  # the name holds a fill
    first = inserted(session.call("layer_insert", {"kind": "fill"}))
    second = inserted(session.call("layer_insert", {"kind": "fill"}))
    assert nodes(session)[first]["name"] == nodes(session)[second]["name"] == "Fill"
    before = revision_of(session)
    ambiguous = session.call("layer_insert", {"kind": "fill", "name": "Fill"})
    assert ambiguous["error"]["code"] == "ambiguous_name"
    assert sorted(ambiguous["error"]["details"]["candidates"]) == sorted([first, second])
    assert str(first) in ambiguous["error"]["message"] and revision_of(session) == before
    folder = inserted(session.call("layer_insert", {"kind": "group", "name": "Folder"}))
    scoped = {"kind": "fill", "name": "Fill", "inside": folder}
    child = inserted(session.call("layer_insert", scoped))
    assert child not in (first, second)  # another scope: the group's sub-layers

    saved = revision_of(session)
    assert session.call("project_save")["result"]["current"] == saved
    assert "error" not in session.call("project_close")
    reopened = session.call("project_open", {"path": str(tmp_path / "plane.uzp"), "wait": True})
    assert reopened["result"]["revision"] == saved
    after = nodes(session)
    assert {base, first, second, folder} <= set(after) and after[base]["name"] == "Base"
    assert after[child]["parent"] == folder
    again = session.call("layer_insert", {"kind": "fill", "name": "Base"})
    assert inserted(again) == base and again["result"]["status"] == "no_op"


# ── 3.3 LAY-07 ──────────────────────────────────────────────────────────────────────────────────


def test_sync_stack_rebuilds_only_the_named_group(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.3 (LAY-07): only the named root group is rebuilt; another root group is hidden, not
    deleted, unless a keep_visible prefix matches it; unrelated resources survive and still
    resolve; the images are imported under the resource prefix and group."""
    session, _ = opened(painter, tmp_path, sessions)
    masks = tmp_path / "masks"
    masks.mkdir()
    shutil.copy(PROBE_IMAGES / "mask-left-half.png", masks / "M_left.png")
    shutil.copy(PROBE_IMAGES / "checker-16.png", masks / "T_checker.png")
    other = tmp_path / "ao-white.png"
    shutil.copy(PROBE_IMAGES / "ao-white.png", other)
    session.call("resource_import", {"path": str(other), "usage": "TEXTURE", "name": "C_tex"})
    keep = inserted(session.call("layer_insert", {"kind": "group", "name": "A keep"}))
    old_b = inserted(session.call("layer_insert", {"kind": "group", "name": "B"}))
    inserted(session.call("layer_insert", {"kind": "fill", "name": "old", "inside": old_b}))
    c = inserted(session.call("layer_insert", {"kind": "group", "name": "C"}))
    c_fill = inserted(
        session.call(
            "layer_insert",
            {"kind": "fill", "inside": c, "params": {"active_channels": ["BaseColor"]}},
        )
    )
    bitmap = {"kind": "bitmap", "resource": "C_tex"}
    session.call("source_set", {"uid": c_fill, "channel": "BaseColor", "source": bitmap})
    stack_json = {
        "title": "B",
        "groups": [
            {"key": "outer", "name": "Outer", "mask": None},
            {"key": "lining", "name": "Lining", "mask": "M_left"},
        ],
        "layers": [
            {"group": "outer", "name": "base", "base": [204, 51, 26], "rough": 0.86},
            {"group": "lining", "name": "tex", "base_tex": "T_checker", "metal": 0.0},
        ],
    }
    (tmp_path / "stack.json").write_text(json.dumps({"piece": stack_json}), encoding="utf-8")
    reply = session.call(
        "sync_stack",
        {
            "stack_json": str(tmp_path / "stack.json"),
            "stack_key": "piece",
            "masks_dir": str(masks),
            "keep_visible": ["A"],
            "resource_prefix": "sync_",
            "resource_group": "masks",
        },
    )
    assert reply["result"]["status"] == "committed", reply
    sync = reply["result"]["returned"]["sync"]
    assert sync["deleted"] == [old_b] and sorted(sync["imported"]) == ["M_left", "T_checker"]
    assert [entry["uid"] for entry in sync["hidden"]] == [c]
    after = nodes(session)
    assert old_b not in after and after[sync["root_uid"]]["name"] == "B"
    assert after[keep]["visible"] is True and after[c]["visible"] is False
    assert c_fill in after
    resources = {
        entry["name"]: entry for entry in session.call("resource_list")["result"]["resources"]
    }
    assert resources["C_tex"]["used"] is True
    assert resources["sync_M_left"]["group"] == resources["sync_T_checker"]["group"] == "masks"
    repeat = session.call(
        "sync_stack",
        {
            "stack_json": stack_json,
            "masks_dir": str(masks),
            "keep_visible": ["A"],
            "resource_prefix": "sync_",
        },
    )
    assert sorted(repeat["result"]["returned"]["sync"]["skipped"]) == ["M_left", "T_checker"]
    assert (
        len([n for n in nodes(session).values() if n["name"] == "B" and n["parent"] is None]) == 1
    )


# ── 3.4 batch, long tools, busy ─────────────────────────────────────────────────────────────────


def test_batch_stops_on_error_with_per_call_results(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Spec scenario, 3.4 (INT-06): the first call's result is reported, the second its error, and
    the third is not executed; a batch with a key replays its committed calls on retry."""
    session, revision = opened(painter, tmp_path, sessions)
    calls = [
        {"tool": "layer_insert", "arguments": {"kind": "fill", "name": "one"}},
        {"tool": "layer_set", "arguments": {"uid": 999999, "visible": False}},
        {"tool": "layer_insert", "arguments": {"kind": "fill", "name": "three"}},
    ]
    reply = session.call("batch", {"calls": calls, "stop_on_error": True})
    result = reply["result"]
    assert result["status"] == "stopped" and (result["executed"], result["failed"]) == (2, 1)
    first, second, third = result["results"]
    assert first["status"] == "succeeded" and first["body"]["committed_revision"] == revision + 1
    assert second["status"] == "failed" and second["body"]["error"]["code"] == "invalid_arguments"
    assert third == {"index": 2, "tool": "layer_insert", "status": "not_executed"}
    assert revision_of(session) == revision + 1
    assert {n["name"] for n in nodes(session).values()} == {"one"}

    keyed = {"calls": [calls[0], calls[2]], "idempotency_key": "batch-1"}
    done = session.call("batch", keyed)["result"]
    assert done["status"] == "completed" and revision_of(session) == revision + 2
    replay = session.call("batch", keyed)["result"]
    assert [row["body"]["receipt"]["admission"] for row in replay["results"]] == [
        "executed",  # "one" already existed: the named insert was a no-op, not stored
        "stored_outcome",
    ]
    assert revision_of(session) == revision + 2


def test_long_tools_with_and_without_wait(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.4, 2.8: `project_create` returns `{job_id, status}` at once or waits with wait=true; its
    operation row is the new project's first transaction, so a retry with its key returns the
    stored outcome; an untitled project closes only with discard."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    started = session.call("project_create", {"mesh": str(PLANE)})
    assert started["result"]["status"] == "running" and started["job_id"]
    assert "error" not in session.call("wait_idle", {"timeout": 120})
    finished = session.call("job_result", {"job_id": started["job_id"]})
    assert finished["result"]["status"] == "committed"
    assert finished["receipt"]["job"]["committed"] == {"revision": finished["result"]["revision"]}
    refused = session.call("project_close")
    assert refused["error"]["code"] == "project_error"
    assert "error" not in session.call("project_close", {"discard": True})

    arguments = {
        "mesh": str(PLANE),
        "settings": {"default_texture_resolution": 512},
        "mesh_maps": [
            {"texture_set": "uzp_plane", "usage": "AO", "path": str(PROBE_IMAGES / "ao-white.png")}
        ],
        "idempotency_key": "create-1",
        "expected_revision": 0,
        "wait": True,
    }
    created = session.call("project_create", arguments)
    assert (
        created["result"]["status"] == "committed" and created["receipt"]["admission"] == "executed"
    )
    [texture_set] = session.call("set_list")["result"]["texture_sets"]
    assert texture_set["resolution"]["width"] == 512 and "AO" in texture_set["mesh_maps"]
    retried = session.call("project_create", arguments)
    assert retried["receipt"]["admission"] == "stored_outcome"
    assert retried["result"] == created["result"]
    workflow = session.call(
        "project_create", {"mesh": str(PLANE), "settings": {"project_workflow": "UVTile"}}
    )
    assert workflow["error"]["code"] == "capability_gap"


def test_project_create_takes_its_colour_management_as_an_argument(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Decisions 207 and 212: the worker reads no environment, so `project_create` takes the OCIO
    configuration as `ocio_config_hash`. Painter's substance config creates an OCIO project with
    that hash, which save and reopen keep; any other hash is refused `capability_gap` before the
    job, with no project created; omitting it gives a Legacy project."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    other = session.call(
        "project_create", {"mesh": str(PLANE), "ocio_config_hash": "ab" * 32, "wait": True}
    )
    assert other["error"]["code"] == "capability_gap", other
    assert "only Painter's substance config" in other["error"]["message"]
    malformed = session.call("project_create", {"mesh": str(PLANE), "ocio_config_hash": "OCIO"})
    assert malformed["error"]["code"] == "invalid_arguments"
    assert session.call("project_inspect")["result"] == {"open": False}

    colour: dict[str, Any] = {}
    for name, extra in (("ocio", {"ocio_config_hash": OCIO_CONFIG}), ("legacy", {})):
        created = session.call("project_create", {"mesh": str(PLANE), "wait": True, **extra})
        assert created["result"]["status"] == "committed", created
        path = tmp_path / f"{name}.uzp"
        saved = session.call("project_save_as", {"path": str(path), "wait": True})
        assert "error" not in saved, saved
        assert "error" not in session.call("project_close")
        colour[name] = run_script(
            painter,
            tmp_path,
            f"""
            from uzpainter import colormanagement as cm, project
            project.open({str(path.as_posix())!r})
            result = cm.get_color_management()
            """,
        )
    assert colour["ocio"] == {
        "config_hash": OCIO_CONFIG,
        "io_rules": [],
        "mode": "ocio",
        "working_space": "",
    }
    assert colour["legacy"]["mode"] == "" and colour["legacy"]["config_hash"] == ""


GAP_FIELDS = {"tool", "type", "reason", "operations"}


def basecolor_config(out: Path, *rules: dict[str, Any]) -> dict[str, Any]:
    """An export of the plane's BaseColor document map as PNG 16 with passthrough padding, `rules`
    after the one that sets every parameter."""
    channels = [
        {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": "baseColor"}
        for c in "RGB"
    ]
    base = {"fileFormat": "png", "bitDepth": "16", "dithering": False}
    return {
        "exportPath": str(out),
        "defaultExportPreset": "b",
        "exportPresets": [
            {"name": "b", "maps": [{"fileName": "$textureSet_BaseColor", "channels": channels}]}
        ],
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [
            {"parameters": rule} for rule in ({**base, "paddingAlgorithm": "passthrough"}, *rules)
        ],
    }


def test_every_release_gap_is_one_capability_gap(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """practical-e2e B4 (decision 242): a release gap reaches the client as `capability_gap {tool,
    type, reason, operations}` whichever layer refuses it: the supervisor's gate (a gap family, a
    gated value), the capture's `painter_iray` (`PathTracerUnavailable`, formerly `call_failed`)
    and the evaluator, whose `NotYetSupported` (an OCIO bitmap sampling Session O does not record)
    was `call_failed` in `export`, `capture`, `material_views` and `region_stats`. Nothing is
    written."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    fill = ocio_with_a_refused_bitmap(session, tmp_path)
    out = tmp_path / "out"
    evaluated: dict[str, dict[str, Any]] = {
        "export": {"config": basecolor_config(out / "basecolor"), "wait": True},
        "capture": {"mode": "base_color", "path": "caps/base.png"},
        "material_views": {"mask": fill, "path": "views"},
        "region_stats": {"mask": fill, "map": "BaseColor"},
    }
    for name, arguments in evaluated.items():
        reply = session.call(name, arguments)
        assert reply["error"]["code"] == "capability_gap", (name, reply)
        details = reply["error"]["details"]
        assert set(details) == GAP_FIELDS and details["tool"] == name, details
        assert details["type"] == "NotYetSupported" and details["operations"] == [], details
        assert "evaluator:unsupported_source" in details["reason"], details
        assert "under OCIO" in details["reason"], details
    iray = session.call("capture", {"mode": "painter_iray", "path": "caps/iray.png"})["error"]
    assert iray["code"] == "capability_gap" and set(iray["details"]) == GAP_FIELDS, iray
    assert (iray["details"]["tool"], iray["details"]["type"]) == (
        "capture",
        "PathTracerUnavailable",
    )
    family = session.call("resource_search", {"query": "rust"})["error"]
    assert family["code"] == "capability_gap" and set(family["details"]) == GAP_FIELDS, family
    assert family["details"]["type"] == "NotYetSupported" and family["details"]["operations"]
    painted = session.call("layer_insert", {"kind": "paint"})["error"]
    assert painted["code"] == "capability_gap" and set(painted["details"]) == GAP_FIELDS, painted
    assert not any(out.rglob("*.png")) and not any(out.rglob("*.exr"))


def test_mesh_refusals_keep_their_api_class(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Decision 242 (review of practical-e2e B4): a mesh refusal of `project_create` or
    `mesh_reload` has the class the `uzpainter` API raises, with its details, not `call_failed
    {type: RuntimeError}`. A `.ply` or `.dae` mesh is the release gap `ReleaseGap`, so
    `capability_gap {tool, type, reason, operations: []}`. An unknown format (`UnsupportedFormat`)
    and renamed materials (`MaterialMappingError`) are `ProjectError`s, so `project_error {type,
    details}`; the reload's proposal, passed back as `material_mapping`, then commits. Nothing is
    created or committed by a refusal."""
    meshes = tmp_path / "meshes"
    meshes.mkdir()
    for suffix in ("ply", "dae", "stl"):
        shutil.copy(PLANE, meshes / f"plane.{suffix}")
    renamed = meshes / "renamed.obj"
    text = PLANE.read_text(encoding="utf-8")
    renamed.write_text(text.replace("usemtl uzp_plane", "usemtl renamed"), encoding="utf-8")
    project = make_project(painter, tmp_path)
    ply, stl = (meshes / "plane.ply").as_posix(), (meshes / "plane.stl").as_posix()
    api = run_script(
        painter,
        tmp_path,
        f"""
        from uzpainter import project
        result = {{}}
        for name, path in (("ply", {ply!r}), ("stl", {stl!r})):
            try:
                project.create(path)
            except Exception as error:
                result[name] = [type(error).__name__, error.details]
        project.open({project.as_posix()!r})
        try:
            project.reload_mesh({renamed.as_posix()!r})
        except Exception as error:
            result["renamed"] = [type(error).__name__, error.details]
        """,
    )

    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    gap = session.call("project_create", {"mesh": str(meshes / "plane.ply"), "wait": True})["error"]
    assert gap["code"] == "capability_gap" and set(gap["details"]) == GAP_FIELDS, gap
    assert (gap["details"]["tool"], gap["details"]["type"]) == ("project_create", api["ply"][0])
    assert gap["details"]["operations"] == [] and "'.ply' meshes" in gap["details"]["reason"]
    unknown = session.call("project_create", {"mesh": str(meshes / "plane.stl"), "wait": True})
    error = unknown["error"]
    assert error["code"] == "project_error", unknown
    assert [error["details"]["type"], error["details"]["details"]] == api["stl"]
    assert api["stl"] == ["UnsupportedFormat", {"format": "stl"}]
    assert session.call("project_inspect")["result"] == {"open": False}

    opened_reply = session.call("project_open", {"path": str(project), "wait": True})
    revision = opened_reply["result"]["revision"]
    dae = session.call("mesh_reload", {"path": str(meshes / "plane.dae"), "wait": True})["error"]
    assert dae["code"] == "capability_gap" and set(dae["details"]) == GAP_FIELDS, dae
    assert (dae["details"]["tool"], dae["details"]["type"]) == ("mesh_reload", "ReleaseGap")
    assert dae["details"]["operations"] == []
    mapping = session.call("mesh_reload", {"path": str(renamed), "wait": True})["error"]
    assert mapping["code"] == "project_error", mapping
    assert [mapping["details"]["type"], mapping["details"]["details"]] == api["renamed"]
    assert mapping["details"]["details"]["mapping"] == {"uzp_plane": "renamed"}
    assert revision_of(session) == revision
    arguments = {
        "path": str(renamed),
        "settings": {"material_mapping": mapping["details"]["details"]["mapping"]},
        "wait": True,
    }
    accepted = session.call("mesh_reload", arguments)
    assert accepted["result"]["status"] == "committed", accepted
    assert accepted["result"]["returned"]["reload"]["sets"]["renamed"] == [
        {"from": "uzp_plane", "to": "renamed"}
    ]


def test_an_invalid_export_configuration_is_invalid_arguments(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """practical-e2e B6 (decision 242): `diffusion`, `color` or `transparent` padding with no
    `dilationDistance` after the preset map and every matching rule is an invalid configuration,
    `invalid_arguments {type: ValueError}` (formerly `call_failed RuntimeError`), refused before
    the job runs and before anything is written: for an export, its dry run and the `padding`
    override. The distance resolves across the rules: one an earlier rule gives completes a later
    rule's algorithm (that padding is then a release gap, not fitted)."""
    session, revision = opened(painter, tmp_path, sessions)
    out = tmp_path / "out" / "padded"
    for padding in ("diffusion", "color", "transparent"):
        config = basecolor_config(out, {"paddingAlgorithm": padding})
        refused = session.call("export", {"config": config, "wait": True})
        error = refused["error"]
        assert error["code"] == "invalid_arguments", refused
        assert error["details"]["type"] == "ValueError" and "dilationDistance" in error["message"]
        assert refused["receipt"]["job"] is None  # the job never ran
    config = basecolor_config(out, {"paddingAlgorithm": "diffusion"})
    dry = session.call("export", {"config": config, "dry_run": True, "wait": True})
    assert dry["error"]["code"] == "invalid_arguments", dry
    padded = session.call("export", {"config": basecolor_config(out), "padding": "color"})
    assert padded["result"]["status"] == "running", padded  # a job without wait
    assert "error" not in session.call("wait_idle", {"timeout": 120})
    failed = session.call("job_result", {"job_id": padded["job_id"]})
    assert failed["error"]["code"] == "invalid_arguments", failed
    resolved = basecolor_config(out, {"dilationDistance": 16}, {"paddingAlgorithm": "diffusion"})
    gap = session.call("export", {"config": resolved, "wait": True})
    assert gap["error"]["code"] == "capability_gap" and "not fitted" in gap["error"]["message"]
    assert not out.exists() or not any(out.rglob("*.png"))
    assert revision_of(session) == revision


def test_jobs_batches_and_creates_follow_the_result_contract(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """practical-e2e B15 (decisions 158, 242): a `project_create` admitted with no project open
    reads `revision 0 -> 1`, not a null revision; once its job succeeded, `job_status` and
    `job_list` read progress 1.0, as `job_result` does; a `batch` reply carries a receipt, the
    revisions and its calls' change lists like every other reply."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    started = session.call("project_create", {"mesh": str(PLANE)})
    job_id = started["job_id"]
    assert started["revision"] == started["receipt"]["revision"] == 0, started
    assert "error" not in session.call("wait_idle", {"timeout": 120})
    created = session.call("job_result", {"job_id": job_id})
    assert (created["revision"], created["committed_revision"]) == (0, 1), created
    status = session.call("job_status", {"job_id": job_id})["result"]
    assert (status["status"], status["progress"]) == ("succeeded", 1.0), status
    jobs = session.call("job_list")["result"]["jobs"]
    [listed] = [job for job in jobs if job["job_id"] == job_id]
    assert listed["progress"] == created["receipt"]["job"]["progress"] == 1.0, listed

    calls = [{"tool": "layer_insert", "arguments": {"kind": "fill", "name": n}} for n in "AB"]
    batch = session.call("batch", {"calls": calls})
    assert batch["result"]["status"] == "completed", batch
    assert (batch["revision"], batch["committed_revision"], batch["job_id"]) == (1, 3, None)
    assert batch["receipt"]["tool"] == "batch" and batch["receipt"]["revision"] == 1
    uids = [row["body"]["result"]["returned"]["node"] for row in batch["result"]["results"]]
    assert set(uids) <= set(batch["created"]) and batch["warnings"] == [], batch
    assert "error" not in session.call("project_close", {"discard": True})


def test_busy_and_wait_idle_timeout(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.4 (INT-05): a typed mutation while a long job runs is refused `busy {job_id}`, not
    queued; `wait_idle` with a short timeout fails `timeout`."""
    session, revision = opened(painter, tmp_path, sessions, "--test-faults")
    job = session.call("test_job", {"name": "slow", "steps": 40, "step_ms": 100})
    job_id = job["result"]["job_id"]
    busy = session.call("layer_insert", {"kind": "fill"})
    assert busy["error"]["code"] == "busy" and busy["error"]["details"]["job_id"] == job_id
    timeout = session.call("wait_idle", {"timeout": 0.05})
    assert timeout["error"]["code"] == "timeout"
    session.call("job_cancel", {"job_id": job_id})
    assert "error" not in session.call("wait_idle", {"timeout": 120})
    assert revision_of(session) == revision


# ── 3.5 capability gaps ─────────────────────────────────────────────────────────────────────────


def test_unavailable_families_fail_before_mutation(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Spec scenario, 3.5: each unavailable family fails `capability_gap` before admission (no
    job, no revision) and is a gap in `uzpainter://capabilities`."""
    session, revision = opened(painter, tmp_path, sessions)
    jobs_before = len(session.call("job_list")["result"]["jobs"])
    for name, arguments in GAP_CALLS.items():
        reply = session.call(name, arguments)
        assert reply["error"]["code"] == "capability_gap", (name, reply)
        assert reply["job_id"] is None and reply["error"]["details"]["operations"], name
    for name, arguments in (
        ("layer_insert", {"kind": "paint"}),
        ("effect_insert", {"uid": 1, "stack": "content", "kind": "anchor"}),
        ("layer_set", {"uid": 1, "geometry_mask": {"type": "Mesh", "items": []}}),
        ("fill_set", {"uid": 1, "source_mode": "Material"}),
    ):
        reply = session.call(name, arguments)
        assert reply["error"]["code"] == "capability_gap", (name, reply)
    assert revision_of(session) == revision
    assert len(session.call("job_list")["result"]["jobs"]) == jobs_before
    text = session.request("resources/read", {"uri": "uzpainter://capabilities"})["contents"][0]
    document = json.loads(text["text"])
    gaps = {row["tool"] for row in document["tools"] if row["status"] == "release-gap"}
    assert gaps == set(GAP_CALLS)
    # The resource publishes the shipped manifest unchanged, painter_iray among its release gaps
    # (phase2.3_realtime-preview item 3.3, decision 162).
    shipped = json.loads((painter.parent / "capabilities.json").read_text(encoding="utf-8"))
    assert document["entries"] == shipped["entries"]
    assert document["compat_profile"] == shipped["compat_profile"]
    iray = [
        entry
        for entry in document["entries"]
        if (entry["symbol"], entry["context"]) == ("uzpainter.render.capture", "mode:painter_iray")
    ]
    assert [entry["status"] for entry in iray] == ["release-gap"]
    refused = session.call("capture", {"mode": "painter_iray", "path": "iray.png"})
    assert refused["error"]["details"]["type"] == "PathTracerUnavailable", refused
    summary = session.call("capabilities")["result"]
    assert set(summary["gaps"]) == set(GAP_CALLS) and summary["entries"]["release-gap"] > 0


def test_a_direct_pipe_client_gets_the_same_gaps(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """3.5, 2.10 (decision 164): without the supervisor's gate, the worker itself refuses a gap
    family and a release gap its native code meets (a paint layer) with `capability_gap`, and
    nothing is committed."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(painter, tmp_path, *BASE)
    pipes.append(pipe)
    revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
    key = {"idempotency_key": "pipe-1", "expected_revision": revision}
    paint = pipe.call("layer_insert", {"kind": "paint"}, **key)
    assert paint["error"]["code"] == "capability_gap", paint
    assert paint["error"]["details"]["type"] == "NotYetSupported"
    bake = pipe.call("bake_start", {}, idempotency_key="pipe-2", expected_revision=revision)
    assert bake["error"]["code"] == "capability_gap"
    [operation] = bake["error"]["details"]["operations"]
    assert operation["symbol"] == "substance_painter.baking.bake_async"
    assert pipe.call("project_inspect")["result"]["revision"] == revision


# ── 3.6 resources and prompts ───────────────────────────────────────────────────────────────────


def test_resources_and_prompts_are_listed_and_read(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.6, 2.9: the eight resources (seven and the jobs template) and the four prompts are listed;
    each project resource names its project and revision."""
    session, revision = opened(painter, tmp_path, sessions)
    listed = {item["uri"] for item in session.request("resources/list", {})["resources"]}
    assert listed == {
        "uzpainter://capabilities",
        "uzpainter://project/manifest",
        "uzpainter://project/recipe",
        "uzpainter://project/layers",
        "uzpainter://project/resources",
        "uzpainter://assets/parity",
        "uzpainter://ledger",
    }
    templates = session.request("resources/templates/list", {})["resourceTemplates"]
    assert [item["uriTemplate"] for item in templates] == ["uzpainter://jobs/{job_id}"]

    def read(uri: str) -> Any:
        [content] = session.request("resources/read", {"uri": uri})["contents"]
        assert content["mimeType"] == "application/json"
        return json.loads(content["text"])

    manifest = read("uzpainter://project/manifest")
    assert manifest["revision"] == revision and manifest["manifest"]["texture_sets"]
    for uri in ("project/recipe", "project/layers", "project/resources"):
        document = read(f"uzpainter://{uri}")
        assert document["project_uuid"] == manifest["project_uuid"], uri
        assert document["revision"] == revision and document["content"] is not None, uri
    assert read("uzpainter://assets/parity")["status"] == "release-gap"
    inserted(session.call("layer_insert", {"kind": "fill"}))
    jobs = read("uzpainter://ledger")["jobs"]
    newest = jobs[0]
    assert read(f"uzpainter://jobs/{newest['job_id']}")["tool"] == "layer_insert"

    prompts = {item["name"] for item in session.request("prompts/list", {})["prompts"]}
    assert prompts == {
        "stack_json_template",
        "smart_json_template",
        "baking_preset_template",
        "export_config_template",
    }
    for name in prompts:
        [message] = session.request("prompts/get", {"name": name})["messages"]
        assert message["role"] == "user" and "```json" in message["content"]["text"], name
