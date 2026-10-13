"""Tests of phase1.5_compositor-tile-dag (P1-COMPOSITOR, `docs/architecture/04-layer-stack-and-
compositing.md` §2, §7; `src/evaluator/`, `assets/templates/`).

Every native case runs `uzp-evaluator-tests.exe` (`tests/evaluator/evaluator_test.cpp`, `zig build
evaluator-tests`). The CPU cases (arithmetic, templates, evaluation order, cache and invalidation,
admission) run anywhere. The GPU cases skip under `UZP_NO_GPU=1` (hosted CI, decision 028) or when
the executable reports no DX12 adapter (exit code 77). The Tier 0 comparisons (base values and
channel sets per template, evaluation order, groups) read the private oracle store through
`tools.parity` and skip, saying so, on a machine without it; the local run on the owner's machine
(`parity/reports/phase1/compositor-tile-dag.md`) is their evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator.union_run import note_rasters, observe
from tools.parity.fit.common import Context
from tools.parity.fit.oracle import Golden
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "assets" / "templates"
MANIFESTS = REPO_ROOT / "parity" / "manifests" / "tier0"
FIXTURES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "bitmaps"

EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
GPU_CASES = frozenset({"gpu-vs-cpu", "kernel-sweep"})
FORMATS = {"sRGB8", "L8", "RGB8", "L16", "RGB16", "L16F", "RGB16F", "L32F", "RGB32F"}

# Export map name (documentMap/<name>) -> ChannelType of the stack channel it exports.
EXPORT_CHANNELS = {
    "basecolor": "BaseColor",
    "height": "Height",
    "metallic": "BaseMetalness",
    "normal": "Normal",
    "roughness": "SpecularRoughness",
    "emissive": "EmissionColor",
    "opacity": "Opacity",
    "glossiness": "Glossiness",
    "specular": "Specular",
    "diffuse": "Diffuse",
    "specularlevel": "Specularlevel",
    "anisotropyangle": "Anisotropyangle",
    "anisotropylevel": "SpecularRoughnessAnisotropy",
    "scattering": "SubsurfaceRadiusScale",
    "transmissive": "Transmissive",
    "ambientocclusion": "AO",
    "displacement": "Displacement",
    "blendingmask": "BlendingMask",
    "ior": "Ior",
    "reflection": "Reflection",
    **{f"user{i}": f"User{i}" for i in range(8)},
}


def run_case(exe: Path, case: str, *args: str, needs_gpu: bool = False) -> tuple[set[str], str]:
    """Run one case; return its passed checks and its output. Fails on any failed check."""
    if (case in GPU_CASES or needs_gpu) and NO_GPU:
        pytest.skip(
            f"UZP_NO_GPU=1: `{case}` needs a DX12 hardware adapter; run it locally on the "
            "owner's machine (decision 028)"
        )
    proc = subprocess.run(
        [str(exe), case, str(TEMPLATES_DIR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    return passed, output


# ── Native CPU cases (hosted CI and local) ───────────────────────────────────


def test_arithmetic_rules(evaluator_tests: Path) -> None:
    """2.5: the scalar rules the kernels and the CPU reference share (write rule ties down,
    half toward zero, sRGB tables, fused multiply-add, the isolated composite)."""
    passed, _ = run_case(evaluator_tests, "arith")
    assert {
        "0.5 writes code 32767 on 16 bits (ties down)",
        "every 16-bit code reads as float32(code / 65535) and writes back to itself",
        "127/255 rounds toward zero to the half below (0x37F7)",
        "every finite half converts to float and back to its own bits",
        "every sRGB8 code decodes and encodes back to itself",
        "Fma is the float32 rounding of the exact product plus addend",
        "Normal over an opaque backdrop is a (1 - alpha) + r alpha",
        "Multiply over a transparent backdrop passes the source through",
        "the 32-bit float store re-composites over the base",
    } <= passed


def test_template_library(evaluator_tests: Path) -> None:
    """2.6: the 27 project templates and the channel defaults load; base values resolve through
    the template, then the defaults, and fail explicitly otherwise."""
    passed, _ = run_case(evaluator_tests, "templates")
    assert {
        "the template library loads",
        "27 project templates: 26 shipped templates and the default",
        "the default template has five channels (BaseColor, BaseMetalness, Height, Normal, "
        "SpecularRoughness)",
        "an added user channel starts from the channel default 1.0",
        "an unknown template is refused",
        "a channel without an observed base value is refused explicitly",
    } <= passed


def test_evaluation_order_on_the_cpu(evaluator_tests: Path) -> None:
    """2.4, 3.3 (unit half), 3.4 (unit half): bottom-up order with asymmetric blends on every
    tested format, visibility and Disable, groups from a transparent start, PassThrough,
    instances, 1:1 bitmaps, a non-separable mode and explicit failures."""
    passed, _ = run_case(evaluator_tests, "order")
    for fmt in ("RGB16", "L16", "RGB32F"):
        assert (
            f"{fmt}: the stack equals the bottom-up model (base, A Normal, B Subtract 0.8)"
        ) in passed
        assert f"{fmt}: the two orders differ (the blend is asymmetric)" in passed
        assert (
            f"{fmt}: a Normal group composites its children from a transparent start, "
            "quantised per child, then blends at its opacity"
        ) in passed
    assert {
        "Disable applies to one channel only: the L16 channel still receives B",
        "an empty stack evaluates to the base constant without a tile",
        "a group with default blending behaves as Normal at opacity 1",
        "a PassThrough group composites its children onto the stack below it and mixes by its "
        "opacity",
        "an instance layer evaluates its source layer in its own position",
        "a 1:1 bitmap on RGB16 copies every code exactly",
        "a paint layer fails with unsupported_node",
        "a non-separable blend mode (Tint) evaluates",
        "a bitmap without bytes fails with missing_resource",
    } <= passed


def test_cache_and_invalidation(evaluator_tests: Path) -> None:
    """3.5: a ten-layer stack over two tiles and two channels; one layer's opacity changes on one
    channel in a new revision: that channel re-evaluates only the layers above the edit, the
    other channel is served from the cache, and the partial result equals a fresh evaluation."""
    passed, _ = run_case(evaluator_tests, "cache")
    assert {
        "first evaluation: two tiles, ten blends and the read-out over the base each, the bitmap "
        "uploaded per tile, no hit",
        "the same revision again: both tiles served from the cache, nothing computed",
        "the edited channel re-evaluates only the layers above the edit: per tile the read-out "
        "and the five prefixes above miss, the prefix below the edit hits, five blends and the "
        "read-out run, nothing is uploaded",
        "the other channel's tiles keep their subtree hash and are served from the cache",
        "the partially re-evaluated result equals a fresh evaluation bit for bit",
    } <= passed


def test_admission(evaluator_tests: Path) -> None:
    """3.6: three 4096^2 sets under a budget that holds one set's live tiles evaluate in sequence
    with LRU eviction and never exceed the budget; a set above the budget is refused at creation."""
    passed, _ = run_case(evaluator_tests, "admission")
    assert {
        "every channel of the three 4096^2 sets evaluates under a budget that holds one set",
        "the store never held more than the budget",
        "the second and third sets evicted least recently used tiles of the earlier ones",
        "an 8192^2 set is refused at creation with texture_set_over_budget",
        "the evaluator refuses a set above the budget",
    } <= passed


# ── Native GPU cases (owner's machine) ───────────────────────────────────────


def test_gpu_equals_cpu_on_random_stacks(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.5: the generated kernels, dispatched through the engine thread, give the same bytes as
    the CPU reference on random stacks over every channel format."""
    passed, _ = run_case(evaluator_tests, "gpu-vs-cpu", str(tmp_path))
    assert any(p.startswith("every random stack evaluates to the same bytes") for p in passed)


