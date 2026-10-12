"""Height-to-normal and the virtual normal maps (`parity/semantics/height-to-normal.json`).

Goldens of the current envelope (decision 037): the UI-set method goldens of
`phase0.7_tier0-semantics-ui-cases` (decision 047: `Sharp` and `Smooth (Sobel)` on the sphere, the
bevelled cube and a 4x2 plane grid whose sets sweep the height amplitude: opacity 1, 0.75, 0.5,
0.25, 0.1 and 2, 3, 4 copies in LinearDodge), the default-method goldens (`height-normal-*`, which
explicit `Sharp` reproduces byte for byte) and `blend-normal-channel` (normal maps in the Normal
channel, empty Height, Normal_OpenGL exported). Each exports `Normal_OpenGL` and `Normal_DirectX`
(PNG 16) and the Height and Normal channels (OpenEXR 32f). The recordings of decision 077 add a
Normal mesh map in OpenGL and DirectX projects, SignedAddition on Height, Normal-channel coverage,
8- and 16-bit Normal imports in both conventions and the amplitude sweep at 512, 1024 and 2048 px.

The model (implemented by `src/evaluator/height_to_normal.cpp` operation for operation, decisions
064, 065 and 079) reads the Height channel's read-out before its write rule, rebuilt here from the
authored bitmaps and the recorded layer sequence with the evaluator's composite (`arith.h`), the
Normal channel's root list from a transparent start (colour and coverage) and the bound Normal mesh
map. Candidates: finite-difference bump mapping (P-PBRT), the Sobel operator (P-SOBEL), reoriented
normal mapping (P-BARRE), the OpenGL/DirectX formats (A-HELP-GUIDE) and the float-to-UNORM
conversion (X-D3D12); the reciprocal square root, reciprocal, square root, sine, cosine and
arccosine are the recording GPU's (`tools/parity/fit/hwmath.py`).
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
# The recordings of decision 077: golden -> texture sets.
MESH_MAP = (f"{DEFAULT}-mesh-map", f"{DEFAULT}-mesh-map-directx")
SIGNED_ADDITION = "semantics/height-signed-addition"
COVERAGE = f"{DEFAULT}-channel-coverage"
IMPORTS = ("semantics/normal-channel-import", "semantics/normal-channel-import-directx")
RESOLUTIONS = tuple(f"{DEFAULT}-resolution-{w}" for w in ("512", "1024", "1024-sobel", "2048"))
RECORDED_SETS: dict[str, tuple[str, ...]] = {
    MESH_MAP[0]: PLANE_SETS,
    MESH_MAP[1]: PLANE_SETS[:4],
    SIGNED_ADDITION: PLANE_SETS,
    COVERAGE: PLANE_SETS,
    IMPORTS[0]: PLANE_SETS[:4],
    IMPORTS[1]: PLANE_SETS[:4],
    **{name: PLANE_SETS[:4] for name in RESOLUTIONS},
}
FLAT = np.asarray([0.5, 0.5, 1.0], np.float32)  # the Normal channel's read-out base
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


def height_vector(h: Array, method: str, width: int = RESOLUTION) -> Vec:
    """The height-derived vector of `method` per texel (rows top first, wrap-around); z is a
    UV-space gradient, SHARP_Z or SOBEL_Z times 256 / the set's `width`."""
    h = np.asarray(h, F32)
    scale = F32(RESOLUTION / width)

    def at(dx: int, dy: int) -> Array:  # at(dx, dy)[r, c] = h[r + dy, c + dx]
        shifted: Array = np.roll(np.roll(h, -dy, axis=0), -dx, axis=1)
        return shifted

    if method == "Sharp":
        return at(-1, 0) - h, h - at(0, -1), np.full_like(h, F32(SHARP_Z) * scale)
    two = F32(2)
    left = (at(-1, -1) + two * at(-1, 0)) + at(-1, 1)
    right = (at(1, -1) + two * at(1, 0)) + at(1, 1)
    top = (at(-1, -1) + two * at(0, -1)) + at(1, -1)
    bottom = (at(-1, 1) + two * at(0, 1)) + at(1, 1)
    return left - right, bottom - top, np.full_like(h, F32(SOBEL_Z) * scale)


