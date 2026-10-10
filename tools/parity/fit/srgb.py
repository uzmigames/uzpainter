"""sRGB transfer fit (`parity/semantics/srgb-transfer.json`, 04 §4).

Goldens: `colour-ramps-{srgb,working,raw}` (288 uniform colours per documented colour space,
each on an RGB16 channel, User0-3, and an sRGB8 channel, User4-7) and `blend-inputs` (every
sRGB8 storage code exported). Candidates: the IEC 61966-2-1 piecewise transfer functions and
the Direct3D float-to-UNORM conversion (round to nearest).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tools.parity.fit.common import (
    RECORDINGS,
    UNIT,
    Context,
    document,
    entry,
    parameter,
    residual,
    source,
    srgb8_export_table,
    to_storage,
)
from tools.parity.fit.stats import Array, difference

FILE = "srgb-transfer.json"
SPACES = ("srgb", "working", "raw")
SETS = 24


def encode(x: Array) -> Array:
    """IEC 61966-2-1 encoding (linear -> non-linear), float64."""
    x = np.asarray(x, np.float64)
    power = 1.055 * np.power(np.maximum(x, 0.0), 1.0 / 2.4) - 0.055
    result: Array = np.where(x <= 0.0031308, 12.92 * x, power)
    return result


def decode(x: Array) -> Array:
    """IEC 61966-2-1 decoding (non-linear -> linear), float64."""
    x = np.asarray(x, np.float64)
    power = np.power((np.maximum(x, 0.0) + 0.055) / 1.055, 2.4)
    result: Array = np.where(x <= 0.04045, x / 12.92, power)
    return result


def significand_round(x: Array, bits: int) -> Array:
    """Round to `bits` significant binary digits (nearest), keeping the exponent."""
    mantissa, exponent = np.frexp(np.asarray(x, np.float64))
    scale = float(1 << bits)
    result: Array = np.ldexp(np.round(mantissa * scale) / scale, exponent)
    return result


def unorm(x: Array, bits: int) -> Array:
    """Float to UNORM code: round(x * (2^bits - 1)) after clamping to [0, 1]."""
    top = (1 << bits) - 1
    return np.round(np.clip(np.asarray(x, np.float64), 0.0, 1.0) * top).astype(np.int64)


def srgb8_store(v: Array) -> Array:
    """Storage code of a uniform colour value on an sRGB8 channel: round(255 * encode(v))."""
    return unorm(encode(v), 8)


SIGNIFICANT_BITS = 8


def srgb8_export(codes: Array) -> Array:
    """16-bit export of sRGB8 storage codes: round(65535 * R8(decode(c / 255)))."""
    linear = significand_round(decode(np.asarray(codes, np.float64) / 255.0), SIGNIFICANT_BITS)
    return unorm(linear, 16)


def _ramp_planes(ctx: Context, space: str, recording: str, user: range) -> tuple[Array, Array]:
    """(model input values, stored values) over every texel of the ramp's maps for 4 channels."""
    from tools.parity.tier0_semantics.corpus import ramp_values

    values = ramp_values()
    golden = ctx.golden(f"semantics/colour-ramps-{space}")
    inputs, stored = [], []
    for index in range(SETS):
        for slot, channel in enumerate(user):
            fmt = "RGB16" if channel < 4 else "sRGB8"
            exported = golden.map(recording, f"s{index}/user{channel}").values
            stored.append(to_storage(ctx, exported, fmt))
            first = index * 12 + (slot % 4) * 3
            colour = np.asarray(values[first : first + 3], np.float64)
            inputs.append(np.broadcast_to(colour, exported.shape))
    return np.concatenate(inputs), np.concatenate(stored)


def _rgb16(ctx: Context) -> dict[str, Any]:
    residuals = []
    for space in SPACES:
        for recording in RECORDINGS:
            v, stored = _ramp_planes(ctx, space, recording, range(4))
            diff = difference(unorm(v, 16), stored)
            residuals.append(
                residual(
                    f"tier0/semantics/colour-ramps-{space}",
                    "s0-s23/user0-user3",
                    recording,
                    UNIT["RGB16"],
                    diff,
                )
            )
    return entry(
        "uniform-colour-rgb16",
        "Uniform colour stored on an RGB16 channel (legacy colour management)",
        "code = round(v * 65535) of the uniform colour component v in [0, 1], clamped; no "
        "transfer function is applied: the colour spaces sRGB, Working and Raw give the same "
        "codes in a project whose colour management mode is legacy (the mode the recorder "
        "captured). Export to PNG 16 writes the code unchanged.",
        [
            source("X-D3D12", "Data conversion rules: FLOAT to UNORM (round to nearest)"),
            source("A-PYDOC", "layerstack: ColorSpace of uniform colour sources"),
        ],
        [parameter("scale", 65535, "public_documentation", "code per unit")],
        residuals,
        notes="Residuals pool the 24 texture sets and four RGB16 channels (288 values, three "
        "components each, every texel of each map) per golden and recording.",
    )