def test_kernel_sweep_gpu_equals_cpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.5: every blend mode x channel format over dense value sweeps, with and without the
    coverage plane: GPU kernels equal the CPU reference bit for bit."""
    passed, _ = run_case(evaluator_tests, "kernel-sweep", str(tmp_path))
    assert any(p.startswith("every blend mode x channel format") for p in passed)


# ── Template files (structure, no oracle) ────────────────────────────────────


def template_paths() -> list[Path]:
    return sorted(TEMPLATES_DIR.glob("*.json"))


@pytest.mark.parametrize("path", template_paths(), ids=lambda p: p.stem)
def test_template_file_structure(path: Path) -> None:
    """2.6: every template names its id, kind and channels; every channel a documented format
    (project templates), a three-component float32 base in [0, 1] and a provenance record."""
    document = load_json(path)
    assert document["schema"] == "uzpainter/template/1"
    assert document["id"] == path.stem
    assert document["kind"] in {"project", "channel-defaults"}
    assert document["provenance"]["author"] == "UzmiGames"
    # A channel default may repeat its type with distinct formats (decision 204).
    types = [(c["type"], c.get("format")) for c in document["channels"]]
    assert len(types) == len(set(types)), "a channel type repeats"
    for kind, fmt in types:
        assert fmt is not None or [t for t, _ in types].count(kind) == 1, "a channel type repeats"
    for channel in document["channels"]:
        if document["kind"] == "project":
            assert channel["format"] in FORMATS
        else:  # a channel default applies to any format, or to the one it names
            assert channel.get("format", "sRGB8") in FORMATS
        base = channel["base"]
        assert len(base) == 3 and all(0.0 <= v <= 1.0 for v in base)
        for v in base:
            assert struct.unpack("<f", struct.pack("<f", v))[0] == v, "base values are float32"
        provenance = channel["base_provenance"]
        assert provenance["kind"] in {"observed", "fitted", "inferred", "unobserved"}
        if provenance["kind"] in {"observed", "inferred"}:
            assert re.fullmatch(r"[0-9a-f]{64}", provenance["record_sha256"])
            assert provenance["golden_id"].startswith("tier0/")
        if provenance["kind"] == "fitted":
            assert (REPO_ROOT / provenance["semantics"]).is_file()
    if document["kind"] == "project" and path.stem != "default":
        assert document["painter_template"].endswith(".spt")


def test_template_set_covers_the_shipped_templates() -> None:
    """2.6: one template per shipped `.spt` of the Tier 0 template capture, plus the default
    project and the channel defaults."""
    manifest = load_json(MANIFESTS / "defaults-templates" / "project-templates.json")
    shipped = {step["args"]["template"] for step in manifest["instruction_sequence"]["steps"]}
    authored = {
        load_json(p)["painter_template"]
        for p in template_paths()
        if load_json(p)["kind"] == "project" and p.stem != "default"
    }
    assert authored == shipped
    assert (TEMPLATES_DIR / "default.json").is_file()
    assert (TEMPLATES_DIR / "channel-defaults.json").is_file()


# ── Tier 0 goldens (owner's machine: private store, decision 028) ────────────


def needs_store() -> Context:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return Context(store, REPO_ROOT)


def backends() -> list[str]:
    return ["cpu", "gpu"]


# The material channels Painter exports sRGB-encoded when stored as sRGB8 (src/export/plan.h
# `SrgbEncodedOnExport`).
SRGB_ENCODED_ON_EXPORT = frozenset({"BaseColor", "Specular", "Emissive"})


def write16(v: float) -> int:
    """The evaluator's 16-bit UNORM write rule: truncate to 20 fractional bits, nearest, ties
    down."""
    v = min(max(float(np.float32(v)), 0.0), 1.0)
    j = int(v * (1 << 20))
    return (j * 65535 + (1 << 19) - 1) >> 20


def evaluate(exe: Path, spec: dict[str, Any], workdir: Path, backend: str) -> dict[str, Any]:
    """Runs the `evaluate` case on `spec` (written to `workdir/spec.json`); returns result.json."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    out = workdir / f"out-{backend}"
    _, output = run_case(
        exe, "evaluate", str(workdir / "spec.json"), str(out), backend, needs_gpu=backend == "gpu"
    )
    result: dict[str, Any] = load_json(out / "result.json")
    result["_dir"] = str(out)
    note_rasters(result, output)
    return result


