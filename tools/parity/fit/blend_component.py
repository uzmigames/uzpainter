"""Non-separable and normal-map blend modes (entries of `blend-modes.json`, 04 §3).

Goldens: `blend-component` (per texture set s0..s6 the modes Tint, Saturation, Color, Value,
NormalMapCombine, NormalMapDetail, NormalMapInverseDetail: a lower fill with field A and an
upper fill with field B in the mode, on the eight blend channels), `blend-inputs` (the fields as
each channel stores them: the model operands) and `blend-normal-channel` (tangent-space fields
`normal-a` under `normal-b` on the Normal channel and its `Normal_OpenGL` virtual map).

Candidates: the HSV/HSL and W3C (Lum/SetLum/SetSat) non-separable modes, and the normal-map
blends of Barré-Brisebois and Hill (linear, UDN, partial derivatives, whiteout, reoriented
normal mapping). `fit-blend` publishes these entries with its own (`entries`).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.fit.common import (
    RECORDINGS,
    UNIT,
    Context,
    channel_format,
    entry,
    parameter,
    residual,
    source,
    to_storage,
)
from tools.parity.fit.srgb import encode
from tools.parity.fit.srgb import unorm as nearest_code
from tools.parity.fit.stats import Array, difference
from tools.parity.tier0_semantics import fixtures
from tools.parity.tier0_semantics.corpus import BLEND_CHANNELS

COMPONENT = "semantics/blend-component"
INPUTS = "semantics/blend-inputs"
NORMAL = "semantics/blend-normal-channel"
HSV_MODES = ("Tint", "Saturation", "Color", "Value")  # blend-component s0..s3
NORMAL_MODES = ("NormalMapCombine", "NormalMapDetail", "NormalMapInverseDetail")  # s4..s6
VALUE_GAIN = 2.0  # fitted: the value written by the HSV modes is twice the source value
SATURATION_EPSILON = 2.0**-12  # fitted: S = (max - min) / (max + eps)
GUARD_BITS = 4  # UNORM write: the value is truncated to (bits + 4) fractional bits first
F32 = np.float32


# --- Storage conversions -----------------------------------------------------------------------


def unorm(x: Array, bits: int) -> Array:
    """Float -> UNORM code: clamp to [0, 1], truncate to `bits + 4` fractional binary digits,
    then round to the nearest code with ties rounded down."""
    fine = float(1 << (bits + GUARD_BITS))
    v = np.floor(np.clip(np.asarray(x, np.float64), 0.0, 1.0) * fine) / fine
    result: Array = np.ceil(v * ((1 << bits) - 1) - 0.5).astype(np.int64)
    return result


def half_truncate(x: Array) -> Array:
    """Float -> half precision rounding toward zero (the RGB16F channel write), as float64."""
    single = np.asarray(x, np.float32)
    half = single.astype(np.float16)
    over = np.abs(half.astype(np.float32)) > np.abs(single)
    result: Array = np.where(over, np.nextafter(half, np.float16(0)), half).astype(np.float64)
    return result


def store(x: Array, fmt: str) -> Array:
    """A linear result -> the channel's storage value (codes for integer formats, floats else)."""
    if fmt in ("RGB16", "L16"):
        return unorm(x, 16)
    if fmt in ("RGB8", "L8"):
        return unorm(x, 8)
    if fmt == "sRGB8":
        return nearest_code(encode(np.clip(np.asarray(x, np.float64), 0.0, 1.0)), 8)
    if fmt in ("RGB16F", "L16F"):
        return half_truncate(x)
    # RGB32F: composited over the white base, 1 + (v - 1) in float32.
    single = np.asarray(x, np.float32)
    result: Array = (np.float32(1) + (single - np.float32(1))).astype(np.float64)
    return result


# --- HSV modes (Tint, Saturation, Color, Value) -------------------------------------------------


def rgb_to_hsv(c: Array, eps: float = SATURATION_EPSILON) -> tuple[Array, Array, Array]:
    """Hue in [0, 1) (0 for a grey), saturation (max - min) / (max + eps), value max."""
    c = np.asarray(c, np.float64)
    top, low = c.max(-1), c.min(-1)
    span = top - low
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    safe = np.where(span > 0, span, 1.0)
    hue = np.where(
        top == r,
        ((g - b) / safe) % 6.0,
        np.where(top == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0),
    )
    hue = np.where(span > 0, hue, 0.0) / 6.0
    denominator = top + eps
    saturation = np.where(denominator > 0, span / np.where(denominator > 0, denominator, 1.0), 0.0)
    return hue, saturation, top


