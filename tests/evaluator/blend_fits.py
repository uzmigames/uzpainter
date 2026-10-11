"""The published fit of phase1.10_compositor-blend-kernels and phase1.11_compositor-blend-gaps:
`parity/semantics/blend-kernels.json`.

Every documented `BlendingMode` as the evaluator implements it (`src/evaluator/arith.cpp`,
`shaders/evaluator_blend.hlsl`, `hwmath.h`), evaluated by the CPU store on the Tier 0 blend sweeps
(`blend-basic`, `blend-additive`, `blend-contrast`, `blend-component`: field B over field A in one
mode per texture set on eight channels of six formats at opacities 1, 0.5 and 0.25), on the hue
grid of the component modes and the off-grid opacities and flat normals of the normal-map modes
(`blend-component-hue`, `blend-normal-opacity` of the current envelope) and on the Normal channel
(`blend-normal-channel`), against both recordings, as |delta| statistics in export units
only (CONTRACT §6.4; nothing recorded is published). The Normal-channel stacks import the
authored normal fields as they are: the evaluator applies the channel's import rule (r, 1 - g, b)
that `blend-modes.json` records (phase1.12_compositor-height-normal). Run on the owner's machine:

    python tests/evaluator/blend_fits.py <uzp-evaluator-tests.exe> <work-dir>

writes the file; `test_compositor_blend_kernels.py::test_published_fit_reproduces` re-derives it
and requires the published file to match.
"""

from __future__ import annotations

import json
import re
import sys
import types
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

from tests.evaluator import masks_fits
from tests.evaluator.quantisation_fits import exported, unit
from tests.evaluator.sources_fits import channel_formats, export16, pooled, srgb8_decode
from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    REPO_ROOT,
    evaluate,
    raster,
    spec_from_manifest,
)
from tools.parity.fit.common import Context, document, entry, parameter, residual, source
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

SEMANTICS = REPO_ROOT / "parity" / "semantics"
FILE = "blend-kernels.json"
NORMAL_CHANNEL = "blend-normal-channel"

# Golden stem and texture set of every mode recorded by the Tier 0 sweeps.
SWEEPS: dict[str, tuple[str, str]] = {
    **{
        m: ("blend-basic", f"s{i}")
        for i, m in enumerate(
            [
                "Normal",
                "Replace",
                "Disable",
                "Multiply",
                "Divide",
                "InverseDivide",
                "Darken",
                "Lighten",
            ]
        )
    },
    **{
        m: ("blend-additive", f"s{i}")
        for i, m in enumerate(
            [
                "LinearDodge",
                "Subtract",
                "InverseSubtract",
                "Difference",
                "Exclusion",
                "SignedAddition",
                "Screen",
                "LinearBurn",
            ]
        )
    },
    **{
        m: ("blend-contrast", f"s{i}")
        for i, m in enumerate(
            [
                "Overlay",
                "ColorBurn",
                "ColorDodge",
                "SoftLight",
                "HardLight",
                "VividLight",
                "LinearLight",
                "PinLight",
            ]
        )
    },
    **{
        m: ("blend-component", f"s{i}")
        for i, m in enumerate(
            [
                "Tint",
                "Saturation",
                "Color",
                "Value",
                "NormalMapCombine",
                "NormalMapDetail",
                "NormalMapInverseDetail",
            ]
        )
    },
}
NORMAL_SETS = {"NormalMapCombine": "s1", "NormalMapDetail": "s2", "NormalMapInverseDetail": "s3"}
COMPONENT_MODES = ("Tint", "Saturation", "Color", "Value")
# Goldens of the current envelope (decision 067) and the texture sets recording each mode: the hue
# grid of the component modes, the normal-map modes off the recorded opacities and on flat normals.
HUE = "semantics/blend-component-hue"
NORMAL_OPACITY = "semantics/blend-normal-opacity"
ENVELOPE_SETS: dict[str, tuple[tuple[str, str], ...]] = {
    "Tint": ((HUE, "s0"), (HUE, "s4")),
    "Color": ((HUE, "s1"),),
    "Saturation": ((HUE, "s2"),),
    "Value": ((HUE, "s3"),),
    "NormalMapCombine": ((NORMAL_OPACITY, "s0"), (NORMAL_OPACITY, "s3")),
    "NormalMapDetail": ((NORMAL_OPACITY, "s1"), (NORMAL_OPACITY, "s4")),
    "NormalMapInverseDetail": ((NORMAL_OPACITY, "s2"), (NORMAL_OPACITY, "s5")),
}
NORMAL_MODES = tuple(NORMAL_SETS)