def raster(result: dict[str, Any], channel: str) -> np.ndarray:
    """The evaluated raster of `channel` as stored values (codes or floats), shape (h, w, c)."""
    entry = result["channels"][channel]
    assert "error" not in entry, entry
    data = (Path(result["_dir"]) / entry["file"]).read_bytes()
    dtype = {(1, "u"): np.uint8, (2, "u"): np.uint16, (2, "f"): np.float16, (4, "f"): np.float32}[
        (entry["bytes_per_channel"], "f" if entry["format"].endswith("F") else "u")
    ]
    shape = (entry["height"], entry["width"], entry["channels"])
    values = np.frombuffer(data, dtype=dtype).reshape(shape)
    return values.astype(np.float64) if entry["format"].endswith("F") else values.astype(np.int64)


def export16_of_constant(constant: list[float], channel: str, fmt: str) -> list[int]:
    """What a 16-bit PNG export of an empty channel's constant holds, per component: the write
    rule of the export depth, whatever the channel format. The signed Height channel exports
    (h + 1) / 2 (its base 0 exports 32767). An sRGB8 BaseColor, Specular or Emissive holds its
    linear constant and exports its sRGB encode (src/export/encode.h, decision 126); stored as L8,
    its G component exports the linear write (decision 204: Dota 2's L8 Specular base writes
    (14330, 2570, 14330))."""
    if channel == "Height":
        return [
            write16(float(np.float32(np.float32(v) + np.float32(1.0)) * np.float32(0.5)))
            for v in constant
        ]
    if fmt in ("sRGB8", "L8") and channel in SRGB_ENCODED_ON_EXPORT:
        from tests.export.tier0 import srgb16  # tests/export imports this module at load

        encoded = [int(c) for c in srgb16(np.asarray(constant, np.float32))]
        if fmt == "L8":
            return [write16(v) if i == 1 else encoded[i] for i, v in enumerate(constant)]
        return encoded
    return [write16(v) for v in constant]