def hsv_to_rgb(h: Array, s: Array, v: Array) -> Array:
    """HSV -> RGB: v * (1 - s + s * clamp(|6 fract(h + k) - 3| - 1, 0, 1)), k = 1, 2/3, 1/3."""
    k = np.array([1.0, 2.0 / 3.0, 1.0 / 3.0])
    p = np.abs(((np.asarray(h)[..., None] + k) % 1.0) * 6.0 - 3.0)
    s3 = np.asarray(s)[..., None]
    result: Array = np.asarray(v)[..., None] * (1.0 - s3 + s3 * np.clip(p - 1.0, 0.0, 1.0))
    return result


def hsv_mode(mode: str, a: Array, b: Array) -> Array:
    """Blend result of an HSV mode, lower layer `a`, upper layer `b` (RGB, unclamped).

    Tint: hue of b, saturation and value of a; Saturation: saturation of b; Color: hue and
    saturation of b; Value: value of b. The value is multiplied by `VALUE_GAIN`.
    """
    ha, sa, va = rgb_to_hsv(a)
    hb, sb, vb = rgb_to_hsv(b)
    h, s, v = {
        "Tint": (hb, sa, va),
        "Saturation": (ha, sb, va),
        "Color": (hb, sb, va),
        "Value": (ha, sa, vb),
    }[mode]
    return hsv_to_rgb(h, s, VALUE_GAIN * v)


def grey_mode(mode: str, a: Array, b: Array) -> Array:
    """The modes on a grey (L) channel: the upper layer for Value and the normal-map modes."""
    return b if mode in ("Value", *NORMAL_MODES) else a


# --- Normal-map modes ---------------------------------------------------------------------------


def dot(u: Array, v: Array) -> Array:
    """float32 dot product, rounded once."""
    total = np.einsum("...i,...i->...", u.astype(np.float64), v.astype(np.float64))
    result: Array = total.astype(F32)
    return result


def normalise(v: Array) -> Array:
    """v * float32(1 / sqrt(dot(v, v))) in float32 (a zero vector gives zeros)."""
    length2 = dot(v, v).astype(np.float64)
    with np.errstate(divide="ignore"):
        inverse = np.where(length2 > 0, 1.0 / np.sqrt(length2), 0.0).astype(F32)
    result: Array = (v * inverse[..., None]).astype(F32)
    return result


def decode_normal(c: Array) -> Array:
    """Colour in [0, 1] -> unit normal: n = 2c - 1 with n.z clamped to >= 0, normalised."""
    n = (np.asarray(c, F32) * F32(2) - F32(1)).astype(F32)
    n[..., 2] = np.maximum(n[..., 2], F32(0))
    return normalise(n)


def encode_normal(n: Array) -> Array:
    result: Array = (n * F32(0.5) + F32(0.5)).astype(F32).astype(np.float64)
    return result


def whiteout(base: Array, detail: Array) -> Array:
    """Whiteout blend (P-BARRE): (b.xy + d.xy, b.z * d.z), unnormalised."""
    result: Array = np.stack(
        [
            base[..., 0] + detail[..., 0],
            base[..., 1] + detail[..., 1],
            base[..., 2] * detail[..., 2],
        ],
        -1,
    ).astype(F32)
    return result


def reoriented(base: Array, detail: Array) -> Array:
    """Reoriented normal mapping (P-BARRE): t = b + (0,0,1), u = d * (-1,-1,1),
    t * dot(t, u) / t.z - u, unnormalised."""
    t = (base + np.array([0.0, 0.0, 1.0], F32)).astype(F32)
    u = (detail * np.array([-1.0, -1.0, 1.0], F32)).astype(F32)
    scale = (dot(t, u) / t[..., 2]).astype(F32)
    result: Array = (t * scale[..., None] - u).astype(F32)
    return result


def toward_flat(n: Array, opacity: float) -> Array:
    """Spherical interpolation from the flat normal (0, 0, 1) to the unit normal n."""
    if opacity >= 1.0:
        return n
    v = n.astype(np.float64)
    angle = np.arccos(np.clip(v[..., 2], -1.0, 1.0))
    sine = np.sin(angle)
    tiny = sine < 1e-12
    safe = np.where(tiny, 1.0, sine)
    w_flat = np.where(tiny, 1.0 - opacity, np.sin((1.0 - opacity) * angle) / safe)
    w_n = np.where(tiny, opacity, np.sin(opacity * angle) / safe)
    result = w_n[..., None] * v
    result[..., 2] += w_flat
    out: Array = result.astype(F32)
    return out