W3C = source("S-W3C-BLEND", "§10.1-10.2 separable blend modes; §10.3 non-separable (candidate)")
PDF = source("S-PDF-BLEND", "ISO 32000-1:2008 §11.3.5 blend modes")
GUIDE = source("A-HELP-GUIDE", "Blending modes")
PYDOC = source("A-PYDOC", "substance_painter.layerstack: BlendingMode, Node.set_blending_mode")
D3D = source(
    "X-D3D12",
    "Floating-point rules: rcp, sqrt, rsqrt within 1 ULP; FLOAT to UNORM, FLOAT to FLOAT16",
)
BARRE = source("P-BARRE", "Blending in Detail: whiteout blending and reoriented normal mapping")

HW = (
    "Divisions and roots use the recording GPU's float32 results (NVIDIA GeForce RTX 4090, D3D12): "
    "the correctly rounded value moved by -2..+1 ulp from tables measured over every float32 "
    "mantissa (src/evaluator/hwmath.h; uzp-evaluator-tests fp-hardware), on the CPU and on every "
    "GPU alike."
)
TRIG = (
    "The GPU's sine and cosine come from tables measured on every index of [0, float32(pi/2)] "
    "(src/evaluator/tables/hw-{sin,cos}.zlib; uzp-evaluator-tests trig-hardware); the GLSL "
    "arcsine is a float32 polynomial with fused multiply-adds (hwmath.h Asin) checked against "
    "the GPU's GLSL asin on every float32 of [0, 1]."
)
MIX = (
    "Opacity alpha (times the mask): over an opaque backdrop v = a (1 - alpha) + r alpha, the "
    "products rounded and summed in float32; over a transparent backdrop the source; else W3C "
    "§5.1. UNORM formats clamp r to [0, 1] first. Operands and writes per channel format as in "
    "quantisation-profile.json (isolated root, sRGB8 on linear values)."
)
KERNELS: dict[str, str] = {
    "Normal": "r = b.",
    "Replace": "r = b, mixed as a + (r - a) alpha.",
    "Disable": "the layer is skipped for the channel.",
    "Multiply": "r = a b.",
    "Divide": "r = max(0, min(1, a rcp(b))) (0/0 gives 1).",
    "InverseDivide": "r = max(0, min(1, b rcp(a))).",
    "Darken": "r = min(a, b) (NaN propagates).",
    "Lighten": "r = max(a, b) (NaN propagates).",
    "LinearDodge": "r = a + b.",
    "Subtract": "r = a - b.",
    "InverseSubtract": "r = b - a.",
    "Difference": "r = |a - b|.",
    "Exclusion": "r = fma(-2 (a - 1/2), b - 1/2, 1/2).",
    "SignedAddition": "r = (a + 2b) - 1.",
    "Screen": "r = fma(-(1 - a), 1 - b, 1).",
    "LinearBurn": "r = (a + b) - 1.",
    "Overlay": "r = HardLight(b, a).",
    "ColorBurn": "r = clamp(fma(a - 1, rcp(b), 1), 0, 1); mixed with one rounding, "
    "v = fma(a, 1 - alpha, r alpha).",
    "ColorDodge": "r = max(0, min(1, a rcp(1 - b))).",
    "SoftLight": "b <= 1/2: r = fma(2a, b, a a (1 - 2b)); "
    "else r = fma(sqrt(a), 2b - 1, 2a (1 - b)).",
    "HardLight": "b <= 1/2: r = 2a b; else r = fma(-2 (1 - a), 1 - b, 1).",
    "VividLight": "b <= 1/2: r = ColorBurn(a, 2b); else r = ColorDodge(a, 2 (b - 1/2)) "
    "(standard mix).",
    "LinearLight": "r = clamp(b <= 1/2 ? (a + 2b) - 1 : a + 2 (b - 1/2), 0, 1).",
    "PinLight": "b <= 1/2: r = min(a, 2b); else r = max(a, 2b - 1).",
}
HSV_TEXT = {
    "Tint": "hue of B, saturation and value of A",
    "Saturation": "saturation of B, hue and value of A",
    "Color": "hue and saturation of B, value of A",
    "Value": "value of B, hue and saturation of A",
}
NORMAL_TEXT = {
    "NormalMapCombine": "whiteout r = (a.xy + b.xy, a.z b.z)",
    "NormalMapDetail": "reoriented normal mapping with base a, detail b",
    "NormalMapInverseDetail": "reoriented normal mapping with base b, detail a",
}