def template_for_golden(golden_stem: str) -> dict[str, Any]:
    for path in template_paths():
        document: dict[str, Any] = load_json(path)
        if document["kind"] != "project":
            continue
        if document["provenance"]["base_values"]["golden_id"] == f"tier0/semantics/{golden_stem}":
            return document
    raise AssertionError(f"no template authored from {golden_stem}")


def base_value_goldens() -> list[str]:
    return sorted(p.stem for p in (MANIFESTS / "semantics").glob("base-values-*.json"))


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("golden_stem", base_value_goldens())
def test_base_values_equal_the_empty_project_exports(
    evaluator_tests: Path, tmp_path: Path, golden_stem: str, backend: str
) -> None:
    """3.1 (LAY-10): an empty project per template evaluates every channel to its base constant,
    and that constant exported at the golden's depth equals the private capture value for value
    (16-bit PNG: the write rule; OpenEXR: the float32 value)."""
    ctx = needs_store()
    golden = ctx.golden(f"semantics/{golden_stem}")
    template = template_for_golden(golden_stem)
    manifest = load_json(MANIFESTS / "semantics" / f"{golden_stem}.json")
    channels = [{"type": c["type"], "format": c["format"]} for c in template["channels"]]
    added = [
        s["args"]
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"].endswith("Stack.add_channel")
    ]
    for args in added:
        name = "SubsurfaceRadiusScale" if args["channel"] == "Scattering" else args["channel"]
        channels.append({"type": name, "format": args["format"]})
    formats = {c["type"]: c["format"] for c in channels}
    outputs = []
    maps: dict[str, str] = {}
    for map_name in golden.maps("r1"):
        export = map_name.split("/", 1)[1]
        channel = EXPORT_CHANNELS[export]
        if channel in {c["type"] for c in channels}:
            outputs.append(channel)
            maps[channel] = map_name
    spec = {
        "template": template["id"],
        "resolution": [256, 256],
        "channels": channels,
        "resources": [],
        "layers": [],
        "outputs": outputs,
    }
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    for channel, map_name in maps.items():
        entry = result["channels"][channel]
        assert "constant" in entry, f"{channel}: an empty stack evaluates to its base constant"
        for recording in ("r1", "r2"):
            decoded = golden.map(recording, map_name)
            observed = decoded.values
            if decoded.integer:
                ours = np.asarray(
                    export16_of_constant(entry["constant"], channel, formats[channel]), np.int64
                )
                unit = "16-bit code value"
            else:
                ours = np.asarray([float(np.float32(v)) for v in entry["constant"]], np.float64)
                unit = "float32 value"
            ours = np.broadcast_to(ours[: observed.shape[-1]], observed.shape)
            observe(golden, map_name, recording, unit, ours, observed)
            unique = np.unique(observed.reshape(-1, observed.shape[-1]), axis=0)
            assert len(unique) == 1, f"{map_name} is not uniform"
            components = unique[0].tolist()
            constant = entry["constant"]
            if decoded.integer:
                exported = export16_of_constant(constant, channel, formats[channel])[
                    : len(components)
                ]
                assert exported == components, (
                    f"{golden_stem} {map_name} {recording}: {exported} != {components}"
                )
            else:
                floats = [float(np.float32(v)) for v in constant][: len(components)]
                assert floats == components, (
                    f"{golden_stem} {map_name} {recording}: {floats} != {components}"
                )


