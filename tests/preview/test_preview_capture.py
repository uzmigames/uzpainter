"""Tests of phase2.2_preview-capture: `uzpainter.render.capture` and the worker's `capture` tool
(src/python/capture.h; docs/architecture/07-preview-and-render-parity.md §5; decision 148).

Everything runs in the `UzPainter.exe` of a fresh Debug `zig build painter` (`painter`, through
`UzPainter.exe run` or a worker pipe). The diagnostic modes and `painter_iray` are CPU-only and run
on Legacy projects of the plane fixture. `painter_viewport` renders on the GPU and only an OCIO
project without fill sources can be rendered today, so its tests use the OCIO bundle of
`conftest.ocio_bundle`; they skip under `UZP_NO_GPU=1` (decision 028).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import textwrap
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from tests.preview.conftest import NO_GPU, OCIO_CONFIG, ocio_bundle, run_report
from tests.supervisor.conftest import PLANE, Pipe
from tools.parity.fit.decode import decode

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "src" / "python" / "capture-receipt.schema.json"
IMAGES = REPO_ROOT / "parity" / "fixtures" / "api-probes"
# The receipt fields of 07-preview-and-render-parity.md §5.
SECTION_5 = {
    "revision",
    "evaluator_profile",
    "render_state_digest",
    "mode",
    "backend",
    "adapter",
    "driver",
    "samples",
    "seed",
    "camera",
    "size",
    "display_configuration",
    "hashes",
}
GPU = pytest.mark.skipif(NO_GPU, reason="UZP_NO_GPU=1: painter_viewport needs a DX12 adapter")

PRELUDE = f"""
import json, os, sys
import uzpainter
from uzpainter import (colormanagement as cm, display, exception, export, layerstack as ls,
                       project, resource, textureset as ts)
PLANE = {PLANE.as_posix()!r}
IMAGES = {IMAGES.as_posix()!r}
CT = ts.ChannelType
WORK = sys.argv[1]
capture = uzpainter.render.capture

