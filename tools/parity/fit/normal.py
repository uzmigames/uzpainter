"""Height-to-normal fit of the project's default method (`parity/semantics/height-to-normal.json`).

Goldens: `height-normal-plane-amplitudes` (grid2x2: the authored height ramps at layer opacity
1, 0.5, 0.25 and doubled by a second fill in LinearDodge), `height-normal-sphere` and
`height-normal-bevelled-cube` (opacity 1). Each exports the `Normal_OpenGL` and
`Normal_DirectX` virtual maps (PNG 16) and the Height and Normal channels (OpenEXR 32f). The
model reads the stored height (the exported Height channel) and predicts both virtual maps.
Candidates: finite-difference bump mapping (P-PBRT), the OpenGL/DirectX normal map formats of
the project settings (A-HELP-GUIDE) and the float-to-UNORM conversion (X-D3D12). The second
height-to-normal method and the strength sweep cannot be set through the API; they are
recorded by `phase0.7_tier0-semantics-ui-cases` and published here as a gap.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility.compare import erode, rasterise_uv
from tools.parity.feasibility.fixtures import Mesh
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
SCALE = 2.56  # gradient scale per texel difference of stored height (fitted at 256 px)
EXTRA_BITS = 4  # fractional bits kept below the target code before the final rounding

PLANE = "semantics/height-normal-plane-amplitudes"
SPHERE = "semantics/height-normal-sphere"
CUBE = "semantics/height-normal-bevelled-cube"
# golden -> texture sets, and whether the comparison domain is the whole image
GOLDENS: dict[str, tuple[tuple[str, ...], bool]] = {
    PLANE: (("s0", "s1", "s2", "s3"), True),
    SPHERE: (("uzp_sphere",), False),
    CUBE: (("uzp_bevelled_cube",), False),
}
SOURCES = [
    source("P-PBRT", "Bump mapping: displacement gradient by finite differences"),
    source("A-HELP-GUIDE", "Project configuration: normal map format (OpenGL / DirectX)"),
    source("X-D3D12", "Data conversion rules: FLOAT to UNORM"),
]

# --- Model ------------------------------------------------------------------------------------


def unorm(value: Array, bits: int) -> Array:
    """Float in [0, 1] to an n-bit UNORM code as observed: the value is truncated to n + 4
    fractional bits, then rounded to the nearest code with ties down (integer arithmetic)."""
    shift = bits + EXTRA_BITS
    top = (1 << bits) - 1
    grid = np.floor(np.clip(np.asarray(value, np.float64), 0.0, 1.0) * float(1 << shift))
    j = grid.astype(np.int64)
    result: Array = (j * top + (1 << (shift - 1)) - 1) >> shift
    return result


def height_normal(height: Array, scale: float = SCALE) -> tuple[Array, Array, Array]:
    """Tangent-space normal (x right, y up, z out) of a height image (rows top first), float32.

    Backward differences in image index space with wrap-around at the image borders:
    dx = h[r, c] - h[r, c-1], dy = h[r, c] - h[r-1, c]; n = normalize(-k dx, k dy, 1).
    """
    h = np.asarray(height, np.float64)
    f32 = np.float32
    dx = (h - np.roll(h, 1, axis=1)).astype(f32)
    dy = (h - np.roll(h, 1, axis=0)).astype(f32)
    k = f32(scale)
    nx, ny = -k * dx, k * dy
    length2 = nx * nx + ny * ny + f32(1)
    inverse = (1.0 / np.sqrt(length2.astype(np.float64))).astype(f32)
    return nx * inverse, ny * inverse, np.ones_like(nx) * inverse


def encode(component: Array) -> Array:
    """n * 0.5 + 0.5 in float32, then the 16-bit UNORM conversion."""
    half = np.float32(0.5)
    return unorm(np.asarray(component, np.float32) * half + half, 16)


def normal_maps(height: Array) -> dict[str, Array]:
    """The 16-bit `Normal_OpenGL` and `Normal_DirectX` codes (h, w, 3) of a stored height."""
    nx, ny, nz = height_normal(height)
    x, z = encode(nx), encode(nz)
    return {
        "Normal_OpenGL": np.stack([x, encode(ny), z], axis=-1),
        "Normal_DirectX": np.stack([x, encode(-ny), z], axis=-1),
    }


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
        np.asarray(uvs, np.float64),
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

    if GOLDENS[name][1]:
        return None
    cached = ctx.cached(f"uv-domain/{name}")
    if cached is None:
        obj = fixtures.sphere() if name == SPHERE else fixtures.bevelled_cube()
        cached = ctx.remember(f"uv-domain/{name}", uv_domain(obj))
    domain: npt.NDArray[np.bool_] = cached
    return domain


# --- Entries ----------------------------------------------------------------------------------


def _map_residuals(ctx: Context, map_name: str) -> list[dict[str, Any]]:
    residuals = []
    for name, (sets, _) in GOLDENS.items():
        golden = ctx.golden(name)
        domain = _domain(ctx, name)
        for texture_set in sets:
            for recording in RECORDINGS:
                height = golden.map(recording, f"{texture_set}/height").values[:, :, 0]
                predicted = normal_maps(height)[map_name]
                recorded = golden.map(recording, f"{texture_set}/{map_name}").values
                residuals.append(
                    residual(
                        golden.golden_id,
                        f"{texture_set}/{map_name}",
                        recording,
                        UNIT["export16"],
                        difference(predicted, recorded, domain),
                    )
                )
    return residuals


FORMULA = (
    "Input: the stored height h of the Height channel (L16F; the bitmap code c maps to about "
    "(2c/65535 - 1) times the layer opacity). In image index space (row 0 is the top row, v "
    "up), with wrap-around at the texture borders: dx = h[r,c] - h[r,c-1], dy = h[r,c] - "
    "h[r-1,c] (backward differences, one texel). n = normalize(-k dx, k dy, 1), k = 2.56 per "
    "unit of height difference at 256 px, computed in float32 (normalize = v * rsqrt(dot(v, "
    "v)), rsqrt correctly rounded). Encoding: e = n * 0.5 + 0.5 in float32 for x, y and z. "
    "16-bit code = UNORM16(e): e is truncated to 20 fractional bits (j = floor(e * 2^20)), then "
    "code = floor((j * 65535 + 2^19 - 1) / 2^20), the nearest code with ties down (the 0.5 "
    "of a flat normal's x and y rounds down). No clamp is needed (e is in [0, 1])."
)


def _opengl(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-default-opengl",
        "Normal_OpenGL virtual map from the Height channel, project default method and strength",
        FORMULA + " Normal_OpenGL writes (x, y, z) as RGB (y up).",
        SOURCES,
        [
            parameter("gradient_scale", SCALE, "fitted", "per unit height difference at 256 px"),
            parameter("difference_kernel", [-1, 1], "fitted", "previous texel, current texel"),
            parameter("truncation_bits", 16 + EXTRA_BITS, "fitted", "fractional bits"),
            parameter("resolution", RESOLUTION, "authored", "px"),
        ],
        _map_residuals(ctx, "Normal_OpenGL"),
        notes="Domains: the grid2x2 sets (one quad, full 0-1 UVs) compare the whole image, "
        "borders included (the wrap-around is exercised there); the sphere and the bevelled "
        "cube compare their UV coverage eroded by one texel (58816 and 51040 texels); outside "
        "it the export holds padding. Inside the coverage the stored height of the sphere and "
        "cube equals that of the plane at opacity 1, so the normal is computed in texture space "
        "only (mesh geometry, UV seams and island borders do not enter except through padding "
        "read at island edges). Search: forward, central, Sobel-like mixed kernels miss by "
        "thousands of codes; the backward one-texel difference with k = 2.56 leaves only +-1 "
        "code; k = 2.56 * (1 +- 0.001) gives about 25000 differing values per set. Plain "
        "round-to-nearest leaves 1600-2700 values per set 1 code high at fractions 0.5-0.56; "
        "truncation to 20 bits before rounding removes them. Remaining +-1 code values (tens "
        "per set) sit within 0.06 of a 2^-20 step: float32 rounding of the GPU's rsqrt and "
        "multiply order. The scale is fitted at one resolution: whether it is 0.01 x "
        "resolution (a UV-space gradient) or fixed per texel is not separable here. The empty "
        "Normal channel (base 127/255, 127/255, 1) does not tilt the result: it acts as (0, 0, 1).",
    )


def _directx(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-default-directx",
        "Normal_DirectX virtual map: the OpenGL normal with the green (y) component negated",
        FORMULA + " Normal_DirectX writes (x, -y, z): the y component is negated in float32 "
        "before the encoding.",
        SOURCES,
        [
            parameter("gradient_scale", SCALE, "fitted", "per unit height difference at 256 px"),
            parameter("green_sign", -1, "public_documentation"),
            parameter("truncation_bits", 16 + EXTRA_BITS, "fitted", "fractional bits"),
        ],
        _map_residuals(ctx, "Normal_DirectX"),
        notes="R and B equal those of Normal_OpenGL in every recorded texel. Domains as in "
        "height-normal-default-opengl (whole image for grid2x2, eroded UV coverage for the "
        "sphere and the bevelled cube).",
    )


NORMAL_BASE = (127.0 / 255.0, 127.0 / 255.0, 1.0)


def _normal_channel(ctx: Context) -> dict[str, Any]:
    residuals = []
    base = np.asarray(NORMAL_BASE, np.float32).astype(np.float64)
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
        "(127, 127, 255) read as UNORM8, not a half value of the RGB16F storage. The height "
        "normal of the virtual maps treats this base as the flat normal (0, 0, 1).",
        [source("A-HELP-EXPORT", "Export: document channel maps"), SOURCES[2]],
        [parameter("base", list(NORMAL_BASE), "fitted", "UNORM8 code / 255")],
        residuals,
        notes="Compared over the whole image (the channel holds no layer, padding included).",
    )


def _gap() -> dict[str, Any]:
    return entry(
        "height-normal-second-method-and-strength",
        "Second height-to-normal method and the strength sweep (moved to a UI-recorded task)",
        "Not fitted here. The height-to-normal method and its strength are project or shader "
        "settings the Python API can neither set nor read; the owner moved the second method "
        "and the strength sweep to phase0.7_tier0-semantics-ui-cases (recorded through "
        "Painter's UI, decision 029). Until that task records them they are release gaps.",
        [source("A-HELP-GUIDE", "Project configuration: height and normal settings")],
        [],
        [],
        gap=True,
    )


def fit(ctx: Context) -> dict[str, Any]:
    entries = [_opengl(ctx), _directx(ctx), _normal_channel(ctx), _gap()]
    corpus = [ctx.golden(name).golden_id for name in GOLDENS]
    return document(
        "height-to-normal",
        "Height to normal with the project's default method: finite-difference kernel, scale, "
        "border handling, encoding to 16-bit and the OpenGL/DirectX green flip, fitted on the "
        "Tier 0 height-normal goldens.",
        corpus,
        entries,
    )