def hsv_formula(mode: str) -> str:
    return (
        f"{mode}: f = HSV({HSV_TEXT[mode]}) with the value doubled, in float32 (fitted, "
        "phase1.11): hue in turns from the smallest component (red first, then green before "
        "blue on ties), centre C = 1 (blue), 3 (red), 5 (green) and p, q the other two (g and "
        "r, b and g, r and b): h6 = fma(p - (q + 3e), rcp(d + e), C), d = max - min, e = 2^-12, "
        "h = h6 float32(1/6), plus 1 if negative (1 itself kept); hue weights centred on the "
        "primaries: red fma(6, |h - 1/2|, -1), green fma(-6, |h - 1/3|, 2), blue "
        "fma(-6, |h - 2/3|, 2) with 1/3 and 2/3 as float32, clamped to [0, 1]; v = 2 max, "
        "lo = v fma(-d', rcp(max' + e), 1) of the saturation source (d', max'; Saturation: "
        "1 - d' rcp(max' + e) with two roundings), each component fma(v - lo, w, lo). A grey "
        f"channel keeps A (Value: B). {MIX} {HW}"
    )


def normal_formula(mode: str) -> str:
    return (
        f"{mode}: a, b = normalise(2c - 1) with z clamped to >= 0, normalise(v) = v rsqrt(fma(z, "
        "z, fma(x, x, y y))); below opacity 1, b is first rotated toward (0, 0, 1) by the "
        "opacity alpha (fitted, phase1.11): t = float32(pi/2) - asin(z), z clamped to [0, 1], "
        "with the recording GPU's GLSL arcsine (Vulkan and OpenGL; D3D12 differs); "
        "b' = (b.x k, b.y k, cos(alpha t)), "
        "k = sin(alpha t) rsqrt(fma(-z, z, 1)), sine and cosine the GPU's (table index "
        "floor(2^25 trunc(x float32(1/(2 pi))))); a flat b (z = 1) is kept; "
        f"{NORMAL_TEXT[mode]}: t = base + (0, 0, 1), u = "
        "detail (-1, -1, 1), d = fma(t.z, u.z, fma(t.y, u.y, t.x u.x)), r.xy = fma(t.xy, d, "
        "-(u.xy t.z)), r.z = t.z (d - u.z); result fma(normalise(r), 1/2, 1/2), written as it is "
        f"over an opaque backdrop (the opacity enters only through the rotation). A grey channel "
        f"takes B. {HW} {TRIG}"
    )


def separable_formula(mode: str) -> str:
    text = f"{mode}, per channel in float32 (fma: one rounding): {KERNELS[mode]} {MIX}"
    if mode in ("Divide", "InverseDivide", "ColorBurn", "ColorDodge", "VividLight", "SoftLight"):
        text += " " + HW
    return text


