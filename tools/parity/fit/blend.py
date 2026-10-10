"""Separable blend modes and the order of evaluation (`parity/semantics/blend-modes.json`, 04 §2-3).

Goldens: `blend-basic`, `blend-additive`, `blend-contrast` (per texture set s0..s7 one
`BlendingMode`: a lower fill with field A / grey A at opacity 1, Normal, under an upper fill with
field B / grey B in the set's mode at the channel's opacity, on the eight blend channels of
`corpus.BLEND_CHANNELS`), `blend-inputs` (the fields as each channel stores them: the model
operands) and `blend-order` (three layers in four stack orders over the white base).

Candidates: the W3C Compositing and Blending Level 1 / ISO 32000 separable blend functions, the
usual published definitions of the modes Painter adds (Divide, Subtract, Linear Dodge/Burn,
Vivid/Linear/Pin Light, ...), evaluated in float32 with fused multiply-adds, and the Direct3D
data conversion rules for the storage formats. The non-separable and normal-map modes come from
`blend_component` (fit-blend-component) and are published in the same document.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.fit.common import (
    RECORDINGS,
    UNIT,
    Context,
    channel_format,
    document,
    entry,
    parameter,
    residual,
    source,
    to_storage,
)
from tools.parity.fit.srgb import decode, significand_round, srgb8_store
from tools.parity.fit.stats import Array, difference
from tools.parity.tier0_semantics import fixtures
from tools.parity.tier0_semantics.corpus import BLEND_CHANNELS, BLEND_FAMILIES

FILE = "blend-modes.json"
INPUTS = "semantics/blend-inputs"
ORDER = "semantics/blend-order"
FAMILIES = ("basic", "additive", "contrast")
GUARD_BITS = 4  # UNORM write: the value is truncated to (bits + 4) fractional bits first
SRGB_SIGNIFICANT_BITS = 8  # sRGB8 linear value: IEC decode on 8 significant bits (srgb-transfer)
UNORM_FORMATS = frozenset({"RGB16", "L16", "RGB8", "L8", "sRGB8"})

F32 = np.float32
ZERO, HALF, ONE, TWO = F32(0), F32(0.5), F32(1), F32(2)

Kernel = Callable[[Array, Array], Array]


# --- float32 arithmetic ------------------------------------------------------------------------


def f32(x: Any) -> Array:
    result: Array = np.asarray(x, F32)
    return result


def fma(x: Any, y: Any, z: Any) -> Array:
    """Fused multiply-add x*y + z with a single rounding to float32 (the product of two floats
    is exact in float64)."""
    wide = f32(x).astype(np.float64) * f32(y).astype(np.float64) + f32(z).astype(np.float64)
    return f32(wide)


def rcp(x: Array) -> Array:
    """Reciprocal 1/x in float32 (1/0 = +inf)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return f32(ONE / f32(x))


def mul(x: Array, y: Array) -> Array:
    with np.errstate(invalid="ignore"):
        return f32(f32(x) * f32(y))


def fmin(x: Any, y: Any) -> Array:
    """min that returns the other operand when one is NaN (IEEE 754 minNum, HLSL min)."""
    return f32(np.fmin(f32(x), f32(y)))


def fmax(x: Any, y: Any) -> Array:
    return f32(np.fmax(f32(x), f32(y)))


def clamp01(x: Array) -> Array:
    return fmin(fmax(x, ZERO), ONE)


# --- Separable kernels (a = lower / backdrop, b = upper / source, float32) ---------------------


def hard_light(a: Array, b: Array) -> Array:
    low = f32(TWO * a * b)
    high = fma(-TWO * (ONE - a), ONE - b, ONE)
    return f32(np.where(b <= HALF, low, high))


def color_burn(a: Array, b: Array) -> Array:
    return clamp01(fma(a - ONE, rcp(b), ONE))


def color_dodge(a: Array, b: Array) -> Array:
    return fmax(fmin(ONE, mul(a, rcp(ONE - b))), ZERO)


def soft_light(a: Array, b: Array) -> Array:
    low = fma(TWO * a, b, a * a * (ONE - TWO * b))
    high = fma(np.sqrt(a), TWO * b - ONE, TWO * a * (ONE - b))
    return f32(np.where(b <= HALF, low, high))


def linear_light(a: Array, b: Array) -> Array:
    low = f32((a + TWO * b) - ONE)
    high = f32(a + TWO * (b - HALF))
    return clamp01(f32(np.where(b <= HALF, low, high)))


