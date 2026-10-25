"""The published fit of phase1.11_compositor-mask-effects: `parity/semantics/masks-levels.json`.

Masks, mask and content effects and Levels as the evaluator implements them (`src/evaluator/
dag.cpp`, `evaluate.cpp`, `arith.cpp` Levels and the effect mix, `hwmath.h` log2/exp2), evaluated
by the CPU store on the Tier 0 goldens that record them (`mask-precision`, `group-masks` s2-s3,
`group-coverage-order`, `levels-clamp`, `effect-order`, `api-probes/mask-stack`), against both
recordings, as |delta|
statistics in export units only (CONTRACT §6.4; nothing recorded is published). Also the converter
from a Tier 0 instruction sequence with masks and effects to an evaluator spec (`spec_from_steps`).
Run on the owner's machine:

    python tests/evaluator/masks_fits.py <uzp-evaluator-tests.exe> <work-dir>

writes the file; `test_compositor_mask_effects.py::test_published_fit_reproduces` re-derives it and
requires the published file to match.
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

if __name__ == "__main__":
    # Run as a script: the repository root is the import root, and its `tests` folder is the
    # `tests` package even when another distribution installs one.
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root))
    _tests = types.ModuleType("tests")
    _tests.__path__ = [str(_root / "tests")]
    sys.modules["tests"] = _tests

from tests.evaluator.sources_fits import channel_formats, export16, pooled, srgb8_decode
from tests.evaluator.test_compositor_tile_dag import (
    REPO_ROOT,
    SRGB_ENCODED_ON_EXPORT,
    TEMPLATES_DIR,
    bitmap_color_space,
    evaluate,
    raster,
)
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.common import document, entry, parameter, residual, source
from tools.parity.fit.oracle import Golden, load
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

SEMANTICS = REPO_ROOT / "parity" / "semantics"
FILE = "masks-levels.json"
PUBLISHED = SEMANTICS / FILE
# The goldens of the current oracle envelope (decision 037).
ENVELOPE = current_envelope()
ENVELOPE_MANIFESTS = manifest_root(ENVELOPE)


def envelope_manifest(name: str) -> dict[str, Any]:
    """The public manifest `name` (`<folder>/<stem>`) of the current envelope."""
    result: dict[str, Any] = load_json(ENVELOPE_MANIFESTS / "tier0" / f"{name}.json")
    return result


def envelope_golden(name: str) -> Golden:
    """The golden `name` of the current envelope, from the private store."""
    return load(locate(), ENVELOPE_MANIFESTS / "tier0" / f"{name}.json")


PYDOC = source(
    "A-PYDOC",
    "substance_painter.layerstack: LayerNode.add_mask, MaskBackground, insert_fill (mask and "
    "content stacks), FillEffectNode, LevelsEffectNode and its parameters, Node.set_blending_mode",
)
GUIDE = source("A-HELP-GUIDE", "Masks, fill and levels effects, blending modes")
W3C = source("S-W3C-BLEND", "§5.1 simple alpha compositing; §10 blend modes (the mask kernels)")
D3D = source(
    "X-D3D12",
    "Floating-point rules: rcp within 1 ULP, log2 / exp2 approximations, FLOAT to UNORM",
)

# ── Instruction sequence -> evaluator spec ───────────────────────────────────

LAYER_KINDS = {
    "substance_painter.layerstack.insert_fill": "fill",
    "substance_painter.layerstack.insert_group": "group",
    "substance_painter.layerstack.insert_levels_effect": "levels",
    "substance_painter.layerstack.insert_filter_effect": "filter",
}
GETTERS = ("get_", "is_", "has_", "mask_effects", "source_mode")
# Node uids are the step numbers moved clear of the template's object ids.
UID_OFFSET = 1000
# The filter `effect-order` records (default parameters) and the evaluator's asset for that one
# configuration (src/evaluator/dag.h `kRecordedBlurAsset`, decision 346).
RECORDED_BLUR_SEARCH = "s:starterassets u:filter n:Blur="
RECORDED_BLUR_ASSET = "uzasset://filter/blur@1"

type BitmapDefaultResolver = Callable[[str | None, bytes], str]


class Unmodelled(AssertionError):
    """A step of the texture set that the converter does not model."""


def resource_entry(path: Path, workdir: Path) -> dict[str, Any]:
    """A spec resource for the fixture `path`: its PNG bytes, decoded by the evaluator."""
    data = path.read_bytes()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / path.name).write_bytes(data)
    return {"sha256": hashlib.sha256(data).hexdigest(), "png": path.name}


def is_getter(call: str, args: dict[str, Any]) -> bool:
    name = call.rsplit(".", 1)[-1]
    if args.get("probe"):
        return True
    if name.startswith(GETTERS) or name in GETTERS:
        return True
    if name == "active_channels" and "channels" not in args:
        return True
    return name == "affected_channel" and "channel" not in args


def spec_from_steps(
    manifest: dict[str, Any],
    texture_set: str,
    workdir: Path,
    outputs: list[str],
    *,
    bitmap_default_resolver: BitmapDefaultResolver | None = None,
) -> dict[str, Any]:
    """The evaluator spec of `texture_set` of a Tier 0 instruction sequence with layers, groups,
    masks (background, fill and levels effects with their mono blending) and content effects
    (fill effects with per-channel sources and blending, levels with their affected channel).
    Steps on other texture sets are ignored; probes and getters are skipped; a step this
    converter does not model fails the test. Sequences without a `texture_set` argument have one
    texture set, which is `texture_set`."""
    steps = manifest["instruction_sequence"]["steps"]
    inputs = {i["input_id"]: REPO_ROOT / i["path"] for i in manifest["inputs"]}
    resolution = 256
    channels: list[dict[str, str]] = []
    resources: dict[int, dict[str, Any]] = {}
    nodes: dict[int, dict[str, Any]] = {}
    roots: list[int] = []  # top first

    def ours(step: int | None) -> bool:
        return step is not None and step in nodes and nodes[step]["set"] == texture_set

    def new_node(n: int, kind: str, target: str) -> dict[str, Any]:
        node: dict[str, Any] = {
            "uid": n + UID_OFFSET,
            "kind": kind,
            "set": target,
            "children": [],
            "effects": [],
            "mask": None,
            "blending": {},
            "mono": {"mode": "Normal", "opacity": 1.0},
            "sources": {},
            "mono_source": None,
            "active": None,
            "projection": None,
            "levels": None,
            "affected": None,
            "list": None,
        }
        nodes[n] = node
        return node

    for step in steps:
        call, args, n = step["call"], step["args"], step["step"]
        if call == "substance_painter.project.create":
            resolution = int(args.get("default_texture_resolution", 256))
            continue
        if call.endswith("Stack.add_channel"):
            channels.append({"type": args["channel"], "format": args["format"]})
            continue
        if call.endswith("resource.import_project_resource"):
            resources[n] = resource_entry(inputs[args.get("input", args.get("image"))], workdir)
            continue
        if call.startswith("substance_painter.export."):
            continue
        if is_getter(call, args):
            continue
        if call in LAYER_KINDS:
            kind = LAYER_KINDS[call]
            anchor = args.get("above_step", args.get("inside_step"))
            if anchor is None:
                target = args.get("texture_set", texture_set)
                node = new_node(n, kind, target)
                if target == texture_set:
                    roots.insert(0, n)
                    node["list"] = roots
                continue
            target = nodes[anchor]["set"]
            node = new_node(n, kind, target)
            node["filter_search"] = args.get("filter_search")
            if target != texture_set:
                continue
            if "above_step" in args:
                siblings = nodes[anchor]["list"]
                siblings.insert(siblings.index(anchor), n)
                node["list"] = siblings
            else:
                stack = args.get("stack", args.get("node_stack"))
                owner = nodes[anchor]
                if stack == "Substack":
                    siblings = owner["children"]
                elif stack == "Content":
                    siblings = owner["effects"]
                elif stack == "Mask":
                    if owner["mask"] is None:
                        raise Unmodelled(f"step {n}: an effect in a layer without a mask")
                    siblings = owner["mask"]["effects"]
                    node["in_mask"] = True
                else:
                    raise Unmodelled(f"step {n}: {call} into {stack} is not modelled")
                siblings.insert(0, n)
                node["list"] = siblings
            if "above_step" in args and nodes[anchor].get("in_mask"):
                node["in_mask"] = True
            continue
        node_step = args.get("node_step")
        if not ours(node_step):
            if node_step is None:
                raise Unmodelled(f"step {n}: {call} is not modelled by this converter")
            continue
        node = nodes[node_step]
        name = call.rsplit(".", 1)[-1]
        channel = args.get("channel")
        if name == "add_mask":
            node["mask"] = {"background": args["background"], "effects": []}
        elif name == "active_channels":
            node["active"] = list(args["channels"])
        elif name == "set_source":
            if "resource_step" in args:
                resource = resources[args["resource_step"]]
                png = (workdir / resource["png"]).read_bytes()
                item: dict[str, Any] = {
                    "bitmap": resource["sha256"],
                    "color_space": (
                        bitmap_default_resolver(channel, png)
                        if bitmap_default_resolver is not None and "color_space" not in args
                        else bitmap_color_space(args, channel, png)
                    ),
                }
            else:
                space = args.get("color_space", "Working")
                item = {"uniform": list(args["color"]), "color_space": space}
            if channel is None:
                node["mono_source"] = item
            else:
                node["sources"][channel] = item
        elif name == "set_projection_mode":
            node["projection"] = {**(node["projection"] or {}), "mode": args["projection_mode"]}
        elif name == "set_projection_parameters":
            extra = {k: v for k, v in args.items() if k != "node_step"}
            node["projection"] = {**(node["projection"] or {"mode": "UV"}), **extra}
        elif name in ("set_blending_mode", "set_opacity"):
            if name == "set_blending_mode":
                key, value = "mode", args["blending_mode"]
            else:
                key, value = "opacity", float(args["opacity"])
            if channel is None:
                node["mono"][key] = value
            else:
                entry_ = node["blending"].setdefault(channel, {"mode": "Normal", "opacity": 1.0})
                entry_[key] = value
        elif name == "affected_channel":
            node["affected"] = channel
        elif name == "set_parameters":
            node["levels"] = {k: v for k, v in args.items() if k != "node_step"}
        elif name == "set_name":
            continue
        else:
            raise Unmodelled(f"step {n}: {call} is not modelled by this converter")

    def emit_effect(step: int) -> dict[str, Any]:
        node = nodes[step]
        effect: dict[str, Any] = {"kind": node["kind"], "uid": node["uid"]}
        if node["kind"] == "filter":
            # The one recorded filter configuration (decision 346): the starter-asset Blur at its
            # default parameters, the evaluator's `kRecordedBlurAsset`. This maps the golden's
            # step; it is no alias (resource search still refuses the Painter name).
            if node["filter_search"] != RECORDED_BLUR_SEARCH or node.get("in_mask"):
                raise Unmodelled(f"step {step}: filter effects are a release gap (P3-PROC)")
            effect["asset"] = RECORDED_BLUR_ASSET
            effect["active_channels"] = node["active"] or []
            return effect
        if node["kind"] == "levels":
            effect["components"] = [node["levels"] or {}]
            if not node.get("in_mask"):
                effect["affected_channel"] = node["affected"]
            return effect
        if node["projection"] is not None:
            effect["projection"] = node["projection"]
        if node.get("in_mask"):
            if node["mono_source"] is not None:
                effect["source"] = node["mono_source"]
            effect["mode"] = node["mono"]["mode"]
            effect["opacity"] = node["mono"]["opacity"]
            return effect
        effect["sources"] = node["sources"]
        effect["blending"] = node["blending"]
        if node["active"] is not None:
            effect["active_channels"] = node["active"]
        return effect

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
            if node["effects"]:
                layer["effects"] = [emit_effect(e) for e in node["effects"]]
        else:
            layer["children"] = [emit(child) for child in node["children"]]
        if node["mask"] is not None:
            layer["mask"] = {
                "background": node["mask"]["background"],
                "effects": [emit_effect(e) for e in node["mask"]["effects"]],
            }
        return layer

    if not channels:
        template = load_json(TEMPLATES_DIR / "default.json")
        channels = [{"type": c["type"], "format": c["format"]} for c in template["channels"]]
    return {
        "template": "default",
        "resolution": [resolution, resolution],
        "channels": channels,
        "resources": list(resources.values()),
        "layers": [emit(step) for step in roots],
        "outputs": outputs,
    }


# ── The fit ──────────────────────────────────────────────────────────────────

# (golden folder/stem, texture sets, channels or None for every added channel)
MASK_PRECISION = ("semantics/mask-precision", ["s0", "s1", "s2"], None)
MASK_MIX = ("semantics/mask-precision", ["s3"], None)
GROUP_MASKS = ("semantics/group-masks", ["s2", "s3"], None)
GROUP_COVERAGE = ("semantics/group-coverage-order", ["s0", "s1", "s2", "s3"], None)
LEVELS = ("semantics/effect-order", ["s6"], None)
EFFECT_ORDER = ("semantics/effect-order", ["s0", "s1", "s2", "s3", "s4", "s5", "s7"], None)
LEVELS_CLAMP = ("semantics/levels-clamp", ["s0", "s1", "s2", "s3"], None)
PROBE = ("api-probes/mask-stack", ["uzp_plane"], ["BaseColor"])


def unit(fmt: str) -> str:
    return "float32 value" if fmt.endswith("F") else "16-bit code value"


def exported16(stored: np.ndarray, channel: str, fmt: str, decode: np.ndarray) -> np.ndarray:
    """The 16-bit PNG export of the stored raster of `channel`. An sRGB8 BaseColor, Specular or
    Emissive writes the sRGB encode of its linear read-out, the sRGB8 decode of the stored code
    (src/export/encode.h, decision 126); every other sRGB8 channel (the User channels of the
    semantics goldens) and the UNORM formats write their read-out (`export16`)."""
    if fmt == "sRGB8" and channel in SRGB_ENCODED_ON_EXPORT:
        from tests.export.tier0 import srgb16  # tests/export/tier0 imports this module at load

        encoded: np.ndarray = srgb16(decode[stored].astype(np.float32)).astype(np.int64)
        return encoded
    return export16(stored, fmt, decode)


class Runs:
    """Evaluations of the goldens' texture sets (CPU store), cached."""

    def __init__(self, exe: Path, work: Path) -> None:
        self.exe = exe
        self.work = work
        self.decode = srgb8_decode(exe, work)
        self._results: dict[tuple[str, str], dict[str, Any]] = {}

    def residuals(self, case: tuple[str, list[str], list[str] | None]) -> list[dict[str, Any]]:
        name, texture_sets, selected = case
        manifest = envelope_manifest(name)
        formats = channel_formats(manifest) or {"BaseColor": "sRGB8"}
        golden = envelope_golden(name)
        out = []
        for texture_set in texture_sets:
            channels = selected if selected is not None else sorted(formats)
            key = (name, texture_set)
            if key not in self._results:
                workdir = self.work / name.replace("/", "-") / texture_set
                spec = spec_from_steps(manifest, texture_set, workdir, channels)
                self._results[key] = evaluate(self.exe, spec, workdir, "cpu")
            result = self._results[key]
            for channel in channels:
                fmt = formats[channel]
                ours = raster(result, channel)
                exported = (
                    ours if fmt.endswith("F") else exported16(ours, channel, fmt, self.decode)
                )
                map_name = f"{texture_set}/{channel.lower()}"
                for recording in ("r1", "r2"):
                    theirs = golden.map(recording, map_name).values.reshape(exported.shape)
                    diff = pooled([(exported.astype(np.float64), theirs.astype(np.float64))])
                    out.append(residual(f"tier0/{name}", map_name, recording, unit(fmt), diff))
        return out