def normal_mode(mode: str, lower: Array, upper: Array, opacity: float = 1.0) -> Array:
    """Unit result normal of a normal-map mode; `lower`/`upper` are unit normals (float32).

    The upper layer is first brought toward the flat normal by its opacity; InverseDetail swaps
    the roles of base and detail."""
    top = toward_flat(upper, opacity)
    if mode == "NormalMapCombine":
        return normalise(whiteout(lower, top))
    if mode == "NormalMapDetail":
        return normalise(reoriented(lower, top))
    if mode == "NormalMapInverseDetail":
        return normalise(reoriented(top, lower))
    raise ValueError(f"not a normal-map mode: {mode}")


# --- Fits ---------------------------------------------------------------------------------------


def operands(ctx: Context, user: int) -> tuple[Array, Array, str]:
    """Fields A and B as stored on channel `user`, as linear values, and the channel format.

    Integer formats: code / (2^bits - 1); sRGB8: the 16-bit export value / 65535 (the channel's
    linear value); RGB16F: the stored half; RGB32F: float32(code / 65535) of the authored
    fixtures (the stored value is that composited over the white base)."""
    golden = ctx.golden(INPUTS)
    fmt = channel_format(golden, "s0", f"user{user}")
    planes = []
    for texture_set in ("s0", "s1"):
        exported = golden.map("r1", f"{texture_set}/user{user}").values
        stored = to_storage(ctx, exported, fmt)
        if fmt in ("RGB16", "L16"):
            planes.append(stored / 65535.0)
        elif fmt in ("RGB8", "L8"):
            planes.append(stored / 255.0)
        elif fmt == "sRGB8":
            planes.append(exported / 65535.0)
        elif fmt in ("RGB32F", "L32F"):
            kind = "grey" if BLEND_CHANNELS[user][3] == "grey" else "field"
            name = f"{kind}_{'a' if texture_set == 's0' else 'b'}"
            codes = png.decode(getattr(fixtures, name)()).astype(np.float64)
            planes.append((codes / 65535.0).astype(np.float32).astype(np.float64))
        else:
            planes.append(stored.astype(np.float64))
    return planes[0], planes[1], fmt


def component_result(mode: str, a: Array, b: Array, fmt: str, opacity: float) -> Array:
    """Stored result of `mode` with lower `a`, upper `b` (linear operands) on one channel."""
    floating = fmt.endswith("F")
    if a.shape[-1] == 1:
        blended = grey_mode(mode, a, b)
    elif mode in HSV_MODES:
        blended = hsv_mode(mode, a, b)
        if not floating:
            blended = np.clip(blended, 0.0, 1.0)
    else:
        lower, upper = decode_normal(a), decode_normal(b)
        blended = encode_normal(normal_mode(mode, lower, upper, opacity))
        return store(blended, fmt)
    return store(a * (1.0 - opacity) + blended * opacity, fmt)


def _component_residuals(ctx: Context, mode: str, texture_set: int) -> list[dict[str, Any]]:
    golden = ctx.golden(COMPONENT)
    residuals = []
    for user, (_, _, opacity, _) in enumerate(BLEND_CHANNELS):
        a, b, fmt = operands(ctx, user)
        model = component_result(mode, a, b, fmt, float(np.float32(opacity)))
        for recording in RECORDINGS:
            name = f"s{texture_set}/user{user}"
            recorded = to_storage(ctx, golden.map(recording, name).values, fmt)
            diff = difference(model, recorded)
            residuals.append(residual(golden.golden_id, name, recording, UNIT[fmt], diff))
    return residuals


def normal_channel_inputs() -> tuple[Array, Array]:
    """The authored fields as the Normal channel stores them: (r, 1 - g, b) of code / 65535,
    written to half precision rounding toward zero."""

    def stored(kind: str) -> Array:
        c = png.decode(fixtures.normal_field(kind)).astype(np.float64) / 65535.0
        return half_truncate(np.stack([c[..., 0], 1.0 - c[..., 1], c[..., 2]], -1))

    return stored("a"), stored("b")


def normal_opengl(n: Array) -> Array:
    """Normal_OpenGL virtual map of the stored Normal channel n: encode(normalise(2n - 1))."""
    v = (np.asarray(n, F32) * F32(2) - F32(1)).astype(F32)
    return unorm(encode_normal(normalise(v)), 16)