def vivid_light(a: Array, b: Array) -> Array:
    return f32(np.where(b <= HALF, color_burn(a, TWO * b), color_dodge(a, TWO * (b - HALF))))


def pin_light(a: Array, b: Array) -> Array:
    low = np.minimum(a, TWO * b)
    high = np.maximum(a, TWO * b - ONE)
    return f32(np.where(b <= HALF, low, high))


def divide(a: Array, b: Array) -> Array:
    return fmax(fmin(mul(a, rcp(b)), ONE), ZERO)


@dataclass(frozen=True)
class Mode:
    name: str
    kernel: Kernel
    text: str
    sources: tuple[tuple[str, str], ...]
    replace: bool = False  # opacity mix a + (r - a) * alpha instead of a*(1-alpha) + r*alpha


W3C = "S-W3C-BLEND"
PDF = "S-PDF-BLEND"
GUIDE = ("A-HELP-GUIDE", "Blending modes")
PDF_TABLE = (PDF, "§11.3.5 Table 136, standard separable blend modes")


def _w3c(name: str) -> tuple[str, str]:
    return (W3C, f"§10.1 Separable blend modes: {name}")


MODES: dict[str, Mode] = {
    m.name: m
    for m in (
        Mode("Normal", lambda a, b: f32(b), "r = b", (_w3c("normal"), GUIDE)),
        Mode(
            "Replace",
            lambda a, b: f32(b),
            "r = b; the opacity mix is v = a + (r - a) * alpha (not the a*(1-alpha) + r*alpha "
            "form of the other modes)",
            (_w3c("normal"), GUIDE),
            replace=True,
        ),
        Mode(
            "Disable",
            lambda a, b: f32(a),
            "r = a (the layer leaves the channel unchanged at any opacity)",
            (GUIDE, ("A-PYDOC", "layerstack.BlendingMode.Disable")),
        ),
        Mode(
            "Multiply", lambda a, b: f32(a * b), "r = a * b", (_w3c("multiply"), PDF_TABLE, GUIDE)
        ),
        Mode(
            "Divide",
            divide,
            "r = max(0, min(1, a * rcp(b))) with rcp(b) = 1/b rounded to float32 and min "
            "returning 1 for NaN (0/0 gives 1)",
            (GUIDE, _w3c("color-dodge (closest: division by the source)")),
        ),
        Mode(
            "InverseDivide",
            lambda a, b: divide(b, a),
            "r = max(0, min(1, b * rcp(a))), as Divide with the operands swapped",
            (GUIDE, _w3c("color-dodge (closest: division)")),
        ),
        Mode(
            "Darken", lambda a, b: f32(np.minimum(a, b)), "r = min(a, b)", (_w3c("darken"), GUIDE)
        ),
        Mode(
            "Lighten", lambda a, b: f32(np.maximum(a, b)), "r = max(a, b)", (_w3c("lighten"), GUIDE)
        ),
        Mode(
            "LinearDodge",
            lambda a, b: f32(a + b),
            "r = a + b (additive)",
            (GUIDE, _w3c("screen (closest: additive)")),
        ),
        Mode(
            "Subtract",
            lambda a, b: f32(a - b),
            "r = a - b",
            (GUIDE, _w3c("difference (closest)")),
        ),
        Mode(
            "InverseSubtract",
            lambda a, b: f32(b - a),
            "r = b - a",
            (GUIDE, _w3c("difference (closest)")),
        ),
        Mode(
            "Difference",
            lambda a, b: f32(np.abs(a - b)),
            "r = |a - b|",
            (_w3c("difference"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "Exclusion",
            lambda a, b: fma(-TWO * (a - HALF), b - HALF, HALF),
            "r = fma(-2(a - 0.5), b - 0.5, 0.5) (= a + b - 2ab)",
            (_w3c("exclusion"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "SignedAddition",
            lambda a, b: f32((a + TWO * b) - ONE),
            "r = (a + 2b) - 1 (b - 0.5 added at twice its amplitude)",
            (GUIDE, _w3c("hard-light (closest: signed 2b - 1 term)")),
        ),
        Mode(
            "Screen",
            lambda a, b: fma(-(ONE - a), ONE - b, ONE),
            "r = fma(-(1 - a), 1 - b, 1) (= 1 - (1 - a)(1 - b))",
            (_w3c("screen"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "LinearBurn",
            lambda a, b: f32((a + b) - ONE),
            "r = (a + b) - 1",
            (GUIDE, _w3c("multiply (closest: burn family)")),
        ),
        Mode(
            "Overlay",
            lambda a, b: hard_light(b, a),
            "r = HardLight(b, a): a <= 0.5: 2ab, else fma(-2(1 - b), 1 - a, 1)",
            (_w3c("overlay"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "ColorBurn",
            color_burn,
            "r = clamp(fma(a - 1, rcp(b), 1), 0, 1) (= 1 - min(1, (1 - a)/b))",
            (_w3c("color-burn"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "ColorDodge",
            color_dodge,
            "r = max(0, min(1, a * rcp(1 - b))) (= min(1, a/(1 - b)); NaN gives 1)",
            (_w3c("color-dodge"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "SoftLight",
            soft_light,
            "b <= 0.5: r = fma(2a, b, a*a*(1 - 2b)); else r = fma(sqrt(a), 2b - 1, 2a(1 - b)) "
            "(the Photoshop-style soft light with sqrt(a), not the W3C D(a) polynomial)",
            (_w3c("soft-light (sqrt branch)"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "HardLight",
            hard_light,
            "b <= 0.5: r = 2ab; else r = fma(-2(1 - a), 1 - b, 1) (= Screen(a, 2b - 1))",
            (_w3c("hard-light"), PDF_TABLE, GUIDE),
        ),
        Mode(
            "VividLight",
            vivid_light,
            "b <= 0.5: r = ColorBurn(a, 2b); else r = ColorDodge(a, 2(b - 0.5))",
            (GUIDE, _w3c("color-burn and color-dodge (composed)")),
        ),
        Mode(
            "LinearLight",
            linear_light,
            "b <= 0.5: r = (a + 2b) - 1 (LinearBurn(a, 2b)); else r = a + 2(b - 0.5) "
            "(LinearDodge(a, 2(b - 0.5))); r clamped to [0, 1] on every format",
            (GUIDE, _w3c("hard-light (closest: split at b = 0.5)")),
        ),
        Mode(
            "PinLight",
            pin_light,
            "b <= 0.5: r = min(a, 2b); else r = max(a, 2b - 1)",
            (GUIDE, _w3c("darken and lighten (composed)")),
        ),
    )
}


# --- Operands and storage ---------------------------------------------------------------------


def unorm(x: Array, bits: int) -> Array:
    """Float -> UNORM code: clamp to [0, 1] (NaN -> 0), truncate to `bits + 4` fractional binary
    digits, then round to the nearest code with ties rounded down."""
    v = np.nan_to_num(np.clip(np.asarray(x, np.float64), 0.0, 1.0), nan=0.0)
    fine = float(1 << (bits + GUARD_BITS))
    j = np.floor(v * fine)
    result: Array = np.ceil(j * ((1 << bits) - 1) / fine - 0.5).astype(np.int64)
    return result


def half_truncate(x: Array) -> Array:
    """float32 -> half precision rounding toward zero (the RGB16F write), as float64."""
    single = f32(x)
    half = single.astype(np.float16)
    over = np.abs(half.astype(np.float32)) > np.abs(single)
    result: Array = np.where(over, np.nextafter(half, np.float16(0)), half).astype(np.float64)
    return result


def srgb8_linear(codes: Array) -> Array:
    """The linear value of sRGB8 storage codes: IEC decode on 8 significant bits (float32)."""
    linear = significand_round(decode(np.asarray(codes, np.float64) / 255.0), SRGB_SIGNIFICANT_BITS)
    return f32(linear)


def operand(stored: Array, fmt: str) -> Array:
    """A stored channel value (storage units) -> the float32 operand of the blend."""
    if fmt in ("RGB16", "L16"):
        return f32(np.asarray(stored, np.float64) / 65535.0)
    if fmt in ("RGB8", "L8"):
        return f32(np.asarray(stored, np.float64) / 255.0)
    if fmt == "sRGB8":
        return srgb8_linear(stored)
    return f32(stored)


def store(v: Array, fmt: str) -> Array:
    """A float32 channel value -> the stored value in storage units (codes or floats)."""
    if fmt in ("RGB16", "L16"):
        return unorm(v, 16)
    if fmt in ("RGB8", "L8"):
        return unorm(v, 8)
    if fmt == "sRGB8":
        clipped = np.nan_to_num(np.clip(np.asarray(v, np.float64), 0.0, 1.0), nan=0.0)
        return srgb8_store(clipped)
    if fmt in ("RGB16F", "L16F"):
        return half_truncate(v)
    # RGB32F / L32F: the stack is composited over the white base, 1 + (v - 1) in float32.
    result: Array = f32(f32(f32(v) - ONE) + ONE).astype(np.float64)
    return result


def blend(mode: Mode, a: Array, b: Array, fmt: str, opacity: float) -> Array:
    """The stored result of `mode` with float32 operands a (lower) and b (upper) at `opacity`."""
    alpha = F32(opacity)
    with np.errstate(invalid="ignore", over="ignore"):
        r = f32(mode.kernel(f32(a), f32(b)))
        if fmt in UNORM_FORMATS:
            r = clamp01(r)
        mixed = a + (r - a) * alpha if mode.replace else a * (ONE - alpha) + r * alpha
        v = f32(mixed)
    return store(v, fmt)


def source_operands(ctx: Context, user: int, fmt: str) -> tuple[Array, Array]:
    """Fields A and B on channel `user` as float32 operands.

    Integer, sRGB8 and RGB16F channels: the values stored in `blend-inputs` (s0, s1). RGB32F
    channels keep float32(c / 65535) of the authored 16-bit fields: their export (and the
    `blend-inputs` record) is that value after the base composite of `store`."""
    if fmt in ("RGB32F", "L32F"):
        kind = BLEND_CHANNELS[user][3]
        sources = (
            (fixtures.field_a(), fixtures.field_b())
            if kind == "rgb"
            else (fixtures.grey_a(), fixtures.grey_b())
        )
        planes = [png.decode(data).astype(np.float64) / 65535.0 for data in sources]
        return f32(planes[0]), f32(planes[1])
    golden = ctx.golden(INPUTS)
    a, b = (
        operand(to_storage(ctx, golden.map("r1", f"{s}/user{user}").values, fmt), fmt)
        for s in ("s0", "s1")
    )
    return a, b


# --- Entries -----------------------------------------------------------------------------------

PIPELINE = (
    "Per channel, float32 arithmetic (fma: fused multiply-add, one rounding). Operands a (lower "
    "layer) and b (upper source) as stored: RGB16/L16 c/65535; RGB8 c/255; sRGB8 the linear "
    "value IEC-decode(c/255) on 8 significant bits (blend in linear); RGB16F the stored half; "
    "RGB32F float32(c/65535). On UNORM formats (RGB16, L16, RGB8, sRGB8) r is clamped to [0, 1] "
    "before the opacity mix; float formats keep r unclamped unless the mode clamps. Opacity "
    "alpha = float32(opacity): v = a*(1 - alpha) + r*alpha. Write: UNORM n bits: v clamped to "
    "[0, 1], j = floor(v*2^(n+4)), code = (j*(2^n - 1) + 2^(n+3) - 1) >> (n+4) (nearest, ties "
    "down, after truncation to n+4 fractional bits); sRGB8 code = round(255*encode_IEC(v)); "
    "RGB16F half rounded toward zero; RGB32F 1 + (v - 1) in float32 (composite over the white "
    "base: |v| < 0.5 lands on 2^-24 steps, v < 0 on 2^-23 steps). Kernel: "
)

PIPELINE_SOURCES = [
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM, FLOAT32 to FLOAT16"),
    source("S-SRGB", "IEC 61966-2-1:1999 §5.2-5.3 (transfer functions)"),
]


def _channel_label(user: int) -> str:
    _, fmt, opacity, _ = BLEND_CHANNELS[user]
    return f"user{user} {fmt} a{opacity:g}"


def _summary(residuals: list[dict[str, Any]], maps: list[str]) -> str:
    """Worst |delta| and differing count per map over both recordings."""
    parts = []
    for name in maps:
        rows = [r["difference"] for r in residuals if r["map"] == name]
        worst = max(float(d["max"]) for d in rows)
        differing = max(int(d["differing"]) for d in rows)
        shown = f"{worst:.3g}" if worst else "0"
        parts.append(f"{name} {shown}/{differing}")
    return "; ".join(parts)


def mode_residuals(ctx: Context, family: str, index: int, mode: Mode) -> list[dict[str, Any]]:
    golden = ctx.golden(f"semantics/blend-{family}")
    residuals = []
    for user, (_, _, opacity, _) in enumerate(BLEND_CHANNELS):
        fmt = channel_format(golden, f"s{index}", f"user{user}")
        a, b = source_operands(ctx, user, fmt)
        model = blend(mode, a, b, fmt, opacity)
        name = f"s{index}/user{user}"
        for recording in RECORDINGS:
            recorded = to_storage(ctx, golden.map(recording, name).values, fmt)
            diff = difference(model, recorded)
            residuals.append(residual(golden.golden_id, name, recording, UNIT[fmt], diff))
    return residuals


def mode_entry(ctx: Context, family: str, index: int, mode: Mode) -> dict[str, Any]:
    residuals = mode_residuals(ctx, family, index, mode)
    labels = [f"s{index}/user{u}" for u in range(len(BLEND_CHANNELS))]
    exact = [
        _channel_label(u)
        for u, name in enumerate(labels)
        if all(r["difference"]["differing"] == 0 for r in residuals if r["map"] == name)
    ]
    notes = (
        f"Worst |delta|/differing values per map (both recordings): {_summary(residuals, labels)}. "
        f"Exact on: {', '.join(exact) if exact else 'none'}."
    )
    if any(name in mode.text for name in ("rcp", "sqrt")):
        notes += (
            " The remaining one-step differences follow the hardware reciprocal / square root, "
            "which Direct3D allows to differ from the correctly rounded value; float32 1/x and "
            "sqrt(x) are the nearest public model."
        )
    srgb = [f"s{index}/user{u}" for u, c in enumerate(BLEND_CHANNELS) if c[1] == "sRGB8"]
    if any(r["difference"]["differing"] for r in residuals if r["map"] in srgb):
        notes += (
            " sRGB8 channels (user2, user3) are not reproduced exactly: Painter's linear value "
            "of an sRGB8 code deviates from the IEC decode (srgb-transfer.json, srgb8-export; "
            "large deltas come from the darkest codes). With the per-code linear values of the "
            "export calibration (in memory, not published) every separable mode stays within "
            "1 code on sRGB8, so the kernel is not the cause."
        )
    params = [
        parameter("guard_bits", GUARD_BITS, "fitted", "bits"),
        parameter("srgb8_significant_bits", SRGB_SIGNIFICANT_BITS, "fitted", "bits"),
    ]
    return entry(
        f"blend-{mode.name.lower()}",
        f"BlendingMode.{mode.name} on the user channels (RGB16, sRGB8, RGB8, RGB16F, L16, RGB32F)",
        PIPELINE + mode.text + ".",
        [source(*s) for s in mode.sources] + PIPELINE_SOURCES,
        params,
        residuals,
        notes,
    )


# --- Order of evaluation -----------------------------------------------------------------------

ORDERS = ("ABC", "BAC", "ACB", "CBA")
UNIFORM_C = (0.6, 0.3, 0.9)
ORDER_LAYERS = {"A": ("Normal", 1.0), "B": ("Subtract", 0.8), "C": ("Divide", 0.6)}


def uniform_operand(colour: tuple[float, ...], fmt: str) -> Array:
    """A uniform colour as the channel stores it, as a float32 operand (legacy colour
    management: the value is written like a blend result, sRGB8 through the IEC encode)."""
    return operand(store(f32(colour), fmt), fmt)


def stack(order: str, a: Array, b: Array, c: Array, fmt: str) -> Array:
    """Layers bottom-up over the white base (1.0), each written to the channel format."""
    sources = {"A": a, "B": b, "C": c}
    value = np.ones_like(f32(a))
    stored = store(value, fmt)
    for key in order:
        name, opacity = ORDER_LAYERS[key]
        stored = blend(MODES[name], value, np.broadcast_to(sources[key], value.shape), fmt, opacity)
        value = operand(stored, fmt)
    return stored


def order_entry(ctx: Context) -> dict[str, Any]:
    golden = ctx.golden(ORDER)
    inputs = ctx.golden(INPUTS)
    residuals = []
    for user, source_user in ((0, 0), (1, 2)):  # blend-order User1 is sRGB8, like User2 above
        fmt = channel_format(golden, "s0", f"user{user}")
        a, b = (
            operand(to_storage(ctx, inputs.map("r1", f"{s}/user{source_user}").values, fmt), fmt)
            for s in ("s0", "s1")
        )
        c = uniform_operand(UNIFORM_C, fmt)
        for index, order in enumerate(ORDERS):
            model = stack(order, a, b, c, fmt)
            name = f"s{index}/user{user}"
            for recording in RECORDINGS:
                recorded = to_storage(ctx, golden.map(recording, name).values, fmt)
                diff = difference(model, recorded)
                residuals.append(residual(golden.golden_id, name, recording, UNIT[fmt], diff))
    labels = [f"s{i}/user{u}" for u in (0, 1) for i in range(len(ORDERS))]
    return entry(
        "blend-evaluation-order",
        "Order of evaluation of the layer stack (three non-commuting layers, four orders)",
        "The stack is evaluated bottom-up starting from the white base (1.0 on user channels): "
        "value = 1; for each layer from the bottom: value = stored(blend(mode, value, source, "
        "opacity)) with the separable kernels, opacity mix and storage write of the entries "
        "blend-normal, blend-subtract and blend-divide; every layer result is written to the "
        "channel format before the next layer reads it. Layers: A fields A, Normal, 1.0; B "
        "fields B, Subtract, 0.8; C uniform colour (0.6, 0.3, 0.9) stored like a channel value "
        "(RGB16 UNORM write, sRGB8 round(255*encode_IEC)), Divide, 0.6. Orders ABC, BAC, ACB, "
        "CBA in s0..s3.",
        [
            source(W3C, "§9 Advanced compositing / §10 Blending: bottom-up layer composition"),
            source("A-HELP-GUIDE", "Layer stack: layer order and blending modes"),
            source("X-D3D12", "Data conversion rules: FLOAT to UNORM"),
        ],
        [
            parameter("base", 1.0, "fitted"),
            parameter("uniform_colour_c", list(UNIFORM_C), "authored"),
            parameter("opacities_abc", [1.0, 0.8, 0.6], "authored"),
        ],
        residuals,
        notes=f"Worst |delta|/differing values per map (both recordings): "
        f"{_summary(residuals, labels)}. The orders are not equivalent (the four results "
        "differ), so the per-layer evaluation bottom-up over the white base is what the RGB16 "
        "channel reproduces; sRGB8 differences follow the sRGB8 transfer deviation.",
    )


def passthrough_entry() -> dict[str, Any]:
    return entry(
        "blend-passthrough",
        "BlendingMode.PassThrough (group layers only)",
        "A group in PassThrough does not composite its children into an isolated result: the "
        "children blend directly onto the stack below the group, as if they were not grouped "
        "(the usual pass-through group definition).",
        [
            source("A-PYDOC", "layerstack.BlendingMode.PassThrough"),
            source("A-HELP-GUIDE", "Blending modes: Passthrough (folders)"),
        ],
        [],
        [],
        notes="Not settable through the documented API on Painter 12.1.0 (group-only mode); the "
        "group cases moved to task phase0.7_tier0-semantics-ui-cases. No residual.",
        gap=True,
    )


def separable_entries(ctx: Context) -> tuple[list[dict[str, Any]], list[str]]:
    entries, corpus = [], []
    for family in FAMILIES:
        modes = BLEND_FAMILIES[family]
        corpus.append(ctx.golden(f"semantics/blend-{family}").golden_id)
        entries += [mode_entry(ctx, family, i, MODES[m]) for i, m in enumerate(modes)]
    entries.append(order_entry(ctx))
    entries.append(passthrough_entry())
    corpus += [ctx.golden(INPUTS).golden_id, ctx.golden(ORDER).golden_id]
    return entries, corpus


def fit(ctx: Context) -> dict[str, Any]:
    from tools.parity.fit import blend_component

    entries, corpus = separable_entries(ctx)
    more, more_corpus = blend_component.entries(ctx)
    return document(
        "blend-modes",
        "Blend modes of the layer stack (04 sections 2-3, task phase0.7_tier0-stability-fits): "
        "separable modes fitted in float32 against the W3C / ISO 32000 blend functions and the "
        "usual definitions of the modes Painter adds, with the Direct3D storage conversions; "
        "the order of evaluation; the component and normal-map modes. Operands are the stored "
        "inputs (blend-inputs). Residuals are |delta| in storage units per texture set and "
        "channel against both recordings (r1 same session, r2 after save and reopen).",
        corpus + more_corpus,
        entries + more,
    )