def raises(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except BaseException as error:
        return type(error).__name__ + ": " + str(error)
    return None

def config(folder, maps, file_format, bit_depth):
    entries = []
    for file_name, kind, name, components in maps:
        letters = ["R", "G", "B"] if components == 3 else ["L"]
        channels = [{{"destChannel": c, "srcChannel": c, "srcMapType": kind, "srcMapName": name}}
                    for c in letters]
        entries.append({{"fileName": file_name, "channels": channels}})
    return {{"exportPath": folder, "exportShaderParams": False, "defaultExportPreset": "d",
            "exportPresets": [{{"name": "d", "maps": entries}}],
            "exportList": [{{"rootPath": "uzp_plane"}}],
            "exportParameters": [{{"parameters": {{
                "fileFormat": file_format, "bitDepth": bit_depth, "dithering": False,
                "paddingAlgorithm": "passthrough"}}}}]}}

def exported(folder, maps):
    files = {{}}
    for file_format, bit_depth in (("png", "16"), ("exr", "32f")):
        done = export.export_project_textures(config(folder, maps, file_format, bit_depth))
        for f in done["files"]:
            files[f["relative_path"]] = f["path"]
    return files
"""


def run(painter: Path, tmp_path: Path, body: str, *args: str) -> dict[str, Any]:
    """`UzPainter.exe run` of PRELUDE + `body` with `tmp_path` as WORK; its report."""
    script = tmp_path / "capture-script.py"
    script.write_text(PRELUDE + textwrap.dedent(body), encoding="utf-8")
    return run_report(painter, script, str(tmp_path), *args)


def ok(report: dict[str, Any]) -> Any:
    assert report["status"] == "ok", report.get("error", report)
    return report["result"]


def values(path: str | Path) -> np.ndarray[Any, Any]:
    """The decoded samples of a PNG or OpenEXR file, shape (height, width, channels)."""
    decoded = decode(Path(path).read_bytes())
    return np.asarray(decoded.values)


def check_receipt(receipt: dict[str, Any]) -> None:
    """The receipt validates, the file beside the PNG holds it, and its hashes are the files'."""
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert [e.message for e in validator.iter_errors(receipt)] == []
    files = receipt["files"]
    written = json.loads(Path(files["receipt"]).read_text(encoding="utf-8"))
    assert written == {k: v for k, v in receipt.items() if k != "files"}
    for kind in ("png", "exr"):
        data = Path(files[kind]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == receipt["hashes"][kind]
    assert Path(files["exr"]).stem == Path(files["png"]).stem
    assert Path(files["receipt"]).name == Path(files["png"]).stem + ".receipt.json"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ── 3.5 painter_iray ────────────────────────────────────────────────────────────────────────────

IRAY = """
no_project = raises(capture, 5, "painter_iray")
project.create(PLANE, project.Settings(default_texture_resolution=256))
rev = project.revision()
inside = raises(capture, WORK + "/iray.png", "painter_iray", camera={"bogus": 1}, size=(0, 0),
                samples=-3, seed=-1, preset=7)
result = {"no_project": no_project, "inside": inside, "same": project.revision() == rev,
          "subclass": issubclass(exception.PathTracerUnavailable, exception.NotYetSupported),
          "written": sorted(f for f in os.listdir(WORK) if f.startswith("iray"))}
"""


@pytest.mark.preview_settling("painter_iray_unavailable")
def test_painter_iray_fails_before_any_work(painter: Path, tmp_path: Path) -> None:
    """2.6, 3.5: `painter_iray` raises `PathTracerUnavailable` (a `NotYetSupported`) first: with
    no project open and with arguments that would each fail, nothing is checked, rendered or
    written and the revision is unchanged; the capability manifest keeps it a release gap."""
    result = ok(run(painter, tmp_path, IRAY))
    for key in ("no_project", "inside"):
        assert result[key].startswith("PathTracerUnavailable: capture mode painter_iray"), result
        assert "P3-PATHTRACER" in result[key]
    assert result["subclass"] and result["same"] and result["written"] == []

    manifest = json.loads((painter.parent / "capabilities.json").read_text(encoding="utf-8"))
    status = {
        e["context"]: e["status"]
        for e in manifest["entries"]
        if e["symbol"] == "uzpainter.render.capture"
    }
    assert status == {"any": "pending-evidence", "mode:painter_iray": "release-gap"}
    assert any(
        e["symbol"] == "uzpainter.exception.PathTracerUnavailable" for e in manifest["entries"]
    )


# ── 3.3, 3.4 Diagnostic modes ───────────────────────────────────────────────────────────────────

DIAGNOSTIC = """
project.create(PLANE, project.Settings(default_texture_resolution=256))
stack = ts.get_active_stack()
half = resource.import_project_resource(IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE)
below = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
below.active_channels = {CT.SpecularRoughness, CT.BaseColor}
below.set_source(CT.SpecularRoughness, cm.Color(0.9, 0.9, 0.9, "Raw"))
below.set_source(CT.BaseColor, cm.Color(0.1, 0.1, 0.7, "Raw"))
mat = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
mat.active_channels = {CT.SpecularRoughness, CT.BaseColor}
mat.set_source(CT.SpecularRoughness, cm.Color(0.2, 0.2, 0.2, "Raw"))
mat.set_source(CT.BaseColor, cm.Color(0.7, 0.3, 0.1, "Raw"))
mat.add_mask(ls.MaskBackground.Black)
mask_fill = ls.insert_fill(ls.InsertPosition.inside_node(mat, ls.NodeStack.Mask))
mask_fill.set_source(None, half.identifier())
mask_fill.set_projection_parameters(ls.UVProjectionParams(filtering_mode=ls.FilteringMode.Nearest))
uid = mat.uid()
rev = project.revision()
caps = {"base": capture(WORK + "/cap/base.png", "base_color"),
        "rough": capture(WORK + "/cap/rough.png", "channel:roughness", size=(256, 256)),
        "mask": capture(WORK + "/cap/mask.png", "mask:%d" % uid, stack=None),
        "on_stack": capture(WORK + "/cap/rough-stack.png", "channel:roughness", stack=stack)}
files = exported(WORK + "/exp", [("base", "documentMap", "baseColor", 3),
                                 ("rough", "documentMap", "roughness", 1),
                                 ("mask", "diagnosticMap", "materialMask/%d" % uid, 1)])
refused = {
    "seed": raises(capture, WORK + "/r.png", "channel:roughness", seed=3),
    "camera": raises(capture, WORK + "/r.png", "base_color", camera={}),
    "preset": raises(capture, WORK + "/r.png", "base_color", preset="common"),
    "samples": raises(capture, WORK + "/r.png", "base_color", samples=1),
    "size": raises(capture, WORK + "/r.png", "base_color", size=(128, 128)),
    "mask_stack": raises(capture, WORK + "/r.png", "mask:%d" % uid, stack=stack),
    "no_node": raises(capture, WORK + "/r.png", "mask:999999"),
    "bad_uid": raises(capture, WORK + "/r.png", "mask:abc"),
    "unknown_mode": raises(capture, WORK + "/r.png", "albedo"),
    "unknown_map": raises(capture, WORK + "/r.png", "channel:bogus"),
    "not_png": raises(capture, WORK + "/r.exr", "base_color"),
}
with uzpainter.Transaction("t"):
    refused["transaction"] = raises(capture, WORK + "/r.png", "base_color")
result = {"uid": uid, "caps": caps, "files": files, "refused": refused,
          "same": project.revision() == rev, "rev": rev,
          "stray": sorted(f for f in os.listdir(WORK) if f.startswith("r."))}
"""


@pytest.mark.preview_settling("diagnostic_captures_headless")
def test_diagnostic_captures_equal_channel_exports(painter: Path, tmp_path: Path) -> None:
    """2.5, 3.4: `base_color`, `channel:roughness` and `mask:<uid>` equal the exports of their
    sources (documentMap baseColor and roughness, diagnosticMap materialMask/<uid>) with the same
    format, bit depth and padding, in decoded values, as 16-bit PNG and as OpenEXR 32f. Inapplicable
    arguments and bad modes are refused before anything is written; nothing commits."""
    result = ok(run(painter, tmp_path, DIAGNOSTIC))
    files = {Path(k).stem.split("_")[-1] + Path(k).suffix: v for k, v in result["files"].items()}
    caps = result["caps"]
    for name in ("base", "rough", "mask"):
        receipt = caps[name]
        check_receipt(receipt)
        for kind in ("png", "exr"):
            captured = values(receipt["files"][kind])
            expected = values(files[f"{name}.{kind}"])
            assert captured.shape == expected.shape
            assert np.array_equal(captured, expected), (name, kind)
    assert values(caps["base"]["files"]["png"]).shape == (256, 256, 3)
    assert values(caps["mask"]["files"]["exr"]).shape == (256, 256, 1)
    mask = values(caps["mask"]["files"]["exr"])
    assert mask.min() == 0.0 and mask.max() == 1.0  # the left half is inside
    assert caps["on_stack"]["hashes"] == caps["rough"]["hashes"]
    assert caps["mask"]["source"]["name"] == f"materialMask/{result['uid']}"
    assert caps["rough"]["source"]["type"] == "documentMap"

    refused = result["refused"]
    for key in ("seed", "camera", "preset", "samples"):
        assert refused[key].startswith("ValueError: ") and "does not apply" in refused[key]
    assert refused["size"].startswith("ValueError: ") and "256 x 256" in refused["size"]
    assert refused["mask_stack"].startswith("ValueError: ")
    assert refused["no_node"].startswith("ValueError: ") and "no stack" in refused["no_node"]
    assert refused["bad_uid"].startswith("ValueError: ")
    assert refused["unknown_mode"].startswith("ValueError: unknown capture mode")
    assert refused["unknown_map"].startswith("ValueError: ")
    assert refused["not_png"].startswith("ValueError: ") and ".png" in refused["not_png"]
    assert refused["transaction"].startswith("RuntimeError: a capture reads a committed revision")
    assert result["same"] and result["stray"] == []


def test_receipts_have_every_field(painter: Path, tmp_path: Path) -> None:
    """2.4, 3.3: the receipt schema requires every field of 07 §5 (and the schema id, the
    project, the source and the encoding); a diagnostic receipt validates, holds the revision and
    the profile, and its render-state digest is the SHA-256 of its resolved state. The
    `painter_viewport` receipt is checked in the GPU tests below."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) >= SECTION_5
    assert set(schema["required"]) == set(schema["properties"]) - {"files"}
    result = ok(run(painter, tmp_path, DIAGNOSTIC))
    receipt = result["caps"]["rough"]
    check_receipt(receipt)
    assert receipt["schema"] == "uzpainter/capture-receipt/1"
    assert receipt["revision"] == result["rev"]
    assert receipt["evaluator_profile"]
    assert (receipt["backend"], receipt["adapter"], receipt["driver"]) == ("cpu", None, None)
    assert (receipt["samples"], receipt["seed"], receipt["camera"]) == (None, None, None)
    assert receipt["display_configuration"] is None and receipt["size"] == [256, 256]
    assert receipt["visibility"] is None and receipt["shadows"] is None
    assert receipt["occlusion"] is None
    assert receipt["encoding"] == {
        "png": {"bit_depth": "16", "layout": "L"},
        "exr": {"bit_depth": "32f", "layout": "L"},
        "padding": "passthrough",
    }
    state = {
        "mode": receipt["mode"],
        "source": receipt["source"],
        "size": receipt["size"],
        "encoding": receipt["encoding"],
    }
    assert receipt["render_state_digest"] == hashlib.sha256(canonical(state)).hexdigest()


CHANNELS = """
project.create(PLANE, project.Settings(default_texture_resolution=256))
fill = ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
fill.active_channels = {CT.SpecularRoughness, CT.BaseColor}
fill.set_source(CT.SpecularRoughness, cm.Color(0.3, 0.3, 0.3, "Raw"))
fill.set_source(CT.BaseColor, cm.Color(0.7, 0.3, 0.1, "Raw"))
modes = ["channel:SpecularRoughness", "channel:specularroughness", "channel:Roughness",
         "channel:roughness", "channel:BaseColor", "base_color"]
caps = {mode: capture(WORK + "/cap/%d.png" % i, mode) for i, mode in enumerate(modes)}
result = {
    "caps": {mode: {"png": c["files"]["png"], "source": c["source"]["name"]}
             for mode, c in caps.items()},
    "unknown": raises(capture, WORK + "/r.png", "channel:Rough"),
    "absent": raises(capture, WORK + "/r.png", "channel:User7"),
}
"""


def test_channel_mode_takes_channel_types(painter: Path, tmp_path: Path) -> None:
    """practical-e2e B11 (decision 242): `channel:<name>` takes a channel type as `evaluate_channel`
    and `source_set` do (`SpecularRoughness`), the documentMap the export records for it, and the
    export's documentMap names it took before (`specularroughness`): both capture the same values.
    A name that is neither says so, never that a documentMap spelling is not recorded; a channel
    the stack lacks says the stack has no such channel."""
    result = ok(run(painter, tmp_path, CHANNELS))
    caps = result["caps"]
    sources = {mode: cap["source"] for mode, cap in caps.items()}
    assert sources == {
        "channel:SpecularRoughness": "specularroughness",
        "channel:specularroughness": "specularroughness",
        "channel:Roughness": "roughness",
        "channel:roughness": "roughness",
        "channel:BaseColor": "baseColor",
        "base_color": "baseColor",
    }
    for first, second in (
        ("channel:SpecularRoughness", "channel:specularroughness"),
        ("channel:Roughness", "channel:roughness"),
        ("channel:SpecularRoughness", "channel:Roughness"),
        ("channel:BaseColor", "base_color"),
    ):
        assert np.array_equal(values(caps[first]["png"]), values(caps[second]["png"])), first
    assert result["unknown"].startswith("ValueError: channel:Rough names no channel")
    assert "SpecularRoughness" in result["unknown"] and "specularroughness" in result["unknown"]
    assert (
        result["absent"].startswith("ValueError: ") and "has no channel User7" in result["absent"]
    )


# ── 3.2 Freshness of the diagnostic modes ───────────────────────────────────────────────────────

FRESH = """
project.create(PLANE, project.Settings(default_texture_resolution=256))
stack = ts.get_active_stack()
fill = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
fill.active_channels = {CT.SpecularRoughness}
fill.set_source(CT.SpecularRoughness, cm.Color(0.25, 0.25, 0.25, "Raw"))
first = capture(WORK + "/first.png", "channel:roughness")
fill.set_source(CT.SpecularRoughness, cm.Color(0.75, 0.75, 0.75, "Raw"))
second = capture(WORK + "/second.png", "channel:roughness")
files = exported(WORK + "/exp", [("rough", "documentMap", "roughness", 1)])
result = {"first": first, "second": second, "rev": project.revision(), "files": files}
"""


def test_diagnostic_capture_after_a_mutation_shows_it(painter: Path, tmp_path: Path) -> None:
    """3.2: a capture taken right after a change names the new revision and shows the new values
    (equal to the export of that revision)."""
    result = ok(run(painter, tmp_path, FRESH))
    first, second = result["first"], result["second"]
    assert second["revision"] == result["rev"] == first["revision"] + 1
    # One value per capture: the 8-bit roughness channel's codes of 0.25 and 0.75.
    (low,) = np.unique(values(first["files"]["exr"])).tolist()
    (high,) = np.unique(values(second["files"]["exr"])).tolist()
    assert (round(low * 255), round(high * 255)) == (64, 191)
    exported = {Path(k).suffix: v for k, v in result["files"].items()}
    assert np.array_equal(values(second["files"]["png"]), values(exported[".png"]))
    assert first["render_state_digest"] == second["render_state_digest"]
    assert first["hashes"] != second["hashes"]


# ── 2.8 The worker's tool ───────────────────────────────────────────────────────────────────────


def test_worker_capture_tool(painter: Path, tmp_path: Path, pipes: list[Pipe]) -> None:
    """2.8: the worker lists `capture` (GPU, non-mutating); `painter_iray` is refused before the
    path is looked at; a path outside the output root and selectors a mode does not take are
    `invalid_arguments`; a diagnostic capture runs and writes inside the output root."""
    legacy = tmp_path / "legacy.uzp"
    script = tmp_path / "make.py"
    script.write_text(
        textwrap.dedent(
            f"""
            from uzpainter import project
            project.create({PLANE.as_posix()!r}, project.Settings(default_texture_resolution=256))
            project.save_as({legacy.as_posix()!r})
            result = True
            """
        ),
        encoding="utf-8",
    )
    assert run_report(painter, script)["status"] == "ok"
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "dx12")
    pipes.append(pipe)
    tools = {t["name"]: t for t in pipe.request({"method": "tools/list"})["result"]["tools"]}
    assert (tools["capture"]["gpu"], tools["capture"]["mutating"]) == (True, False)
    assert tools["capture"]["inputSchema"]["required"] == ["mode", "path"]

    revision = pipe.call("project_open", {"path": str(legacy)})["result"]["revision"]
    iray = pipe.call("capture", {"mode": "painter_iray", "path": "../../outside.png"})
    assert iray["error"]["code"] == "capability_gap", iray  # a release gap (decision 242)
    assert iray["error"]["details"]["type"] == "PathTracerUnavailable"
    outside = pipe.call("capture", {"mode": "base_color", "path": str(tmp_path / "x.png")})
    assert outside["error"]["code"] == "invalid_arguments", outside
    selector = pipe.call("capture", {"mode": "mask:1", "path": "m.png", "texture_set": "uzp_plane"})
    assert selector["error"]["code"] == "invalid_arguments", selector
    unknown = pipe.call("capture", {"mode": "base_color", "path": "u.png", "stack": "nope"})
    assert unknown["error"]["code"] == "invalid_arguments", unknown
    refused = pipe.call("capture", {"mode": "base_color", "path": "s.png", "seed": 1})
    assert refused["error"]["details"]["type"] == "ValueError", refused

    reply = pipe.call(
        "capture",
        {"mode": "channel:roughness", "path": "caps/rough.png", "texture_set": "uzp_plane"},
    )
    receipt = reply["result"]
    check_receipt(receipt)
    assert receipt["revision"] == revision
    assert Path(receipt["files"]["png"]).resolve() == (tmp_path / "out" / "caps" / "rough.png")
    assert reply["committed_revision"] == revision
    # practical-e2e B11 (decision 242): the channel types evaluate_channel and source_set take.
    typed = pipe.call("capture", {"mode": "channel:SpecularRoughness", "path": "caps/sr.png"})
    assert typed["result"]["source"]["name"] == "specularroughness", typed
    unknown = pipe.call("capture", {"mode": "channel:Rough", "path": "caps/rough-x.png"})
    assert unknown["error"]["code"] == "call_failed", unknown
    assert unknown["error"]["details"]["type"] == "ValueError"
    assert "names no channel" in unknown["error"]["message"]


# ── 3.1, 3.2 painter_viewport (GPU) ─────────────────────────────────────────────────────────────

user32 = ctypes.WinDLL("user32", use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def windows_of(pid: int) -> list[int]:
    """Every top-level window of process `pid`, visible or not."""
    found: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        owner = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            found.append(hwnd)
        return True

    user32.EnumWindows(_ENUM(visit), 0)
    return found


def display_code(linear: float) -> int:
    """decision 134's table entry of a binary16 value: round(65535 encode(clamp(L, 0, 1)))."""
    value = 0.0 if math.isnan(linear) else min(max(linear, 0.0), 1.0)
    encoded = value * 12.92 if value <= 0.0031308 else 1.055 * math.pow(value, 1.0 / 2.4) - 0.055
    return math.floor(65535.0 * encoded + 0.5)


def check_viewport(receipt: dict[str, Any], size: tuple[int, int]) -> np.ndarray[Any, Any]:
    """A `painter_viewport` capture's receipt and files; its display codes (height, width, 3)."""
    check_receipt(receipt)
    assert receipt["mode"] == "painter_viewport" and receipt["source"] is None
    assert receipt["backend"] == "dx12" and receipt["adapter"] and receipt["driver"]
    assert (receipt["samples"], receipt["size"]) == (1, list(size))
    assert receipt["display_configuration"] == {
        "mode": "ocio",
        "config_sha256": OCIO_CONFIG,
        "view": "Default - sRGB",
    }
    # Decision 251: the self-occlusion rays are stated, and the `shadows` flag (off under the
    # `common` preset) is recorded with its effect, none.
    assert receipt["visibility"] == {
        "model": "ray_traced_self_occlusion",
        "diffuse_rays": 128,
        "specular_rays": 64,
    }
    assert receipt["shadows"]["effect"] == "none in painter_viewport"
    assert isinstance(receipt["shadows"]["requested"], bool)
    # Decision 257: the AO record; which texture sets bind an AO mesh map is the caller's to check
    # (test_viewport_capture_applies_the_ao_mesh_map). Decision 258: the cavity record; the
    # fixtures' meshes state no unit, so the radius is read in mesh units as metres.
    occlusion = receipt["occlusion"]
    assert {k: v for k, v in occlusion.items() if k != "ao_source"} == {
        "model": "cosine_power_visibility",
        "ao_strength": 1.0,
        "ao_channel": "not_applied",
        "axis": "shading_normal_after_fade",
        "cavity": {
            "model": "normal_divergence",
            "version": 1,
            "source": "normal_slot",
            "estimator": "central_difference_4tap_uv_jacobian",
            "slope_nz_min": 0.3,
            "radius": 0.00025,
            "radius_unit": "mesh_unit_as_metre",
            "mapping": "1/(1+r*max(0,kappa))",
            "combine": "weight_product_and_specular_min",
            "spacing": "footprint_grid_up_to_3x3_min_1_texel",
            "stacks_with": ["ao_mesh_map", "painted_albedo_occlusion"],
        },
        "painted_occlusion": "may_compound",
    }
    assert occlusion["ao_source"] and all(
        (s["source"], s["sha256"] is None) in {("none", True), ("mesh_map", False)}
        for s in occlusion["ao_source"]
    ), occlusion
    codes = values(receipt["files"]["png"])
    linear = values(receipt["files"]["exr"])
    assert codes.shape == linear.shape == (size[1], size[0], 3)
    table = {v: display_code(v) for v in np.unique(linear).tolist()}
    assert np.array_equal(codes, np.vectorize(table.__getitem__)(linear))
    return codes


VIEWPORT = """
project.open(BUNDLE)
rev = project.revision()
shot = capture(WORK + "/run/shot.png", "painter_viewport", size=(96, 64))
refused = {
    "no_size": raises(capture, WORK + "/x.png", "painter_viewport"),
    "samples": raises(capture, WORK + "/x.png", "painter_viewport", size=(8, 8), samples=4),
    "stack": raises(capture, WORK + "/x.png", "painter_viewport", size=(8, 8),
                    stack=ts.get_active_stack()),
    "preset": raises(capture, WORK + "/x.png", "painter_viewport", size=(8, 8), preset="bogus"),
}
from uzpainter.render import display as rd
state = rd.preset()
turned = rd.presets()[1]
turned["environment"]["sha256"] = state["environment"]["sha256"]
turned["environment"]["rotation"] = 90.0
rotated = capture(WORK + "/run/rotated.png", "painter_viewport", size=(96, 64), preset=turned)
result = {"shot": shot, "rotated": rotated, "refused": refused, "rev": rev,
          "same": project.revision() == rev and rd.preset() == state,
          "stray": sorted(f for f in os.listdir(WORK) if f.startswith("x."))}
"""


@GPU
@pytest.mark.preview_settling("viewport_capture_headless")
def test_headless_viewport_capture(painter: Path, tmp_path: Path, pipes: list[Pipe]) -> None:
    """2.1-2.3, 3.1: a worker with no window renders `painter_viewport` offscreen: the process
    owns no window before or after, the PNG holds the display codes of the OpenEXR's binary16
    linear values through decision 134's table, and `UzPainter.exe run` (its own device) gives the
    same bytes. A `preset` argument renders that preset without committing it. Refusals come
    before any device; a Legacy project is the unsupported configuration."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "dx12")
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    pid = pipe.process.pid
    assert windows_of(pid) == []
    revision = pipe.call("project_open", {"path": str(bundle)})["result"]["revision"]
    reply = pipe.call(
        "capture", {"mode": "painter_viewport", "path": "vp/shot.png", "size": [96, 64]}
    )
    receipt = reply["result"]
    codes = check_viewport(receipt, (96, 64))
    assert windows_of(pid) == []
    assert receipt["revision"] == revision and receipt["camera"]["source"] == "fit"
    assert receipt["seed"] == 0
    background = codes[0, 0]
    assert (background == background[0]).all() and (codes[32, 48] != background).any()
    pipe.call("project_close")

    # The worker imported the bundle as `<bundle>.uzp`; this run opens that store.
    store = bundle.with_suffix(".uzp")
    report = run(painter, tmp_path, f"BUNDLE = {str(store)!r}\n" + VIEWPORT)
    result = ok(report)
    assert result["shot"]["hashes"] == receipt["hashes"]
    assert result["shot"]["render_state_digest"] == receipt["render_state_digest"]
    refused = result["refused"]
    assert refused["no_size"].startswith("ValueError: painter_viewport needs a size")
    assert (
        refused["samples"].startswith("ValueError: ") and "samples must be 1" in refused["samples"]
    )
    assert refused["stack"].startswith("ValueError: ")
    assert refused["preset"].startswith("UnsupportedInUzPainter: ")
    assert result["same"] and result["stray"] == []
    rotated = result["rotated"]
    check_viewport(rotated, (96, 64))
    assert rotated["revision"] == result["rev"]
    assert rotated["hashes"]["png"] != receipt["hashes"]["png"]
    assert rotated["render_state_digest"] != receipt["render_state_digest"]

    legacy = run(
        painter,
        tmp_path,
        f"""
        project.open({str(tmp_path / "fixture" / "legacy.uzp")!r})
        result = raises(capture, WORK + "/legacy.png", "painter_viewport", size=(8, 8))
        """,
    )
    refusal = ok(legacy)
    assert refusal.startswith("UnsupportedInUzPainter: uzpainter.render.capture")
    assert "unsupported_configuration: Legacy" in refusal and "decision 038" in refusal


@GPU
def test_viewport_capture_after_a_mutation_shows_it(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """3.2: in a worker, a capture right after a committed `camera_set` names the new revision,
    uses the new default camera and shows a different image."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "dx12")
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    revision = pipe.call("project_open", {"path": str(bundle)})["result"]["revision"]
    args = {"mode": "painter_viewport", "size": [64, 64]}
    before = pipe.call("capture", {**args, "path": "before.png"})["result"]
    camera = {
        "position": [0.0, 30.0, 40.0],
        "rotation": [-36.86989764584402, 0.0, 0.0],
        "projection_type": "Perspective",
        "field_of_view": 40.0,
        "focal_length": 50.0,
        "focus_distance": 50.0,
        "aperture": 0.0,
        "orthographic_height": 20.0,
    }
    moved = pipe.call(
        "camera_set", {"camera": camera}, idempotency_key="k-1", expected_revision=revision
    )
    assert moved["committed_revision"] == revision + 1, moved
    after = pipe.call("capture", {**args, "path": "after.png"})["result"]
    check_viewport(before, (64, 64))
    check_viewport(after, (64, 64))
    assert (before["revision"], after["revision"]) == (revision, revision + 1)
    assert after["camera"]["source"] == "default_camera"
    assert after["hashes"]["png"] != before["hashes"]["png"]
    assert pipe.call("project_inspect")["result"]["revision"] == revision + 1


@GPU
def test_a_stored_double_sided_changes_the_digest_and_no_pixel(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """Decision 196 option (b), amendment of 2026-10-19: a stored `double_sided` true changes the
    receipt's `render_state_digest` (it hashes the full shader object) and no pixel: no renderer
    reads the shader parameters and the preview has no face culling, so the PNG and the OpenEXR
    are byte-identical."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "dx12")
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    revision = pipe.call("project_open", {"path": str(bundle)})["result"]["revision"]
    args = {"mode": "painter_viewport", "size": [64, 64]}
    before = pipe.call("capture", {**args, "path": "single.png"})["result"]
    stored = pipe.call(
        "shader_set",
        {"parameters": {"double_sided": True}},
        idempotency_key="k-ds",
        expected_revision=revision,
    )
    assert stored["committed_revision"] == revision + 1, stored
    after = pipe.call("capture", {**args, "path": "double.png"})["result"]
    check_viewport(before, (64, 64))
    check_viewport(after, (64, 64))
    assert (before["revision"], after["revision"]) == (revision, revision + 1)
    assert after["render_state_digest"] != before["render_state_digest"]
    assert after["hashes"] == before["hashes"]


# ── The AO mesh map (phase2.3_realtime-preview item 2.5; decision 257) ────────────────────────

AO_INPUT = """
project.open(BUNDLE)
stack = ts.get_active_stack()
texture_set = ts.all_texture_sets()[0]
def shot(name):
    return capture(WORK + "/ao/" + name + ".png", "painter_viewport", size=(96, 64))
none = shot("none")
stack.add_channel(CT.AO, ts.ChannelFormat.L8)
has_channel = CT.AO in stack.all_channels()
channel = shot("channel")
half = resource.import_project_resource(AO_HALF, resource.Usage.TEXTURE, "ao-half")
texture_set.set_mesh_map_resource(ts.MeshMapUsage.AO, half.identifier())
mapped = shot("mapped")
rgb = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE, "ao-rgb")
texture_set.set_mesh_map_resource(ts.MeshMapUsage.AO, rgb.identifier())
refused = raises(shot, "rgb")
stray = sorted(f for f in os.listdir(WORK + "/ao") if f.startswith("rgb"))
result = {"none": none, "has_channel": has_channel, "channel": channel, "mapped": mapped,
          "refused": refused, "stray": stray}
"""


def grey_png(path: Path, size: int, code: int) -> None:
    """A `size` x `size` 8-bit grey PNG whose every code is `code`."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = size.to_bytes(4, "big") * 2 + bytes([8, 0, 0, 0, 0])
    rows = (b"\x00" + bytes([code]) * size) * size
    signature = bytes([0x89]) + b"PNG\r\n\x1a\n"
    data = chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    path.write_bytes(signature + data)


@GPU
def test_viewport_capture_applies_the_ao_mesh_map(painter: Path, tmp_path: Path) -> None:
    """Item 2.5 (decision 257), the real input path: `OcclusionOf` passes the texture set's AO mesh
    map through to the viewport's occlusion slot. Without one the set reads ao = 1: an AO channel
    in the stack changes no pixel and the receipt says `ao_channel: "not_applied"` and source
    `none`. A bound 8-bit grey map of code 128 at the set's resolution darkens the render, never
    brightens a pixel, and the receipt names it with its image's SHA-256 (in the digest). An RGB
    image of another size bound as the AO mesh map fails the capture with the pass-through's
    `unsupported_source`; it is never read as ao = 1."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    ao_half = tmp_path / "ao-half.png"
    grey_png(ao_half, 256, 128)
    script = f"BUNDLE = {str(bundle)!r}\nAO_HALF = {ao_half.as_posix()!r}\n" + AO_INPUT
    shots = ok(run(painter, tmp_path, script))
    none, channel, mapped = shots["none"], shots["channel"], shots["mapped"]
    for receipt in (none, channel, mapped):
        check_viewport(receipt, (96, 64))
    assert shots["has_channel"]
    for receipt in (none, channel):
        assert [s["source"] for s in receipt["occlusion"]["ao_source"]] == ["none"]
        assert receipt["occlusion"]["ao_channel"] == "not_applied"
    assert channel["hashes"]["exr"] == none["hashes"]["exr"]
    assert channel["hashes"]["png"] == none["hashes"]["png"]

    (source,) = mapped["occlusion"]["ao_source"]
    assert source["source"] == "mesh_map"
    assert source["sha256"] == hashlib.sha256(ao_half.read_bytes()).hexdigest()
    assert mapped["render_state_digest"] != channel["render_state_digest"]
    before = values(channel["files"]["exr"])
    after = values(mapped["files"]["exr"])
    background = before[0, 0]
    hit = (before != background).any(axis=2)
    assert hit.sum() > 500
    assert (after[hit] <= before[hit]).all()
    assert after[hit].mean() < 0.9 * before[hit].mean()

    refused = shots["refused"]
    assert refused is not None and "unsupported_source" in refused, refused
    assert shots["stray"] == []


# ── Orthographic cameras (phase2.3_realtime-preview; decision 163) ─────────────────────────────

ORTHOGRAPHIC = """
project.open(BUNDLE)
def cam(position, rotation, projection="Orthographic", fov=40.0, focal=50.0):
    return {"position": position, "rotation": rotation, "projection_type": projection,
            "field_of_view": fov, "focal_length": focal, "focus_distance": 50.0, "aperture": 0.0,
            "orthographic_height": 40.0}
top = cam([0.0, 50.0, 0.0], [-90.0, 0.0, 0.0])
def shot(name, size, camera):
    return capture(WORK + "/ortho/" + name + ".png", "painter_viewport", size=size, camera=camera)
result = {
    "square": shot("square", (64, 64), top),
    "landscape": shot("landscape", (96, 64), top),
    "portrait": shot("portrait", (64, 96), top),
    "lens": shot("lens", (64, 64), cam([0.0, 50.0, 0.0], [-90.0, 0.0, 0.0], fov=90.0, focal=20.0)),
    "farther": shot("farther", (64, 64), cam([0.0, 500.0, 0.0], [-90.0, 0.0, 0.0])),
    "behind": shot("behind", (64, 64), cam([0.0, -50.0, 0.0], [-90.0, 0.0, 0.0])),
    "crossing": shot("crossing", (64, 64), cam([0.0, 0.0, 0.0], [-45.0, 0.0, 0.0])),
    "perspective": shot("perspective", (64, 64),
                        cam([0.0, 50.0, 0.0], [-90.0, 0.0, 0.0], projection="Perspective")),
}
"""


def covered(
    codes: np.ndarray[Any, Any], background: np.ndarray[Any, Any], solid: bool = True
) -> tuple[int, ...]:
    """The first and last row and column whose pixels differ from the background colour; with
    `solid`, every pixel inside those bounds differs (the plane is a rectangle on screen)."""
    hit = (codes != background).any(axis=2)
    rows = np.flatnonzero(hit.any(axis=1))
    columns = np.flatnonzero(hit.any(axis=0))
    if solid:
        assert hit[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1].all()
    return (int(rows[0]), int(rows[-1]), int(columns[0]), int(columns[-1]))


@GPU
def test_orthographic_capture_casts_parallel_rays(painter: Path, tmp_path: Path) -> None:
    """Decision 163: an orthographic camera renders the 20 x 20 plane, seen from above, with
    `orthographic_height` 40 as the view's full vertical extent and the width that times the
    aspect, so the plane covers exactly the pixels whose centres lie on it (half the height at
    every aspect). The lens fields do not apply, the distance does not change the image, only hits
    in front of the plane through the camera count (a camera under the plane sees nothing, a tilted
    camera on it sees the half in front), and a perspective camera at the same place frames the
    plane by its vertical field of view, with no hole on its shared diagonal (decision 178)."""
    bundle = ocio_bundle(painter, tmp_path / "fixture", mesh=PLANE)
    shots = ok(run(painter, tmp_path, f"BUNDLE = {str(bundle)!r}\n" + ORTHOGRAPHIC))
    sizes = {"landscape": (96, 64), "portrait": (64, 96)}
    codes = {name: check_viewport(r, sizes.get(name, (64, 64))) for name, r in shots.items()}
    background = codes["square"][0, 0]
    assert shots["square"]["camera"]["source"] == "argument"
    assert shots["square"]["camera"]["record"]["projection_type"] == "Orthographic"

    assert covered(codes["square"], background) == (16, 47, 16, 47)
    assert covered(codes["landscape"], background) == (16, 47, 32, 63)
    assert covered(codes["portrait"], background) == (24, 71, 8, 55)
    assert shots["lens"]["hashes"]["png"] == shots["square"]["hashes"]["png"]
    assert shots["lens"]["render_state_digest"] != shots["square"]["render_state_digest"]
    assert covered(codes["farther"], background) == (16, 47, 16, 47)
    assert (codes["behind"] == background).all()
    # Eye plane through the plane's centre, tilted 45 degrees: the half with z < 0 is in front
    # and shows above the image centre, sin(45) * 10 = 7.07 high.
    assert covered(codes["crossing"], background) == (21, 31, 16, 47)
    # tan(20 degrees) * 50 = 18.2 at the plane: the plane's 10 is 17.6 pixels of the 32. Coverage
    # is watertight (decision 178): the rays along the plane's shared diagonal hit it too.
    assert covered(codes["perspective"], background) == (14, 49, 14, 49)