def capture_channels(templates_golden: Golden, painter_template: str) -> dict[str, str]:
    """The channel -> ChannelFormat set the template capture read back for `painter_template`
    (the capture names the template it opened in its values)."""
    for output in templates_golden.recordings["r1"].outputs.values():
        if output["kind"] != "template_capture":
            continue
        values = output["values"]
        if values.get("template") != painter_template:
            continue
        assert values["accepted"], f"{painter_template}: the capture was not accepted"
        (stack,) = values["texture_sets"].values()
        return {name: str(spec["format"]) for name, spec in stack["stacks"][""].items()}
    raise AssertionError(f"no template capture for {painter_template}")


def test_template_channel_sets_equal_the_capture() -> None:
    """3.2: the channel set and ChannelFormat of every authored template equal the private
    template capture (26 shipped templates), and the default template equals the no-template
    project of the base-values golden."""
    ctx = needs_store()
    templates = ctx.golden("defaults-templates/project-templates")
    for path in template_paths():
        document = load_json(path)
        if document["kind"] != "project":
            continue
        authored = {c["type"]: c["format"] for c in document["channels"]}
        if path.stem == "default":
            default = ctx.golden("semantics/base-values-default")
            manifest = load_json(MANIFESTS / "semantics" / "base-values-default.json")
            added = {
                "SubsurfaceRadiusScale"
                if s["args"]["channel"] == "Scattering"
                else s["args"]["channel"]
                for s in manifest["instruction_sequence"]["steps"]
                if s["call"].endswith("Stack.add_channel")
            }
            capture = default.output("r1", "template/texture-sets")["values"]["texture_sets"]
            (stack,) = capture.values()
            recorded = {
                name: str(spec["format"])
                for name, spec in stack["stacks"][""].items()
                if name not in added
            }
        else:
            recorded = capture_channels(templates, document["painter_template"])
        assert authored == recorded, path.stem


# ── Stack construction from an instruction sequence ─────────────────────────


def fixture_resource(name: str, workdir: Path) -> dict[str, Any]:
    """A spec resource for the authored fixture bitmap `name`: its PNG bytes, decoded by the
    evaluator's resource provider (`src/evaluator/sources.h`)."""
    data = (FIXTURES / f"{name}.png").read_bytes()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{name}.png").write_bytes(data)
    return {"sha256": hashlib.sha256(data).hexdigest(), "png": f"{name}.png"}


# Channels whose bitmap sources Painter 12.1.5 reports in the Data colour space when the steps set
# none (the recorded `get_source` readbacks of the current envelope).
DATA_CHANNELS = frozenset(
    {"AO", "BaseMetalness", "SpecularRoughness", *(f"User{i}" for i in range(10))}
)


def bitmap_color_space(args: dict[str, Any], channel: str | None, png: bytes) -> str:
    """The colour space of the bitmap source a `set_source` step binds (`channel` None: a mask's
    mono source): the step's `color_space` (documented `SourceBitmap.set_color_space`), else the
    one Painter 12.1.5 gives it, as the recorded `get_source` readbacks report: sRGB for a colour
    bitmap on BaseColor, DataSigned on Height, NormalXYZLeft on Normal, Data on the
    `DATA_CHANNELS` and as a mask source. Any other case has no recorded default and fails."""
    if "color_space" in args:
        return str(args["color_space"])
    colour = png[25] in (2, 6)  # the PNG IHDR colour type: RGB or RGBA
    if channel == "BaseColor" and colour:
        return "sRGB"
    if channel == "Height":
        return "DataSigned"
    if channel == "Normal":
        return "NormalXYZLeft"
    if channel is None or channel in DATA_CHANNELS:
        return "Data"
    raise AssertionError(f"no recorded default colour space for this bitmap on {channel}")


LAYER_CALLS = {
    "substance_painter.layerstack.insert_fill": "fill",
    "substance_painter.layerstack.insert_group": "group",
}


