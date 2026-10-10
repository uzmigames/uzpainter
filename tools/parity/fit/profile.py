"""Evaluator profile from the three-1/3-opacity-fills experiment (`evaluator-profile.json`, 04 §4).

Golden `quantisation-thirds`: per texture set three uniform fills (colour triplets of
`THIRDS_COLOURS`) at opacity 1/3 in Normal mode over the empty stack (base 1.0), on one channel
per `ChannelFormat` member. Two quantisation models are compared with both recordings:

- end: the accumulator stays in float64 and is quantised to the channel format once, at the end;
- per-layer: each layer's content and the accumulator after each layer are quantised to the
  channel format.

For sRGB8 two blending spaces are compared: linear (values decoded with IEC 61966-2-1, blended,
re-encoded) and encoded (blending the encoded values directly). A uniform colour on an L channel
is the mean of its three components (measured on this golden).
"""

from __future__ import annotations

from collections.abc import Callable
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
    to_storage,
)
from tools.parity.fit.srgb import decode, encode
from tools.parity.fit.stats import Array, difference

FILE = "evaluator-profile.json"
GOLDEN = "tier0/semantics/quantisation-thirds"
OPACITY = float(np.float32(1.0 / 3.0))  # the opacity as Painter stores and reads it back
PROFILE_ID = "painter-12.1-layerq-linear"

Quantiser = Callable[[float], float]


def quantiser(fmt: str) -> Quantiser:
    """Round a float to the value the channel format can store (sRGB8: in linear terms)."""
    if fmt in ("RGB16", "L16"):
        return lambda x: round(min(max(x, 0.0), 1.0) * 65535) / 65535
    if fmt in ("RGB8", "L8"):
        return lambda x: round(min(max(x, 0.0), 1.0) * 255) / 255
    if fmt in ("RGB16F", "L16F"):
        return lambda x: float(np.float16(x))
    if fmt in ("RGB32F", "L32F"):
        return lambda x: float(np.float32(x))
    if fmt == "sRGB8":
        return lambda x: float(decode(np.asarray(round(float(encode(np.asarray(x))) * 255) / 255)))
    raise ValueError(f"unknown channel format {fmt}")


def storage(fmt: str, x: float) -> float:
    """The stored value in storage units (codes for integer formats)."""
    if fmt in ("RGB16", "L16"):
        return float(round(min(max(x, 0.0), 1.0) * 65535))
    if fmt in ("RGB8", "L8"):
        return float(round(min(max(x, 0.0), 1.0) * 255))
    if fmt == "sRGB8":
        return float(round(float(encode(np.asarray(x))) * 255))
    return quantiser(fmt)(x)


def thirds(colours: list[float], fmt: str, per_layer: bool, space: str = "linear") -> float:
    """Three Normal fills at opacity 1/3 over the base 1.0: acc <- acc + (c - acc) * alpha."""
    if space == "encoded":  # sRGB8 only: blend the encoded values, round to a code at the end
        acc = 1.0
        for c in colours:
            acc = acc + (float(encode(np.asarray(c))) - acc) * OPACITY
            if per_layer:
                acc = round(acc * 255) / 255
        return float(round(acc * 255))
    q = quantiser(fmt)
    acc = 1.0
    for c in colours:
        value = q(c) if per_layer else c
        acc = acc + (value - acc) * OPACITY
        if per_layer:
            acc = q(acc)
    return storage(fmt, acc)


def _components(fmt: str, triplet: list[float]) -> list[float]:
    return [sum(triplet) / 3.0] if fmt.startswith("L") else list(triplet)


def model_map(
    fmt: str, set_index: int, per_layer: bool, space: str, shape: tuple[int, ...]
) -> Array:
    from tools.parity.tier0_semantics.corpus import THIRDS_COLOURS

    colours = [[float(np.float32(v)) for v in rgb] for rgb in THIRDS_COLOURS[set_index]]
    planes = len(_components(fmt, colours[0]))
    values = [
        thirds([_components(fmt, c)[k] for c in colours], fmt, per_layer, space)
        for k in range(planes)
    ]
    return np.broadcast_to(np.asarray(values), shape)


def _residuals(
    ctx: Context, per_layer: bool, space: str, formats: tuple[tuple[str, str], ...]
) -> list[dict[str, Any]]:
    golden = ctx.golden("semantics/quantisation-thirds")
    residuals = []
    for channel, fmt in formats:
        for recording in RECORDINGS:
            models, observed = [], []
            for s in range(4):
                exported = golden.map(recording, f"s{s}/{channel.lower()}").values
                stored = to_storage(ctx, exported, fmt)
                model = model_map(fmt, s, per_layer, space, stored.shape)
                models.append(model.astype(stored.dtype) if fmt not in FLOATS else model)
                observed.append(stored)
            diff = difference(np.concatenate(models), np.concatenate(observed))
            residuals.append(
                residual(GOLDEN, f"s0-s3/{channel.lower()}", recording, UNIT[fmt], diff)
            )
    return residuals