def _normal_channel_residuals(ctx: Context, mode: str, texture_set: int) -> list[dict[str, Any]]:
    golden = ctx.golden(NORMAL)
    a, b = normal_channel_inputs()
    if mode == "Normal":
        channel = b
    else:
        lower, upper = (normalise((x.astype(F32) * F32(2) - F32(1)).astype(F32)) for x in (a, b))
        channel = half_truncate(encode_normal(normal_mode(mode, lower, upper)))
    models = {"normal": (channel, "RGB16F"), "Normal_OpenGL": (normal_opengl(channel), "export16")}
    residuals = []
    for name, (model, unit) in models.items():
        output = f"s{texture_set}/{name}"
        for recording in RECORDINGS:
            recorded = golden.map(recording, output).values
            diff = difference(model, recorded.astype(model.dtype))
            residuals.append(residual(golden.golden_id, output, recording, UNIT[unit], diff))
    return residuals


HSV_SOURCES = [
    source("A-HELP-GUIDE", "Blending modes: Tint, Saturation, Color, Value"),
    source("A-PYDOC", "substance_painter.layerstack: BlendingMode"),
    source("S-W3C-BLEND", "Non-separable blend modes (candidate compared)"),
]
NORMAL_SOURCES = [
    source("P-BARRE", "Blending in Detail: whiteout blending and reoriented normal mapping"),
    source("A-PYDOC", "substance_painter.layerstack: BlendingMode (normal-map modes)"),
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM, FLOAT to FLOAT16"),
]
STORAGE_TEXT = (
    "Operands are fields A (lower) and B (upper) as the channel stores them (blend-inputs): "
    "integer codes / (2^bits - 1), linear values on sRGB8 (the channel's 16-bit export / 65535), "
    "the stored half on RGB16F, float32(code / 65535) of the authored fixtures on RGB32F. "
    "Writes: RGB16/L16 and RGB8 take v clamped to [0, 1], truncated "
    "to bits + 4 fractional binary digits and rounded to the nearest code, ties down; sRGB8 "
    "writes round(255 * encode(v)) with the IEC 61966-2-1 encoding; RGB16F rounds to half "
    "toward zero; RGB32F stores 1 + (v - 1) in float32 (composite over the white base)."
)

HSV_TEXT = {
    "Tint": "hue of B, saturation and value of A",
    "Saturation": "saturation of B, hue and value of A",
    "Color": "hue and saturation of B, value of A",
    "Value": "value of B, hue and saturation of A",
}

NORMAL_TEXT = {
    "NormalMapCombine": "whiteout: r = normalise(a.xy + b.xy, a.z * b.z)",
    "NormalMapDetail": "reoriented normal mapping with base a and detail b: t = a + (0,0,1), "
    "u = b * (-1,-1,1), r = normalise(t * dot(t,u) / t.z - u)",
    "NormalMapInverseDetail": "reoriented normal mapping with base b and detail a (roles "
    "swapped): t = b + (0,0,1), u = a * (-1,-1,1), r = normalise(t * dot(t,u) / t.z - u)",
}


def _hsv_entry(ctx: Context, index: int, mode: str) -> dict[str, Any]:
    formula = (
        f"{mode}: f = HSV({HSV_TEXT[mode]}) with the value multiplied by {VALUE_GAIN:g}; "
        "RGB -> HSV: v = max, s = (max - min) / (max + eps), hue by the hexcone sector "
        "(0 for a grey); HSV -> RGB: v * (1 - s + s * clamp(|6 fract(h + k) - 3| - 1, 0, 1)), "
        "k = (1, 2/3, 1/3). Computed in float64 on linear operands; f is clamped to [0, 1] on "
        "integer formats (sRGB8 included) and not clamped on float formats; result "
        "A * (1 - opacity) + f * opacity. On a grey (L) channel Tint, Saturation and Color keep "
        "A and "
        f"Value takes B, without gain. {STORAGE_TEXT}"
    )
    notes = (
        "The gain of 2 on the value is exact (the value of every unclipped texel matches "
        "2 * max to the code on RGB16) and holds on every RGB channel and opacity; it is "
        "absent on the L16 channel. The W3C luminosity variant (Lum weights 0.3, 0.59, 0.11, "
        "ClipColor) and an HSL variant do not match (grey A gives 2A, not Lum or L). The "
        "saturation epsilon 2^-12 was fitted (median of the implied epsilon 2.44e-4). The "
        "residual is a hue offset: on RGB16 the measured hue fraction is "
        "(mid - min - n) / (max - min + m) with m = 2^-12 and n = 2^-11 or -2^-10 depending on "
        "which channel is the middle one; it is not reproduced (open item) and grows without "
        "bound where the hue source is nearly grey (max - min of a few codes)."
    )
    return entry(
        f"blend-{mode.lower()}",
        f"BlendingMode {mode} on the user channels",
        formula,
        HSV_SOURCES,
        [
            parameter("value_gain", VALUE_GAIN, "fitted"),
            parameter("saturation_epsilon", SATURATION_EPSILON, "fitted"),
            parameter("unorm_guard_bits", GUARD_BITS, "fitted", "bits"),
        ],
        _component_residuals(ctx, mode, index),
        notes=notes,
    )