def _srgb8_store(ctx: Context) -> dict[str, Any]:
    residuals = []
    for space in SPACES:
        for recording in RECORDINGS:
            v, stored = _ramp_planes(ctx, space, recording, range(4, 8))
            diff = difference(srgb8_store(v), stored)
            residuals.append(
                residual(
                    f"tier0/semantics/colour-ramps-{space}",
                    "s0-s23/user4-user7",
                    recording,
                    UNIT["sRGB8"],
                    diff,
                )
            )
    return entry(
        "uniform-colour-srgb8-store",
        "Uniform colour stored on an sRGB8 channel (legacy colour management)",
        "code = round(255 * encode(v)), with encode the IEC 61966-2-1 linear-to-sRGB function "
        "(12.92 v for v <= 0.0031308, else 1.055 v^(1/2.4) - 0.055) and v the colour "
        "component taken as linear; same codes for the sRGB, Working and Raw colour spaces "
        "(legacy colour management). Storage codes are recovered from the 16-bit export "
        "through the export calibration of the entry srgb8-export.",
        [
            source("S-SRGB", "IEC 61966-2-1:1999 §5.3 (encoding transfer function)"),
            source("X-D3D12", "Data conversion rules: FLOAT to SRGB (UNORM_SRGB)"),
        ],
        [
            parameter("linear_segment_slope", 12.92, "public_documentation"),
            parameter("threshold", 0.0031308, "public_documentation"),
            parameter("exponent", 2.4, "public_documentation"),
            parameter("offset", 0.055, "public_documentation"),
        ],
        residuals,
        notes="Every differing code is one code off, and all but one sit within 0.06 code of a "
        "rounding boundary of 255 * encode(v): a hardware sRGB conversion with a tolerance "
        "(Direct3D allows a tolerance on sRGB conversions) is the likely cause; the exact "
        "rounding is not reproduced (open item).",
    )


def _srgb8_export(ctx: Context) -> dict[str, Any]:
    residuals = []
    golden = ctx.golden("semantics/blend-inputs")
    for recording in RECORDINGS:
        exported = np.concatenate(
            [golden.map(recording, f"s{s}/user{u}").values for s in (0, 1) for u in (2, 3)]
        )
        codes = to_storage(ctx, exported, "sRGB8")
        diff = difference(srgb8_export(codes), exported.astype(np.int64))
        residuals.append(
            residual(
                "tier0/semantics/blend-inputs",
                "s0-s1/user2-user3",
                recording,
                UNIT["export16"],
                diff,
            )
        )
    table = srgb8_export_table(ctx)
    codes = np.arange(256)
    per_code = difference(srgb8_export(codes)[:, None, None], table[:, None, None])
    return entry(
        "srgb8-export",
        "Export of an sRGB8 channel to a 16-bit PNG",
        "export = round(65535 * R8(decode(c / 255))) for the storage code c, with decode the "
        "IEC 61966-2-1 sRGB-to-linear function (c'/12.92 for c' <= 0.04045, else "
        "((c' + 0.055)/1.055)^2.4) and R8 rounding to 8 significant binary digits (the export "
        "values lie on an 8-significant-bit grid). The 16-bit export of an sRGB8 channel is "
        "therefore approximately linear, although the PNG is tagged sRGB.",
        [
            source("S-SRGB", "IEC 61966-2-1:1999 §5.2 (decoding transfer function)"),
            source("A-HELP-EXPORT", "Export settings: bit depth and colour space of PNG output"),
        ],
        [
            parameter("significant_bits", SIGNIFICANT_BITS, "fitted", "bits"),
            parameter("scale", 65535, "public_documentation", "code per unit"),
        ],
        residuals,
        notes=f"Over the 256 storage codes the model differs on {per_code.differing} codes "
        f"(max |delta| {int(per_code.max)} export codes). The export grid has 8 significant "
        "bits, but the underlying curve deviates from the IEC decode by up to about 0.25 % "
        "of full scale at mid range (an approximation of the transfer function inside "
        "Painter's export path); not reproduced exactly (open item).",
    )


def fit(ctx: Context) -> dict[str, Any]:
    corpus = [f"tier0/semantics/colour-ramps-{s}" for s in SPACES]
    corpus.append("tier0/semantics/blend-inputs")
    return document(
        "srgb-transfer",
        "Transfer functions of uniform colours and channel storage (04 section 4, task "
        "phase0.7_tier0-stability-fits): fitted against IEC 61966-2-1 from the Tier 0 colour "
        "ramps (288 values per colour space) and the exported sRGB8 codes of the blend inputs. "
        "Residuals are |delta| in storage units against both recordings (r1 same session, r2 "
        "after save and reopen).",
        corpus,
        [_rgb16(ctx), _srgb8_store(ctx), _srgb8_export(ctx)],
    )