def unorm(value: Array, bits: int) -> Array:
    """Float in [0, 1] to an n-bit UNORM code as observed: the value is truncated to n + 4
    fractional bits, then rounded to the nearest code with ties down (integer arithmetic)."""
    shift = bits + EXTRA_BITS
    top = (1 << bits) - 1
    grid = np.floor(np.clip(np.asarray(value, F64), 0.0, 1.0) * float(1 << shift))
    j = grid.astype(np.int64)
    result: Array = (j * top + (1 << (shift - 1)) - 1) >> shift
    return result


def channel_normal(colour: Vec, coverage: Array) -> Vec:
    """The Normal channel's normal C of its root-list colour X and coverage a: flat at a = 0,
    decode(X) at a = 1, else u = decode(X rcp(a)) turned toward (0, 0, 1) by a, (u.x k, u.y k,
    cos(t)) with t = a acos(z), z = u.z clamped to [0, 1], k = sin(t) rsqrt(fma(-z, z, 1)), every
    function the recording GPU's (kept as u where z = 1)."""
    a = np.asarray(coverage, F32)
    partial = a < F32(1)
    inverse = hwmath.rcp(np.where(a > 0, a, F32(1)))
    x, y, zc = (
        np.where(partial, (np.asarray(c, F32) * inverse).astype(F32), np.asarray(c, F32))
        for c in colour
    )
    u = decode((x, y, zc))
    z = np.clip(u[2], F32(0), F32(1))
    w = fma(-z, z, np.ones_like(z))
    turn = partial & (w > 0)
    t = (a * hwmath.acos(z)).astype(F32)
    k = (hwmath.sin(t) * hwmath.rsqrt(np.where(w > 0, w, F32(1)))).astype(F32)
    none = ~(a > 0)
    return (
        np.where(none, F32(0), np.where(turn, u[0] * k, u[0])),
        np.where(none, F32(0), np.where(turn, u[1] * k, u[1])),
        np.where(none, F32(1), np.where(turn, hwmath.cos(t), u[2])),
    )


def normal_maps(
    height: Array,
    method: str = "Sharp",
    channel: Vec | None = None,
    *,
    coverage: Array | None = None,
    mesh: Vec | None = None,
    mesh_directx: bool = False,
    width: int = RESOLUTION,
) -> dict[str, Array]:
    """The 16-bit `Normal_OpenGL` and `Normal_DirectX` codes (h, w, 3) of a height read-out, the
    Normal channel's root-list colour `channel` at `coverage` (full when None; the flat colour
    when `channel` is None) and the Normal mesh map's operands `mesh` (flat when None; its y
    negated with `mesh_directx`), on a set `width` texels wide."""
    h = np.asarray(height, F32)
    flat = (np.zeros_like(h), np.zeros_like(h), np.ones_like(h))
    if channel is None:
        channel = (np.full_like(h, F32(0.5)), np.full_like(h, F32(0.5)), np.ones_like(h))
    first = flat
    if mesh is not None:
        first = decode(mesh)
        if mesh_directx:
            first = (first[0], -first[1], first[2])
    base = normalise(reoriented(first, normalise(height_vector(h, method, width))))
    detail = decode(channel) if coverage is None else channel_normal(channel, coverage)
    n = normalise(reoriented(base, detail))
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


def signed_texels(codes: Array) -> Array:
    """The signed value float32(float32(2 t) - 1) of each 16-bit code, t = float32(code / 65535)."""
    t = (np.asarray(codes, F64) / 65535.0).astype(F32)
    out: Array = F32(2) * t - F32(1)
    return out


def height_content(codes: Array, width: int = RESOLUTION) -> Array:
    """The stored content of a bitmap fill on Height at a `width` px set: half toward zero of the
    signed texels (colour-transfer.json, bitmap-height-signed), magnified by the default
    projection (the signed values are filtered, `magnified`)."""
    return half_toward_zero(magnified(signed_texels(codes), width))


Source = tuple[str, Any]  # ("bitmap", input id) or ("uniform", colour)


class Fill:
    """One fill layer of a recorded sequence on one channel: mode, opacity, source and mask (None,
    or the bitmap input of the single fill effect of a Black mask)."""

    def __init__(self, mode: str, opacity: float, source: Source | None, mask: str | None) -> None:
        self.mode, self.opacity, self.source, self.mask = mode, opacity, source, mask