class Runs:
    """Evaluations of the blend sweeps (CPU store unless asked), cached per texture set."""

    def __init__(self, exe: Path, work: Path) -> None:
        self.exe = exe
        self.work = work
        self.ctx = Context(locate(), REPO_ROOT)
        self._results: dict[tuple[str, str, str], dict[str, Any]] = {}

    def result(self, stem: str, texture_set: str, backend: str = "cpu") -> dict[str, Any]:
        key = (stem, texture_set, backend)
        if key not in self._results:
            manifest = load_json(MANIFESTS / "semantics" / f"{stem}.json")
            workdir = self.work / stem / texture_set
            workdir.mkdir(parents=True, exist_ok=True)
            if stem == NORMAL_CHANNEL:
                spec = spec_from_manifest(manifest, texture_set, workdir, ["Normal"])
                spec["channels"] = [{"type": "Normal", "format": "RGB16F"}]
                for layer in spec["layers"]:
                    layer["uid"] += 1000  # clear of the default template's object ids
            else:
                spec = spec_from_manifest(
                    manifest, texture_set, workdir, list(channel_formats(manifest))
                )
            self._results[key] = evaluate(self.exe, spec, workdir, backend)
        return self._results[key]

    def recorded(self, stem: str, recording: str, map_name: str) -> np.ndarray:
        values: np.ndarray = self.ctx.golden(f"semantics/{stem}").map(recording, map_name).values
        return values

    def envelope_result(self, name: str, texture_set: str, backend: str = "cpu") -> dict[str, Any]:
        """The evaluation of a texture set of the golden `name` of the current envelope."""
        key = (name, texture_set, backend)
        if key not in self._results:
            manifest = masks_fits.envelope_manifest(name)
            workdir = self.work / name.replace("/", "-") / texture_set
            workdir.mkdir(parents=True, exist_ok=True)
            spec = spec_from_manifest(
                manifest, texture_set, workdir, list(channel_formats(manifest))
            )
            self._results[key] = evaluate(self.exe, spec, workdir, backend)
        return self._results[key]


def comparisons(
    runs: Runs, decode: np.ndarray, mode: str, backend: str = "cpu"
) -> list[tuple[str, str, str, str, np.ndarray, np.ndarray]]:
    """(golden id, map, recording, unit, ours, theirs) of every map recording `mode`."""
    out = []
    stem, texture_set = SWEEPS[mode]
    formats = channel_formats(load_json(MANIFESTS / "semantics" / f"{stem}.json"))
    result = runs.result(stem, texture_set, backend)
    for channel, fmt in formats.items():
        ours = exported(result, channel, fmt, decode)
        for recording in ("r1", "r2"):
            map_name = f"{texture_set}/{channel.lower()}"
            theirs = runs.recorded(stem, recording, map_name).reshape(ours.shape).astype(ours.dtype)
            out.append((f"tier0/semantics/{stem}", map_name, recording, unit(fmt), ours, theirs))
    for name, texture_set in ENVELOPE_SETS.get(mode, ()):
        golden = masks_fits.envelope_golden(name)
        envelope_formats = channel_formats(masks_fits.envelope_manifest(name))
        result = runs.envelope_result(name, texture_set, backend)
        for channel, fmt in envelope_formats.items():
            ours = exported(result, channel, fmt, decode)
            for recording in ("r1", "r2"):
                map_name = f"{texture_set}/{channel.lower()}"
                recorded: np.ndarray = golden.map(recording, map_name).values
                theirs = recorded.reshape(ours.shape).astype(ours.dtype)
                out.append((f"tier0/{name}", map_name, recording, unit(fmt), ours, theirs))
    if mode in NORMAL_SETS:
        texture_set = NORMAL_SETS[mode]
        ours = raster(runs.result(NORMAL_CHANNEL, texture_set, backend), "Normal")
        for recording in ("r1", "r2"):
            map_name = f"{texture_set}/normal"
            theirs = runs.recorded(NORMAL_CHANNEL, recording, map_name).reshape(ours.shape)
            out.append(
                (
                    f"tier0/semantics/{NORMAL_CHANNEL}",
                    map_name,
                    recording,
                    "float32 value",
                    ours,
                    theirs,
                )
            )
    return out


