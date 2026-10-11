"""Height-to-normal and the virtual normal maps (`parity/semantics/height-to-normal.json`).

Goldens of the current envelope (decision 037): the UI-set method goldens of
`phase0.7_tier0-semantics-ui-cases` (decision 047: `Sharp` and `Smooth (Sobel)` on the sphere, the
bevelled cube and a 4x2 plane grid whose sets sweep the height amplitude: opacity 1, 0.75, 0.5,
0.25, 0.1 and 2, 3, 4 copies in LinearDodge), the default-method goldens (`height-normal-*`, which
explicit `Sharp` reproduces byte for byte) and `blend-normal-channel` (normal maps in the Normal
channel, empty Height, Normal_OpenGL exported). Each exports `Normal_OpenGL` and `Normal_DirectX`
(PNG 16) and the Height and Normal channels (OpenEXR 32f).

The model (implemented by `src/evaluator/height_to_normal.cpp` operation for operation, decisions
064 and 065) reads the Height channel's read-out before its write rule, rebuilt here from the
authored bitmap and the recorded layer sequence with the evaluator's composite (`arith.h`), and the
exported Normal channel. Candidates: finite-difference bump mapping (P-PBRT), the Sobel operator
(P-SOBEL), reoriented normal mapping (P-BARRE), the OpenGL/DirectX formats (A-HELP-GUIDE) and the
float-to-UNORM conversion (X-D3D12); the reciprocal square root is the recording GPU's
(`tools/parity/fit/hwmath.py`).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility.compare import erode, rasterise_uv
from tools.parity.feasibility.fixtures import Mesh
from tools.parity.fit import hwmath
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

FILE = "height-to-normal.json"
RESOLUTION = 256
SHARP_Z = 0.390625  # 1 / 2.56: the z of the Sharp vector at 256 texels (fitted)
SOBEL_Z = 3.125  # 8 x 0.390625: the (1, 2, 1) x central-difference weight sum (fitted)
EXTRA_BITS = 4  # fractional bits kept below the target code before the final rounding
F32 = np.float32
F64 = np.float64

SHARP = "semantics-ui/height-normal-sharp"
SOBEL = "semantics-ui/height-normal-sobel"
DEFAULT = "semantics/height-normal"
NORMAL_CHANNEL = "semantics/blend-normal-channel"
PLANE_SETS = tuple(f"s{i}" for i in range(8))
# golden -> (texture sets, method)
GOLDENS: dict[str, tuple[tuple[str, ...], str]] = {
    f"{SHARP}-plane-strength": (PLANE_SETS, "Sharp"),
    f"{SHARP}-sphere": (("uzp_sphere",), "Sharp"),
    f"{SHARP}-bevelled-cube": (("uzp_bevelled_cube",), "Sharp"),
    f"{DEFAULT}-plane-amplitudes": (("s0", "s1", "s2", "s3"), "Sharp"),
    f"{DEFAULT}-sphere": (("uzp_sphere",), "Sharp"),
    f"{DEFAULT}-bevelled-cube": (("uzp_bevelled_cube",), "Sharp"),
    f"{SOBEL}-plane-strength": (PLANE_SETS, "SmoothSobel"),
    f"{SOBEL}-sphere": (("uzp_sphere",), "SmoothSobel"),
    f"{SOBEL}-bevelled-cube": (("uzp_bevelled_cube",), "SmoothSobel"),
}
MAPS = ("Normal_OpenGL", "Normal_DirectX")
SOURCES = [
    source("P-PBRT", "Bump mapping: displacement gradient by finite differences"),
    source("P-SOBEL", "The Sobel operator: (1, 2, 1) smoothing times a central difference"),
    source("P-BARRE", "Blending in Detail (2012): reoriented normal mapping"),
    source("A-HELP-GUIDE", "Texture Set Settings: height to normal method; normal map format"),
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM; rsqrt within 1 ULP"),
]

# --- float32 arithmetic of the evaluator (arith.h) -------------------------------------------


def fma(x: npt.ArrayLike, y: npt.ArrayLike, z: npt.ArrayLike) -> Array:
    """arith::Fma: the exact product in double plus z in double, rounded to float32."""
    result: Array = (
        np.asarray(x, F32).astype(F64) * np.asarray(y, F32).astype(F64)
        + np.asarray(z, F32).astype(F64)
    ).astype(F32)
    return result


Vec = tuple[Array, Array, Array]


def normalise(v: Vec) -> Vec:
    """v hw::Rsqrt(fma(z, z, fma(x, x, y y)))."""
    x, y, z = (np.asarray(c, F32) for c in v)
    inv = hwmath.rsqrt(fma(z, z, fma(x, x, y * y)))
    return x * inv, y * inv, z * inv


def decode(c: Vec) -> Vec:
    """normalise(2c - 1) with z clamped to >= 0."""
    two, one = F32(2), F32(1)
    x, y, z = ((np.asarray(k, F32) * two) - one for k in c)
    return normalise((x, y, np.fmax(z, F32(0))))


def reoriented(base: Vec, detail: Vec) -> Vec:
    """Reoriented normal mapping of `detail` on `base`, not normalised (arith.cpp Reoriented)."""
    tx, ty, tz = (
        np.asarray(base[0], F32),
        np.asarray(base[1], F32),
        np.asarray(base[2], F32) + F32(1),
    )
    ux, uy, uz = (
        -np.asarray(detail[0], F32),
        -np.asarray(detail[1], F32),
        np.asarray(detail[2], F32),
    )
    d = fma(tz, uz, fma(ty, uy, tx * ux))
    return fma(tx, d, -(ux * tz)), fma(ty, d, -(uy * tz)), tz * (d - uz)


def height_vector(h: Array, method: str) -> Vec:
    """The height-derived vector of `method` per texel (rows top first, wrap-around)."""
    h = np.asarray(h, F32)

    def at(dx: int, dy: int) -> Array:  # at(dx, dy)[r, c] = h[r + dy, c + dx]
        shifted: Array = np.roll(np.roll(h, -dy, axis=0), -dx, axis=1)
        return shifted

    if method == "Sharp":
        return at(-1, 0) - h, h - at(0, -1), np.full_like(h, F32(SHARP_Z))
    two = F32(2)
    left = (at(-1, -1) + two * at(-1, 0)) + at(-1, 1)
    right = (at(1, -1) + two * at(1, 0)) + at(1, 1)
    top = (at(-1, -1) + two * at(0, -1)) + at(1, -1)
    bottom = (at(-1, 1) + two * at(0, 1)) + at(1, 1)
    return left - right, bottom - top, np.full_like(h, F32(SOBEL_Z))


def unorm(value: Array, bits: int) -> Array:
    """Float in [0, 1] to an n-bit UNORM code as observed: the value is truncated to n + 4
    fractional bits, then rounded to the nearest code with ties down (integer arithmetic)."""
    shift = bits + EXTRA_BITS
    top = (1 << bits) - 1
    grid = np.floor(np.clip(np.asarray(value, F64), 0.0, 1.0) * float(1 << shift))
    j = grid.astype(np.int64)
    result: Array = (j * top + (1 << (shift - 1)) - 1) >> shift
    return result


def normal_maps(
    height: Array, method: str = "Sharp", channel: Vec | None = None
) -> dict[str, Array]:
    """The 16-bit `Normal_OpenGL` and `Normal_DirectX` codes (h, w, 3) of a height read-out and
    a Normal-channel read-out colour (the flat colour when None)."""
    h = np.asarray(height, F32)
    flat = (np.zeros_like(h), np.zeros_like(h), np.ones_like(h))
    if channel is None:
        channel = (np.full_like(h, F32(0.5)), np.full_like(h, F32(0.5)), np.ones_like(h))
    base = normalise(reoriented(flat, normalise(height_vector(h, method))))
    n = normalise(reoriented(base, decode(channel)))
    half = F32(0.5)
    x, y, z = (unorm(fma(c, half, half), 16) for c in n)
    return {
        "Normal_OpenGL": np.stack([x, y, z], axis=-1),
        "Normal_DirectX": np.stack([x, unorm(fma(-n[1], half, half), 16), z], axis=-1),
    }


# --- The Height read-out ---------------------------------------------------------------------


def half_toward_zero(v: Array) -> Array:
    """float32 values rounded to binary16 toward zero (the L16F write rule), as float32."""
    f = np.asarray(v, F32)
    h = f.astype(np.float16)
    over = np.abs(h.astype(F32)) > np.abs(f)
    hb = h.view(np.uint16).astype(np.int32) - over.astype(np.int32)
    result: Array = hb.astype(np.uint16).view(np.float16).astype(F32)
    return result


def height_content(codes: Array) -> Array:
    """The stored content of a bitmap fill on Height: half toward zero of float32(2 t) - 1,
    t = float32(code / 65535) (colour-transfer.json, bitmap-height-signed)."""
    t = (np.asarray(codes, F64) / 65535.0).astype(F32)
    return half_toward_zero(F32(2) * t - F32(1))


def height_layers(manifest: dict[str, Any], texture_set: str) -> list[tuple[str, float]]:
    """The (mode, opacity) of the Height fills of `texture_set`, bottom-up, from the recorded
    instruction sequence (`position: top` inserts on top; `above_step` above that layer)."""
    order: list[int] = []
    owner: dict[int, str] = {}
    blending: dict[int, list[Any]] = {}
    for step in manifest["instruction_sequence"]["steps"]:
        call, args, n = step["call"], step["args"], step["step"]
        if call.endswith("layerstack.insert_fill"):
            if "above_step" in args:
                anchor = args["above_step"]
                owner[n] = owner[anchor]
                order.insert(order.index(anchor) + 1, n)
            else:
                owner[n] = str(args.get("texture_set", texture_set))
                order.append(n)
            blending[n] = ["Normal", 1.0]
        elif call.endswith("Node.set_blending_mode") and args.get("channel") == "Height":
            blending[args["node_step"]][0] = args["blending_mode"]
        elif call.endswith("Node.set_opacity") and args.get("channel") == "Height":
            blending[args["node_step"]][1] = float(args["opacity"])
    return [(blending[n][0], blending[n][1]) for n in order if owner[n] == texture_set]


def height_readout(content: Array, layers: list[tuple[str, float]]) -> Array:
    """The Height read-out before the write rule: the layers composited bottom-up from a
    transparent start (colour and coverage written half toward zero after each layer), then over
    the base 0 as fma(C - base, a, base) (arith::Composite, the fused read-out of profile
    painter-12.1-isolated-coverage-weights; over the base 0 it equals base + (C - base) a of the
    earlier profiles)."""
    q = np.asarray(content, F32)
    colour = np.zeros_like(q)
    alpha: Array | None = None
    for mode, opacity in layers:
        a = F32(opacity)
        if alpha is None:  # over the transparent start: the source as it is
            colour = q.copy()
            alpha = np.full_like(q, half_toward_zero(np.asarray([a], F32))[0])
            continue
        if not np.all(alpha == F32(1)):
            raise ValueError("a layer over a partly covered Height is not modelled here")
        r = colour + q if mode == "LinearDodge" else q
        if mode not in ("Normal", "LinearDodge"):
            raise ValueError(f"{mode} on Height is not modelled here")
        colour = half_toward_zero(colour * (F32(1) - a) + r * a)
    if alpha is None:
        return np.zeros_like(q)
    base = F32(0)
    return fma(colour - base, alpha, np.full_like(colour, base))


# --- Comparison domain ------------------------------------------------------------------------


def uv_mesh(obj: bytes) -> Mesh:
    """UV triangles of an authored OBJ (fan-triangulated faces, `v/vt/vn` references)."""
    uvs: list[tuple[float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for line in obj.decode("utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "vt":
            uvs.append((float(parts[1]), float(parts[2])))
        elif parts[0] == "f":
            index = [int(ref.split("/")[1]) - 1 for ref in parts[1:]]
            triangles += [(index[0], index[k], index[k + 1]) for k in range(1, len(index) - 1)]
    none = np.zeros((len(uvs), 3))
    return Mesh(
        "uv",
        none,
        none,
        np.asarray(uvs, F64),
        np.asarray(triangles, np.int64),
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        lambda points: points,
    )


def uv_domain(obj: bytes) -> npt.NDArray[np.bool_]:
    """Texels covered by the UV triangles, eroded by one texel (the rest is export padding)."""
    domain: npt.NDArray[np.bool_] = erode(rasterise_uv(uv_mesh(obj), RESOLUTION))
    return domain


def _domain(ctx: Context, name: str) -> npt.NDArray[np.bool_] | None:
    from tools.parity.tier0_semantics import fixtures

    if name.endswith("plane-strength") or name.endswith("plane-amplitudes"):
        return None
    kind = "sphere" if name.endswith("sphere") else "bevelled-cube"
    cached = ctx.cached(f"uv-domain/{kind}")
    if cached is None:
        obj = fixtures.sphere() if kind == "sphere" else fixtures.bevelled_cube()
        cached = ctx.remember(f"uv-domain/{kind}", uv_domain(obj))
    domain: npt.NDArray[np.bool_] = cached
    return domain


# --- Entries ----------------------------------------------------------------------------------


def _content(ctx: Context) -> Array:
    from tools.parity.tier0_semantics import fixtures

    cached = ctx.cached("height-content")
    if cached is None:
        from tools.parity.feasibility import png

        codes = png.decode(fixtures.height_ramps()).astype(np.int64)
        cached = ctx.remember(
            "height-content", height_content(codes.reshape(RESOLUTION, RESOLUTION, -1)[..., 0])
        )
    content: Array = cached
    return content


def _readout(ctx: Context, name: str, texture_set: str) -> Array:
    key = f"readout/{name}/{texture_set}"
    cached = ctx.cached(key)
    if cached is None:
        golden = ctx.golden(name)
        cached = ctx.remember(
            key, height_readout(_content(ctx), height_layers(golden.manifest, texture_set))
        )
    readout: Array = cached
    return readout


def _stable(ctx: Context, name: str, map_name: str) -> bool:
    golden = ctx.golden(name)
    return golden.map_sha256("r1", map_name) == golden.map_sha256("r2", map_name)


def _selected(stable: bool, recording: str, unstable: bool) -> bool:
    """Every r1 map and every r2 map that equals its r1; with `unstable`, both recordings of the
    maps whose r2 differs from r1."""
    return not stable if unstable else (stable or recording == "r1")


def _method_residuals(ctx: Context, method: str, unstable: bool = False) -> list[dict[str, Any]]:
    """Residuals of the virtual maps (`_selected`)."""
    residuals = []
    for name, (sets, golden_method) in GOLDENS.items():
        if golden_method != method:
            continue
        golden = ctx.golden(name)
        domain = _domain(ctx, name)
        for texture_set in sets:
            predicted = normal_maps(_readout(ctx, name, texture_set), method)
            for map_name in MAPS:
                key = f"{texture_set}/{map_name}"
                stable = _stable(ctx, name, key)
                for recording in RECORDINGS:
                    if not _selected(stable, recording, unstable):
                        continue
                    recorded = golden.map(recording, key).values
                    residuals.append(
                        residual(
                            golden.golden_id,
                            key,
                            recording,
                            UNIT["export16"],
                            difference(predicted[map_name], recorded, domain),
                        )
                    )
    return residuals


def _height_residuals(ctx: Context, unstable: bool = False) -> list[dict[str, Any]]:
    residuals = []
    for name, (sets, _) in GOLDENS.items():
        golden = ctx.golden(name)
        domain = _domain(ctx, name)
        for texture_set in sets:
            key = f"{texture_set}/height"
            stored = half_toward_zero(_readout(ctx, name, texture_set)).astype(F64)
            stable = _stable(ctx, name, key)
            for recording in RECORDINGS:
                if not _selected(stable, recording, unstable):
                    continue
                recorded = golden.map(recording, key).values[..., 0].astype(F64)
                residuals.append(
                    residual(
                        golden.golden_id,
                        key,
                        recording,
                        UNIT["L16F"],
                        difference(stored, recorded, domain),
                    )
                )
    return residuals


STENCILS = (
    "Input: the Height read-out before its write rule (the root layers composited from a "
    "transparent start, colour and coverage written half toward zero after each layer, then over "
    "the base 0 as fma(C - base, a, base): at opacity 0.75 and 0.1 the stored half is "
    "not what the stencil reads). Rows top first, wrap-around at the texture borders, h(dx, dy) "
    "the height at column + dx, row + dy."
)
COMBINATION = (
    "H = normalise(v); A = normalise(reoriented(F, H)), F = (0, 0, 1) (the mesh normal slot, "
    "flat: no Normal mesh map recorded); C = decode(Normal channel read-out over the flat colour "
    "(0.5, 0.5, 1)); n = normalise(reoriented(A, C)). normalise(v) = v rsqrt(fma(z, z, fma(x, x, "
    "y y))) with the recording GPU's float32 rsqrt (src/evaluator/hwmath.h); decode(c) = "
    "normalise(2c - 1, z clamped to >= 0); reoriented(b, d): t = b + (0, 0, 1), u = d (-1, -1, "
    "1), e = fma(t.z, u.z, fma(t.y, u.y, t.x u.x)), r = (fma(t.x, e, -(u.x t.z)), fma(t.y, e, "
    "-(u.y t.z)), t.z (e - u.z)) (fma: the exact product plus z in double, rounded to float32). "
    "Normal_OpenGL = UNORM16(fma(n, 1/2, 1/2)); Normal_DirectX negates n.y first. UNORM16(e): e "
    "truncated to 20 fractional bits, then the nearest code, ties down."
)


def _method_entry(ctx: Context, method: str) -> dict[str, Any]:
    if method == "Sharp":
        vector = "Sharp: v = (h(-1, 0) - h(0, 0), h(0, 0) - h(0, -1), 0.390625) in float32."
        ident, label = "height-normal-sharp", "Sharp (the default)"
        z = parameter("z", SHARP_Z, "fitted", "at 256 texels (1 / 2.56)")
    else:
        vector = (
            "Smooth (Sobel): v = (L - R, B - T, 3.125), L = (h(-1,-1) + 2 h(-1,0)) + h(-1,1), "
            "R = (h(1,-1) + 2 h(1,0)) + h(1,1), T = (h(-1,-1) + 2 h(0,-1)) + h(1,-1), B = "
            "(h(-1,1) + 2 h(0,1)) + h(1,1), each sum in float32 in this order."
        )
        ident, label = "height-normal-sobel", "Smooth (Sobel)"
        z = parameter("z", SOBEL_Z, "fitted", "at 256 texels (8 / 2.56)")
    return entry(
        ident,
        f"Normal_OpenGL and Normal_DirectX virtual maps from the Height channel, method {label}",
        f"{STENCILS} {vector} {COMBINATION}",
        SOURCES,
        [
            z,
            parameter(
                "difference_kernel", "backward" if method == "Sharp" else "sobel_3x3", "fitted"
            ),
            parameter("truncation_bits", 16 + EXTRA_BITS, "fitted", "fractional bits"),
            parameter("resolution", RESOLUTION, "authored", "px"),
            parameter("hardware_tables", "src/evaluator/tables/hw-rsqrt.zlib", "fitted"),
        ],
        _method_residuals(ctx, method),
        notes="Every r1 map, and every r2 map that equals its r1 (plane-strength s1 and s4 "
        "differ after save and reopen: height-normal-save-reopen-divergence). Domains: the plane "
        "grids compare the whole image, borders included (the wrap-around is exercised there); "
        "the sphere and the bevelled cube their UV coverage eroded by one texel (58816 and 51040 "
        "texels; outside it the export holds padding). The amplitude sweep stands in for a "
        "strength setting Painter 12.1.5 does not have (decision 047): the vector is linear in "
        "the height, with no other scale. Search (decisions 064): (-k dx, k dy, 1), k = 2.56, "
        "leaves 600+ texels one code off over the sweep; one normalisation of v alone 657, "
        "reoriented onto the flat normal with v as detail only (rnm(F, H)) 655 and with H as "
        "base only (rnm(H, F)) 359; the two reorientations leave none. For Sobel the float32 "
        "summation order is not separated by the goldens (an exact sum and this order both "
        "match every texel); this order is the implemented convention. The scale is recorded at "
        "256 texels only: other resolutions are a gap (height-normal-resolution-scaling).",
    )


def _readout_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-height-readout",
        "The Height channel's read-out (EXR export) of the amplitude sweep and the meshes",
        "The exported Height is the read-out of height-normal-sharp written half toward zero: "
        "a bitmap fill stores half toward zero of float32(2 t) - 1, t = float32(code / 65535); "
        "a fill at opacity a over the transparent start keeps its colour and the coverage "
        "half(a); LinearDodge copies over a covered accumulator add, the sum written half "
        "toward zero; the read-out fma(C - 0, a, 0) is written half toward zero.",
        [
            source(
                "A-PYDOC", "layerstack: insert_fill, FillLayerNode.set_source, Node.set_opacity"
            ),
            SOURCES[4],
        ],
        [parameter("storage", "L16F", "fitted")],
        _height_residuals(ctx),
        notes="Every r1 export and every r2 export that equals its r1 (whole image on the plane "
        "grids, eroded UV coverage on the meshes). LinearDodge on Height: s5-s7 of the sweep and "
        "s3 of plane-amplitudes.",
    )


def _divergence_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-save-reopen-divergence",
        "r2 of the amplitude sweep at opacity 0.75 and 0.1 (after save and reopen)",
        "Not a fit target (decision 032: r1 is the exact target; parity/exceptions.json EXC-003). "
        "After save and reopen Painter's Height export and both virtual maps of plane-strength s1 "
        "(opacity 0.75) and s4 (opacity 0.1) differ from r1 for both methods; the model, exact on "
        "r1, is compared here with both recordings.",
        [source("A-PYDOC", "project.save, project.open")],
        [],
        _method_residuals(ctx, "Sharp", unstable=True)
        + _method_residuals(ctx, "SmoothSobel", unstable=True)
        + _height_residuals(ctx, unstable=True),
        notes="The opacity read back after the reopen equals r1's, so the difference is in "
        "Painter's evaluation after the reopen. Neither the reopened Height export as the stencil "
        "input nor one opacity for every texel explains r2 (searched: 40 112 and 27 064 values "
        "off on s1). The read-out at 0.75 and 0.1 is the only case where the pre-write value is "
        "off the half grid.",
    )


def _normal_channel_entry(ctx: Context) -> dict[str, Any]:
    golden = ctx.golden(NORMAL_CHANNEL)
    residuals = []
    for texture_set in ("s0", "s1", "s2", "s3"):
        for recording in RECORDINGS:
            stored = golden.map(recording, f"{texture_set}/normal").values.astype(F32)
            channel = (stored[..., 0], stored[..., 1], stored[..., 2])
            predicted = normal_maps(np.zeros(stored.shape[:2], F32), "Sharp", channel)[
                "Normal_OpenGL"
            ]
            recorded = golden.map(recording, f"{texture_set}/Normal_OpenGL").values
            residuals.append(
                residual(
                    golden.golden_id,
                    f"{texture_set}/Normal_OpenGL",
                    recording,
                    UNIT["export16"],
                    difference(predicted, recorded),
                )
            )
    return entry(
        "height-normal-normal-channel",
        "The Normal channel in the virtual map: the last detail of the combination",
        "With a flat Height, Normal_OpenGL = UNORM16(fma(n, 1/2, 1/2)), n = normalise(reoriented("
        "A, decode(C))), A = normalise(reoriented(F, normalise(0, 0, 0.390625))), C the Normal "
        "channel read-out (here its exported RGB16F value: full coverage, so the read-out over "
        "the flat colour is that value). The channel stores an imported normal map as (r, 65535 - "
        "g, b) / 65535 written half toward zero (blend-modes.json blend-normal-channel-import).",
        SOURCES[2:],
        [parameter("detail_slot", "Normal channel", "fitted")],
        residuals,
        notes="The channel as the first base instead (reoriented(C, H)) leaves 180-192 values per "
        "set one code off. An empty Normal channel exports its base float32(127/255) yet acts as "
        "exactly flat (the height goldens): the virtual map composites the channel over (0.5, "
        "0.5, 1), a rule that also covers full coverage; partial coverage is not recorded "
        "(height-normal-unrecorded-inputs).",
    )


NORMAL_BASE = (127.0 / 255.0, 127.0 / 255.0, 1.0)


def _normal_channel_base(ctx: Context) -> dict[str, Any]:
    residuals = []
    base = np.asarray(NORMAL_BASE, F32).astype(F64)
    for name, (sets, _) in GOLDENS.items():
        golden = ctx.golden(name)
        for texture_set in sets:
            fmt = channel_format(golden, texture_set, "normal")
            for recording in RECORDINGS:
                exported = golden.map(recording, f"{texture_set}/normal").values
                stored = to_storage(ctx, exported, fmt)
                predicted = np.broadcast_to(base, stored.shape)
                residuals.append(
                    residual(
                        golden.golden_id,
                        f"{texture_set}/normal",
                        recording,
                        UNIT[fmt],
                        difference(predicted, stored),
                    )
                )
    return entry(
        "height-normal-default-normal-channel-base",
        "Empty Normal channel (no layer) exported as OpenEXR 32f: its base value",
        "Every texel = (float32(127/255), float32(127/255), 1.0): the 8-bit flat normal code "
        "(127, 127, 255) read as UNORM8, not a half value of the RGB16F storage. The virtual maps "
        "read this empty channel as the flat normal (0, 0, 1) (height-normal-normal-channel).",
        [source("A-HELP-EXPORT", "Export: document channel maps"), SOURCES[4]],
        [parameter("base", list(NORMAL_BASE), "fitted", "UNORM8 code / 255")],
        residuals,
        notes="Compared over the whole image (the channel holds no layer, padding included).",
    )


def _gaps() -> list[dict[str, Any]]:
    request = (
        " Recording request: parity/reports/phase1/compositor-height-normal.md §5 "
        "(task phase1.12_compositor-height-normal)."
    )
    return [
        entry(
            "height-normal-mesh-normal-map",
            "A Normal mesh map in the virtual maps and the geometry-only pass-through",
            "Not recorded. No golden binds a Normal mesh map (baked or imported) next to the "
            "virtual maps. By elimination its slot would be F, the first base under the height "
            "normal; the evaluator refuses a bound Normal mesh map in the combined maps "
            "(unsupported_source) and passes the map through unchanged (codes as UNORM operands, "
            "green inverted for the other convention as Painter's DirectX bake is the inverted "
            "OpenGL bake, tangent-frame.json) for the geometry-only source." + request,
            [
                source(
                    "A-HELP-EXPORT",
                    "Export: virtual maps Normal_OpenGL / Normal_DirectX; meshMap normal_base",
                )
            ],
            [],
            [],
            gap=True,
        ),
        entry(
            "height-normal-resolution-scaling",
            "The height-to-normal scale at set resolutions other than 256",
            "Not recorded. Every height-normal golden is 256 x 256: whether z (0.390625, 3.125) is "
            "fixed per texel or scales with the resolution (a UV-space gradient, z = 100 / "
            "width) is not separable. The evaluator refuses other resolutions (unsupported_source)."
            + request,
            [SOURCES[0]],
            [],
            [],
            gap=True,
        ),
        entry(
            "height-signed-addition",
            "SignedAddition on the Height channel",
            "Not recorded. The blend-kernels fit of SignedAddition (r = (a + 2b) - 1) comes from "
            "UNORM and float colour channels; no golden blends Height in SignedAddition, so its "
            "behaviour on the signed channel (range, clamp, base 0) is unobserved. The evaluator "
            "applies the kernel as on any float channel." + request,
            [source("A-PYDOC", "BlendingMode.SignedAddition")],
            [],
            [],
            gap=True,
        ),
        entry(
            "height-normal-unrecorded-inputs",
            "Normal-channel coverage, DirectX projects and 8-bit Normal imports",
            "Not recorded: a Normal-channel layer at partial coverage (the composite over the flat "
            "colour is a hypothesis that covers the empty and the fully covered channel), a "
            "non-empty Normal channel or a Normal-channel bitmap in a DirectX project (refused, "
            "unsupported_source), and 8-bit normal maps imported into the Normal channel (the "
            "green inversion applied by analogy)." + request,
            [source("A-HELP-GUIDE", "Project configuration: normal map format")],
            [],
            [],
            gap=True,
        ),
    ]


def fit(ctx: Context) -> dict[str, Any]:
    entries = [
        _method_entry(ctx, "Sharp"),
        _method_entry(ctx, "SmoothSobel"),
        _normal_channel_entry(ctx),
        _readout_entry(ctx),
        _normal_channel_base(ctx),
        _divergence_entry(ctx),
        *_gaps(),
    ]
    corpus = [ctx.golden(name).golden_id for name in GOLDENS] + [
        ctx.golden(NORMAL_CHANNEL).golden_id
    ]
    return document(
        "height-to-normal",
        "Height to normal for both methods of Painter 12.1.5 (Sharp, Smooth (Sobel)) and the "
        "virtual normal maps Normal_OpenGL / Normal_DirectX: the stencils on the Height read-out, "
        "the reoriented combination with the Normal channel, the encoding to 16 bits, fitted on "
        "the Tier 0 height-normal goldens and blend-normal-channel.",
        corpus,
        entries,
        painter_build=ctx.painter_build,
    )