def fills(manifest: dict[str, Any], texture_set: str, channel: str) -> list[Fill]:
    """The fills of `texture_set` whose active channels include `channel` (every channel when the
    sequence does not restrict them), bottom-up (`position: top` inserts on top; `above_step`
    above that layer), with their mode, opacity and source on `channel` and their mask."""
    steps = manifest["instruction_sequence"]["steps"]
    imports = {
        s["step"]: s["args"].get("input")
        for s in steps
        if s["call"].endswith("import_project_resource")
    }
    order: list[int] = []
    owner: dict[int, str] = {}
    layer: dict[int, dict[str, Any]] = {}
    mask_of: dict[int, int] = {}  # mask effect step -> layer step
    for step in steps:
        call, args, n = step["call"], step["args"], step["step"]
        if call.endswith("layerstack.insert_fill"):
            if args.get("stack") == "Mask":
                mask_of[n] = args["inside_step"]
                continue
            if "above_step" in args:
                anchor = args["above_step"]
                owner[n] = owner[anchor]
                order.insert(order.index(anchor) + 1, n)
            else:
                owner[n] = str(args.get("texture_set", texture_set))
                order.append(n)
            layer[n] = {
                "mode": "Normal",
                "opacity": 1.0,
                "active": None,
                "source": None,
                "mask": None,
            }
        elif call.endswith("active_channels") and "channels" in args:
            layer[args["node_step"]]["active"] = list(args["channels"])
        elif call.endswith("set_source"):
            node = args["node_step"]
            source: Source = (
                ("bitmap", imports[args["resource_step"]])
                if "resource_step" in args
                else ("uniform", tuple(args["color"]))
            )
            if node in mask_of:
                layer[mask_of[node]]["mask"] = source[1]
            elif args.get("channel") in (channel, None):
                layer[node]["source"] = source
        elif call.endswith("Node.set_blending_mode") and args.get("channel") == channel:
            layer[args["node_step"]]["mode"] = args["blending_mode"]
        elif call.endswith("Node.set_opacity") and args.get("channel") == channel:
            layer[args["node_step"]]["opacity"] = float(args["opacity"])
    result = []
    for n in order:
        entry_ = layer[n]
        if owner[n] != texture_set or (
            entry_["active"] is not None and channel not in entry_["active"]
        ):
            continue
        result.append(Fill(entry_["mode"], entry_["opacity"], entry_["source"], entry_["mask"]))
    return result


def height_layers(manifest: dict[str, Any], texture_set: str) -> list[tuple[str, float]]:
    """The (mode, opacity) of the Height fills of `texture_set`, bottom-up (`fills`)."""
    return [(f.mode, f.opacity) for f in fills(manifest, texture_set, "Height")]


def stack_readout(contents: list[Array], layers: list[tuple[str, float]]) -> Array:
    """The Height read-out before the write rule: the layers (each with its content) composited
    bottom-up from a transparent start (colour and coverage written half toward zero after each
    layer; Normal r = b, LinearDodge r = a + b, SignedAddition r = (a + 2b) - 1, mixed as
    a (1 - alpha) + r alpha), then over the base 0 as fma(C - base, a, base) (arith::Composite,
    the fused read-out of profile painter-12.1-isolated-coverage-weights; over the base 0 it
    equals base + (C - base) a of the earlier profiles)."""
    colour: Array | None = None
    alpha = F32(0)
    for q_, (mode, opacity) in zip(contents, layers, strict=True):
        q = np.asarray(q_, F32)
        a = F32(opacity)
        if colour is None:  # over the transparent start: the source as it is
            colour = q.copy()
            alpha = half_toward_zero(np.asarray([a], F32))[0]
            continue
        if alpha != F32(1):
            raise ValueError("a layer over a partly covered Height is not modelled here")
        if mode == "Normal":
            r = q
        elif mode == "LinearDodge":
            r = colour + q
        elif mode == "SignedAddition":
            r = (colour + F32(2) * q) - F32(1)
        else:
            raise ValueError(f"{mode} on Height is not modelled here")
        colour = half_toward_zero(colour * (F32(1) - a) + r * a)
    if colour is None:
        return np.zeros(np.shape(contents[0]) if contents else (RESOLUTION, RESOLUTION), F32)
    return fma(colour, np.full_like(colour, alpha), np.zeros_like(colour))


def height_readout(content: Array, layers: list[tuple[str, float]]) -> Array:
    """`stack_readout` with every layer's content `content`."""
    if not layers:
        return np.zeros_like(np.asarray(content, F32))
    return stack_readout([content] * len(layers), layers)