def residuals(runs: Runs, decode: np.ndarray, mode: str) -> list[dict[str, Any]]:
    return [
        residual(golden_id, map_name, recording, unit_, pooled([(ours, theirs)]))
        for golden_id, map_name, recording, unit_, ours, theirs in comparisons(runs, decode, mode)
    ]


HW_PARAMS = [
    parameter("hardware_tables", "src/evaluator/tables/hw-{rcp,sqrt,rsqrt}.zlib", "fitted"),
    parameter("hardware_gpu", "NVIDIA GeForce RTX 4090, D3D12", "fitted"),
]


def mode_entry(runs: Runs, decode: np.ndarray, mode: str) -> dict[str, Any]:
    if mode in COMPONENT_MODES:
        return entry(
            f"kernel-{mode.lower()}",
            f"BlendingMode.{mode} in the evaluator",
            hsv_formula(mode),
            [W3C, GUIDE, PYDOC, D3D],
            [
                parameter("value_gain", 2.0, "fitted"),
                parameter("hsv_epsilon", 2.0**-12, "fitted"),
                parameter("hue_offset", 3 * 2.0**-12, "fitted"),
                *HW_PARAMS,
            ],
            residuals(runs, decode, mode),
            notes=(
                "The float32 hue was identified on tier0/semantics/blend-component-hue (decision "
                "073): the numerator p - (q + 3e) and the weights centred on the primaries; "
                "tier0/semantics/blend-component is the held-out validation."
            ),
        )
    if mode in NORMAL_MODES:
        return entry(
            f"kernel-{mode.lower()}",
            f"BlendingMode.{mode} in the evaluator (user channels and the Normal channel)",
            normal_formula(mode),
            [BARRE, PYDOC, D3D],
            [
                parameter("flat_normal", [0.0, 0.0, 1.0], "public_documentation"),
                *HW_PARAMS,
                parameter("trig_tables", "src/evaluator/tables/hw-{sin,cos}.zlib", "fitted"),
            ],
            residuals(runs, decode, mode),
        )
    hardware = mode in (
        "Divide",
        "InverseDivide",
        "ColorBurn",
        "ColorDodge",
        "VividLight",
        "SoftLight",
    )
    return entry(
        f"kernel-{mode.lower()}",
        f"BlendingMode.{mode} in the evaluator",
        separable_formula(mode),
        [W3C, PDF, GUIDE, PYDOC, D3D],
        HW_PARAMS if hardware else [],
        residuals(runs, decode, mode),
    )


PASSTHROUGH = "semantics-ui/group-passthrough-masks"
PASSTHROUGH_SETS = ("s0", "s1", "s2", "s3")
# An operator settings-sheet entry that set a node's mode through Painter's UI.
UI_MODE = re.compile(r"Layers/Blending mode \(step (\d+), (\w+)\)")


def passthrough_spec(
    manifest: dict[str, Any], texture_set: str, workdir: Path, channels: list[str]
) -> dict[str, Any]:
    """The spec of a `semantics-ui/group-passthrough-masks` texture set: its instruction sequence
    (masks_fits.spec_from_steps) with the group modes the operator set through the UI (the
    runtime member `Passthrough`, the documented `PassThrough`)."""
    spec = masks_fits.spec_from_steps(manifest, texture_set, workdir, channels)
    nodes: dict[int, dict[str, Any]] = {}
    pending = list(spec["layers"])
    while pending:
        node = pending.pop()
        nodes[node["uid"]] = node
        pending.extend(node.get("children", []))
    for setting in manifest["applied_settings"]:
        match = UI_MODE.fullmatch(setting["name"])
        if match is None:
            continue
        node = nodes.get(int(match.group(1)) + masks_fits.UID_OFFSET)
        if node is not None:
            assert setting["value"] == "Passthrough", setting
            node.setdefault("blending", {}).setdefault(match.group(2), {})["mode"] = "PassThrough"
    return spec