def _normal_entry(ctx: Context, index: int, mode: str) -> dict[str, Any]:
    formula = (
        f"{mode}: a, b = normalise(2c - 1) of the lower (A) and upper (B) colours with z clamped "
        "to >= 0 before normalising; b is first rotated toward the flat normal (0,0,1) by the "
        "layer opacity (spherical interpolation, b' = slerp((0,0,1), b, opacity)); "
        f"{NORMAL_TEXT[mode]}; the result is written as r * 0.5 + 0.5 (opacity enters only "
        "through b'). float32 arithmetic: dot products rounded once to float32, normalise(v) = "
        "v * float32(1 / sqrt(dot(v, v))). On a grey (L) channel the result is B. On the Normal "
        "channel the stored A and B are the imported bitmaps (r, 1 - g, b) rounded to half "
        "toward zero; the Normal_OpenGL virtual map writes normalise(2n - 1) * 0.5 + 0.5 of the "
        f"stored channel n to 16 bits. {STORAGE_TEXT}"
    )
    notes = (
        "Exact on the Normal channel (half) and on RGB8, L16 against both recordings. RGB16 "
        "differs by one code on at most 0.2 % of the values, RGB16F by one half step, RGB32F "
        "by float rounding (the evaluation order of the float32 operations is not pinned down). "
        "sRGB8 differs by one code on about 4 % of the values, like the uniform-colour store "
        "(srgb-transfer); its operands are the channel's exported linear values (the "
        "IEC decode instead leaves up to 30 codes near zero-length vectors, where normalising "
        "amplifies small operand differences). Opacity 0.25 on RGB32F: spherical interpolation "
        "matches within 2e-7 (4e-6 with the blend-inputs export as operands), a normalised "
        "linear interpolation toward (0,0,1) leaves 0.03 and "
        "a linear interpolation of the encoded colours 0.38. Candidates rejected on the Normal "
        "channel (max |delta|, half): UDN 0.05, partial derivatives 0.04, linear 0.16 for "
        "Combine; whiteout 0.07 and swapped RNM 0.06 for Detail."
    )
    residuals = _component_residuals(ctx, mode, 4 + index)
    residuals += _normal_channel_residuals(ctx, mode, 1 + index)
    return entry(
        f"blend-{mode.lower()}",
        f"BlendingMode {mode} on the user channels and the Normal channel",
        formula,
        NORMAL_SOURCES,
        [
            parameter("unorm_guard_bits", GUARD_BITS, "fitted", "bits"),
            parameter("flat_normal", [0.0, 0.0, 1.0], "public_documentation"),
        ],
        residuals,
        notes=notes,
    )


def _normal_channel_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "blend-normal-channel-import",
        "A normal bitmap on the Normal channel in Normal mode, and the Normal_OpenGL virtual map",
        "The Normal channel (RGB16F) stores an imported 16-bit normal bitmap as (r, 1 - g, b) "
        "of code / 65535 (green inverted), rounded to half toward zero. The Normal_OpenGL "
        "virtual map writes normalise(2n - 1) * 0.5 + 0.5 of the stored channel n in float32 "
        "to 16 bits: truncated to 20 fractional binary digits, rounded to the nearest code, "
        "ties down.",
        [
            source("X-D3D12", "Data conversion rules: FLOAT to FLOAT16, FLOAT to UNORM"),
            source("A-HELP-EXPORT", "Virtual maps: Normal_OpenGL"),
        ],
        [parameter("unorm_guard_bits", GUARD_BITS, "fitted", "bits")],
        _normal_channel_residuals(ctx, "Normal", 0),
        notes="Rounding to nearest (instead of toward zero) differs on half of the values by "
        "one half step. The virtual map differs by one code where the value lies within about "
        "0.06 code of a rounding boundary.",
    )


def entries(ctx: Context) -> tuple[list[dict[str, Any]], list[str]]:
    """The public entries of the component modes and the corpus golden ids they use."""
    result = [_hsv_entry(ctx, i, mode) for i, mode in enumerate(HSV_MODES)]
    result += [_normal_entry(ctx, i, mode) for i, mode in enumerate(NORMAL_MODES)]
    result.append(_normal_channel_entry(ctx))
    corpus = [ctx.golden(name).golden_id for name in (COMPONENT, INPUTS, NORMAL)]
    return result, corpus