def magnified(signed: Array, width: int) -> Array:
    """The signed texels of a 256 px bitmap sampled onto a `width` px set by the default UV
    projection (bilinear, repeat): texel centres x = (i + 1/2) 256 / width - 1/2, the dyadic
    weights applied to the signed values 2t - 1 exactly and rounded once to float32 (the
    evaluator's integer filter, projection_uv.h BilinearFilter, gives the same values here)."""
    s = np.asarray(signed, np.float64)
    n = s.shape[0]
    if width == n:
        return np.asarray(signed, F32)
    i = np.arange(width)
    x = (i + 0.5) * (n / width) - 0.5
    x0 = np.floor(x).astype(np.int64)
    f = x - x0
    rows = s[x0 % n, :] * (1 - f)[:, None] + s[(x0 + 1) % n, :] * f[:, None]
    out: Array = (rows[:, x0 % n] * (1 - f)[None, :] + rows[:, (x0 + 1) % n] * f[None, :]).astype(
        F32
    )
    return out


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


def _width(manifest: dict[str, Any]) -> int:
    """The project's set resolution (`project.create`), 256 when not stated."""
    for step in manifest["instruction_sequence"]["steps"]:
        if step["call"] == "substance_painter.project.create":
            return int(step["args"].get("default_texture_resolution", RESOLUTION))
    return RESOLUTION


def directx_project(manifest: dict[str, Any]) -> bool:
    for step in manifest["instruction_sequence"]["steps"]:
        if step["call"] == "substance_painter.project.create":
            return bool(step["args"].get("normal_map_format") == "DirectX")
    return False


def _bitmap(ctx: Context, manifest: dict[str, Any], input_id: str) -> tuple[Array, int]:
    """The codes (h, w, c) and the bit depth of an authored input of `manifest`."""
    from tools.parity.feasibility import png

    path = next(i["path"] for i in manifest["inputs"] if i["input_id"] == input_id)
    cached = ctx.cached(f"bitmap/{path}")
    if cached is None:
        data = (ctx.repository / path).read_bytes()
        cached = ctx.remember(f"bitmap/{path}", (png.decode(data).astype(np.int64), int(data[24])))
    codes, bits = cached
    return codes, bits


def _height_of(ctx: Context, manifest: dict[str, Any], fill: Fill, width: int) -> Array:
    """The stored content of a fill on Height: a bitmap's signed texels (`height_content`), a
    uniform colour the mean of its components written half toward zero."""
    if fill.source is None or fill.source[0] == "uniform":
        colour = (0.0, 0.0, 0.0) if fill.source is None else fill.source[1]
        mean = F32((float(F32(colour[0])) + float(F32(colour[1])) + float(F32(colour[2]))) / 3.0)
        return np.full((width, width), half_toward_zero(np.asarray([mean], F32))[0], F32)
    codes, _ = _bitmap(ctx, manifest, str(fill.source[1]))
    return height_content(codes[..., 0], width)


def _readout(ctx: Context, name: str, texture_set: str) -> Array:
    key = f"readout/{name}/{texture_set}"
    cached = ctx.cached(key)
    if cached is None:
        manifest = ctx.golden(name).manifest
        width = _width(manifest)
        layers = fills(manifest, texture_set, "Height")
        contents = [_height_of(ctx, manifest, f, width) for f in layers]
        readout_ = (
            stack_readout(contents, [(f.mode, f.opacity) for f in layers])
            if layers
            else np.zeros((width, width), F32)
        )
        cached = ctx.remember(key, readout_)
    readout: Array = cached
    return readout


def _normal_list(ctx: Context, name: str, texture_set: str) -> tuple[Vec, Array] | None:
    """The Normal channel's root list from a transparent start, colour X and coverage a, or None
    for an empty channel. One fill is modelled: a bitmap stores (r, max - g, b) / max, a uniform
    colour its value, written half toward zero; a = half toward zero of opacity x mask (a Black
    mask with a bitmap fill effect: its 16-bit code / 65535)."""
    manifest = ctx.golden(name).manifest
    layers = fills(manifest, texture_set, "Normal")
    if not layers:
        return None
    if len(layers) != 1 or layers[0].source is None or layers[0].mode != "Normal":
        raise ValueError(f"{name} {texture_set}: one Normal fill in Normal mode is modelled here")
    fill = layers[0]
    width = _width(manifest)
    assert fill.source is not None
    if fill.source[0] == "uniform":
        colour = half_toward_zero(np.asarray(fill.source[1], F32))
        x: Vec = tuple(np.full((width, width), c, F32) for c in colour)  # type: ignore[assignment]
    else:
        codes, bits = _bitmap(ctx, manifest, str(fill.source[1]))
        top = (1 << bits) - 1
        x = (
            half_toward_zero((codes[..., 0] / top).astype(F32)),
            half_toward_zero(((top - codes[..., 1]) / top).astype(F32)),
            half_toward_zero((codes[..., 2] / top).astype(F32)),
        )
    a = np.full((width, width), F32(fill.opacity), F32)
    if fill.mask is not None:
        mask, _ = _bitmap(ctx, manifest, str(fill.mask))
        a = (a * (mask[..., 0] / 65535.0).astype(F32)).astype(F32)
    return x, half_toward_zero(a)


