"""Authored AO_Mixed operand probe: where Painter's product leaves float32 `a * c` (item 2.10).

The admitted controls fit AO_Mixed's quantizer and operands except at a few operand pairs,
where Painter's product of bit-exact exported operands lands one to three float32 ulps below
float32(a * c) (`tools/parity/fit/ao_mixed_scan.py`). This request separates the candidate
causes with authored float32 operands placed at the quantizer's 12-bit steps j / 4096:

- s0: constant 1.0 mesh times an L32F channel at every step +-6 ulps (a channel-side
  transform shows directly, the product being a multiplication by one);
- s1: the mirror, the step values in the mesh and an explicit Raw white channel;
- s2: lattice mesh codes x / 255 times channels whose exact product sits at step + t ulp,
  t in [-3, 3] by half ulps; s3: the same with the lattice on the channel; s7: neither operand
  on a lattice (an operand transform tied to one side versus product rounding);
- s4, s5, s6: the reopen question of decision 131: L16 at opacity 0.5 and 1 and L32F at 0.75,
  with sources whose blend lands on the steps, so r2 shows which operand reopen substitutes.

Every value is an authored formula; no recorded value is used.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import Golden, start
from tools.parity.tier0_semantics.request_fixtures import exr_float_y

Image = npt.NDArray[np.float32]
SIZE = 256 * 256
STEPS = 4096
TARGETS = np.arange(-6, 7, dtype=np.float64) / 2  # t in ulps of the step, by half ulps
L16_HALF = np.float32(32767 / 65535)  # opacity 0.5 as Painter applies it to L16 (ties down)

ONE = "ao-probe-one-y"
STEP_VALUES = "ao-probe-steps-y"
LATTICE_MESH, LATTICE_MESH_CHANNEL = "ao-probe-lattice-mesh-y", "ao-probe-lattice-mesh-channel-y"
LATTICE_CHANNEL_MESH, LATTICE_CHANNEL = (
    "ao-probe-lattice-channel-mesh-y",
    "ao-probe-lattice-channel-y",
)
FREE_MESH, FREE_CHANNEL = "ao-probe-free-mesh-y", "ao-probe-free-channel-y"
L16_HALF_SOURCE, L32F_THREE_QUARTER_SOURCE = "ao-probe-l16-half-y", "ao-probe-l32f-075-y"


def shift(x: npt.ArrayLike, k: npt.ArrayLike) -> Image:
    """Non-negative float32 `x` moved by `k` float32 steps (next representable values)."""
    bits = np.asarray(x, np.float32).view(np.int32).astype(np.int64) + np.asarray(k, np.int64)
    result: Image = bits.astype(np.int32).view(np.float32)
    return result


def _image(values: npt.ArrayLike) -> Image:
    """`values` in row-major order, padded with 1.0 to 256 x 256."""
    flat = np.asarray(values, np.float32).ravel()
    if flat.size > SIZE:
        raise ValueError("probe values exceed one 256 x 256 texture set")
    padded = np.ones(SIZE, np.float32)
    padded[: flat.size] = flat
    return padded.reshape(256, 256)


def _hash(index: npt.NDArray[np.int64], salt: int) -> npt.NDArray[np.int64]:
    """A fixed integer hash of the texel index (Knuth's multiplicative constant)."""
    result: npt.NDArray[np.int64] = ((index + salt) * 2654435761) % (1 << 32)
    return result


def step_values() -> Image:
    """Every step j / 4096 (0 < j < 4096) moved by -6..6 float32 steps, then 0 and 1 - 0..6."""
    j = np.arange(1, STEPS, dtype=np.float64)
    steps = (j / STEPS).astype(np.float32)
    moved = [shift(steps, k) for k in range(-6, 7)]
    ends = [np.float32(0), *shift(np.full(7, 1, np.float32), np.arange(-6, 1))]
    return _image(np.concatenate([*moved, np.asarray(ends, np.float32)]))


def near_product(fixed: Image, salt: int) -> Image:
    """The float32 partner `o` of each `fixed` value whose exact product `fixed * o` is
    closest to step j / 4096 plus t ulps of that step: t cycles over `TARGETS`, j is a fixed
    hash of the texel index in [1, 4096 * fixed - 1] (so that o stays at most 1)."""
    f = fixed.ravel().astype(np.float64)
    index = np.arange(SIZE, dtype=np.int64)
    top = np.maximum(np.floor(STEPS * f).astype(np.int64) - 1, 1)
    j = 1 + _hash(index, salt) % top
    step = j.astype(np.float64) / STEPS
    target = step + TARGETS[index % TARGETS.size] * np.spacing(step.astype(np.float32))
    first = (step / f).astype(np.float32)
    best = first.copy()
    error = np.full(SIZE, np.inf)
    for k in range(-16, 17):
        o = shift(first, k)
        # f * o is exact in float64 (24 x 24 bits); its distance to the target is exact enough.
        e = np.abs(f * o.astype(np.float64) - target)
        better = (e < error) & (o <= 1)
        best = np.where(better, o, best)
        error = np.where(better, e, error)
    return best.reshape(256, 256)


def lattice_codes(salt: int) -> Image:
    """Lattice values float32(x / 255), x = 1..254 cycling over the texels."""
    x = 1 + (np.arange(SIZE, dtype=np.int64) + salt) % 254
    return (x.astype(np.float64) / 255).astype(np.float32).reshape(256, 256)


def free_values() -> Image:
    """Off-lattice float32 values in [0.25, 1), a fixed hash of the texel index."""
    h = _hash(np.arange(SIZE, dtype=np.int64), 7).astype(np.float64) / (1 << 32)
    return (0.25 + 0.75 * h).astype(np.float32).reshape(256, 256)


def _sources(
    blend: Callable[[Image], Image], first_step: int, guess: Callable[[Image], Image]
) -> Image:
    """Sources in [0, 1] whose blend equals each step j / 4096 (j >= `first_step`) moved by
    -4..4 float32 steps: the source nearest the closed-form `guess` whose blend hits the target
    exactly. Targets no source in [0, 1] reaches are left out."""
    j = np.arange(first_step, STEPS + 1, dtype=np.float64)
    steps = (j / STEPS).astype(np.float32)
    targets = np.concatenate([shift(steps, k) for k in range(-4, 5)])
    targets = targets[targets <= 1]
    start_value = np.clip(guess(targets), 0, 1).astype(np.float32)
    found = np.full(targets.size, np.nan, np.float32)
    for k in sorted(range(-64, 65), key=abs):
        s = shift(start_value, k)
        hit = np.isnan(found) & (s >= 0) & (s <= 1) & (blend(s) == targets)
        found = np.where(hit, s, found)
    return _image(found[~np.isnan(found)])


def blend_l16_half(source: Image) -> Image:
    """float32(S * al) + float32(1 - al), al the L16 code of opacity 0.5 (ties down)."""
    s = np.asarray(source, np.float32)
    result: Image = ((s * L16_HALF).astype(np.float32) + (np.float32(1) - L16_HALF)).astype(
        np.float32
    )
    return result


def blend_l32f(source: Image, opacity: float) -> Image:
    """fma(float32(S - 1), opacity, 1) with one rounding (decision 131's L32F channel)."""
    d = (np.asarray(source, np.float32) - np.float32(1)).astype(np.float32).astype(np.float64)
    exact = d * float(np.float32(opacity)) + 1.0  # exact in float64: 24 x 24-bit product + 1
    result: Image = exact.astype(np.float32)
    return result


def l16_half_sources() -> Image:
    return _sources(
        blend_l16_half,
        STEPS // 2,
        lambda t: ((t.astype(np.float64) - (1 - float(L16_HALF))) / float(L16_HALF)).astype(
            np.float32
        ),
    )


def l32f_three_quarter_sources() -> Image:
    return _sources(
        lambda s: blend_l32f(s, 0.75),
        STEPS // 4,
        lambda t: ((t.astype(np.float64) - 0.25) / 0.75).astype(np.float32),
    )


def _pair(fixed: Callable[[], Image], salt: int) -> tuple[Callable[[], Image], Callable[[], Image]]:
    return fixed, lambda: near_product(fixed(), salt)


LATTICE_MESH_PAIR = _pair(lambda: lattice_codes(0), 11)
LATTICE_CHANNEL_PAIR = _pair(lambda: lattice_codes(127), 23)
FREE_PAIR = _pair(free_values, 37)

# Authored inputs: id -> float32 image generator (written as Y/FLOAT OpenEXR).
IMAGES: dict[str, Callable[[], Image]] = {
    ONE: lambda: np.ones((256, 256), np.float32),
    STEP_VALUES: step_values,
    LATTICE_MESH: LATTICE_MESH_PAIR[0],
    LATTICE_MESH_CHANNEL: LATTICE_MESH_PAIR[1],
    LATTICE_CHANNEL: LATTICE_CHANNEL_PAIR[0],
    LATTICE_CHANNEL_MESH: LATTICE_CHANNEL_PAIR[1],
    FREE_MESH: FREE_PAIR[0],
    FREE_CHANNEL: FREE_PAIR[1],
    L16_HALF_SOURCE: l16_half_sources,
    L32F_THREE_QUARTER_SOURCE: l32f_three_quarter_sources,
}


def exr(name: str) -> Callable[[], bytes]:
    return lambda: exr_float_y(IMAGES[name]())


# Texture set -> (AO format, mesh input, fill source input or None for Raw white, opacity).
SETS: dict[str, tuple[str, str, str | None, float]] = {
    "s0": ("L32F", ONE, STEP_VALUES, 1.0),
    "s1": ("L32F", STEP_VALUES, None, 1.0),
    "s2": ("L32F", LATTICE_MESH, LATTICE_MESH_CHANNEL, 1.0),
    "s3": ("L32F", LATTICE_CHANNEL_MESH, LATTICE_CHANNEL, 1.0),
    "s4": ("L16", ONE, L16_HALF_SOURCE, 0.5),
    "s5": ("L16", ONE, STEP_VALUES, 1.0),
    "s6": ("L32F", ONE, L32F_THREE_QUARTER_SOURCE, 0.75),
    "s7": ("L32F", FREE_MESH, FREE_CHANNEL, 1.0),
}
MAPS = ["virtualMap/AO_Mixed:L", "documentMap/ambientOcclusion:L", "meshMap/ambient_occlusion:L"]


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    s = start("grid4x2")
    for texture_set, (channel_format, _, _, _) in SETS.items():
        s.add(ps.ADD_CHANNEL, channel="AO", format=channel_format, texture_set=texture_set)
    inputs = list(IMAGES)
    resources = s.imports(*inputs)
    for texture_set, (_, mesh, _, _) in SETS.items():
        s.add(ps.SET_MESH_MAP, texture_set=texture_set, usage="AO", resource_step=resources[mesh])
    for texture_set, (_, _, source, opacity) in SETS.items():
        node = s.fill(["AO"], texture_set=texture_set)
        if source is None:
            s.colour(node, "AO", [1.0, 1.0, 1.0], "Raw")
        else:
            s.bitmap(node, "AO", resources[source])
            rr.projection(s, node, "Nearest", "RepeatNone")
        s.blend(node, "AO", "Normal", opacity)
    rr.export(s, MAPS, rr.PNG8, "passthrough")
    rr.export(s, MAPS, rr.EXR32F, "passthrough")
    return Golden(
        "ao-mixed-operand-probe",
        "tier0/ao-mixed/operator",
        "Decision 131 operand probe (phase3.2_unreal-ue56-packed-preset item 2.10), Legacy, "
        "grid4x2, eight full-UV sets at 256 px. Every input is an authored Y/FLOAT OpenEXR "
        "(tools/parity/tier0_semantics/ao_operand_probe.py), never recorded pixels. Each set "
        "binds its own AO mesh map and has one AO fill in Normal, Nearest, identity UV, "
        "RepeatNone. s0: mesh 1.0, L32F channel at every 12-bit step j/4096 moved by -6..6 "
        "float32 steps, opacity 1. s1: the step values as the mesh, explicit Raw white L32F "
        "fill at opacity 1. s2: mesh float32(x/255), x = 1..254, times an L32F channel whose "
        "exact product sits nearest step + t ulp, t in [-3, 3] by half ulps; s3: the lattice "
        "on the channel and the partner in the mesh; s7: both off-lattice in [0.25, 1). "
        "s4: L16 at opacity 0.5, mesh 1.0, sources whose blend float32(S al) + float32(1 - al) "
        "(al the L16 code of 0.5, ties down) hits steps j/4096 >= 0.5 moved by -4..4; s5: L16 "
        "at opacity 1 with the s0 step values; s6: L32F at opacity 0.75 with sources whose "
        "fma(S - 1, 0.75, 1) hits steps >= 0.25 moved by -4..4. Unused texels hold 1.0. "
        "AO_Mixed, the AO channel and the AO mesh map are exported twice immediately as PNG 8 "
        "and twice as OpenEXR 32f, passthrough, no dithering; the recorder repeats all "
        "exports after Full save/close/reopen (r2). Check the template capture's AO formats "
        "and that the mesh and r1 channel exports equal the authored operands (the blends' "
        "formulas for s4 and s6) before interpreting AO_Mixed. No operator result is presumed.",
        "grid4x2",
        ["grid4x2", *inputs],
        s,
    )