def spec_from_manifest(
    manifest: dict[str, Any], texture_set: str, workdir: Path, outputs: list[str]
) -> dict[str, Any]:
    """The evaluator spec of texture set `texture_set` of a Tier 0 instruction sequence: channels,
    resources, and the layer tree (top first) with blending, opacities and sources. Steps on other
    texture sets are ignored; a step this converter does not model fails the test."""
    steps = manifest["instruction_sequence"]["steps"]
    resolution = 256
    channels: list[dict[str, str]] = []
    resources: dict[int, dict[str, Any]] = {}
    nodes: dict[int, dict[str, Any]] = {}
    roots: list[int] = []  # top first

    def owner_set(step: int) -> str:
        node = nodes[step]
        return str(node["set"])

    for step in steps:
        call, args, n = step["call"], step["args"], step["step"]
        if call == "substance_painter.project.create":
            resolution = int(args.get("default_texture_resolution", 256))
        elif call.endswith("Stack.add_channel"):
            channels.append({"type": args["channel"], "format": args["format"]})
        elif call.endswith("resource.import_project_resource"):
            resources[n] = fixture_resource(args["input"], workdir)
        elif call in LAYER_CALLS:
            kind = LAYER_CALLS[call]
            if "texture_set" in args:
                target = args["texture_set"]
                if target != texture_set:
                    nodes[n] = {"set": target}
                    continue
                node = {
                    "set": target,
                    "kind": kind,
                    "uid": n,
                    "children": [],
                    "blending": {},
                    "sources": {},
                    "active": None,
                    "projection": None,
                }
                nodes[n] = node
                roots.insert(0, n)
            else:
                anchor = args.get("above_step", args.get("inside_step"))
                target = owner_set(anchor)
                if target != texture_set:
                    nodes[n] = {"set": target}
                    continue
                node = {
                    "set": target,
                    "kind": kind,
                    "uid": n,
                    "children": [],
                    "blending": {},
                    "sources": {},
                    "active": None,
                    "projection": None,
                }
                nodes[n] = node
                if "above_step" in args:
                    siblings = (
                        roots if anchor in roots else nodes[nodes[anchor]["parent"]]["children"]
                    )
                    siblings.insert(siblings.index(anchor), n)
                    node["parent"] = nodes[anchor].get("parent")
                else:
                    if args.get("stack") != "Substack":
                        raise AssertionError(
                            f"step {n}: {call} into {args.get('stack')} is not modelled"
                        )
                    nodes[anchor]["children"].insert(0, n)
                    node["parent"] = anchor
        elif call.endswith("FillLayerNode.active_channels"):
            if owner_set(args["node_step"]) == texture_set:
                nodes[args["node_step"]]["active"] = list(args["channels"])
        elif call.endswith("FillLayerNode.set_source"):
            if owner_set(args["node_step"]) != texture_set:
                continue
            if "resource_step" in args:
                resource = resources[args["resource_step"]]
                png = (workdir / resource["png"]).read_bytes()
                space = bitmap_color_space(args, args["channel"], png)
                source = {"bitmap": resource["sha256"], "color_space": space}
            else:
                space = args.get("color_space", "Working")
                source = {"uniform": list(args["color"]), "color_space": space}
            nodes[args["node_step"]]["sources"][args["channel"]] = source
        elif call.endswith("FillLayerNode.set_projection_parameters"):
            if owner_set(args["node_step"]) == texture_set:
                projection = {k: v for k, v in args.items() if k != "node_step"}
                nodes[args["node_step"]]["projection"] = {"mode": "UV", **projection}
        elif call.endswith("Node.set_blending_mode"):
            if owner_set(args["node_step"]) == texture_set:
                blending = nodes[args["node_step"]]["blending"]
                entry = blending.setdefault(args["channel"], {"mode": "Normal", "opacity": 1.0})
                entry["mode"] = args["blending_mode"]
        elif call.endswith("Node.set_opacity"):
            if owner_set(args["node_step"]) == texture_set:
                blending = nodes[args["node_step"]]["blending"]
                entry = blending.setdefault(args["channel"], {"mode": "Normal", "opacity": 1.0})
                entry["opacity"] = float(args["opacity"])
        elif call.endswith("export_project_textures"):
            continue
        else:
            touched = args.get("node_step")
            ours = touched is not None and touched in nodes
            if ours and nodes[touched].get("set") == texture_set:
                raise AssertionError(f"step {n}: {call} is not modelled by this converter")

    def emit(step: int) -> dict[str, Any]:
        node = nodes[step]
        layer: dict[str, Any] = {
            "kind": node["kind"],
            "uid": node["uid"],
            "name": f"step{step}",
            "blending": node["blending"],
        }
        if node["kind"] == "fill":
            layer["sources"] = node["sources"]
            if node["active"] is not None:
                layer["active_channels"] = node["active"]
            if node["projection"] is not None:
                layer["projection"] = node["projection"]
        else:
            layer["children"] = [emit(child) for child in node["children"]]
        return layer

    return {
        "template": "default",
        "resolution": [resolution, resolution],
        "channels": channels,
        "resources": list(resources.values()),
        "layers": [emit(step) for step in roots],
        "outputs": outputs,
    }