HW_POW = [
    parameter(
        "hardware_tables", "src/evaluator/tables/hw-{lg2-hi,lg2-lo,ex2-pos,ex2-neg}.zlib", "fitted"
    ),
    parameter("hardware_rcp", "src/evaluator/tables/hw-rcp.zlib", "fitted"),
    parameter("hardware_gpu", "NVIDIA GeForce RTX 4090, D3D12", "fitted"),
]


def build_document(exe: Path, work: Path) -> dict[str, Any]:
    runs = Runs(exe, work)
    entries = [
        entry(
            "mask-precision",
            "Mask stacks: background, a bitmap fill effect and its opacity, mask storage precision",
            "m := background (White 1, Black 0); each visible mask effect bottom-up: a fill "
            "effect m := m + (r - m) alpha with r = kernel(mode, m, b) clamped to [0, 1], b the "
            "source's mono value and alpha the effect's opacity; m is stored at 16 bits (the "
            "UNORM write rule) after every effect on every channel format; the layer blends with "
            "opacity x m (a disabled or absent mask counts as 1).",
            [PYDOC, GUIDE, D3D],
            [
                parameter("mask_bits", 16, "fitted"),
                parameter("write_rule", "UNORM16, n + 4 fractional bits, ties down", "fitted"),
            ],
            runs.residuals(MASK_PRECISION),
        ),
        entry(
            "mask-stack-effect-mix",
            "The mix of a mask effect over the mask below it (two mask effects, Multiply)",
            "v = a + (r - a) alpha for every mode (the layer mix a (1 - alpha) + r alpha misses 6 "
            "of 65536 texels of the second, Multiply, effect); a content fill effect takes the "
            "layer mix instead (entry content-effect-order).",
            [PYDOC, W3C],
            [],
            runs.residuals(MASK_MIX),
        ),
        entry(
            "group-masks",
            "Masks on a group (default mode and Normal) and on its Multiply child",
            "A group's mask multiplies the opacity of its isolated composite exactly as a layer's "
            "mask does; a child's mask applies inside the group.",
            [PYDOC, W3C],
            [],
            runs.residuals(GROUP_MASKS),
            notes=(
                "Evaluated under profile painter-12.1-isolated-coverage-weights (decision 058). "
                "Every map equals both recordings. The sRGB8 maps: the group coverage "
                "(255 + y)/510 lies half-way between two 8-bit codes on even rows, and Painter "
                "stores the code of its binary16 value (up on rows y mod 64 >= 32, down "
                "elsewhere; decision 044); the float32 value stored all ties down (3 709 values "
                "off). On the RGB32F row where the child's mask is 0 the uniform's float32 value "
                "reproduces the recordings (1 + (v - 1) leaves 8 values off). Where the child's "
                "mask is strictly between 0 and 1 the uniform Screen fill above it composites "
                "over a partly covered backdrop with the coverage weights of entry "
                "group-coverage-order (the W3C straight-colour order of the earlier profiles "
                "left 20 631 RGB32F and 57 RGB16 values one step off)."
            ),
        ),
        entry(
            "group-coverage-order",
            "The float32 source-over onto a partly covered backdrop inside an isolated group",
            "A layer composited onto a backdrop that is not opaque (coverage ab < 1, including a "
            "backdrop layer of coverage 0), with alpha as = opacity x mask x source alpha and "
            "blend result B = kernel(mode, Cb, Cs): wb = fl(ab fl(1 - as)), ao = fl(as + wb), "
            "ws = fl(ao - ab) (the weight of the source alone re-derived from the rounded "
            "coverage), C = fl(fma(ws, Cs, fma(ab, fl(as B), fl(wb Cb))) x Rcp(ao)) with the "
            "recording GPU's reciprocal; the coverage is ao. Over an opaque backdrop it reduces "
            "to the fitted opacity mix fl(fl(Cb (1 - as)) + fl(B as)); the first layer of an "
            "isolated list is copied over the empty start. The sRGB8 coverage plane goes "
            "through binary16 only from 1/2 up (decision 059); the RGB8 and L8 coverage planes "
            "take the plain 8-bit write rule, ties down.",
            [PYDOC, W3C, D3D],
            [parameter("hardware_rcp", "src/evaluator/tables/hw-rcp.zlib", "fitted")],
            runs.residuals(GROUP_COVERAGE),
            notes=(
                "Diagnostic golden of phase1.10_compositor-float32-residual (decision 048): over "
                "an opaque black root the export is g x ag, lossless where it lies in [1/2, 1). "
                "The order is identified on it and confirmed on group-masks s2-s3 and "
                "quantisation-thirds (quantisation-profile.json). Rows whose coverage sum "
                "0.5 + 0.5 m is exact in float32 already matched the W3C straight-colour order; "
                "the others differ through ws = ao - ab. Opacity 0.3 over a mask of 0 gives "
                "fl(fl(Cs as) x Rcp(as)), not Cs, while the mask's own layer (the first of the "
                "group) is copied. Even rows of the 0.5 sets put the group coverage on an 8-bit "
                "tie: RGB8 and L8 store all of them down (the plain rule, no binary16). With "
                "opacity 0.3, eight coverages in [0.3, 0.5) lie on 8-bit ties: the sRGB8 plane "
                "stores all of them down while binary16 sends five up, so the binary16 step "
                "applies from 1/2 up only (its mechanism is not identified; the evidence below "
                "1/2 is these eight rows)."
            ),
        ),
        entry(
            "levels",
            "The Levels effect of a content stack (one effect per channel)",
            "t = (v - in_min) Rcp(in_max - in_min) with the recording GPU's reciprocal; when gamma "
            "is not 1, t = sign(t) pow(|t|, gamma) with pow(x, g) = exp2(g log2 x) through the "
            "recording GPU's log2 and exp2 (hwmath.h tables); out = fma(t, out_max - out_min, "
            "out_min); the result is stored in the channel format.",
            [PYDOC, GUIDE, D3D],
            HW_POW,
            runs.residuals(LEVELS),
        ),
        entry(
            "levels-clamp",
            "Levels at and beyond the range ends, with and without clamp",
            "clamp limits the normalised input t to [0, 1] before gamma; the output range is not "
            "clamped (out of [0, 1] values reach the float channels; UNORM channels clamp at "
            "storage); chained levels effects store between effects.",
            [PYDOC, D3D],
            HW_POW,
            runs.residuals(LEVELS_CLAMP),
        ),
        entry(
            "mask-stack-probe",
            "A Black mask with a UV-projected 8-bit bitmap fill effect in Screen at 0.75 under a "
            "clamped levels effect with gamma 1.2 (API probe, BaseColor sRGB8)",
            "The mask formulas above; the levels effect of a mask has no blending (the API "
            "refuses it) and remaps the mask in place. The BaseColor export is the sRGB encode "
            "of the stored code's sRGB8 decode (decision 126). Unstable golden: r1 (same "
            "session) is the exact target (decision 032); r2's residual is reported.",
            [PYDOC],
            HW_POW,
            runs.residuals(PROBE),
            notes=(
                "Equals r1 on all 196 608 values. Where the mask is 0 the layer stores the "
                "template base float32(0.8) as sRGB8 code 231, whose decode 0.80078125 exports "
                "59422, not the 59397 of the empty channel's constant. r2 differs from r1 on "
                "4 608 values by up to 252 codes (Painter is unstable on this probe after save "
                "and reopen, parity/reports/phase0/tier0-stability.md §4; not admitted), so the "
                "entry stays calibrated. The residuals published before came from this fit "
                "writing BaseColor's linear decode, the rule of the User channels, instead of its "
                "sRGB encode: 3048 while the template base held the export value 0.9063401 as a "
                "linear value (itself 3334 off with the encode), 6943 once decision 126 made the "
                "base linear. The evaluation of the mask stack did not change."
            ),
        ),
        entry(
            "content-effect-order",
            "Content effects in list order (fill effect and levels)",
            "Content effects run bottom-up in list order on the layer's own content for the "
            "channel, the content stored in the channel format after each effect: a fill effect "
            "blends its source for the channel with its per-channel mode and opacity through the "
            "layer mix fl(fl(a fl(1 - alpha)) + fl(r alpha)) with r = kernel(mode, a, b) (not the "
            "mask effect mix fl(a + fl(fl(r - a) alpha))), a levels effect remaps its affected "
            "channel only, and the starter-asset Blur at its default parameters, Normal at "
            "opacity 1, on this 256 x 256 RGB16 or sRGB8 content is the content rounded toward "
            "zero to binary16.",
            [PYDOC, W3C],
            [],
            runs.residuals(EFFECT_ORDER),
            notes=(
                "Decision 346. The Blur rule holds only in that recorded configuration: it is "
                "not a Blur implementation, every other filter, parameter, blending, format, "
                "resolution and colour management fails with unsupported_node, the family is "
                "uncertified and no alias names it. Evidence that no kernel acts there: the "
                "linear fields of s7 (codes 257 x, 257 y, 256 x + y) are unchanged at the texture "
                "borders, which bounds any kernel weight off the centre below 0.002. With the "
                "mask effect mix the content fill effect misses s3 on 20 values, s4 on 32, s0, "
                "s1 and s2 on 1 or 2 (one 16-bit code, RGB16). s6 is entry `levels`."
            ),
        ),
        entry(
            "geometry-mask-mesh",
            "Geometry masks of type Mesh (inclusion or exclusion list of mesh objects)",
            "The mask is multiplied by the texel-centre coverage (UV raster convention) of the "
            "texture set's triangles of the included objects; UVTile geometry masks fail "
            "explicitly.",
            [PYDOC],
            [],
            [],
            notes="Release gap: no Tier 0 golden records a geometry mask.",
            gap=True,
        ),
    ]
    corpus = sorted(
        f"tier0/{case[0]}"
        for case in (
            MASK_PRECISION,
            MASK_MIX,
            GROUP_MASKS,
            GROUP_COVERAGE,
            LEVELS,
            EFFECT_ORDER,
            LEVELS_CLAMP,
            PROBE,
        )
    )
    published = document(
        "masks-levels",
        "Masks, mask and content effects and the Levels effect of the evaluator (04 sections 1 "
        "and 2, task phase1.11_compositor-mask-effects), evaluated by the CPU store under the "
        "current profile. Residuals are |delta| in export units (16-bit PNG codes, OpenEXR "
        "float32 values) per texture set and channel, against both recordings (r1 same session, "
        "r2 after save and reopen).",
        corpus,
        entries,
    )
    # The goldens are the current envelope's (decision 037).
    published["painter_build_id"] = ENVELOPE["painter_build"]
    return published


def serialise(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tests/evaluator/masks_fits.py <uzp-evaluator-tests.exe> <work-dir>")
        return 2
    doc = build_document(Path(argv[0]), Path(argv[1]))
    PUBLISHED.write_text(serialise(doc), encoding="utf-8", newline="\n")
    print(f"wrote parity/semantics/{FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