FLOATS = frozenset({"RGB16F", "L16F", "RGB32F", "L32F"})


def _formats() -> tuple[tuple[str, str], ...]:
    from tools.parity.tier0_semantics.corpus import FORMAT_CHANNELS

    return tuple(FORMAT_CHANNELS)


def _summary(residuals: list[dict[str, Any]]) -> tuple[int, float]:
    differing = sum(r["difference"]["differing"] for r in residuals)
    worst = max(float(r["difference"]["max"]) for r in residuals)
    return differing, worst


SOURCES = [
    source("S-W3C-BLEND", "§5.1 Normal blend mode; §6 simple alpha compositing"),
    source("S-SRGB", "IEC 61966-2-1:1999 §5.2-5.3 (transfer functions)"),
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM, FLOAT to FLOAT16"),
]
MIX = (
    "acc_0 = 1 (empty stack); acc_i = acc_(i-1) + (c_i - acc_(i-1)) * alpha with alpha = "
    "float32(1/3) in float64 arithmetic; an L channel takes the mean of the colour's three "
    "components. Quantiser Q: RGB16/L16 round(x*65535), RGB8/L8 round(x*255), RGB16F/L16F "
    "nearest half, RGB32F/L32F nearest float32, sRGB8 round(255*encode(x)) with encode/decode "
    "IEC 61966-2-1 (blending on linear values)."
)


def fit(ctx: Context) -> dict[str, Any]:
    formats = _formats()
    end = _residuals(ctx, False, "linear", formats)
    layer = _residuals(ctx, True, "linear", formats)
    srgb = tuple((c, f) for c, f in formats if f == "sRGB8")
    encoded = _residuals(ctx, True, "encoded", srgb)
    end_diff, end_max = _summary(end)
    layer_diff, layer_max = _summary(layer)
    enc_diff, enc_max = _summary(encoded)
    lin_srgb = [r for r in layer if r["map"].endswith(srgb[0][0].lower())]
    lin_diff, lin_max = _summary(lin_srgb)
    golden = ctx.golden("semantics/quantisation-thirds")
    maps = golden.maps("r1")
    unstable = sum(golden.map_sha256("r1", m) != golden.map_sha256("r2", m) for m in maps)
    chosen = layer if layer_diff <= end_diff else end
    chosen_name = "per-layer" if chosen is layer else "end"
    entries = [
        entry(
            "quantisation-end",
            "Quantisation at the end of the stack only (exact model)",
            MIX + " End model: acc stays unquantised; Q is applied once to the final acc.",
            SOURCES,
            [parameter("opacity", OPACITY, "authored")],
            end,
        ),
        entry(
            "quantisation-per-layer",
            "Quantisation after every layer (per-layer-quantised model)",
            MIX + " Per-layer model: each layer's content c_i and the accumulator after each "
            "layer are quantised with Q.",
            SOURCES,
            [parameter("opacity", OPACITY, "authored")],
            layer,
        ),
        entry(
            "srgb8-blending-space-encoded",
            "sRGB8 blending on encoded values (rejected candidate)",
            "acc_i = acc_(i-1) + (encode(c_i) - acc_(i-1)) * alpha on IEC 61966-2-1 encoded "
            "values, rounded to an 8-bit code after each layer.",
            SOURCES,
            [parameter("opacity", OPACITY, "authored")],
            encoded,
        ),
        entry(
            "evaluator-profile",
            f"Evaluator profile {PROFILE_ID} (provisional)",
            MIX + f" Selected: the {chosen_name} model, sRGB8 channels blended on linear values.",
            SOURCES,
            [
                parameter("evaluator_profile", PROFILE_ID, "fitted"),
                parameter("quantisation_points", chosen_name, "fitted"),
                parameter("srgb8_blending_space", "linear", "fitted"),
            ],
            chosen,
            notes=(
                f"Differing values over the nine channel formats and both recordings: end model "
                f"{end_diff} (max |delta| {end_max:g}), per-layer model {layer_diff} (max "
                f"{layer_max:g}). sRGB8: linear per-layer {lin_diff} (max {lin_max:g}) against "
                f"encoded {enc_diff} (max {enc_max:g}), so sRGB8 channels blend on linear "
                "values. Neither quantisation model reproduces the golden exactly and the "
                f"golden is unstable (r1 and r2 differ on {unstable} of {len(maps)} maps), so the "
                "profile is provisional: quantisation points stay an open item."
            ),
        ),
    ]
    return document(
        "evaluator-profile",
        "Evaluator profile settled by the three-1/3-opacity-fills experiment (04 section 4, "
        "task phase0.7_tier0-stability-fits): end against per-layer quantisation on every "
        "ChannelFormat member and encoded against linear blending on sRGB8. Residuals are "
        "|delta| in storage units against both recordings.",
        [GOLDEN],
        entries,
    )