def _mesh(ctx: Context, name: str) -> Vec | None:
    """The bound Normal mesh map's operands float32(code / 65535), or None."""
    manifest = ctx.golden(name).manifest
    steps = manifest["instruction_sequence"]["steps"]
    imports = {
        s["step"]: s["args"].get("input")
        for s in steps
        if s["call"].endswith("import_project_resource")
    }
    for step in steps:
        if (
            step["call"].endswith("TextureSet.set_mesh_map_resource")
            and step["args"]["usage"] == "Normal"
        ):
            codes, bits = _bitmap(ctx, manifest, str(imports[step["args"]["resource_step"]]))
            if bits != 16:
                raise ValueError("a 16-bit Normal mesh map is modelled here")
            return tuple((codes[..., c] / 65535.0).astype(F32) for c in range(3))  # type: ignore[return-value]
    return None


def _method_of(manifest: dict[str, Any], texture_set: str) -> str:
    """The texture set's method as the operator set it (Sharp when no settings-sheet entry)."""
    name = f"Texture Set Settings/Height to normal method ({texture_set})"
    for setting in manifest.get("applied_settings", []):
        if setting["name"] == name:
            return "SmoothSobel" if "Sobel" in str(setting["value"]) else "Sharp"
    return "Sharp"


def normal_export(
    colour: Vec | None, coverage: Array | None, directx: bool, shape: tuple[int, int]
) -> Array:
    """The exported Normal channel (OpenEXR 32f): an empty channel its template base
    float32(127/255, 127/255, 1) in both conventions; else the root list over the flat colour,
    half toward zero of fma(X - B, a, B), B = (0.5, 0.5, 1); a DirectX project's export inverts
    the stored green once more, half toward zero of 1 - g."""
    if colour is None or coverage is None:
        out: Array = np.broadcast_to(np.asarray(NORMAL_BASE, F32), (*shape, 3)).astype(F32)
        return out
    a = np.asarray(coverage, F32)
    e = [
        half_toward_zero(fma(np.asarray(c, F32) - FLAT[i], a, np.full_like(a, FLAT[i])))
        for i, c in enumerate(colour)
    ]
    if directx:
        e[1] = half_toward_zero(F32(1) - e[1])
    result: Array = np.stack(e, axis=-1)
    return result


