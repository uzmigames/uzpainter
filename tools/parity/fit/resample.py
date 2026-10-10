"""UV-projection resampling fit (`parity/semantics/resampling.json`).

Golden `resample-uv` (grid2x2, the eight user channels RGB16): per user channel one fill whose
UV projection maps the 64 x 64 pattern or the 256 x 256 field A with a scale, rotation or offset
(`corpus.RESAMPLE_CHANNELS`); texture set s0 filters `BilinearHQ` with `Repeat`, s1
`BilinearSharp`, s2 `Nearest`, s3 `BilinearHQ` with `RepeatNone` (`corpus.RESAMPLE_FILTERS`,
`RESAMPLE_WRAPS`). The bitmaps are imported 16-bit and stored exactly on RGB16, so the model
samples the authored codes and is compared with the stored 16-bit codes.

Model: the UV transform of the documented `UVProjectionParams` (A-PYDOC) about the UV centre,
nearest or bilinear texture filtering with the D3D fixed-point sub-texel precision (X-D3D12,
P-PBRT), all in integer arithmetic so it is reproducible bit for bit.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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
from tools.parity.fit.stats import Array, difference
from tools.parity.tier0_semantics.corpus import (
    RESAMPLE_CHANNELS,
    RESAMPLE_FILTERS,
    RESAMPLE_WRAPS,
    RESOLUTION,
)

FILE = "resampling.json"
GOLDEN = "semantics/resample-uv"
SETS = ("s0", "s1", "s2", "s3")
TOP16 = 65535
SUBTEXEL_BITS = 8  # fixed-point fraction of the texel coordinate
VALUE_BITS = 20  # fractional bits of the filtered value kept before the 16-bit rounding
ONE = 1 << SUBTEXEL_BITS
BASE_BELOW = TOP16  # the empty stack under the fill: user channels hold 1.0 (white)

SOURCES = [
    source("A-PYDOC", "layerstack: UVProjectionParams (scale, rotation, offset), FilteringMode"),
    source("A-PYDOC", "layerstack: UVWrappingMode (Repeat, RepeatNone)"),
    source("X-D3D12", "Texture sampling: texel coordinate fixed-point precision, filtering"),
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM"),
    source("P-PBRT", "Image texture: bilinear and point (nearest) filtering, wrap modes"),
]


# --- UV transform -----------------------------------------------------------------------------


def texel_coordinates(
    size: int,
    scale: Sequence[float],
    rotation: float,
    offset: Sequence[float],
    width: int,
    height: int,
) -> tuple[Array, Array, Array]:
    """Continuous texel coordinates (x, y) of every output texel, and its UV-domain mask.

    Output texel (i, j) of a `size` x `size` map (row j = 0 on top) sits at u = (i + 0.5) / size,
    v = 1 - (j + 0.5) / size (v up). About the UV centre: (a, b) = scale * (u - 0.5, v - 0.5);
    u' = cos(r) a + sin(r) b + 0.5 - offset_u, v' = -sin(r) a + cos(r) b + 0.5 - offset_v
    (r = rotation in degrees). The bitmap row 0 is its top: x = u' * width - 0.5,
    y = (1 - v') * height - 0.5, texel centres at integers. The mask is u', v' in [0, 1).
    """
    j, i = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (i + 0.5) / size
    v = 1.0 - (j + 0.5) / size
    a = (u - 0.5) * scale[0]
    b = (v - 0.5) * scale[1]
    r = math.radians(rotation)
    c, s = math.cos(r), math.sin(r)
    u2 = c * a + s * b + 0.5 - offset[0]
    v2 = -s * a + c * b + 0.5 - offset[1]
    inside = (u2 >= 0.0) & (u2 < 1.0) & (v2 >= 0.0) & (v2 < 1.0)
    return u2 * width - 0.5, (1.0 - v2) * height - 0.5, inside


def _address(index: Array, extent: int, wrap: str) -> Array:
    if wrap == "Repeat":
        result: Array = np.mod(index, extent)
        return result
    clamped: Array = np.clip(index, 0, extent - 1)
    return clamped


# --- Filters ----------------------------------------------------------------------------------


def nearest(image: Array, x: Array, y: Array, wrap: str) -> Array:
    """The texel containing the sample point: (floor(x + 0.5), floor(y + 0.5))."""
    h, w = image.shape[:2]
    xi = np.floor(x + 0.5).astype(np.int64)
    yi = np.floor(y + 0.5).astype(np.int64)
    result: Array = image[_address(yi, h, wrap), _address(xi, w, wrap)]
    return result


def bilinear_weights(fx: Array, fy: Array) -> tuple[Array, Array, Array, Array]:
    """Integer weights (sum 256) of the four taps from 8-bit sub-texel fractions fx, fy.

    w11 = round(fx * fy / 256) with ties down; w10 = fx - w11; w01 = fy - w11;
    w00 = 256 - fx - fy + w11 (each equals its exact bilinear weight to within 1/2).
    """
    w11 = (fx * fy + (ONE // 2 - 1)) >> SUBTEXEL_BITS
    return ONE - fx - fy + w11, fx - w11, fy - w11, w11


def unorm16(weighted: Array) -> Array:
    """16-bit code of a filtered value given as sum(weight * code) with weights summing to 256.

    v = weighted / (256 * 65535) is truncated to 20 fractional bits, then rounded to the nearest
    16-bit code with ties down.
    """
    v20 = (weighted << VALUE_BITS) // (ONE * TOP16)
    result: Array = (v20 * TOP16 + (1 << (VALUE_BITS - 1)) - 1) >> VALUE_BITS
    return result


def bilinear(image: Array, x: Array, y: Array, wrap: str) -> Array:
    """Bilinear filter on 16-bit codes with 8-bit sub-texel precision, integer arithmetic."""
    h, w = image.shape[:2]
    fixed_x = np.floor(x * ONE + 0.5).astype(np.int64)
    fixed_y = np.floor(y * ONE + 0.5).astype(np.int64)
    x0, y0 = fixed_x >> SUBTEXEL_BITS, fixed_y >> SUBTEXEL_BITS
    weights = bilinear_weights(fixed_x & (ONE - 1), fixed_y & (ONE - 1))
    codes = np.asarray(image, np.int64)
    weighted = np.zeros(x.shape + codes.shape[2:], np.int64)
    taps = ((0, 0), (1, 0), (0, 1), (1, 1))
    for weight, (dx, dy) in zip(weights, taps, strict=True):
        texels = codes[_address(y0 + dy, h, wrap), _address(x0 + dx, w, wrap)]
        weighted += (weight[..., None] if codes.ndim == 3 else weight) * texels
    return unorm16(weighted)


def resample(
    image: Array,
    scale: Sequence[float],
    rotation: float,
    offset: Sequence[float],
    filtering: str,
    wrap: str,
    size: int = RESOLUTION,
    below: int = BASE_BELOW,
) -> Array:
    """The fill's stored 16-bit codes: `image` UV-projected onto a `size` x `size` channel.

    With `RepeatNone` the texels outside the UV domain keep the value below the fill.
    """
    h, w = image.shape[:2]
    x, y, inside = texel_coordinates(size, scale, rotation, offset, w, h)
    sampled = (nearest if filtering == "Nearest" else bilinear)(image, x, y, wrap)
    if wrap == "RepeatNone":
        mask = inside[..., None] if sampled.ndim == 3 else inside
        sampled = np.where(mask, sampled, below)
    return sampled


# --- Fit --------------------------------------------------------------------------------------


def sources_images() -> dict[str, Array]:
    """The authored bitmaps as 16-bit codes: pattern64 (64 x 64) and field A (256 x 256), RGB."""
    from tools.parity.tier0_semantics import fixtures

    return {
        "pattern64": png.decode(fixtures.pattern64()).astype(np.int64),
        "field-a": png.decode(fixtures.field_a()).astype(np.int64),
    }


def _residuals(ctx: Context, texture_set: str) -> list[dict[str, Any]]:
    golden = ctx.golden(GOLDEN)
    index = SETS.index(texture_set)
    filtering, wrap = RESAMPLE_FILTERS[index], RESAMPLE_WRAPS[index]
    images = sources_images()
    result = []
    for k, (name, scale, rotation, offset) in enumerate(RESAMPLE_CHANNELS):
        channel = f"user{k}"
        fmt = channel_format(golden, texture_set, channel)
        predicted = resample(images[name], scale, rotation, offset, filtering, wrap)
        for recording in RECORDINGS:
            stored = to_storage(ctx, golden.map(recording, f"{texture_set}/{channel}").values, fmt)
            result.append(
                residual(
                    golden.golden_id,
                    f"{texture_set}/{channel}",
                    recording,
                    UNIT[fmt],
                    difference(predicted, stored),
                )
            )
    return result


TRANSFORM = (
    "UV transform (all entries): output texel (i, j) of the 256 x 256 channel (row 0 on top) at "
    "u = (i + 0.5)/256, v = 1 - (j + 0.5)/256 (v up); (a, b) = (scale_u (u - 0.5), scale_v "
    "(v - 0.5)); u' = cos r a + sin r b + 0.5 - offset_u; v' = -sin r a + cos r b + 0.5 - "
    "offset_v (r = rotation, degrees; scale about the UV centre, then rotation about it; a "
    "positive offset moves the image towards +u/+v). Bitmap texel coordinates (row 0 on top, "
    "centres at integers): x = u' W - 0.5, y = (1 - v') H - 0.5, float64."
)

BILINEAR = (
    " Bilinear on the stored 16-bit codes: X = floor(256 x + 0.5), Y = floor(256 y + 0.5) (8-bit "
    "sub-texel fixed point); x0 = X >> 8, fx = X & 255 (same for y); integer weights w11 = "
    "(fx fy + 127) >> 8 (round, ties down), w10 = fx - w11, w01 = fy - w11, w00 = 256 - fx - fy "
    "+ w11; S = sum of weight * code over the four taps; the value v = S / (256 * 65535) is "
    "truncated to 20 fractional bits (V = floor(S 2^20 / (256 * 65535))) and stored as the "
    "16-bit code floor((V * 65535 + 2^19 - 1) / 2^20) (nearest, ties down). No clamp needed."
)


def _bilinear_entry(
    ctx: Context, entry_id: str, texture_set: str, wrap_text: str
) -> dict[str, Any]:
    index = SETS.index(texture_set)
    filtering = RESAMPLE_FILTERS[index]
    return entry(
        entry_id,
        f"UV projection with the {filtering} filter, {RESAMPLE_WRAPS[index]} wrap",
        TRANSFORM + BILINEAR + wrap_text,
        SOURCES,
        [
            parameter("filtering_mode", filtering, "public_documentation"),
            parameter("uv_wrapping_mode", RESAMPLE_WRAPS[index], "public_documentation"),
            parameter("subtexel_bits", SUBTEXEL_BITS, "fitted", "bits"),
            parameter("weight_bits", SUBTEXEL_BITS, "fitted", "bits"),
            parameter("value_truncation_bits", VALUE_BITS, "fitted", "fractional bits"),
            parameter("uv_pivot", [0.5, 0.5], "fitted"),
        ],
        _residuals(ctx, texture_set),
        notes=_NOTES[entry_id],
    )


_MAGNIFICATION_NOTES = (
    "Scales 1, 0.73, 1.37 x 2.11, rotation 30 and the offsets (users 0-5, 7) are magnification or "
    "1:1 and are reproduced to within 1 code (about 0.15 % of the values; the half-texel offset "
    "of user 7 about 1.6 %, all ties at exactly .5 that the GPU sends both ways). Fitted "
    "structure: a per-tap 4 x 4 least-squares kernel on the offset channel gives the four "
    "bilinear weights as exact multiples of 1/256; float bilinear weights miss by up to 341 "
    "codes, rounding fx and fy alone by up to 225, rounding each product weight separately "
    "(half even) by up to 457 (tie cases of fx fy = 128 mod 256), w11 rounded ties down: 1 code. "
    "Plain rounding of S / 256 leaves about 6000 values per map one code high at fractions "
    "0.50-0.56; truncating v to 20 bits first (the n + 4 bit truncation of the AO and normal "
    "fits) leaves about 280. Float32 orderings of the sum (normalised taps, fma or pairwise) "
    "move the remaining count between 70 and 190 per map but none is exact; the integer form "
    "is kept for reproducibility on DX12 and Vulkan. "
)

_NOTES = {
    "resample-bilinearhq-repeat": _MAGNIFICATION_NOTES
    + "Gap: minification (user 6, field A at scale 3.3, 3.3 texels per output texel) is not "
    "modelled. BilinearHQ there is a wider prefilter: away from the wrap seam the result is "
    "16-19 codes below single-level bilinear (an effective shift of -0.069 texel toward lower "
    "bitmap indices in x and y) and the step response across the seam reaches 2 texels. "
    "Trilinear over a box-filtered mip chain (best LOD 1.3, with or without a shift) misses by "
    "about 3100-4800 codes; other mip chains (point, [1 3 3 1]) do not fit either.",
    "resample-bilinearsharp": _MAGNIFICATION_NOTES
    + "Identical to BilinearHQ except under minification (user 6, scale 3.3): BilinearSharp is "
    "unshifted (within 3 codes of single-level bilinear away from the wrap seam) but its step "
    "response across the seam is wider than bilinear (non-zero about 1 texel from the seam). "
    "Trilinear over a box mip chain fits best at LOD about 0.39 (max 134 codes, float); not "
    "modelled, so user 6 keeps the bilinear residual.",
    "resample-bilinearhq-repeatnone": _MAGNIFICATION_NOTES
    + "RepeatNone: inside the UV domain the taps clamp to the bitmap edge (wrapping instead "
    "misses by up to 38837 codes on the 1:1 pattern); outside it the fill leaves the channel "
    "below (here the empty stack, 1.0). u' = 0 is inside (user 7); whether u' = 1 is inside is "
    "not exercised. User 6 (scale 3.3) inherits the BilinearHQ minification gap.",
}


def _nearest_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "resample-nearest",
        "UV projection with the Nearest filter, Repeat wrap",
        TRANSFORM + " Nearest: the texel (floor(x + 0.5) mod W, floor(y + 0.5) mod H), i.e. "
        "floor(u' W), floor((1 - v') H); its 16-bit code is stored unchanged.",
        SOURCES,
        [
            parameter("filtering_mode", "Nearest", "public_documentation"),
            parameter("uv_wrapping_mode", "Repeat", "public_documentation"),
            parameter("uv_pivot", [0.5, 0.5], "fitted"),
        ],
        _residuals(ctx, "s2"),
        notes="Each of the 2 x 2 x 2 conventions (v up or down, rotation sign, offset sign) was "
        "tested on the eight maps: only v up, rotation by -r of the sample point and a "
        "subtracted offset reproduce all of them; the pattern texels are unique, so every "
        "output texel identifies its source texel. Scale-then-rotate and rotate-then-scale are "
        "equivalent on this corpus (no non-uniform scale with rotation). The field A half-texel "
        "offset puts u' exactly on texel boundaries, which floor resolves upward as fitted.",
    )


def fit(ctx: Context) -> dict[str, Any]:
    entries = [
        _bilinear_entry(
            ctx, "resample-bilinearhq-repeat", "s0", " Repeat: tap indices modulo W, H."
        ),
        _bilinear_entry(ctx, "resample-bilinearsharp", "s1", " Repeat: tap indices modulo W, H."),
        _nearest_entry(ctx),
        _bilinear_entry(
            ctx,
            "resample-bilinearhq-repeatnone",
            "s3",
            " RepeatNone: tap indices clamped to [0, W - 1], [0, H - 1]; output texels whose u' "
            "or v' is outside [0, 1) keep the value below the fill (the stack base, 1.0, here).",
        ),
    ]
    return document(
        "resampling",
        "UV-projection resampling of authored bitmaps (04-layer-stack-and-compositing.md section "
        "4): UV transform convention and the BilinearHQ, BilinearSharp and Nearest filters with "
        "Repeat and RepeatNone wrapping, fitted on the Tier 0 golden resample-uv.",
        ["tier0/semantics/resample-uv"],
        entries,
    )