def passthrough_residuals(runs: Runs, decode: np.ndarray) -> list[dict[str, Any]]:
    manifest = masks_fits.envelope_manifest(PASSTHROUGH)
    golden = masks_fits.envelope_golden(PASSTHROUGH)
    formats = channel_formats(manifest)
    out = []
    for texture_set in PASSTHROUGH_SETS:
        workdir = runs.work / PASSTHROUGH.replace("/", "-") / texture_set
        spec = passthrough_spec(manifest, texture_set, workdir, sorted(formats))
        result = evaluate(runs.exe, spec, workdir, "cpu")
        for channel in sorted(formats):
            fmt = formats[channel]
            ours = raster(result, channel)
            value = ours if fmt.endswith("F") else export16(ours, fmt, decode)
            map_name = f"{texture_set}/{channel.lower()}"
            for recording in ("r1", "r2"):
                theirs = golden.map(recording, map_name).values.reshape(value.shape)
                diff = pooled([(value.astype(np.float64), theirs.astype(np.float64))])
                out.append(residual(f"tier0/{PASSTHROUGH}", map_name, recording, unit(fmt), diff))
    return out


def passthrough_entry(runs: Runs, decode: np.ndarray) -> dict[str, Any]:
    return entry(
        "kernel-passthrough",
        "BlendingMode.PassThrough (group layers only; the runtime member is Passthrough)",
        "A PassThrough group composites its visible children onto a copy of the accumulator "
        "below it, each child stored in the channel format with its own mode, opacity and mask, "
        "and then moves the accumulator toward that result by the group's opacity t times its "
        "mask: v = fma(g - a, t, a) over an opaque backdrop (one rounding); over a transparent "
        "backdrop the result with coverage t times its coverage; between, the premultiplied lerp "
        "(not recorded). Set through Painter's UI (decision 029); the documented BlendingMode."
        "PassThrough does not exist at runtime.",
        [PYDOC, GUIDE],
        [],
        passthrough_residuals(runs, decode),
        notes=(
            "Fitted on tier0/semantics-ui/group-passthrough-masks s0-s3 (no mask, a group mask, "
            "a child mask, both; RGB16, sRGB8 and RGB32F); its Normal-mode controls s4-s7 are "
            "the group-masks stack. The scaled-children hypothesis of phase1.4 is refuted."
        ),
    )


MODES = list(SWEEPS)


def build(exe: Path, work: Path) -> dict[str, Any]:
    runs = Runs(exe, work)
    decode = srgb8_decode(exe, work)
    entries = [mode_entry(runs, decode, mode) for mode in MODES]
    entries.append(passthrough_entry(runs, decode))
    corpus = sorted(
        {f"tier0/semantics/{stem}" for stem, _ in SWEEPS.values()}
        | {f"tier0/semantics/{NORMAL_CHANNEL}", f"tier0/{HUE}", f"tier0/{NORMAL_OPACITY}"}
        | {f"tier0/{PASSTHROUGH}"}
    )
    return document(
        "blend-kernels",
        "The blend kernels of the evaluator (04 section 3, tasks "
        "phase1.10_compositor-blend-kernels and phase1.11_compositor-blend-gaps) for every "
        "documented BlendingMode, evaluated by the "
        "CPU store under the current profile on the Tier 0 blend sweeps, on the hue grid of the "
        "component modes, on the normal-map modes off the recorded opacities and on flat "
        "normals, on the Normal channel and on the UI-set Passthrough groups. Residuals are "
        "|delta| in export units (16-bit PNG codes, OpenEXR float32 values) per texture set and "
        "channel, against both recordings (r1 same session, r2 after save and reopen). "
        "Supersedes blend-modes.json for the evaluator; blend-modes.json keeps the phase0.7 "
        "candidate fits.",
        corpus,
        entries,
    )


def serialise(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tests/evaluator/blend_fits.py <uzp-evaluator-tests.exe> <work-dir>")
        return 2
    doc = build(Path(argv[0]), Path(argv[1]))
    (SEMANTICS / FILE).write_text(serialise(doc), encoding="utf-8", newline="\n")
    print(f"wrote parity/semantics/{FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