def _recorded_residuals(
    ctx: Context, names: tuple[str, ...], unstable: bool = False
) -> list[dict[str, Any]]:
    """Residuals of every exported map of the decision-077 goldens `names` (`_selected`): the
    virtual maps, the Height and Normal channels and the Normal mesh map's export."""
    residuals = []
    for name in names:
        golden = ctx.golden(name)
        manifest = golden.manifest
        directx = directx_project(manifest)
        mesh = _mesh(ctx, name)
        for texture_set in RECORDED_SETS[name]:
            height = _readout(ctx, name, texture_set)
            listed = _normal_list(ctx, name, texture_set)
            colour, coverage = (None, None) if listed is None else listed
            predicted: dict[str, tuple[Array, str]] = {
                key: (value, UNIT["export16"])
                for key, value in normal_maps(
                    height,
                    _method_of(manifest, texture_set),
                    colour,
                    coverage=coverage,
                    mesh=mesh,
                    mesh_directx=directx,
                    width=height.shape[1],
                ).items()
            }
            predicted["height"] = (half_toward_zero(height).astype(F64), UNIT["L16F"])
            predicted["normal"] = (
                normal_export(colour, coverage, directx, height.shape).astype(F64),
                UNIT["RGB16F"],
            )
            if mesh is not None:
                codes = np.stack([np.rint(c.astype(F64) * 65535.0) for c in mesh], axis=-1).astype(
                    np.int64
                )
                predicted["normal_base"] = (codes, UNIT["export16"])
            for map_name, (values, unit) in predicted.items():
                key = f"{texture_set}/{map_name}"
                if key not in golden.maps("r1"):
                    continue
                stable = _stable(ctx, name, key)
                for recording in RECORDINGS:
                    if not _selected(stable, recording, unstable):
                        continue
                    recorded = golden.map(recording, key).values
                    if map_name == "height":
                        recorded = recorded[..., 0].astype(F64)
                    residuals.append(
                        residual(
                            golden.golden_id, key, recording, unit, difference(values, recorded)
                        )
                    )
    return residuals


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
    "H = normalise(v); A = normalise(reoriented(F, H)), F = (0, 0, 1) without a Normal mesh map "
    "(height-normal-mesh-normal-map); C = decode(X) of the Normal channel's root list X at full "
    "coverage, the flat normal for an empty channel (height-normal-channel-coverage); n = "
    "normalise(reoriented(A, C)). normalise(v) = v rsqrt(fma(z, z, fma(x, x, "
    "y y))) with the recording GPU's float32 rsqrt (src/evaluator/hwmath.h); decode(c) = "
    "normalise(2c - 1, z clamped to >= 0); reoriented(b, d): t = b + (0, 0, 1), u = d (-1, -1, "
    "1), e = fma(t.z, u.z, fma(t.y, u.y, t.x u.x)), r = (fma(t.x, e, -(u.x t.z)), fma(t.y, e, "
    "-(u.y t.z)), t.z (e - u.z)) (fma: the exact product plus z in double, rounded to float32). "
    "Normal_OpenGL = UNORM16(fma(n, 1/2, 1/2)); Normal_DirectX negates n.y first. UNORM16(e): e "
    "truncated to 20 fractional bits, then the nearest code, ties down."
)


def _method_entry(ctx: Context, method: str) -> dict[str, Any]:
    if method == "Sharp":
        vector = (
            "Sharp: v = (h(-1, 0) - h(0, 0), h(0, 0) - h(0, -1), 0.390625) in float32 (256 px)."
        )
        ident, label = "height-normal-sharp", "Sharp (the default)"
        z = parameter("z", SHARP_Z, "fitted", "at 256 texels (1 / 2.56)")
    else:
        vector = (
            "Smooth (Sobel): v = (L - R, B - T, 3.125) (256 px), L = (h(-1,-1) + 2 h(-1,0)) + "
            "h(-1,1), R = (h(1,-1) + 2 h(1,0)) + h(1,1), T = (h(-1,-1) + 2 h(0,-1)) + h(1,-1), B = "
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
        "match every texel); this order is the implemented convention. Other set sizes scale z "
        "as 256 / W (height-normal-resolution-scaling).",
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
        "exactly flat (the height goldens); partial coverage: height-normal-channel-coverage.",
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


RECORDED_NOTES = (
    "Every r1 map and every r2 map that equals its r1, whole image (the sets of a 4x2 or 2x2 "
    "plane grid). Exported Normal channel and mesh map included where the golden exports them."
)


def _mesh_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-mesh-normal-map",
        "A Normal mesh map in the virtual maps (OpenGL and DirectX projects, both methods)",
        "The bound Normal mesh map is F, the first base: F = decode(M), M = float32(code / 65535) "
        "of its 16-bit codes, its y negated when the map is in the DirectX convention (a map "
        "imported into a project takes the project's convention); A = normalise(reoriented(F, "
        "H)); n = normalise(reoriented(A, C)) as in height-normal-sharp. The exported mesh map "
        "(meshMap/normal_base) is the bitmap's codes unchanged in either project (the "
        "geometry-only pass-through in the map's own convention).",
        [
            SOURCES[2],
            source("A-PYDOC", "textureset.TextureSet.set_mesh_map_resource, MeshMapUsage.Normal"),
            source(
                "A-HELP-EXPORT",
                "Export: virtual maps Normal_OpenGL / Normal_DirectX; meshMap normal_base",
            ),
        ],
        [parameter("mesh_slot", "first base F", "fitted")],
        _recorded_residuals(ctx, MESH_MAP),
        notes=RECORDED_NOTES
        + " Search (decision 079): the mesh map after the height normal (reoriented(H, F)) leaves "
        "about 138 000 values off, after the Normal channel about 92 000, the codes passed through "
        "unchanged 3 072 values one code off on the mesh map alone. Recorded: 16-bit maps at the "
        "set resolution in the project's convention; other maps are refused "
        "(height-normal-unrecorded-inputs).",
    )


