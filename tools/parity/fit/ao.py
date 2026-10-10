"""`AO_Mixed` operator fit (`parity/semantics/ao-mixed.json`).

Golden `ao-mixed` (grid2x2): the authored AO mesh map (grey A, ramp along x) assigned to every
texture set, and an AO channel (L16) whose fill is grey B (ramp along y) at opacity 1 (s0) and
0.5 (s1), a uniform 0.5 (s2), or no layer (s3). Exports `AO_Mixed` (virtual map) and the
`ambientOcclusion` channel, PNG 16. The operator is modelled on the stored channel (the exported
L16 codes) and the authored mesh map. Candidates: the mixed AO virtual map of the output
templates (A-HELP-EXPORT, A-PYDOC) and the float-to-UNORM conversion (X-D3D12).
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
    document,
    entry,
    parameter,
    residual,
    source,
    to_storage,
)
from tools.parity.fit.stats import Array, difference

FILE = "ao-mixed.json"
GOLDEN = "semantics/ao-mixed"
SETS = ("s0", "s1", "s2", "s3")
TOP16 = 65535
EXTRA_BITS = 4  # fractional bits kept below the 8-bit code before the final rounding
SHIFT = 8 + EXTRA_BITS


def ao_mixed(mesh_map: Array, channel: Array) -> Array:
    """`AO_Mixed` 16-bit export codes from the 16-bit codes of the AO mesh map and AO channel.

    v = (a / 65535) * (c / 65535); v is truncated to 12 fractional bits, rounded to the nearest
    8-bit code with ties down, and exported as code * 257. Integer arithmetic throughout.
    """
    a = np.asarray(mesh_map, np.int64)
    c = np.asarray(channel, np.int64)
    j = (a * c * (1 << SHIFT)) // (TOP16 * TOP16)
    code8 = (j * 255 + (1 << (SHIFT - 1)) - 1) >> SHIFT
    result: Array = code8 * 257
    return result


def mesh_map_codes() -> Array:
    """The authored AO mesh map (grey A) as 16-bit codes, shape (256, 256)."""
    from tools.parity.tier0_semantics import fixtures

    codes = png.decode(fixtures.grey_a()).astype(np.int64)
    result: Array = codes[:, :, 0] if codes.ndim == 3 else codes
    return result


def _operator(ctx: Context) -> dict[str, Any]:
    golden = ctx.golden(GOLDEN)
    mesh_map = mesh_map_codes()
    residuals = []
    for texture_set in SETS:
        fmt = channel_format(golden, texture_set, "ao")
        for recording in RECORDINGS:
            exported = golden.map(recording, f"{texture_set}/ambientOcclusion").values[:, :, 0]
            channel = to_storage(ctx, exported, fmt)
            predicted = ao_mixed(mesh_map, channel)
            recorded = golden.map(recording, f"{texture_set}/AO_Mixed").values[:, :, 0]
            residuals.append(
                residual(
                    golden.golden_id,
                    f"{texture_set}/AO_Mixed",
                    recording,
                    UNIT["export16"],
                    difference(predicted, recorded),
                )
            )
    return entry(
        "ao-mixed-operator",
        "AO_Mixed virtual map: baked AO mesh map combined with the AO channel",
        "AO_Mixed = a * c, the product (multiply) of the baked AO mesh map value a and the AO "
        "channel value c, both linear in [0, 1] (a = mesh map code / 65535, c = stored L16 code "
        "/ 65535; no colour transfer). The result is written at 8-bit precision: v = a * c is "
        "truncated to 12 fractional bits (j = floor(v * 4096)), then code8 = floor((j * 255 + "
        "2047) / 4096), the nearest 8-bit code with ties down; the PNG 16 export writes code8 * "
        "257. An AO channel with no layer stores its base 1.0 (code 65535), so AO_Mixed equals "
        "the mesh map quantised to 8 bits. No clamp is needed (a * c is in [0, 1]).",
        [
            source("A-HELP-EXPORT", "Output templates: virtual maps, Mixed AO"),
            source("A-PYDOC", "textureset: MeshMapUsage.AO; ChannelType.AO"),
            source("X-D3D12", "Data conversion rules: FLOAT to UNORM"),
        ],
        [
            parameter("operator", "multiply", "fitted"),
            parameter("result_bits", 8, "fitted", "bits"),
            parameter("truncation_bits", 8 + EXTRA_BITS, "fitted", "fractional bits"),
            parameter("empty_channel_base", 1.0, "fitted"),
        ],
        residuals,
        notes="Whole image (one quad per set, full 0-1 UVs). min(a, c) misses by up to 16448 "
        "export codes; a 16-bit product misses by up to 145. Every recorded AO_Mixed value is on "
        "the 8-bit lattice (multiple of 257). Plain round-to-nearest of 255 * a * c leaves 2060 "
        "(s0) and about 2400 (s1) values one 8-bit code high, all at fractions 0.50-0.56; the "
        "12-bit truncation removes them (the same n + 4 bit truncation fits the 16-bit normal "
        "maps, height-to-normal.json). s0, s2 and s3 are exact against both recordings. s1 "
        "(fill at opacity 0.5) leaves 30 (r1) and 17 (r2) values one 8-bit code (257) off, every "
        "one within 0.03 of a 2^-12 step; the oracle is unstable on the same values (r1 and r2 "
        "differ in 27 values, max 257, all within 0.03 of a step), so an exact fit against both "
        "recordings is impossible there. Using the unquantised blend 0.5 + 0.5 * b in place of "
        "the stored L16 channel fits worse (29 and 50 values).",
    )


def _empty_channel(ctx: Context) -> dict[str, Any]:
    golden = ctx.golden(GOLDEN)
    fmt = channel_format(golden, "s3", "ao")
    residuals = []
    for recording in RECORDINGS:
        exported = golden.map(recording, "s3/ambientOcclusion").values
        stored = to_storage(ctx, exported, fmt)
        residuals.append(
            residual(
                golden.golden_id,
                "s3/ambientOcclusion",
                recording,
                UNIT[fmt],
                difference(np.full_like(stored, TOP16), stored),
            )
        )
    return entry(
        "ao-channel-empty-base",
        "AO channel (L16) with no layer: its stored base value",
        "Every texel stores 1.0 (code 65535 on L16): the base of an empty AO channel is white "
        "(no occlusion), so AO_Mixed of an empty channel is the baked mesh map alone.",
        [source("A-PYDOC", "textureset: ChannelType.AO")],
        [parameter("base", 1.0, "fitted")],
        residuals,
        notes="Observed on the operands: the uniform 0.5 fill of s2 rounds the L16 tie "
        "0.5 * 65535 down, while the opacity-0.5 fill of grey B over the base (s1) rounds the "
        "same tie up where its blend is 0.5 (b = 0); the L16 channel stack itself belongs to the "
        "blend fits.",
    )


def fit(ctx: Context) -> dict[str, Any]:
    entries = [_operator(ctx), _empty_channel(ctx)]
    return document(
        "ao-mixed",
        "The AO_Mixed virtual map operator: baked AO mesh map times the AO channel, its 8-bit "
        "quantisation, and the empty AO channel base, fitted on the Tier 0 ao-mixed golden.",
        [ctx.golden(GOLDEN).golden_id],
        entries,
    )