def compare_exact(ours: np.ndarray, golden: Golden, map_name: str) -> None:
    """Value for value against both recordings (CONTRACT section 3: no tolerance; a NaN matches
    only a NaN)."""
    for recording in ("r1", "r2"):
        theirs = golden.map(recording, map_name).values
        assert ours.shape == theirs.shape, (ours.shape, theirs.shape)
        unit = "float32 value" if ours.dtype.kind == "f" else "16-bit code value"
        observe(golden, map_name, recording, unit, ours, theirs)
        equal = (ours == theirs) | (np.isnan(ours) & np.isnan(theirs))
        differing = int(np.count_nonzero(~equal))
        worst = float(np.abs(ours - theirs).max()) if differing else 0.0
        assert differing == 0, (
            f"{map_name} {recording}: {differing} differing values, max |delta| {worst}"
        )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_evaluation_order_equals_the_golden(
    evaluator_tests: Path, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.3: `blend-order` (fields A Normal 1.0, B Subtract 0.8, uniform C Divide 0.6 in the
    orders ABC, BAC, ACB, CBA): the RGB16 channel equals the golden value for value, so the stack
    is evaluated bottom-up from the base with per-layer storage. The sRGB8 channel of this golden
    depends on the import of a 16-bit bitmap into sRGB8 storage, the colour-transfer rule of
    phase1.8_compositor-sources-projection, and is not compared here."""
    ctx = needs_store()
    golden = ctx.golden("semantics/blend-order")
    manifest = load_json(MANIFESTS / "semantics" / "blend-order.json")
    spec = spec_from_manifest(manifest, texture_set, tmp_path, ["User0"])
    assert len(spec["layers"]) == 3
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    compare_exact(raster(result, "User0"), golden, f"{texture_set}/user0")


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1"])
def test_group_without_masks_equals_the_golden(
    evaluator_tests: Path, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.4: `group-masks` without masks: s0 (the group in Painter's default mode) and s1 (the
    group in `Normal`) at opacity 0.75 over fields A, holding fields B (Multiply) under a uniform
    fill (Screen 0.5). RGB16 and RGB32F equal the goldens value for value: a group composites its
    children from a transparent start, quantised to the channel format after each child, and is
    blended at its opacity; Painter's default group mode behaves as `Normal`. The sRGB8 channel
    waits for the bitmap import rule of phase1.8; s2 and s3 (masks) are phase1.11's."""
    ctx = needs_store()
    golden = ctx.golden("semantics/group-masks")
    manifest = load_json(MANIFESTS / "semantics" / "group-masks.json")
    spec = spec_from_manifest(manifest, texture_set, tmp_path, ["User0", "User2"])
    assert len(spec["layers"]) == 2 and spec["layers"][0]["kind"] == "group"
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    compare_exact(raster(result, "User0"), golden, f"{texture_set}/user0")
    compare_exact(raster(result, "User2"), golden, f"{texture_set}/user2")


def test_default_group_mode_equals_normal() -> None:
    """3.4: the recorded default-mode group (s0) and the `Normal` group (s1) of `group-masks` are
    identical on every channel: the default mode is not a pass-through."""
    ctx = needs_store()
    golden = ctx.golden("semantics/group-masks")
    for user in ("user0", "user1", "user2"):
        assert golden.map_sha256("r1", f"s0/{user}") == golden.map_sha256("r1", f"s1/{user}")