def _coverage_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-channel-coverage",
        "The Normal channel at partial coverage: its read-out and its normal in the virtual maps",
        "The channel's layers composite over the flat colour B = (0.5, 0.5, 1) (its read-out, "
        "exported: half toward zero of fma(X - B, a, B)), while an empty channel exports the "
        "template base 127/255 (height-normal-default-normal-channel-base). The virtual maps read "
        "the root list from a transparent start, colour X and coverage a = half toward zero of "
        "opacity x mask: C = (0, 0, 1) where a = 0, decode(X) where a = 1, else u = decode(X "
        "rcp(a)) turned toward (0, 0, 1) by a: (u.x k, u.y k, cos(t)), t = a acos(z), z = u.z "
        "clamped to [0, 1], k = sin(t) rsqrt(fma(-z, z, 1)); rcp, acos, sin, cos and rsqrt are the "
        "recording GPU's (the acos its Vulkan arccosine: 2 P(sqrt(fma(-1/2, z, 1/2))) for z > "
        "0.57, else float32(pi/2) - P(z), P the arcsine polynomial of hwmath.h).",
        [SOURCES[2], SOURCES[4], source("X-VULKAN", "GLSL.std.450 Acos on the recording GPU")],
        [
            parameter("readout_base", [0.5, 0.5, 1.0], "fitted"),
            parameter("division", "X rcp(a)", "fitted"),
        ],
        _recorded_residuals(ctx, (COVERAGE,)),
        notes=RECORDED_NOTES
        + " The division of a colour that is not premultiplied tilts a flat layer at opacity 1/2 "
        "toward +x +y. Search (decision 079): the read-out over 127/255 leaves 131 072 Normal "
        "values off; the virtual maps from the read-out thousands of values (up to 8 610 codes); "
        "t = pi/2 - asin(z) (the blend modes' rotation) 82 values one code off; IEEE X / a 78 "
        "(Normal_OpenGL) on the mask-coded set. The Vulkan arccosine was measured on 33 554 432 "
        "inputs over [-1, 1]. r2 of s2 differs from r1 "
        "(height-normal-coverage-save-reopen-divergence).",
    )


def _import_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-channel-import",
        "8- and 16-bit normal maps on the Normal channel of OpenGL and DirectX projects",
        "The channel stores an imported normal map as (r, max - g, b) / max written half toward "
        "zero in both conventions (8 and 16 bits); the virtual maps read that storage. A DirectX "
        "project's export of a non-empty Normal channel inverts the stored green again: half "
        "toward zero of 1 - g; an empty channel exports 127/255 in both.",
        [SOURCES[3], source("A-HELP-GUIDE", "Project configuration: normal map format")],
        [parameter("storage_convention", "OpenGL", "fitted")],
        _recorded_residuals(ctx, IMPORTS),
        notes=RECORDED_NOTES
        + " Feeding the virtual maps the DirectX export with y negated leaves 41 800 values up to "
        "20 codes off (mesh-map-directx s2). Recorded in DirectX projects: one bitmap fill in "
        "Normal mode at opacity 1; other stacks are refused (height-normal-unrecorded-inputs).",
    )


def _resolution_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-normal-resolution-scaling",
        "The height-to-normal scale and the magnified Height at 512, 1024 and 2048 px",
        "z is a UV-space gradient: 100 / W (Sharp) and 800 / W (Sobel) on a W px set. The Height "
        "bitmap is filtered as signed values: each texel 2t - 1 in float32 before the bilinear "
        "filter of the default projection (magnified(), projection_uv.h), then written half "
        "toward zero.",
        [SOURCES[0], SOURCES[1], source("A-HELP-GUIDE", "Texture Set Settings: size")],
        [
            parameter("z_sharp", "100 / W", "fitted"),
            parameter("z_sobel", "800 / W", "fitted"),
        ],
        _recorded_residuals(ctx, RESOLUTIONS),
        notes=RECORDED_NOTES
        + " Search (decision 079): z fixed at 0.390625 leaves about 428 000 (512) to 6.7 M (2048) "
        "values off; filtering t then taking 2v - 1 leaves 16 (512) to 462 (2048) Height values "
        "one half step off near 0. Recorded sizes only: 256, 512, 1024, 2048. r2 of 2048 s2 "
        "differs from r1 (height-normal-resolution-save-reopen-divergence).",
    )


def _signed_addition_entry(ctx: Context) -> dict[str, Any]:
    return entry(
        "height-signed-addition",
        "SignedAddition on the Height channel",
        "The blend kernel r = (a + 2b) - 1 on the signed Height (a bitmap stores 2t - 1, a uniform "
        "colour the mean of its components), mixed a (1 - alpha) + r alpha and written half toward "
        "zero (stack_readout); over the empty Height the first layer's content as it is.",
        [source("A-PYDOC", "BlendingMode.SignedAddition"), SOURCES[4]],
        [parameter("kernel", "(a + 2b) - 1", "fitted")],
        _recorded_residuals(ctx, (SIGNED_ADDITION,)),
        notes=RECORDED_NOTES,
    )


def _recorded_divergences(ctx: Context) -> list[dict[str, Any]]:
    return [
        entry(
            "height-normal-coverage-save-reopen-divergence",
            "r2 of height-normal-channel-coverage s2 (a mask-coded Normal fill, after save and "
            "reopen)",
            "Not a fit target (decision 032: r1 is the exact target; parity/exceptions.json "
            "EXC-004). After save and reopen Painter's Normal export and both virtual maps of s2 "
            "differ from r1; a second Painter process reproduced both recordings (decision 077). "
            "The model, exact on r1, is compared here with both recordings.",
            [source("A-PYDOC", "project.save, project.open")],
            [],
            _recorded_residuals(ctx, (COVERAGE,), unstable=True),
            notes="No coverage variant explains r2's Normal export (round to nearest half 110 508 "
            "values off, 8-bit coverage 122 174, the unquantised coverage 110 675).",
        ),
        entry(
            "height-normal-resolution-save-reopen-divergence",
            "r2 of height-normal-resolution-2048 s2 (opacity 0.25, after save and reopen)",
            "Not a fit target (decision 032: r1 is the exact target; parity/exceptions.json "
            "EXC-005). After save and reopen 4 and 5 values of the virtual maps of s2 differ from "
            "r1 by one code; a second Painter process reproduced both recordings (decision 077).",
            [source("A-PYDOC", "project.save, project.open")],
            [],
            _recorded_residuals(ctx, RESOLUTIONS, unstable=True),
            notes="r2 equals the stencils on the stored Height (written half toward zero) instead "
            "of the read-out before the write rule: at opacity 0.25 the values of the stored half "
            "near 0 are subnormal and truncated.",
        ),
    ]


def _gaps() -> list[dict[str, Any]]:
    return [
        entry(
            "height-normal-unrecorded-inputs",
            "Normal inputs and set sizes the recordings do not cover",
            "Not recorded, refused with unsupported_source (decision 079): a DirectX project's "
            "Normal channel other than one bitmap fill in Normal mode at opacity 1 without mask or "
            "effects (other modes, coverage, stacks, uniform colours); a Normal mesh map in the "
            "combination that is 8-bit, of another size or in the other convention; sets other "
            "than square 256, 512, 1024 or 2048 px. Modelled by the recorded rules but not "
            "recorded: Normal root lists of several layers at partial coverage (one rule for "
            "any root list), "
            "and the signed bilinear filter of the Height with non-dyadic weights (rotated or "
            "scaled projections; the recorded magnifications have dyadic weights).",
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
        _mesh_entry(ctx),
        _coverage_entry(ctx),
        _import_entry(ctx),
        _resolution_entry(ctx),
        _signed_addition_entry(ctx),
        *_recorded_divergences(ctx),
        *_gaps(),
    ]
    corpus = [ctx.golden(name).golden_id for name in (*GOLDENS, NORMAL_CHANNEL, *RECORDED_SETS)]
    return document(
        "height-to-normal",
        "Height to normal for both methods of Painter 12.1.5 (Sharp, Smooth (Sobel)) and the "
        "virtual normal maps Normal_OpenGL / Normal_DirectX: the stencils on the Height read-out, "
        "the reoriented combination with the Normal mesh map and the Normal channel (at any "
        "coverage, both conventions), the scale at 256 to 2048 px, the encoding to 16 bits, "
        "fitted on the Tier 0 height-normal goldens, blend-normal-channel and the recordings of "
        "decision 077.",
        corpus,
        entries,
        painter_build=ctx.painter_build,
    )
