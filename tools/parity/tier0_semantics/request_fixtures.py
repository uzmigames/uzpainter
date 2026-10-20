"""UzmiGames-authored fixtures of the Phase 1 recording requests (decision 100).

The recording plan of 2026-10-12 (R1-R8) merged with the phase1.16 request R-090
(`parity/reports/phase1/export-processing-encoders.md` section 5) needs meshes with separated UV
islands, slow ramps for dithering, an impulse texel, half-step codes, an 8-bit sRGB-tagged ramp
and the authored export configurations (`recipe_json`) of the literal export probes. Conventions
as in `fixtures.py`: OBJ in centimetres, +Y up; bitmap texel (x, y) is column x, row y from the
top row; a UV `(u, v)` covers texel column `u * N`, row `(1 - v) * N` of an N px texture.
"""

from __future__ import annotations

import decimal
import json
import math
import struct
import zlib
from fractions import Fraction
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.tier0_semantics.fixtures import (
    PROBE_PARAMETERS,
    PROBE_PRESET,
    Config,
    Pixel,
    code,
    fmt,
    obj,
    png16,
    probe_channel,
    probe_grey,
    probe_map,
    probe_rgb,
)

# --- Meshes with separated UV islands (R1, R-090 P9) -----------------------------------------

# Islands mesh, in texels of a 256 px texture, as (x0, x1, y0, y1) from the bottom-left of UV
# space: island 1 touches the tile's left border (u = 0), island 2 sits 1 texel to its right,
# island 3 3 texels to the right of island 2; island 4 (a square turned 30 degrees, so its borders
# cross texels diagonally) lies about 20 texels below islands 1 and 2. Borders sit off texel
# boundaries, so coverage is partial along every edge.
ISLANDS_TEXELS = 256.0
ISLAND_ROWS = (135.4, 231.6)
ISLAND_COLUMNS = ((0.0, 96.3), (97.3, 160.7), (163.7, 230.2))
ISLAND_GAPS = (1.0, 3.0)
TURNED_CENTRE = (110.0, 60.2)
TURNED_HALF = 40.0
TURNED_DEGREES = 30.0


def quad_obj_lines(
    corners: list[tuple[float, float, float]], uvs: list[tuple[float, float]], base: int
) -> tuple[list[str], list[str]]:
    """Vertex/UV lines and the two faces of one quad (corners counter-clockwise seen from +Y)."""
    data = [f"v {fmt(*p)}\n" for p in corners]
    data += [f"vt {fmt(*uv)}\n" for uv in uvs]
    a, b, c, d = (base + i for i in range(1, 5))
    return data, [f"f {a}/{a}/1 {b}/{b}/1 {c}/{c}/1\n", f"f {a}/{a}/1 {c}/{c}/1 {d}/{d}/1\n"]


def turned_square() -> list[tuple[float, float]]:
    """Island 4's UV corners (counter-clockwise), in texels."""
    cx, cy = TURNED_CENTRE
    angle = math.radians(TURNED_DEGREES)
    corners = []
    for sx, sy in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
        x, y = sx * TURNED_HALF, sy * TURNED_HALF
        corners.append(
            (
                cx + x * math.cos(angle) - y * math.sin(angle),
                cy + x * math.sin(angle) + y * math.cos(angle),
            )
        )
    return corners


def island_uvs() -> list[list[tuple[float, float]]]:
    """Every island's UV corners (counter-clockwise), in texels."""
    y0, y1 = ISLAND_ROWS
    rects = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for x0, x1 in ISLAND_COLUMNS]
    return [*rects, turned_square()]


def islands() -> bytes:
    """Four separate 10 cm quads in the XZ plane (normal +Y), one texture set `uzp_islands`,
    mapped to the four UV islands of `island_uvs`."""
    data: list[str] = ["vn 0.0 1.0 0.0\n"]
    faces: list[str] = []
    for index, corners in enumerate(island_uvs()):
        cx = index * 12.0
        quad = [
            (cx - 5.0, 0.0, 5.0),
            (cx + 5.0, 0.0, 5.0),
            (cx + 5.0, 0.0, -5.0),
            (cx - 5.0, 0.0, -5.0),
        ]
        uvs = [(x / ISLANDS_TEXELS, y / ISLANDS_TEXELS) for x, y in corners]
        lines, quad_faces = quad_obj_lines(quad, uvs, index * 4)
        data += lines
        faces += quad_faces
    return obj(
        "uzp_islands",
        "Four UV islands in one texture set: one on the tile's left border, gaps of 1 and 3 "
        "texels, one turned 30 degrees about 20 texels below (at 256 px).",
        [("uzp_islands", faces)],
        "".join(data),
    )


# Seam mesh (R-090 P9): quads A (x 0..10 cm) and B (x 10..20 cm) share the 3D edge x = 10 cm
# and two vertices, but map to two UV islands: A at scale 0.375 per 10 cm touching the tile's
# left border, B at scale 0.25 turned 90 degrees (x runs along v, z along u). The shared edge is
# A's right border (u = 0.375) and B's bottom border (v = 0.6).
SEAM_A = {"u0": 0.0, "v0": 0.1, "scale": 0.375}
SEAM_B = {"u0": 0.55, "v0": 0.6, "scale": 0.25}
SEAM_SIDE_COLUMN = 128  # the side mask is white from this texel column on (B's side)


def seam_uv_a(x: float, z: float) -> tuple[float, float]:
    return (SEAM_A["u0"] + SEAM_A["scale"] * x / 10.0, SEAM_A["v0"] + SEAM_A["scale"] * z / 10.0)


def seam_uv_b(x: float, z: float) -> tuple[float, float]:
    return (
        SEAM_B["u0"] + SEAM_B["scale"] * z / 10.0,
        SEAM_B["v0"] + SEAM_B["scale"] * (x - 10.0) / 10.0,
    )


def seam() -> bytes:
    """Two quads sharing one 3D edge (and its two vertices), one texture set `uzp_seam`, two UV
    islands of different scales, offsets and a 90 degree turn."""
    positions = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
    positions += [(0.0, 0.0, 10.0), (10.0, 0.0, 10.0), (20.0, 0.0, 10.0)]
    data = [f"v {fmt(*p)}\n" for p in positions] + ["vn 0.0 1.0 0.0\n"]
    # Faces counter-clockwise seen from +Y: (x, z) = (0, 10), (10, 10), (10, 0), (0, 0).
    quads = (((4, 5, 2, 1), seam_uv_a), ((5, 6, 3, 2), seam_uv_b))
    faces: list[str] = []
    uv_index = 0
    for corners, mapping in quads:
        indices = []
        for corner in corners:
            x, _, z = positions[corner - 1]
            data.append(f"vt {fmt(*mapping(x, z))}\n")
            uv_index += 1
            indices.append((corner, uv_index))
        (a, ta), (b, tb), (c, tc), (d, td) = indices
        faces += [f"f {a}/{ta}/1 {b}/{tb}/1 {c}/{tc}/1\n", f"f {a}/{ta}/1 {c}/{tc}/1 {d}/{td}/1\n"]
    return obj(
        "uzp_seam",
        "Two quads sharing the edge x = 10 cm, two UV islands: A at scale 0.375 on the left "
        "border, B at scale 0.25 turned 90 degrees.",
        [("uzp_seam", faces)],
        "".join(data),
    )


def seam_side_mask() -> bytes:
    """Grey mask: 1 on B's side of the tile (columns 128 and up), 0 on A's side."""
    return png16(256, 256, 1, lambda x, y: (0xFFFF if x >= SEAM_SIDE_COLUMN else 0,))


# --- Bitmaps ------------------------------------------------------------------------------------

# Slow ramps (R3): 16-bit codes around the middle of the range that cross only a few 8-bit steps
# (one 8-bit step is 257 codes): R rises 4 codes per texel along x (about 4 steps over the
# width), G the same along y; B is a staircase of eight levels inside one 8-bit step (code 127
# plus 0, 32, ..., 224 sixteen-bit codes), each 32 texels wide.
SLOW_CENTRE = 128 * 257
SLOW_STEP = 4


def slow_texel(x: int, y: int) -> Pixel:
    return (
        SLOW_CENTRE + (x - 128) * SLOW_STEP,
        SLOW_CENTRE + (y - 128) * SLOW_STEP,
        127 * 257 + (x // 32) * 32,
    )


def slow_ramp(grey: bool = False) -> bytes:
    """RGB slow ramps; the grey copy holds the R ramp."""
    if grey:
        return png16(256, 256, 1, lambda x, y: slow_texel(x, y)[:1])
    return png16(256, 256, 3, slow_texel)


IMPULSE_TEXEL = (100, 37)


def impulse_texel() -> bytes:
    """RGB 256 x 256, black but one white texel at (100, 37) (R-090 P4)."""
    return png16(256, 256, 3, lambda x, y: (0xFFFF,) * 3 if (x, y) == IMPULSE_TEXEL else (0, 0, 0))


def half_step_texel(x: int, y: int) -> Pixel:
    """R just below and G just above the midpoint between the 8-bit codes x and x + 1 (at 255 the
    codes stay in range); B the 8-bit lattice along y."""
    return (min(x * 257 + 128, 0xFFFF), min(x * 257 + 129, 0xFFFF), y * 257)


def half_steps(grey: bool = False) -> bytes:
    """RGB half-step codes (R4, decision 089's 8-bit write); the grey copy holds R."""
    if grey:
        return png16(256, 256, 1, lambda x, y: half_step_texel(x, y)[:1])
    return png16(256, 256, 3, half_step_texel)


def srgb8_ramp() -> bytes:
    """8-bit RGB like the wand's base bitmap (R5): R the codes 0..255 along x, G along y, B
    falling along x."""
    return png16(256, 256, 3, lambda x, y: (x, y, 255 - x), bits=8)


def srgb8_grey_ramp() -> bytes:
    """8-bit grey (decision 145 s0): column x holds code x, so every code 0..255 appears."""
    return png16(256, 256, 1, lambda x, y: (x,), bits=8)


# Decision 219: the ramp builds the same mip chain under every candidate sRGB8 mip filter, so the
# filter is separated on random codes, at a 256 px and a 512 px bitmap (decision 225).
SRGB8_RANDOM_SIZES = (256, 512)


def srgb8_random(size: int) -> bytes:
    """8-bit RGB `size` x `size` of deterministic pseudo-random codes (the top byte of a 32-bit
    LCG, a seed per size)."""
    state = [20262190 + size]

    def nxt() -> int:
        state[0] = (state[0] * 1664525 + 1013904223) % (1 << 32)
        return state[0] >> 24

    values = [(nxt(), nxt(), nxt()) for _ in range(size * size)]
    return png16(size, size, 3, lambda x, y: values[y * size + x], bits=8)


# --- Held-out minification of decision 084 -----------------------------------------------------

# Square power-of-two bitmap sizes no fitted minification golden used (decisions 078, 084 used
# the 64 px pattern and impulse).
HELD_OUT_SIZES = (128, 32)


def held_out_pattern(size: int) -> bytes:
    """RGB `size` x `size` deterministic pseudo-random codes (32-bit LCG, a seed per size), like
    `fixtures.pattern64` but never used by a fit."""
    state = [20261013 + size]

    def nxt() -> int:
        state[0] = (state[0] * 1664525 + 1013904223) % (1 << 32)
        return state[0] >> 16

    values = [(nxt(), nxt(), nxt()) for _ in range(size * size)]
    return png16(size, size, 3, lambda x, y: values[y * size + x])


# --- Padding probes of decision 129 (P-ramp, P-tie) -----------------------------------------

# P-ramp meshes: seam.obj's vertices, normal and faces, two UV islands sharing the 3D edge
# x = 10 cm; A's right edge u1 is the seam, B (turned 90 degrees) meets it on its bottom edge v0.
# UV boxes (u0, u1, v0, v1) of A and B per scale ratio (decision 129 section 4).
UVBox = tuple[float, float, float, float]
RAMP_RESOLUTION = 1024
RAMP_MESHES: dict[str, tuple[UVBox, UVBox]] = {
    "r1": ((0.125, 0.375, 0.125, 0.375), (0.5625, 0.8125, 0.625, 0.875)),
    "r2": ((0.125, 0.375, 0.125, 0.375), (0.5625, 0.6875, 0.625, 0.75)),
    "r15": ((0.0625, 0.4375, 0.1, 0.475), (0.55, 0.8, 0.6, 0.85)),
}
# Fractional-phase controls: every UV shifted by `shift` / 1024 in u and v.
RAMP_PHASES = {"p0": 0.0, "p25": 0.25, "p75": 0.75}
# The meshes' world bounding box is x 0..20 cm by z 0..10 cm. Decision 210's P-ramp-17 scales
# r1-p0's positions so that the largest extent is 34 cm (centre (17, 0, 8.5), half-extent 17);
# its UVs are unchanged.
RAMP_EXTENT = 20.0
RAMP_BOX17_EXTENT = 34.0


def ramp_seam(mesh: str, phase: str, extent: float = RAMP_EXTENT) -> bytes:
    """One P-ramp mesh, the text decision 129 fixes by SHA-256 (`vt` as %.9f, LF); `extent`
    scales the world positions so that the box's largest extent is `extent` cm."""
    scale = extent / RAMP_EXTENT
    shift = RAMP_PHASES[phase] / RAMP_RESOLUTION
    a, b = RAMP_MESHES[mesh]
    au0, au1, av0, av1 = (c + shift for c in a)
    bu0, bu1, bv0, bv1 = (c + shift for c in b)
    uvs = [(au0, av1), (au1, av1), (au1, av0), (au0, av0)]
    uvs += [(bu1, bv0), (bu1, bv1), (bu0, bv1), (bu0, bv0)]
    lines = ["# UzPainter R-090 P-ramp probe mesh (specification), Apache-2.0", "o uzp_seam"]
    lines += [f"v {fmt(x * scale, 0.0, z * scale)}" for z in (0.0, 10.0) for x in (0.0, 10.0, 20.0)]
    lines += ["vn 0.0 1.0 0.0", *(f"vt {u:.9f} {v:.9f}" for u, v in uvs), "usemtl uzp_seam"]
    lines += ["f 4/1/1 5/2/1 2/3/1", "f 4/1/1 2/3/1 1/4/1", "f 5/5/1 6/6/1 3/7/1"]
    lines += ["f 5/5/1 3/7/1 2/8/1"]
    return ("\n".join(lines) + "\n").encode("ascii")


# P-tie mesh: three separate 10 cm quads, each its own axis-aligned UV island of side 0.125,
# lower-left corners as below, one texture set `uzp_tie`.
TIE_SIDE = 0.125
TIE_CORNERS = ((0.1875, 0.1875), (0.6875, 0.1875), (0.4375, 0.6875))
TIE_RESOLUTIONS = (512, 2048)
# World x of the quads' centres (z spans -5..5 cm). Decision 210's P-tie-dyadic-box moves them so
# that the mesh's bounding box is centred at the origin with half-extent 16 cm (x -16..16).
TIE_CENTRES = (0.0, 12.0, 24.0)
TIE_BOX16_CENTRES = (-11.0, 0.0, 11.0)


def tie(centres: tuple[float, ...] = TIE_CENTRES) -> bytes:
    """The P-tie mesh (decision 129): its text and SHA-256 are fixed by this generator. Other
    `centres` move the quads in x and keep the UVs (decision 210)."""
    data: list[str] = ["vn 0.0 1.0 0.0\n"]
    faces: list[str] = []
    for index, (u0, v0) in enumerate(TIE_CORNERS):
        cx = centres[index]
        quad = [(cx - 5.0, 0.0, 5.0), (cx + 5.0, 0.0, 5.0), (cx + 5.0, 0.0, -5.0)]
        quad.append((cx - 5.0, 0.0, -5.0))
        u1, v1 = u0 + TIE_SIDE, v0 + TIE_SIDE
        corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        lines, quad_faces = quad_obj_lines(quad, corners, index * 4)
        data += lines
        faces += quad_faces
    moved = (
        ""
        if centres == TIE_CENTRES
        else f" Quads centred at x = {', '.join(f'{c:g}' for c in centres)} cm (decision 210)."
    )
    return obj(
        "uzp_tie",
        "Three axis-aligned UV islands of side 0.125 at (0.1875, 0.1875), (0.6875, 0.1875) and "
        "(0.4375, 0.6875) (decision 129 P-tie)." + moved,
        [("uzp_tie", faces)],
        "".join(data),
    )


def exr_float_rgb(rgb: npt.NDArray[np.float32]) -> bytes:
    """Scanline OpenEXR, channels B, G, R as FLOAT, ZIP compression (16 lines a block),
    increasing Y; `rgb` is (height, width, 3), row 0 the top row."""
    height, width, _ = rgb.shape

    def attribute(name: str, kind: str, value: bytes) -> bytes:
        return name.encode() + b"\0" + kind.encode() + b"\0" + struct.pack("<i", len(value)) + value

    channels = b"".join(c + b"\0" + struct.pack("<iB3xii", 2, 0, 1, 1) for c in (b"B", b"G", b"R"))
    box = struct.pack("<iiii", 0, 0, width - 1, height - 1)
    header = (
        struct.pack("<ii", 20000630, 2)
        + attribute("channels", "chlist", channels + b"\0")
        + attribute("compression", "compression", b"\3")
        + attribute("dataWindow", "box2i", box)
        + attribute("displayWindow", "box2i", box)
        + attribute("lineOrder", "lineOrder", b"\0")
        + attribute("pixelAspectRatio", "float", struct.pack("<f", 1.0))
        + attribute("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0))
        + attribute("screenWindowWidth", "float", struct.pack("<f", 1.0))
        + b"\0"
    )
    planes = rgb.astype("<f4")
    blocks: list[bytes] = []
    for y in range(0, height, 16):
        # Each line holds its B, G and R samples in turn; ZIP splits even and odd bytes, then
        # stores each byte as its difference from the previous one plus 128 before deflating.
        raw = planes[y : y + 16, :, ::-1].transpose(0, 2, 1).tobytes()
        codes = np.frombuffer(raw, dtype=np.uint8)
        split = np.concatenate([codes[0::2], codes[1::2]]).astype(np.int16)
        split[1:] = (split[1:] - split[:-1] + 128) & 0xFF
        packed = zlib.compress(split.astype(np.uint8).tobytes(), 9)
        data = packed if len(packed) < len(raw) else raw
        blocks.append(struct.pack("<ii", y, len(data)) + data)
    offsets = []
    position = len(header) + 8 * len(blocks)
    for block in blocks:
        offsets.append(struct.pack("<Q", position))
        position += len(block)
    return header + b"".join(offsets) + b"".join(blocks)


def uv_ramp(size: int) -> bytes:
    """`size` x `size` float32: R(x, y) = (x + 0.5) / size, G(x, y) = (y + 0.5) / size, B = 0.5
    (x the column, y the row from the top; decision 129)."""
    centres = (np.arange(size, dtype=np.float64) + 0.5) / size
    rgb = np.empty((size, size, 3), dtype=np.float32)
    rgb[:, :, 0] = centres[None, :]
    rgb[:, :, 1] = centres[:, None]
    rgb[:, :, 2] = 0.5
    return exr_float_rgb(rgb)


# --- Decision 266: kernel-code padding probes -------------------------------------------------

# A UV ramp reads only the centroid of each ring texel's kernel. The kernel code reads each tap:
# three one-hot bitmaps give the texel (x, y) the class k = x mod 3 + 3 (y mod 3) (x the column,
# y the row from the top), slot k of 9, so the 9 texels of any 3 x 3 window own one scalar each.
# Four code bitmaps hold periodic pseudo-random values: d and e (codes k/256, k in 1..255, one
# 17 x 13 texel tile each), f = (d + e)/2 (the superposition control) and g = 1 - d (the affine
# control). Every value is exact in float32.
KERNEL_RESOLUTIONS = (256, 512, 1024, 2048)
KERNEL_ONEHOT = ("a", "b", "c")
KERNEL_CODES = ("d", "e", "f", "g")
KERNEL_PERIOD = (17, 13)  # columns, rows
KERNEL_SEEDS = {"d": 20261018, "e": 20261266}


def kernel_onehot(size: int, part: str) -> bytes:
    """`size` x `size` float32: R, G, B are 1.0 where the class x mod 3 + 3 (y mod 3) is
    3p, 3p + 1, 3p + 2 (p = 0, 1, 2 for parts a, b, c), else 0."""
    p = KERNEL_ONEHOT.index(part)
    k = np.arange(size)[None, :] % 3 + 3 * (np.arange(size)[:, None] % 3)
    rgb = np.stack([k == 3 * p + c for c in range(3)], axis=-1).astype(np.float32)
    return exr_float_rgb(rgb)


def kernel_tile(name: str) -> npt.NDArray[np.float64]:
    """The 13 x 17 x 3 tile of code `name` (rows, columns, RGB)."""
    if name == "f":
        return (kernel_tile("d") + kernel_tile("e")) / 2.0
    if name == "g":
        return 1.0 - kernel_tile("d")
    columns, rows = KERNEL_PERIOD
    state = [KERNEL_SEEDS[name]]

    def nxt() -> int:
        state[0] = (state[0] * 1664525 + 1013904223) % (1 << 32)
        return state[0] >> 24

    codes = [nxt() % 255 + 1 for _ in range(rows * columns * 3)]
    return np.array(codes, dtype=np.float64).reshape(rows, columns, 3) / 256.0


def kernel_code(size: int, name: str) -> bytes:
    """`size` x `size` float32: code `name`'s tile repeated from the top-left texel."""
    columns, rows = KERNEL_PERIOD
    tile = kernel_tile(name)
    rgb = np.tile(tile, (size // rows + 1, size // columns + 1, 1))[:size, :size]
    return exr_float_rgb(np.ascontiguousarray(rgb, dtype=np.float32))


# The kernel atlas: one texture set `uzp_kernel_atlas` of separate 3D pieces, each a small UV
# configuration. Layout coordinates are texels (column, row from the top) of a 512 px tile; a
# mesh for resolution N maps them to u = column / N, v = 1 - row / N, so every resolution sees
# the same texel configuration. Flat islands are isometric: 3D (x, 0, z) = (column - 256, 0,
# row - 256) cm. Two anchor triangles that cover no texel centre put the mesh box at exactly
# [-256, 256] in x and z, so the box-normalised positions are exact in float32. Items are packed
# in shelves 8 texels apart inside texels 16..496.
ATLAS_RESOLUTIONS = (512, 1024, 2048)
ATLAS_TEXELS = 512
ATLAS_MARGIN = 16
ATLAS_GAP = 8
ATLAS_HALF = 256.0
# The moved atlas (decision 266): positions scaled by 1.7 and offset, so that the box is
# neither centred nor of power-of-two extent and the normalised positions round.
ATLAS_MOVED_SCALE = 1.7
ATLAS_MOVED_OFFSET = (3.1, 0.0, -2.3)

Vec3 = tuple[float, float, float]
Face = tuple[list[Vec3], list[tuple[float, float]]]  # 3D corners, layout (column, row) corners


def _flat_face(uvs: list[tuple[float, float]]) -> Face:
    """A flat isometric face from its layout corners."""
    return [(c - ATLAS_HALF, 0.0, r - ATLAS_HALF) for c, r in uvs], uvs


def _frame_face(
    origin: Vec3, e1: Vec3, e2: Vec3, lp: float, lq: float, scale: float, turn: float
) -> Face:
    """A parallelogram origin + p e1 + q e2 (p in [0, lp], q in [0, lq]); its UV is (p, q) / scale
    turned `turn` degrees (u right, v up), at layout origin (0, 0)."""
    cos, sin = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    if turn % 90 == 0:
        cos, sin = round(cos), round(sin)
    corners3: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    for p, q in ((0.0, 0.0), (lp, 0.0), (lp, lq), (0.0, lq)):
        x, y, z = (o + p * a + q * b for o, a, b in zip(origin, e1, e2, strict=True))
        corners3.append((x, y, z))
        uvs.append(((p * cos - q * sin) / scale, -(p * sin + q * cos) / scale))
    return corners3, uvs


def _moved_uv(face: Face, column: float, row: float) -> Face:
    """`face` with its UV bounding box's top-left corner moved to (column, row)."""
    corners3, uvs = face
    c0, r0 = min(c for c, _ in uvs), min(r for _, r in uvs)
    return corners3, [(c - c0 + column, r - r0 + row) for c, r in uvs]


class AtlasItem:
    """One configuration: the UV boxes it reserves (width, height), the faces it builds from
    the boxes' top-left corners, and the texel centres it must cover."""

    def __init__(
        self,
        name: str,
        boxes: list[tuple[int, int]],
        build: Any,
        covers: int,
    ) -> None:
        self.name, self.boxes, self.build, self.covers = name, boxes, build, covers


def _flat_item(name: str, polygons: list[list[tuple[float, float]]], covers: int) -> AtlasItem:
    """Flat isometric islands given as polygons in item-local layout coordinates."""
    width = math.ceil(max(c for poly in polygons for c, _ in poly))
    height = math.ceil(max(r for poly in polygons for _, r in poly))

    def build(origins: list[tuple[float, float]]) -> list[Face]:
        [(oc, orow)] = origins
        return [_flat_face([(oc + c, orow + r) for c, r in poly]) for poly in polygons]

    return AtlasItem(name, [(width, height)], build, covers)


def _texels(cells: list[tuple[int, int]], inset: float = 0.25) -> list[list[tuple[float, float]]]:
    """One square island of side 1 - 2 inset around each texel (column, row)."""
    return [
        [
            (c + inset, r + inset),
            (c + 1 - inset, r + inset),
            (c + 1 - inset, r + 1 - inset),
            (c + inset, r + 1 - inset),
        ]
        for c, r in cells
    ]


def _rect(columns: int, rows: int) -> list[tuple[float, float]]:
    """A rectangle covering the texel centres of `columns` x `rows` texels from (0, 0)."""
    i = 0.25
    return [(i, i), (columns - i, i), (columns - i, rows - i), (i, rows - i)]


X_AXIS: Vec3 = (1.0, 0.0, 0.0)
MINUS_Z: Vec3 = (0.0, 0.0, -1.0)


def _seam_item(
    name: str,
    side: float,
    ratio: float,
    turn: float,
    covers: int,
    fold: tuple[float, float] = (1.0, 0.0),
    phase: tuple[float, float] = (0.25, 0.25),
) -> AtlasItem:
    """Two 3D squares of side `side` sharing one edge: A flat and isometric, B beyond A's +x edge
    (folded down by the angle of (cos, sin) = `fold`), its UV island at scale 1 / `ratio`, turned
    `turn` degrees, in a box of its own. A's box reserves room for B in 3D."""
    b_side = side / ratio
    reach = math.ceil(2 * side + 1)
    b_box = math.ceil(
        b_side * (abs(math.cos(math.radians(turn))) + abs(math.sin(math.radians(turn)))) + 1
    )

    def build(origins: list[tuple[float, float]]) -> list[Face]:
        (ac, ar), (bc, br) = origins
        c0, r0 = ac + phase[0], ar + phase[0] + side  # A's (p, q) = (0, 0): its bottom-left
        a_origin = (c0 - ATLAS_HALF, 0.0, r0 - ATLAS_HALF)
        a_face = _frame_face(a_origin, X_AXIS, MINUS_Z, side, side, 1.0, 0.0)
        a = _moved_uv(a_face, ac + phase[0], ar + phase[0])
        e1 = (fold[0], -fold[1], 0.0)
        b_origin = (a_origin[0] + side, 0.0, a_origin[2])
        b = _frame_face(b_origin, e1, MINUS_Z, side, side, ratio, turn)
        return [a, _moved_uv(b, bc + phase[1], br + phase[1])]

    return AtlasItem(name, [(reach, math.ceil(side + 1)), (b_box, b_box)], build, covers)


def _corner_item(
    name: str,
    side: float,
    ratios: tuple[float, float],
    turns: tuple[float, float],
    covers: int,
) -> AtlasItem:
    """A cube corner: three squares of side `side` meeting at one 3D vertex V, F1 flat and
    isometric, F2 hanging down from F1's far (-z) edge, F3 from its -x edge; three seams end at
    V. F2 and F3 are UV islands of their own at scales 1 / `ratios`, turned by `turns`."""
    boxes = [(math.ceil(side + 1), math.ceil(side + 1))]
    boxes += [(math.ceil(side / r * 1.5 + 1), math.ceil(side / r * 1.5 + 1)) for r in ratios]

    def build(origins: list[tuple[float, float]]) -> list[Face]:
        (fc, fr), (c2, r2), (c3, r3) = origins
        c0, r0 = fc + 0.25, fr + 0.25 + side
        x0, z0 = c0 - ATLAS_HALF, r0 - side - ATLAS_HALF  # V = (x0, 0, z0)
        f1_face = _frame_face((x0, 0.0, z0 + side), X_AXIS, MINUS_Z, side, side, 1.0, 0.0)
        f1 = _moved_uv(f1_face, fc + 0.25, fr + 0.25)
        f2 = _frame_face((x0, 0.0, z0), X_AXIS, (0.0, -1.0, 0.0), side, side, ratios[0], turns[0])
        f3 = _frame_face(
            (x0, -side, z0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), side, side, ratios[1], turns[1]
        )
        return [f1, _moved_uv(f2, c2 + 0.25, r2 + 0.25), _moved_uv(f3, c3 + 0.25, r3 + 0.25)]

    return AtlasItem(name, boxes, build, covers)


def _fan_item(
    name: str, half: int, per_side: int, apex: float, phase: tuple[float, float], covers: int
) -> AtlasItem:
    """A pole: the 4 * `per_side` triangles of a square of half-size `half` cm around its centre
    (lifted by `apex` cm), meeting at that one 3D vertex. In UV the triangles stand side by side
    on one row, each with its own copy of the apex (as at a UV sphere's pole), so every spoke is
    a seam whose two sides face each other across a V-shaped gap. `phase` offsets the strip so
    that no texel centre lies on a triangle edge."""
    segment = 2 * half / per_side
    count = 4 * per_side
    width, height = math.ceil(count * segment + 1), 2 * half + 1

    def build(origins: list[tuple[float, float]]) -> list[Face]:
        [(oc, orow)] = origins
        cx, cz = oc + width // 2 - ATLAS_HALF, orow + height // 2 - ATLAS_HALF
        steps = [-half + j * segment for j in range(per_side)]
        loop = [(s, -half) for s in steps] + [(half, s) for s in steps]
        loop += [(-s, half) for s in steps] + [(-half, -s) for s in steps]
        ring = [(cx + x, 0.0, cz + z) for x, z in loop]
        top: Vec3 = (cx, apex, cz)
        if _normal(ring[0], ring[1], top)[1] < 0:
            ring.reverse()
        base_row = orow + phase[1] + half
        faces: list[Face] = []
        for i in range(count):
            left = oc + phase[0] + i * segment
            uvs = [
                (left, base_row),
                (left + segment, base_row),
                (left + segment / 2, base_row - half),
            ]
            faces.append(([ring[i], ring[(i + 1) % count], top], uvs))
        return faces

    return AtlasItem(name, [(width, height)], build, covers)


def _normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    length = math.sqrt(sum(v * v for v in n))
    return (n[0] / length + 0.0, n[1] / length + 0.0, n[2] / length + 0.0)


FOLD_90 = (0.0, 1.0)
FOLD_53 = (0.6, 0.8)  # cos, sin of atan(4/3): B's far edge at whole centimetres


def atlas_items() -> list[AtlasItem]:
    """The configurations of decision 266's kernel atlas, in packing order."""
    tri = [(0.25, 0.25), (2.5, 0.25), (0.25, 2.5)]  # L-tromino: covers (0,0), (1,0), (0,1)
    diamond = [(4.5, 0.25), (8.75, 4.5), (4.5, 8.75), (0.25, 4.5)]
    diagonal = [(0.25, 0.5), (0.5, 0.25), (1.75, 1.5), (1.5, 1.75)]
    anti = [(0.25, 1.5), (1.5, 0.25), (1.75, 0.5), (0.5, 1.75)]
    return [
        _flat_item("row-384", [_rect(384, 1)], 384),
        _flat_item("row-128", [_rect(128, 1)], 128),
        _flat_item("block-32", [_rect(32, 32)], 1024),
        _flat_item("column-128", [_rect(1, 128)], 128),
        _flat_item("row-32", [_rect(32, 1)], 32),
        _flat_item("column-32", [_rect(1, 32)], 32),
        _flat_item("row-8", [_rect(8, 1)], 8),
        _flat_item("column-8", [_rect(1, 8)], 8),
        _flat_item("row-3", [_rect(3, 1)], 3),
        _flat_item("column-3", [_rect(1, 3)], 3),
        _flat_item("point", _texels([(0, 0)]), 1),
        _flat_item("pair-axis-x", [_rect(2, 1)], 2),
        _flat_item("pair-axis-y", [_rect(1, 2)], 2),
        _flat_item("pair-diagonal-one-quad", [diagonal], 2),
        _flat_item("pair-antidiagonal-one-quad", [anti], 2),
        _flat_item("pair-diagonal-two-pieces", _texels([(0, 0), (1, 1)]), 2),
        _flat_item("pair-knight-two-pieces", _texels([(0, 0), (2, 1)]), 2),
        _flat_item("gap-x-two-pieces", _texels([(0, 0), (2, 0)]), 2),
        _flat_item("gap-y-two-pieces", _texels([(0, 0), (0, 2)]), 2),
        _flat_item("gap-diagonal-two-pieces", _texels([(0, 0), (2, 2)]), 2),
        _flat_item("l-tromino", [tri], 3),
        _flat_item("block-2", [_rect(2, 2)], 4),
        _flat_item("block-3", [_rect(3, 3)], 9),
        _flat_item("block-4", [_rect(4, 4)], 16),
        _flat_item("diamond-4", [diamond], 41),
        _seam_item("seam-r1-single", 1.0, 1.0, 0.0, 2),
        _seam_item("seam-r1-turn90", 2.0, 1.0, 90.0, 8),
        _seam_item("seam-r1.5", 3.0, 1.5, 0.0, 13),
        _seam_item("seam-r1.5-single", 1.5, 1.5, 0.0, 2, phase=(0.75, 0.25)),
        _seam_item("seam-r2-turn90", 4.0, 2.0, 90.0, 20),
        _seam_item("seam-r2-single-b", 2.0, 2.0, 0.0, 5),
        _seam_item("seam-r1.25", 5.0, 1.25, 0.0, 41),
        _seam_item("seam-r1-turn30", 4.0, 1.0, 30.0, 32),
        _seam_item("seam-r1-turn90-fold90", 2.0, 1.0, 90.0, 8, FOLD_90),
        _seam_item("seam-r2-turn90-fold90", 4.0, 2.0, 90.0, 20, FOLD_90),
        _seam_item("seam-r1-turn90-fold53", 5.0, 1.0, 90.0, 50, FOLD_53),
        _corner_item("corner-r1", 4.0, (1.0, 1.0), (90.0, 180.0), covers=48),
        _corner_item("corner-r1-r1.5-r2", 6.0, (1.5, 2.0), (0.0, 90.0), covers=61),
        _fan_item("pole-4", 6, 1, 0.0, (0.375, 0.125), covers=144),
        _fan_item("pole-8", 8, 2, 0.0, (0.375, 0.125), covers=256),
        _fan_item("pole-8-pyramid", 8, 2, 8.0, (0.375, 0.125), covers=256),
        _fan_item("pole-12", 6, 3, 0.0, (0.375, 0.25), covers=120),
    ]


def _anchor_faces(origin: tuple[float, float]) -> list[Face]:
    """Two triangles at the box corners (-256, 0, -256) and (256, 0, 256), their UVs inside
    texel `origin` and its right neighbour, off every texel centre."""
    oc, orow = origin
    faces: list[Face] = []
    for k, corner in enumerate((-ATLAS_HALF, ATLAS_HALF)):
        step = 0.25 if corner < 0 else -0.25
        corners3 = [
            (corner, 0.0, corner),
            (corner + step, 0.0, corner),
            (corner, 0.0, corner + step),
        ]
        c, r = oc + k, orow
        faces.append(
            (corners3, [(c + 0.625, r + 0.625), (c + 0.875, r + 0.625), (c + 0.625, r + 0.875)])
        )
    return faces


def atlas_faces() -> list[tuple[str, list[Face]]]:
    """Every item's faces at its packed place (shelves left to right, top to bottom), then the
    anchors."""
    limit = ATLAS_TEXELS - ATLAS_MARGIN
    column, row, shelf = ATLAS_MARGIN, ATLAS_MARGIN, 0
    placed: list[tuple[str, list[Face]]] = []
    for item in atlas_items():
        origins = []
        for width, height in item.boxes:
            if column + width > limit:
                column, row, shelf = ATLAS_MARGIN, row + shelf + ATLAS_GAP, 0
            origins.append((float(column), float(row)))
            column += width + ATLAS_GAP
            shelf = max(shelf, height)
        placed.append((item.name, item.build(origins)))
    if column + 2 > limit:
        column, row, shelf = ATLAS_MARGIN, row + shelf + ATLAS_GAP, 0
    assert row + shelf <= limit, "the kernel atlas does not fit its tile"
    placed.append(("anchors", _anchor_faces((float(column), float(row)))))
    return placed


def _number(value: float) -> str:
    """The exact decimal of a dyadic value (at most 2^-24), else 9 decimals."""
    if (value * (1 << 24)).is_integer():
        text = f"{value:.24f}".rstrip("0")
        return text + "0" if text.endswith(".") else text
    return f"{value:.9f}"


def kernel_atlas(resolution: int, moved: bool = False) -> bytes:
    """The kernel atlas mesh for `resolution` (u = column / N, v = 1 - row / N); `moved` scales
    the positions by 1.7 and offsets them (decision 266). Shared 3D corners of one item share
    one `v` line, so its seams are real; every face has its own normal."""
    data: list[str] = []
    faces: list[str] = []
    positions: dict[tuple[str, Vec3], int] = {}
    uv_count = normal_count = 0
    sx, sy, sz = ATLAS_MOVED_OFFSET if moved else (0.0, 0.0, 0.0)
    scale = ATLAS_MOVED_SCALE if moved else 1.0
    for name, item_faces in atlas_faces():
        for corners3, uvs in item_faces:
            area = sum(
                uvs[i][0] * -uvs[(i + 1) % len(uvs)][1] - uvs[(i + 1) % len(uvs)][0] * -uvs[i][1]
                for i in range(len(uvs))
            )
            order = list(range(len(uvs))) if area > 0 else list(reversed(range(len(uvs))))
            n = _normal(*(corners3[i] for i in order[:3]))
            data.append(f"vn {_number(n[0])} {_number(n[1])} {_number(n[2])}\n")
            normal_count += 1
            refs = []
            for i in order:
                key = (name, corners3[i])
                if key not in positions:
                    x, y, z = corners3[i]
                    p = (x * scale + sx, y * scale + sy, z * scale + sz)
                    data.append(
                        f"v {fmt(*p)}\n" if moved else f"v {' '.join(_number(c) for c in p)}\n"
                    )
                    positions[key] = len(positions) + 1
                c, r = uvs[i]
                data.append(f"vt {_number(c / resolution)} {_number(1.0 - r / resolution)}\n")
                uv_count += 1
                refs.append(f"{positions[key]}/{uv_count}/{normal_count}")
            for k in range(1, len(refs) - 1):
                faces.append(f"f {refs[0]} {refs[k]} {refs[k + 1]}\n")
    what = " positions x 1.7 offset by (3.1, 0, -2.3) cm;" if moved else ""
    return obj(
        "uzp_kernel_atlas",
        f"Decision 266 kernel atlas at {resolution} px:{what} separate pieces of single texels, "
        "pairs, gaps, rows, blocks, UV seams, cube corners and poles.",
        [("uzp_kernel_atlas", faces)],
        "".join(data),
    )


# --- Decision 272: tie-order sweep probes -----------------------------------------------------

# Many copies of one UV configuration whose 3D placement sweeps systematically, to map where the
# order of two exactly tied 1/d shares flips. Every copy is its own 3D piece and its own UV
# island; its sub-texel UV phase is the same in every copy, only its whole-texel slot changes.
# Layout units are texels of a 512 px tile (u = column / 512, v = 1 - row / 512). A unit's local
# 3D is isometric, (column, 0, row) cm, then scaled per axis, turned about +y by a multiple of
# 90 degrees and moved so that its centre lands on a target. Copies whose 3D boxes would meet
# are stacked in y (flat copies; y rounding cannot reach the distance comparison at these sizes,
# and the y-control copies test that). Two families (strips: straight-edge ties; seams: seam
# own-diagonal ties and fan V-gaps) are each written under three mesh boxes: `centred`
# ([-256, 256] in x and z, so normalised positions are p / 256), `offcentre` (every vertex
# moved by (256, 0, 256): the same normalised values reached through fl(p/h) in [0, 2]) and
# `box320` (anchors at +-320: normalised binades no longer sit on world binades).
SWEEP_RESOLUTION = 512
SWEEP_MARGIN = 16
SWEEP_GAP = 6
SWEEP_FAMILIES = ("strips", "seams")
SWEEP_BOXES = ("centred", "offcentre", "box320")
SWEEP_HALF = {"centred": 256.0, "offcentre": 256.0, "box320": 320.0}
SWEEP_SHIFT: dict[str, Vec3] = {
    "centred": (0.0, 0.0, 0.0),
    "offcentre": (256.0, 0.0, 256.0),
    "box320": (0.0, 0.0, 0.0),
}
SWEEP_Y_HALF = 64.0
# Bases of the ulp, scale and order sweeps (x, z in cm), away from every world binade and from
# the binades of box320 and offcentre over the whole unit.
SWEEP_BASES: dict[str, tuple[float, float]] = {
    "A": (100.0, 52.0),
    "B": (48.0, 100.0),
    "C": (-150.0, -44.0),
    "V": (-100.0, 100.0),
}
# Straddled boundaries (cm): x' = 0, +-1/16 ... +-3/4 of the centred box (and fl(p/h) = 0.25,
# 0.5, 1 of offcentre), then x' = +-1/8, +-1/4, +-1/2 of box320.
WORLD_BOUNDARIES = (0.0, 16.0, -16.0, 32.0, -32.0, 64.0, -64.0, 128.0, -128.0, 192.0, -192.0)
BOX320_BOUNDARIES = (40.0, -40.0, 80.0, -80.0, 160.0, -160.0)
SWEEP_STEPS = 16  # k = 0 .. 15 ulps
UNIFORM_SCALES = (0.5, 0.75, 1.25, 1.5, 1.7, 2.0, 3.0)
AXIS_SCALES: tuple[tuple[float, float], ...] = (
    (1.7, 1.0),
    (1.0, 1.7),
    (2.0, 1.0),
    (1.0, 2.0),
    (1.5, 1.0),
    (1.0, 1.5),
)
AXIS_SCALES += ((0.75, 1.0), (1.0, 0.75))
SEAM_SIDE = 8.0
SEAM_RATIO = 2.0
VGAP_HALF = 4

Tri = tuple[list[Vec3], list[tuple[float, float]]]  # 3 corners: 3D, layout (column, row)


class SweepCopy:
    """One copy: its unit, placement and vertex order (`split` picks a quad's diagonal, `rot`
    rotates every triangle's vertex list, `order` 1 reverses the face order), its triangles in
    world cm before the box shift, and its UV slot size."""

    def __init__(
        self,
        name: str,
        unit: str,
        target: Vec3,
        theta: int = 0,
        scale: Vec3 = (1.0, 1.0, 1.0),
        perm: tuple[int, int, int] = (1, 0, 0),
        fold: tuple[float, float] = (1.0, 0.0),
    ) -> None:
        self.name, self.unit, self.target, self.theta = name, unit, target, theta
        self.scale, self.perm, self.fold = scale, perm, fold
        local, centre = _sweep_unit(unit, perm[0], fold)
        cos, sin = ((1, 0), (0, 1), (-1, 0), (0, -1))[theta // 90]

        def place(p: Vec3) -> Vec3:
            x, y, z = (p[i] * scale[i] for i in range(3))
            return (x * cos + z * sin, y, -x * sin + z * cos)

        c = place(centre)
        offset = tuple(t - q for t, q in zip(target, c, strict=True))
        tris = [
            ([tuple(a + o for a, o in zip(place(p), offset, strict=True)) for p in ps], uvs)
            for ps, uvs in local
        ]
        rot = perm[1]
        tris = [(ps[rot:] + ps[:rot], uvs[rot:] + uvs[:rot]) for ps, uvs in tris]
        self.tris: list[Tri] = [
            (list(map(_vec3, ps)), uvs) for ps, uvs in (tris[::-1] if perm[2] else tris)
        ]
        self.size = (
            math.ceil(max(c for _, uvs in local for c, _ in uvs)),
            math.ceil(max(r for _, uvs in local for _, r in uvs)),
        )

    def bounds(self) -> tuple[Vec3, Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return _vec3(low), _vec3(high)


def _vec3(p: Any) -> Vec3:
    return (float(p[0]), float(p[1]), float(p[2]))


def _quad_tris(corners3: list[Vec3], uvs: list[tuple[float, float]], split: int) -> list[Tri]:
    """A counter-clockwise (v up) quad as two triangles: `split` 1 fans from corner 0 (the kernel
    atlas's diagonal), 0 from corner 1 (the other diagonal)."""
    s = 1 - split
    idx = [(s, s + 1, s + 2), (s, s + 2, (s + 3) % 4)]
    return [([corners3[i] for i in t], [uvs[i] for i in t]) for t in idx]


def _sweep_unit(unit: str, split: int, fold: tuple[float, float]) -> tuple[list[Tri], Vec3]:
    """A unit's triangles in local 3D and layout coordinates, and its local centre."""
    kind, _, size = unit.partition("-")
    if kind in ("row", "column"):
        length = int(size)
        w, h = (length, 1) if kind == "row" else (1, length)
        i = 0.25
        uvs = [(i, h - i), (w - i, h - i), (w - i, i), (i, i)]  # BL, BR, TR, TL
        return _quad_tris([(c, 0.0, r) for c, r in uvs], uvs, split), (w / 2, 0.0, h / 2)
    if kind == "seam":
        side = SEAM_SIDE
        a_face = _frame_face((0.0, 0.0, side), X_AXIS, MINUS_Z, side, side, 1.0, 0.0)
        a3, a_uv = _moved_uv(a_face, 0.0, 0.125)
        e1 = (fold[0], -fold[1], 0.0)
        b_face = _frame_face((side, 0.0, side), e1, MINUS_Z, side, side, SEAM_RATIO, 90.0)
        b3, b_uv = _moved_uv(b_face, side + 1 + SWEEP_GAP + 0.125, 0.0)
        tris = _quad_tris(a3, a_uv, split) + _quad_tris(b3, b_uv, split)
        return tris, (side, 0.0, side / 2)
    if kind == "vgap":
        half = float(VGAP_HALF)
        rim = [(-half, 0.0, half), (half, 0.0, half), (half, 0.0, -half)]
        apex: Vec3 = (0.0, 0.0, 0.0)
        base = 0.125 + half
        tris = []
        for k in range(2):
            left = 0.375 + 2 * half * k
            layout = [(left, base), (left + 2 * half, base), (left + half, base - half)]
            tris.append(([rim[k], rim[k + 1], apex], layout))
        return tris, apex
    raise ValueError(unit)


def _ulp(value: float) -> float:
    return float(np.spacing(np.float32(abs(value))))


def _sweeps(prefix: str, unit: str, base: str, y0: float, **kw: Any) -> list[SweepCopy]:
    """k-ulp translations of `unit` at base `base`: across x (k = 0..15, y = y0 + k), then
    along z (k = 1..15, y = -(y0 + k))."""
    bx, bz = SWEEP_BASES[base]
    copies = [
        SweepCopy(f"{prefix}-x+{k}", unit, (bx + k * _ulp(bx), y0 + k, bz), **kw)
        for k in range(SWEEP_STEPS)
    ]
    copies += [
        SweepCopy(f"{prefix}-z+{k}", unit, (bx, -(y0 + k), bz + k * _ulp(bz)), **kw)
        for k in range(1, SWEEP_STEPS)
    ]
    return copies


PERMS = [(s, r, o) for s in (1, 0) for r in (0, 1, 2) for o in (0, 1)]


def strip_copies() -> list[SweepCopy]:
    """The strips family: straight-edge ties along rows (u ties) and columns (v ties)."""
    copies: list[SweepCopy] = []
    # F1: 16-texel strips straddling binade boundaries, along x and along z in 3D.
    for unit, theta, axis in (
        ("row-16", 0, "x"),
        ("column-16", 90, "x"),
        ("row-16", 90, "z"),
        ("column-16", 0, "z"),
    ):
        shift = 0.0 if unit.startswith("row") else 2.0
        for bounds, lines in (
            (WORLD_BOUNDARIES, (52.0, -148.0)),
            (BOX320_BOUNDARIES, (58.0, -142.0)),
        ):
            for line in lines:
                for b in bounds:
                    at = line + shift
                    target = (b, 0.0, at) if axis == "x" else (at, 0.0, b)
                    copies.append(
                        SweepCopy(f"f1-{unit}-t{theta}-{axis}{b:+g}-at{at:+g}", unit, target, theta)
                    )
    # F2: k-ulp translations at bases A, B, C (rows) and A (columns).
    for base in ("A", "B", "C"):
        copies += _sweeps(f"f2-row-8-{base}", "row-8", base, 0.0)
    copies += _sweeps("f2-column-8-A", "column-8", "A", 20.0)
    ax, az = SWEEP_BASES["A"]
    # F3: the y control, base A unshifted at six heights.
    copies += [
        SweepCopy(f"f3-row-8-A-y{y:+g}", "row-8", (ax, y, az))
        for y in (40.0, 44.0, 48.0, -40.0, -44.0, -48.0)
    ]
    # F4: uniform and per-axis scales at base A.
    scales = [(s, s, s) for s in UNIFORM_SCALES] + [(sx, 1.0, sz) for sx, sz in AXIS_SCALES]
    copies += [
        SweepCopy(f"f4-row-8-A-s{sx:g}x{sz:g}", "row-8", (ax, -50.0 - j, az), scale=(sx, sy, sz))
        for j, (sx, sy, sz) in enumerate(scales)
    ]
    # F5: vertex orders (diagonal, rotation, face order) at base A (rows) and B (columns).
    rows = [p for p in PERMS if p != (1, 0, 0)]
    copies += [
        SweepCopy(f"f5-row-8-A-p{s}{r}{o}", "row-8", (ax, 50.0 + j, az), perm=(s, r, o))
        for j, (s, r, o) in enumerate(rows)
    ]
    bx, bz = SWEEP_BASES["B"]
    copies += [
        SweepCopy(f"f5-column-8-B-p{s}{r}{o}", "column-8", (bx, 20.0 + j, bz), perm=(s, r, o))
        for j, (s, r, o) in enumerate(PERMS)
    ]
    return copies


SEAM_TARGETS: tuple[tuple[float, float], ...] = (
    (100.0, -100.0),
    (40.0, 160.0),
    (-150.0, 90.0),
    (-24.0, -30.0),
)
SEAM_TARGETS += ((180.0, 200.0), (-200.0, -180.0))
VGAP_TARGETS: tuple[tuple[float, float], ...] = (
    (140.0, -100.0),
    (60.0, 200.0),
    (-110.0, 60.0),
    (20.0, -40.0),
)
VGAP_TARGETS += ((220.0, 130.0), (-180.0, -120.0))
FOLDS = {"90": FOLD_90, "53": FOLD_53}


def seam_copies() -> list[SweepCopy]:
    """The seams family: ratio-2 seam pairs (A 8 x 8 texels, B 4 x 4 turned 90 degrees, as the
    P-ramp r2; both seam edges on texel boundaries as at r2-p0, the other edges 1/8 texel off so
    that no texel centre lies on a diagonal) and two-triangle fan V-gaps (pole-4's spoke at
    half-size 4)."""
    copies: list[SweepCopy] = []
    # G1 / H1: four turns at six positions, the turns stacked in y.
    for prefix, unit, targets in (("g1", "seam", SEAM_TARGETS), ("h1", "vgap", VGAP_TARGETS)):
        for x, z in targets:
            for j, theta in enumerate((0, 90, 180, 270)):
                name = f"{prefix}-{unit}-t{theta}-x{x:+g}-z{z:+g}"
                copies.append(SweepCopy(name, unit, (x, 12.0 * j, z), theta))
    # G2: folded seams, B hanging 90 or atan(4/3) degrees down, two turns at two positions.
    j = 0
    for fold in ("90", "53"):
        for theta in (0, 90):
            for x, z in (SEAM_TARGETS[0], SEAM_TARGETS[2]):
                name = f"g2-seam-fold{fold}-t{theta}-x{x:+g}-z{z:+g}"
                y = -20.0 - 10.0 * (j // 2)
                copies.append(SweepCopy(name, "seam", (x, y, z), theta, fold=FOLDS[fold]))
                j += 1
    # G3 / H3: k-ulp translations.
    copies += _sweeps("g3-seam-A", "seam", "A", 0.0)
    copies += _sweeps("h3-vgap-V", "vgap", "V", 0.0)
    ax, az = SWEEP_BASES["A"]
    vx, vz = SWEEP_BASES["V"]
    # G4 / H4: scales.
    seam_scales = [(s, s, s) for s in (0.75, 1.5, 1.7, 2.0)]
    seam_scales += [(1.7, 1.0, 1.0), (2.0, 1.0, 1.0), (1.0, 1.0, 1.7), (1.0, 1.0, 2.0)]
    copies += [
        SweepCopy(f"g4-seam-A-s{sx:g}x{sz:g}", "seam", (ax, 20.0 + 2 * j, az), scale=(sx, sy, sz))
        for j, (sx, sy, sz) in enumerate(seam_scales)
    ]
    copies += [
        SweepCopy(f"h4-vgap-V-s{s:g}", "vgap", (vx, -20.0 - 2 * j, vz), scale=(s, s, s))
        for j, s in enumerate((0.75, 1.5, 1.7, 2.0))
    ]
    # G5 / H2: vertex orders. Seams: both quads' diagonal and the face order, then the two
    # rotations; V-gaps: rotation and face order at two turns.
    seam_perms = [(s, 0, o) for s in (1, 0) for o in (0, 1)] + [(1, 1, 0), (1, 2, 0)]
    seam_perms += [(0, 1, 0), (0, 2, 1), (1, 1, 1)]
    copies += [
        SweepCopy(f"g5-seam-A-p{s}{r}{o}", "seam", (ax, -20.0 - 2 * j, az), perm=(s, r, o))
        for j, (s, r, o) in enumerate(p for p in seam_perms if p != (1, 0, 0))
    ]
    vgap_perms = [(1, r, o) for r in (0, 1, 2) for o in (0, 1) if (r, o) != (0, 0)]
    copies += [
        SweepCopy(
            f"h2-vgap-V-t{theta}-p1{r}{o}", "vgap", (vx, 20.0 + 2 * j, vz), theta, perm=(1, r, o)
        )
        for j, (theta, (_, r, o)) in enumerate((theta, p) for theta in (0, 90) for p in vgap_perms)
    ]
    return copies


def sweep_copies(family: str) -> list[SweepCopy]:
    return strip_copies() if family == "strips" else seam_copies()


def sweep_layout(
    family: str,
) -> tuple[list[tuple[SweepCopy, tuple[float, float]]], tuple[float, float]]:
    """Every copy with its slot's top-left texel (shelves left to right, top to bottom), and the
    slot of the two box anchors below the last shelf."""
    limit = SWEEP_RESOLUTION - SWEEP_MARGIN
    column, row, shelf = SWEEP_MARGIN, SWEEP_MARGIN, 0
    placed = []
    for copy in sweep_copies(family):
        width, height = copy.size
        if column + width > limit:
            column, row, shelf = SWEEP_MARGIN, row + shelf + SWEEP_GAP, 0
        placed.append((copy, (float(column), float(row))))
        column += width + SWEEP_GAP
        shelf = max(shelf, height)
    anchors = (float(SWEEP_MARGIN), float(row + shelf + SWEEP_GAP))
    assert anchors[1] + 1 <= limit, "the sweep copies do not fit their tile"
    return placed, anchors


def _f32(value: float) -> str:
    """The exact decimal of fl32(`value`)."""
    text = format(decimal.Decimal(float(np.float32(value))), "f")
    text = text.rstrip("0") if "." in text else text + "."
    text = text + "0" if text.endswith(".") else text
    return "0.0" if text == "-0.0" else text


def tie_sweep(family: str, box: str) -> bytes:
    """The decision 272 sweep mesh of `family` under mesh box `box`: positions written as exact
    float32 decimals, anchors fixing the box at +-half in x and z and +-64 cm in y."""
    placed, anchors = sweep_layout(family)
    tris: list[Tri] = []
    for copy, (oc, orow) in placed:
        tris += [(ps, [(c + oc, r + orow) for c, r in uvs]) for ps, uvs in copy.tris]
    data, faces = _sweep_obj_lines(tris, anchors, SWEEP_HALF[box], SWEEP_SHIFT[box])
    what = {"strips": "straight-edge strips", "seams": "ratio-2 seam pairs and fan V-gaps"}[family]
    return obj(
        "uzp_tie_sweep",
        f"Decision 272 tie-order sweep, {what}, mesh box {box}: {len(placed)} copies of one UV "
        "configuration at swept 3D positions, scales and vertex orders.",
        [("uzp_tie_sweep", faces)],
        "".join(data),
    )


def _sweep_obj_lines(
    tris: list[Tri], anchors: tuple[float, float], half: float, shift: Vec3
) -> tuple[list[str], list[str]]:
    """The OBJ data and face lines of copies' triangles (layout UVs in texels of a 512 px tile)
    and of two box anchors in the slot `anchors`: positions moved by `shift` and written as
    exact float32 decimals, the box fixed at +-`half` in x and z and +-64 cm in y."""
    anchor_column, anchor_row = anchors
    tris = list(tris)
    for k, sign in enumerate((-1.0, 1.0)):
        corner = sign * half
        step = -0.25 * sign
        y = sign * SWEEP_Y_HALF
        ps = [(corner, y, corner), (corner + step, y, corner), (corner, y, corner + step)]
        c = anchor_column + k
        layout = [(c + 0.625, anchor_row + 0.875), (c + 0.875, anchor_row + 0.875)]
        layout.append((c + 0.625, anchor_row + 0.625))
        tris.append((ps, layout))
    data: list[str] = []
    faces: list[str] = []
    positions: dict[Vec3, int] = {}
    normals: dict[str, int] = {}
    uv_count = 0
    for ps, uvs in tris:
        area = sum(
            uvs[i][0] * -uvs[(i + 1) % 3][1] - uvs[(i + 1) % 3][0] * -uvs[i][1] for i in range(3)
        )
        assert area > 0, "every sweep triangle is counter-clockwise in UV"
        n = _normal(*ps)
        text = f"vn {_number(n[0])} {_number(n[1])} {_number(n[2])}\n"
        if text not in normals:
            data.append(text)
            normals[text] = len(normals) + 1
        refs = []
        for p, (c, r) in zip(ps, uvs, strict=True):
            q = (p[0] + shift[0], p[1] + shift[1], p[2] + shift[2])
            if q not in positions:
                data.append(f"v {_f32(q[0])} {_f32(q[1])} {_f32(q[2])}\n")
                positions[q] = len(positions) + 1
            data.append(
                f"vt {_number(c / SWEEP_RESOLUTION)} {_number(1.0 - r / SWEEP_RESOLUTION)}\n"
            )
            uv_count += 1
            refs.append(f"{positions[q]}/{uv_count}/{normals[text]}")
        faces.append(f"f {' '.join(refs)}\n")
    return data, faces


# --- Decision 278: concave seam-gate probes ---------------------------------------------------

# Copies of one flat seam pair (decision 266's `seam-r1-turn90` at side 4): A a 4 x 4 cm square
# at 1 texel per cm, B beyond A's seam edge, folded about it by a signed dihedral angle (positive
# concave: B rises on the side of A's normal; negative convex), its own UV island at ratio 1
# turned 90 degrees. B is a parallelogram `depth` texels across the seam whose far edge is
# sheared by `shear` * depth along the seam, so that the apex of B's seam triangle sits off the
# seam's midpoint by a chosen amount and its elevation above A's plane differs from the fold
# angle. A copy may be scaled and tilted as a whole. Copies are packed as decision 272's (UV
# shelves 7 texels apart, 3D boxes disjoint) in one texture set `uzp_concave_fold`, the mesh box
# exactly [-256, 256] cm in x and z and [-64, 64] in y.
FOLD_PROBES = ("fold", "shape", "fine")
FOLD_SIDE = 4
FOLD_B_COLUMN = FOLD_SIDE + 8  # B's UV box: 8 texels right of A's left edge (covered 8 apart)
FOLD_GAP_3D = 2  # cm between the 3D boxes of neighbouring copies
FOLD_TILTS: dict[str, tuple[Vec3, float]] = {
    "flat": ((1.0, 0.0, 0.0), 0.0),
    "x90": ((1.0, 0.0, 0.0), 90.0),
    "oblique": ((1.0, 2.0, 3.0), 37.0),
}


def _turned(p: Vec3, axis: Vec3, degrees: float) -> Vec3:
    """`p` turned by `degrees` about `axis` through the origin (Rodrigues); multiples of 90
    degrees about a coordinate axis stay exact."""
    if degrees == 0:
        return p
    norm = math.sqrt(sum(a * a for a in axis))
    k = [a / norm for a in axis]
    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    if degrees % 90 == 0:
        cos, sin = round(cos), round(sin)
    dot = sum(a * b for a, b in zip(k, p, strict=True))
    cross = (k[1] * p[2] - k[2] * p[1], k[2] * p[0] - k[0] * p[2], k[0] * p[1] - k[1] * p[0])
    return _vec3([p[i] * cos + cross[i] * sin + k[i] * dot * (1 - cos) + 0.0 for i in range(3)])


class FoldCopy:
    """One copy of the fold pair: the signed fold `angle` in degrees, B's `depth` and `shear`,
    the diagonals of A's and B's quads (`splits`, as `_quad_tris`), a uniform `scale` and a
    `tilt` of FOLD_TILTS. Its triangles are in local cm (A in y = 0 over x in [-side, 0], the
    seam on the z axis from (0, 0, 0) to (0, 0, -side)), with layout UVs from the slot's top-left
    texel; `size` is the UV slot."""

    def __init__(
        self,
        name: str,
        angle: float,
        depth: float = FOLD_SIDE,
        shear: float = 0.0,
        splits: tuple[int, int] = (1, 1),
        scale: float = 1.0,
        tilt: str = "flat",
    ) -> None:
        self.name, self.angle, self.depth, self.shear = name, angle, depth, shear
        self.splits, self.scale, self.tilt = splits, scale, tilt
        side = float(FOLD_SIDE)
        cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        if angle % 90 == 0:
            cos, sin = round(cos), round(sin)
        axis, degrees = FOLD_TILTS[tilt]

        def place(x: float, y: float, z: float) -> Vec3:
            return _turned((x * scale + 0.0, y * scale + 0.0, z * scale + 0.0), axis, degrees)

        a_pq = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
        a3 = [place(p - side, 0.0, -q) for p, q in a_pq]
        a_uv = [(0.25 + p, 0.125 + side - q) for p, q in a_pq]
        along = shear * depth
        b_pq = [(0.0, 0.0), (depth, along), (depth, side + along), (0.0, side)]
        b3 = [place(p * cos, p * sin, -q) for p, q in b_pq]
        b_uv = [(FOLD_B_COLUMN + 0.25 + side + along - q, 0.125 + depth - p) for p, q in b_pq]
        self.tris: list[Tri] = _quad_tris(a3, a_uv, splits[0]) + _quad_tris(b3, b_uv, splits[1])
        self.size = (
            math.ceil(FOLD_B_COLUMN + 0.25 + side + along),
            math.ceil(0.125 + max(side, depth)),
        )

    def bounds(self) -> tuple[Vec3, Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return _vec3(low), _vec3(high)


def _steps(start: float, stop: float, step: float) -> list[float]:
    return [start + step * j for j in range(round((stop - start) / step) + 1)]


# The shape probe's B quads: name -> (depth, shear, B's split). With side 4, the apex of B's seam
# triangle sits along the seam at shear * depth - 2 (split 0) or 2 + shear * depth (split 1) from
# the seam's midpoint, so its offset over its height across the seam is 0, 1 or 2.
FOLD_SHAPES: dict[str, tuple[float, float, int]] = {
    "d4-k0.5-s0": (4.0, 0.5, 0),  # offset 0: apex over the midpoint
    "d4-k0.5-s1": (4.0, 0.5, 1),  # 4 / 4 = 1
    "d4-k1.5-s0": (4.0, 1.5, 0),  # 4 / 4 = 1
    "d2-k0-s1": (2.0, 0.0, 1),  # 2 / 2 = 1
    "d4-k1.5-s1": (4.0, 1.5, 1),  # 8 / 4 = 2
    "d1-k0-s1": (1.0, 0.0, 1),  # 2 / 1 = 2
}


# The fine probe's fold angles (degrees, both signs): 0.01 degree steps from 9.75 to 10.25 and
# 0.001 degree steps from 9.951 to 10.05 around the 10 degrees that the fold probe brackets, then
# wide folds up to 178 degrees.
FOLD_FINE = sorted(
    {round(a, 3) for a in _steps(9.75, 10.25, 0.01) + _steps(9.951, 10.05, 0.001)}
    | {20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 150.0, 165.0, 170.0, 172.0, 175.0, 178.0}
)


def fold_copies(probe: str) -> list[FoldCopy]:
    """The copies of the `fold` probe (the base pair swept concave from 6 to 16 degrees in 0.25
    degree steps with both diagonals, convex and flat controls, tilted and scaled copies), of
    the `shape` probe (six B shapes swept concave from 6 to 36 degrees in 0.5 degree steps) or
    of the `fine` probe (the base pair at FOLD_FINE, concave then convex)."""
    copies: list[FoldCopy] = []
    if probe == "fine":
        return [FoldCopy(f"fine-a{s * a:+.3f}", s * a) for s in (1, -1) for a in FOLD_FINE]
    if probe == "fold":
        for splits in ((1, 1), (0, 0)):
            tag = f"s{splits[0]}{splits[1]}"
            copies += [
                FoldCopy(f"base-{tag}-a{a:+.2f}", a, splits=splits) for a in _steps(6, 16, 0.25)
            ]
        copies += [
            FoldCopy(f"control-a{a:+.2f}", a)
            for a in (0.0, -6.0, -10.0, -12.5, -15.0, -20.0, -45.0)
        ]
        for tilt in ("x90", "oblique"):
            copies += [FoldCopy(f"tilt-{tilt}-a{a:+.2f}", a, tilt=tilt) for a in _steps(6, 16, 0.5)]
        for scale in (0.5, 2.0, 4.0):
            copies += [
                FoldCopy(f"scale{scale:g}-a{a:+.2f}", a, scale=scale) for a in _steps(6, 16, 0.5)
            ]
        return copies
    for shape, (depth, shear, split) in FOLD_SHAPES.items():
        copies += [
            FoldCopy(f"{shape}-a{a:+.2f}", a, depth, shear, (1, split)) for a in _steps(6, 36, 0.5)
        ]
    return copies


def fold_layout(
    probe: str,
) -> tuple[list[tuple[FoldCopy, tuple[float, float], Vec3]], tuple[float, float]]:
    """Every copy with its UV slot's top-left texel (decision 272's shelves) and its 3D offset
    (whole centimetres, shelves along x then z, layers in y), and the anchors' UV slot."""
    return _pack(fold_copies(probe))


def _pack(
    copies: list[Any],
) -> tuple[list[tuple[Any, tuple[float, float], Vec3]], tuple[float, float]]:
    """`fold_layout`'s packing of any copies with `size`, `bounds()` and `tris`."""
    limit = SWEEP_RESOLUTION - SWEEP_MARGIN
    column, row, shelf = SWEEP_MARGIN, SWEEP_MARGIN, 0
    x, z, depth, layer = -250.0, -250.0, 0.0, -60.0
    placed = []
    for copy in copies:
        width, height = copy.size
        if column + width > limit:
            column, row, shelf = SWEEP_MARGIN, row + shelf + SWEEP_GAP, 0
        low, high = copy.bounds()
        extent = [math.ceil(h - lo) for lo, h in zip(low, high, strict=True)]
        if x + extent[0] > 250:
            x, z, depth = -250.0, z + depth + FOLD_GAP_3D, 0.0
        if z + extent[2] > 250:
            x, z, depth, layer = -250.0, -250.0, 0.0, layer + 30.0
        offset = (x - math.floor(low[0]), layer - math.floor(low[1]), z - math.floor(low[2]))
        assert layer + extent[1] < SWEEP_Y_HALF, "the fold copies do not fit the mesh box"
        placed.append((copy, (float(column), float(row)), offset))
        column += width + SWEEP_GAP
        shelf = max(shelf, height)
        x += extent[0] + FOLD_GAP_3D
        depth = max(depth, extent[2])
    anchors = (float(SWEEP_MARGIN), float(row + shelf + SWEEP_GAP))
    assert anchors[1] + 1 <= limit, "the fold copies do not fit their tile"
    return placed, anchors


def concave_fold(probe: str) -> bytes:
    """The decision 278 mesh of `probe`: positions as exact float32 decimals, the box fixed at
    [-256, 256] cm in x and z and [-64, 64] in y."""
    placed, anchors = fold_layout(probe)
    data, faces = _packed_obj_lines(placed, anchors)
    what = {
        "fold": "the base pair folded concave 6 to 16 degrees, convex and flat controls, tilted "
        "and scaled copies",
        "shape": "six B shapes whose seam-triangle apex sits off the seam's midpoint, folded "
        "concave 6 to 36 degrees",
        "fine": "the base pair folded concave and convex by 9.75 to 10.25 degrees in steps down "
        "to 0.001 degree and by 20 to 178 degrees",
    }[probe]
    return obj(
        "uzp_concave_fold",
        f"Decision 278 concave seam-gate probe: {len(placed)} copies of one ratio-1 seam pair, "
        f"{what}.",
        [("uzp_concave_fold", faces)],
        "".join(data),
    )


def _packed_obj_lines(
    placed: list[tuple[Any, tuple[float, float], Vec3]], anchors: tuple[float, float]
) -> tuple[list[str], list[str]]:
    """The OBJ lines of packed copies: each moved to its UV slot and 3D offset, the box exactly
    [-256, 256] cm in x and z and [-64, 64] in y."""
    tris: list[Tri] = []
    for copy, (oc, orow), offset in placed:
        tris += [
            (
                [_vec3([p[i] + offset[i] for i in range(3)]) for p in ps],
                [(c + oc, r + orow) for c, r in uvs],
            )
            for ps, uvs in copy.tris
        ]
    return _sweep_obj_lines(tris, anchors, 256.0, (0.0, 0.0, 0.0))


# --- Decision 289: far-side hinge probes ------------------------------------------------------

# Copies of decision 278's seam pair (A a 4 x 4 cm square at 1 texel per cm, B beyond A's seam
# edge in its own UV island turned 90 degrees, the seam on the z axis from (0, 0, 0) to
# (0, 0, -4)) whose islands are bent along hinges: each island is a list of bands from the seam
# outward, `(uv_depth, angle, gap, stretch)`, a band hinged to the one before it by the signed
# dihedral `angle` (degrees; positive concave: the band rises on the side of the previous band's
# normal), `gap` texels of UV moved away from the previous band (a UV seam with shared 3D
# vertices when non-zero) and `stretch` texels of UV per cm. B's first band is folded about the
# seam by `fold`. A `sliver` (d, angle) replaces B's first two bands by a triangle J with
# vertices (0, 0), (d, 4) and (0, 4) in (depth, along) and the rest of B hinged to it along
# J's edge from (0, 0) to (d, 4). Positions are computed in each island's unfolded frame, the
# hinges applied from the farthest in, so every hinge's near face is still in the frame's plane.
HINGE_PROBES = ("far", "vary", "single")
HINGE_FOLD = -6.0  # the seam fold of every family but econc and eflat: convex, below 278's gate
HINGE_ANGLES = [s * a for a in range(2, 31, 2) for s in (1, -1)] + [0]
HINGE_GAP = 1.0 / 16.0
# Far-side hinges on both sides of decision 278's gate (about 9.94 degrees, bracket (9.930,
# 9.940]), for decision 282's per-hinge gate: 9.935 lies inside the bracket.
HINGE_GATE_ANGLES = [
    s * a
    for a in (9.0, 9.5, 9.75, 9.9, 9.92, 9.935, 9.95, 10.0, 10.25, 10.5, 11.0)
    for s in (1, -1)
]
Band = tuple[float, float, float, float]


def _band(depth: float, angle: float = 0.0, gap: float = 0.0, stretch: float = 1.0) -> Band:
    return (depth, angle, gap, stretch)


class HingeCopy:
    """One hinge copy: A's and B's bands (A's sum to 4 texels of depth, B's to at most 4), the
    seam `fold`, an optional `sliver`, the quads' diagonal `split` (as `_quad_tris`) and a
    `tilt` of FOLD_TILTS. `tris` are A's then B's triangles in local cm with layout UVs from the
    slot's top-left texel; `faces` group them by planar face (A's from the seam outward, then
    B's), `hinges` are (near face, far face, designed signed angle), the seam first; `size` is
    the UV slot."""

    def __init__(
        self,
        name: str,
        b: list[Band],
        a: list[Band] | None = None,
        fold: float = HINGE_FOLD,
        sliver: tuple[float, float] | None = None,
        split: int = 1,
        tilt: str = "flat",
    ) -> None:
        self.name, self.fold, self.sliver, self.split, self.tilt = name, fold, sliver, split, tilt
        a = a or [_band(FOLD_SIDE)]
        side = float(FOLD_SIDE)
        assert sum(band[0] for band in a) == side and sum(band[0] for band in b) <= side
        # A: depth s from the seam toward -x, UV column 4.25 - s and row 4.125 - q.
        a_tris = self._island(a, lambda s, q: (0.25 + side - s, 0.125 + side - q), -1.0)
        b_depth = sum(band[0] + band[2] for band in b)
        b_col = FOLD_B_COLUMN + 0.25 + side

        def b_uv(s: float, q: float) -> tuple[float, float]:
            return (b_col - q, 0.125 + b_depth - s)

        if sliver is None:
            b_tris = self._island(b, b_uv, 1.0)
            b_faces = [[2 * k, 2 * k + 1] for k in range(len(b))]
            b_angles = [band[1] for band in b[1:]]
        else:
            b_tris = self._sliver(b, b_uv, *sliver)
            b_faces, b_angles = [[0], [1, 2]], [sliver[1]]
        cos, sin = math.cos(math.radians(fold)), math.sin(math.radians(fold))
        b_tris = [
            ([(x * cos - y * sin, x * sin + y * cos, z) for x, y, z in ps], u) for ps, u in b_tris
        ]
        n, m = len(a_tris), len(a)
        self.faces = [[2 * k, 2 * k + 1] for k in range(m)] + [[i + n for i in f] for f in b_faces]
        self.hinges = [(0, m, fold)]
        self.hinges += [(k - 1, k, band[1]) for k, band in enumerate(a) if k]
        self.hinges += [(m + k, m + k + 1, angle) for k, angle in enumerate(b_angles)]
        axis, degrees = FOLD_TILTS[tilt]
        self.tris: list[Tri] = [
            ([_turned(_vec3(p), axis, degrees) for p in ps], uvs) for ps, uvs in a_tris + b_tris
        ]
        self.size = (math.ceil(b_col), math.ceil(0.125 + max(side, b_depth)))

    def _island(self, bands: list[Band], uv: Any, direction: float) -> list[Tri]:
        """The bands' quads in the island's unfolded frame (depth s along x times `direction`,
        y = 0, along q on -z), each band turned about its near edge with every band beyond it,
        the farthest hinge first."""
        side = float(FOLD_SIDE)
        quads = []
        s3 = s_uv = 0.0
        for depth, _, gap, stretch in bands:
            s_uv += gap
            pq = [(s3, 0.0), (s3 + depth / stretch, 0.0), (s3 + depth / stretch, side), (s3, side)]
            uvs = [(s_uv, 0.0), (s_uv + depth, 0.0), (s_uv + depth, side), (s_uv, side)]
            quads.append(([(s * direction, 0.0, -q) for s, q in pq], [uv(s, q) for s, q in uvs]))
            s3, s_uv = s3 + depth / stretch, s_uv + depth
        points = [ps for ps, _ in quads]
        for k in range(len(bands) - 1, 0, -1):
            centre = points[k][0]
            turned = _hinge_turn(points[k:], centre, (0.0, 0.0, -1.0), bands[k][1], points[k][1])
            points[k:] = turned
        # A's quads run clockwise in UV in this order: start them at their far edge instead.
        order = [0, 1, 2, 3] if direction > 0 else [1, 0, 3, 2]
        tris: list[Tri] = []
        for ps, (_, uvs) in zip(points, quads, strict=True):
            tris += _quad_tris([_vec3(ps[i]) for i in order], [uvs[i] for i in order], self.split)
        return tris

    def _sliver(self, bands: list[Band], uv: Any, d: float, angle: float) -> list[Tri]:
        """J = (0, 0), (d, 4), (0, 4) and K = (0, 0), (depth, 0), (depth, 4), (d, 4) of B in
        (depth, along), K hinged to J by `angle` about J's edge from (0, 0) to (d, 4)."""
        side = float(FOLD_SIDE)
        [(depth, _, gap, stretch)] = bands
        assert gap == 0.0 and stretch == 1.0
        j_pq = [(0.0, 0.0), (d, side), (0.0, side)]
        k_pq = [(0.0, 0.0), (depth, 0.0), (depth, side), (d, side)]
        [k3] = _hinge_turn(
            [[(s, 0.0, -q) for s, q in k_pq]],
            (0.0, 0.0, 0.0),
            (d, 0.0, -side),
            angle,
            (depth, 0.0, 0.0),
        )
        j_tri: Tri = ([_vec3((s, 0.0, -q)) for s, q in j_pq], [uv(s, q) for s, q in j_pq])
        k_tris = _quad_tris([_vec3(p) for p in k3], [uv(s, q) for s, q in k_pq], self.split)
        return [j_tri, *k_tris]

    def bounds(self) -> tuple[Vec3, Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return _vec3(low), _vec3(high)


def _hinge_turn(
    groups: list[list[Vec3]], centre: Vec3, axis: Vec3, angle: float, ref: Vec3
) -> list[list[Vec3]]:
    """`groups` turned about the line through `centre` along `axis` (in the plane y = 0) by
    `angle` degrees (Rodrigues), the sense chosen so that a positive angle lifts `ref`, a
    point of y = 0 off the line, toward +y: concave for a near face in y = 0 with normal +y."""
    if angle == 0:
        return groups
    norm = math.sqrt(sum(a * a for a in axis))
    k = [a / norm for a in axis]
    r = [ref[i] - centre[i] for i in range(3)]
    lift = k[2] * r[0] - k[0] * r[2]  # (k x r)_y: the y rate of `ref` turned by +theta
    assert abs(r[1]) < 1e-12 and abs(lift) > 1e-9
    theta = math.radians(angle) * (1.0 if lift > 0 else -1.0)
    cos, sin = math.cos(theta), math.sin(theta)

    def turn(p: Vec3) -> Vec3:
        rel = [p[i] - centre[i] for i in range(3)]
        dot = sum(a * b for a, b in zip(k, rel, strict=True))
        if max(abs(rel[i] - k[i] * dot) for i in range(3)) < 1e-12:
            return p  # on the hinge: shared with the near face, so kept bit for bit
        cross = (
            k[1] * rel[2] - k[2] * rel[1],
            k[2] * rel[0] - k[0] * rel[2],
            k[0] * rel[1] - k[1] * rel[0],
        )
        return _vec3(
            [
                rel[i] * cos + cross[i] * sin + k[i] * dot * (1 - cos) + centre[i] + 0.0
                for i in range(3)
            ]
        )

    return [[turn(p) for p in group] for group in groups]


def _strip(j: float, angle: float, rest: Band | None = None) -> list[Band]:
    """B as J (depth `j`, at the seam) and K (the rest, hinged by `angle`)."""
    return [_band(j), rest or _band(FOLD_SIDE - j, angle)]


def hinge_copies(probe: str) -> list[Any]:
    """The copies of the `far` probe (one far-side hinge beyond J at two J depths, two hinges,
    a sliver J and a J-depth sweep), of the `vary` probe (the hinge across a UV seam, a
    stretched K, a concave and a flat seam fold, a bent own island and own taps two faces
    away) or of the `single` probe (decision 282's single-hinge fold sweep below the gate and
    the base family's other diagonal and an oblique tilt, then far-side hinges on both sides of
    decision 278's gate behind a 6 and a 20 degree convex seam)."""
    copies: list[Any] = []
    sweep = HINGE_ANGLES
    if probe == "far":
        copies += [HingeCopy(f"strip-a{a:+d}", _strip(0.4375, a)) for a in sweep]
        copies += [HingeCopy(f"strip-fk-a{a:+d}", _strip(0.125, a)) for a in sweep]
        copies += [
            HingeCopy(f"two-a{a:+d}", [_band(0.3125), _band(0.1875, a), _band(3.5, a)])
            for a in sweep
        ]
        copies += [HingeCopy(f"sliver-a{a:+d}", [_band(FOLD_SIDE)], sliver=(1.0, a)) for a in sweep]
        copies += [
            HingeCopy(f"jsweep-j{j:g}-a{a:+d}", _strip(j, a))
            for j in (0.0625, 0.125, 0.1875, 0.3125, 0.4375, 0.5625)
            for a in (-24, -12, 12, 24)
        ]
        return copies
    if probe == "vary":
        copies += [
            HingeCopy(f"seam-a{a:+d}", _strip(0.4375, a, _band(3.5, a, HINGE_GAP))) for a in sweep
        ]
        copies += [
            HingeCopy(f"stretch-a{a:+d}", _strip(0.4375, a, _band(3.5625, a, stretch=1.5)))
            for a in sweep
        ]
        copies += [HingeCopy(f"econc-a{a:+d}", _strip(0.4375, a), fold=6.0) for a in sweep]
        copies += [HingeCopy(f"eflat-a{a:+d}", _strip(0.4375, a), fold=0.0) for a in sweep]
        copies += [
            HingeCopy(f"ecurve-a{a:+d}", _strip(0.4375, a), a=[_band(0.1875), _band(3.8125, -6.0)])
            for a in sweep
        ]
        copies += [
            HingeCopy(
                f"own-a{a:+d}", [_band(FOLD_SIDE)], a=[_band(2.0), _band(0.5, a), _band(1.5, a)]
            )
            for a in sweep
        ]
        return copies
    for splits in ((1, 1), (0, 0)):
        tag = f"s{splits[0]}{splits[1]}"
        copies += [
            FoldCopy(f"single-{tag}-a{a:+.1f}", a, splits=splits) for a in _steps(0.5, 9.5, 0.5)
        ]
    copies += [FoldCopy(f"single-a{-a:+.1f}", -a) for a in _steps(0.5, 9.5, 0.5)]
    copies += [HingeCopy(f"strip-s0-a{a:+d}", _strip(0.4375, a), split=0) for a in sweep]
    copies += [
        HingeCopy(f"strip-oblique-a{a:+d}", _strip(0.4375, a), tilt="oblique") for a in sweep
    ]
    gate = HINGE_GATE_ANGLES
    copies += [HingeCopy(f"gate-e6-a{a:+.3f}", _strip(0.4375, a)) for a in gate]
    copies += [HingeCopy(f"gate-e20-a{a:+.3f}", _strip(0.4375, a), fold=-20.0) for a in gate]
    copies += [HingeCopy(f"strip-e20-a{a:+d}", _strip(0.4375, a), fold=-20.0) for a in sweep]
    copies += [
        HingeCopy(
            f"gate-two-e20-a{a:+.3f}", [_band(0.3125), _band(0.1875, a), _band(3.5, a)], fold=-20.0
        )
        for a in gate
    ]
    return copies


def hinge_layout(
    probe: str,
) -> tuple[list[tuple[Any, tuple[float, float], Vec3]], tuple[float, float]]:
    return _pack(hinge_copies(probe))


def hinge_probe(probe: str) -> bytes:
    """The decision 289 mesh of `probe`: positions as exact float32 decimals, the box fixed at
    [-256, 256] cm in x and z and [-64, 64] in y."""
    placed, anchors = hinge_layout(probe)
    data, faces = _packed_obj_lines(placed, anchors)
    what = {
        "far": "a hinge beyond the far triangle swept convex and concave 2 to 30 degrees, at two "
        "far-triangle depths, two hinges deep, a sliver far triangle, and a far-triangle depth "
        "sweep",
        "vary": "the far-side hinge across a UV seam, under a stretched UV, behind a concave and a "
        "flat seam fold and a bent own island, and own taps two faces away",
        "single": "decision 278's pair folded 0.5 to 9.5 degrees concave and convex, the hinge "
        "sweep with the other diagonal and tilted, and far-side hinges of 9 to 11 degrees on both "
        "sides of decision 278's gate behind 6 and 20 degree convex seams",
    }[probe]
    return obj(
        "uzp_hinge",
        f"Decision 289 far-side hinge probe: {len(placed)} copies of one ratio-1 seam pair, "
        f"{what}.",
        [("uzp_hinge", faces)],
        "".join(data),
    )


# --- Decision 289 (for decision 291): window-side probe -------------------------------------

# Flat seam pairs (A x in [-4, 0], B x in [0, 4], both q in [0, 4] cm, y = 0, 1 texel per cm)
# whose islands map to UV by a proper rotation with a rational cosine and sine (Pythagorean
# triples) and a translation chosen so that, in exact arithmetic, the far point f of two of A's
# ring texels beyond the seam lies on a window boundary: f_u - 1/2 an integer for one, f_v - 1/2
# for the other. The oblique island's UVs are not dyadic, so the written float32 UVs put f a few
# 1e-5 texel to one side, and the decoded window reads Painter's side directly.
SIDE_TRIPLES = (
    (3, 4, 5),
    (4, 3, 5),
    (5, 12, 13),
    (12, 5, 13),
    (8, 15, 17),
    (15, 8, 17),
    (7, 24, 25),
    (24, 7, 25),
)
SIDE_ORDERS = ((1, 0), (0, 0), (1, 1))  # (quad diagonal as `_quad_tris`, vertex rotation)
Exact2 = tuple[Fraction, Fraction]


def _side_turn(rot: Exact2, x: Fraction, q: Fraction) -> Exact2:
    """(column, row) of the point (x, q) cm under an island's rotation, before its origin."""
    c, s = rot
    return (c * x - s * q, -(s * x + c * q))


def _side_ring(uv: list[Exact2]) -> set[tuple[int, int]]:
    """The uncovered 8-neighbours of a convex UV quad's covered texel centres, exactly."""

    def inside(x: int, y: int) -> bool:
        px, py = Fraction(2 * x + 1, 2), Fraction(2 * y + 1, 2)
        sides = [
            (q[0] - p[0]) * (py - p[1]) - (q[1] - p[1]) * (px - p[0])
            for p, q in zip(uv, uv[1:] + uv[:1], strict=True)
        ]
        return all(v > 0 for v in sides) or all(v < 0 for v in sides)

    lo_c, hi_c = math.floor(min(c for c, _ in uv)), math.ceil(max(c for c, _ in uv))
    lo_r, hi_r = math.floor(min(r for _, r in uv)), math.ceil(max(r for _, r in uv))
    cells = {(x, y) for x in range(lo_c, hi_c) for y in range(lo_r, hi_r) if inside(x, y)}
    near = {(x + dx, y + dy) for x, y in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    return near - cells


class SideCopy:
    """One window-side copy: `oblique` "b" turns B by the triple (A axis-aligned, its UV box
    at `offset`), "a" turns A (B axis-aligned); `cos` and `sin` are exact. `targets` are two of
    A's ring texels beyond the seam, with the axis and the exact far coordinate (column or row,
    texel centres at + 1/2) that lies on a window boundary; `tris` are A's then B's triangles in
    local cm with layout UVs from the slot's top-left texel; `uv_exact` their exact corners."""

    def __init__(
        self,
        name: str,
        cos: Fraction,
        sin: Fraction,
        oblique: str,
        offset: Exact2 = (Fraction(1, 4), Fraction(1, 8)),
        order: tuple[int, int] = (1, 0),
    ) -> None:
        self.name, self.oblique, self.order = name, oblique, order
        one, zero, side = Fraction(1), Fraction(0), Fraction(FOLD_SIDE)
        a_rot, b_rot = ((one, zero), (cos, sin)) if oblique == "b" else ((cos, sin), (one, zero))
        a_xq = [(-side, zero), (zero, zero), (zero, side), (-side, side)]
        b_xq = [(zero, zero), (side, zero), (side, side), (zero, side)]
        a_raw = [_side_turn(a_rot, x, q) for x, q in a_xq]
        a_origin = (offset[0] - min(c for c, _ in a_raw), offset[1] - min(r for _, r in a_raw))
        a_uv = [(c + a_origin[0], r + a_origin[1]) for c, r in a_raw]
        beyond = []
        for cell in sorted(_side_ring(a_uv)):
            x, q = self.ring_point(a_rot, a_origin, cell)
            if 0 < x < 1 and 0 < q < side:
                beyond.append((x, q, cell))
        beyond.sort()
        (xu, qu, cu), (xv, qv, cv) = beyond[0], beyond[1]
        b_raw = [_side_turn(b_rot, x, q) for x, q in b_xq]
        fu, fv = _side_turn(b_rot, xu, qu)[0], _side_turn(b_rot, xv, qv)[1]
        col0 = max(c for c, _ in a_uv) + 8 - min(c for c, _ in b_raw)
        col0 += (Fraction(1, 2) - fu - col0) % 1  # f_u - 1/2 an integer, B at least 8 right of A
        row0 = Fraction(1, 8) - min(r for _, r in b_raw)
        row0 += (Fraction(1, 2) - fv - row0) % 1
        b_uv = [(c + col0, r + row0) for c, r in b_raw]
        self.targets = [(cu, "u", fu + col0), (cv, "v", fv + row0)]
        split, rot = order
        self.tris: list[Tri] = []
        for xq, uv in ((a_xq, a_uv), (b_xq, b_uv)):
            corners = [(float(x), 0.0, float(-q) + 0.0) for x, q in xq]
            tris = _quad_tris(corners, [(float(c), float(r)) for c, r in uv], split)
            self.tris += [(ps[rot:] + ps[:rot], us[rot:] + us[:rot]) for ps, us in tris]
        self.uv_exact = a_uv + b_uv
        self.size = (
            math.ceil(max(c for c, _ in self.uv_exact)),
            math.ceil(max(r for _, r in self.uv_exact)),
        )

    @staticmethod
    def ring_point(rot: Exact2, origin: Exact2, cell: tuple[int, int]) -> Exact2:
        """The (x, q) cm of texel `cell`'s centre through an island's map, exactly."""
        c, s = rot
        du = Fraction(2 * cell[0] + 1, 2) - origin[0]
        dv = -(Fraction(2 * cell[1] + 1, 2) - origin[1])
        return (c * du + s * dv, -s * du + c * dv)

    def bounds(self) -> tuple[Vec3, Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return _vec3(low), _vec3(high)


# A's UV box corner, in sixteenths of a texel off the 1/8 grid, searched in this order.
SIDE_OFFSETS = [
    (Fraction(a, 16), Fraction(b, 16)) for a in range(1, 16, 2) for b in range(1, 16, 2)
]
SIDE_MARGIN = 1.0 / 64.0  # texel: every centre this far from every edge, beyond the 1/256 snap


def side_margin(copy: SideCopy | CornerCopy) -> float:
    """The smallest texel distance from a texel centre to an edge of the copy's triangles."""
    low = math.inf
    for _, uvs in copy.tris:
        cols, rows = [c for c, _ in uvs], [r for _, r in uvs]
        for x in range(math.floor(min(cols)) - 1, math.ceil(max(cols)) + 1):
            for y in range(math.floor(min(rows)) - 1, math.ceil(max(rows)) + 1):
                for p, q in zip(uvs, uvs[1:] + uvs[:1], strict=True):
                    ex, ey = q[0] - p[0], q[1] - p[1]
                    t = ((x + 0.5 - p[0]) * ex + (y + 0.5 - p[1]) * ey) / (ex * ex + ey * ey)
                    t = min(max(t, 0.0), 1.0)
                    low = min(low, math.hypot(x + 0.5 - p[0] - t * ex, y + 0.5 - p[1] - t * ey))
    return low


def side_copies() -> list[SideCopy]:
    """Every triple both ways round and with both signs of the sine: B turned with A's box at
    the first two SIDE_OFFSETS that keep SIDE_MARGIN in all three orders, and A turned at the
    first; each in the three diagonal and vertex orders of SIDE_ORDERS."""
    copies: list[SideCopy] = []
    for a, b, n in SIDE_TRIPLES:
        for sign in (1, -1):
            cos, sin, tag = Fraction(a, n), Fraction(sign * b, n), f"{a}-{sign * b}-{n}"
            for oblique, wanted in (("b", 2), ("a", 1)):
                found = 0
                for k, offset in enumerate(SIDE_OFFSETS):
                    trial = [
                        SideCopy(
                            f"{oblique}-{tag}-o{k}-s{o[0]}r{o[1]}", cos, sin, oblique, offset, o
                        )
                        for o in SIDE_ORDERS
                    ]
                    if min(map(side_margin, trial)) >= SIDE_MARGIN:
                        copies += trial
                        found += 1
                        if found == wanted:
                            break
                assert found == wanted, (tag, oblique)
    return copies


def side_layout() -> tuple[list[tuple[Any, tuple[float, float], Vec3]], tuple[float, float]]:
    return _pack(side_copies())


def window_side() -> bytes:
    """The window-side mesh: positions exact, the box fixed at [-256, 256] cm in x and z and
    [-64, 64] in y."""
    placed, anchors = side_layout()
    data, faces = _packed_obj_lines(placed, anchors)
    return obj(
        "uzp_window_side",
        f"Decision 289 window-side probe (decision 291): {len(placed)} flat seam pairs whose "
        "oblique island is turned by a Pythagorean angle, so that two ring texels' far points lie "
        "exactly on a window boundary in exact arithmetic and a few 1e-5 texel off it in float32.",
        [("uzp_window_side", faces)],
        "".join(data),
    )


# --- Decision 298: corner-reach probe ----------------------------------------------------------

# Copies of one island corner, for decision 294's corner reach: island A (1 texel per cm) is two
# triangles F1 = (V, W1, C) and F2 = (V, C, W2) meeting along the hinge V C. Its seam edges
# e1 = V W1 (F1's) and e2 = V W2 (F2's) meet at the UV corner V, where A's boundary bends by
# `bend` degrees (0: e2 continues e1 straight). F2 is folded about V C by `facet` degrees
# (positive concave), so that e2 lies on another planar face than F1. B1 lies across e1, folded
# about it by its gate's angle; B2 lies across e2 in F2's plane. Each is its own UV island, a
# translate of its unfolded place. The target ring texel T lies `across` texels beside e1 and
# `reach` texels from V, so that e2's nearest point to T is its end V and T's tau is F1. The
# local frame: x and y in texels, y up, V at the origin, e1 up the y axis and A on the side
# x < 0; 3D (x, 0, -y) cm before the folds.
CORNER_ARM = 4.0  # |V W1| = |V W2| = |V C|
CORNER_DEPTH = 2.0  # B2's depth across e2, and a full B1's across e1
CORNER_EMPTY = 0.375  # an empty B1's depth: a strip between two texel columns, no centre covered
CORNER_GAP = 4  # whole texels between a copy's UV islands
CORNER_FACET = 6.0  # F2 folded concave about V C, below decision 278's gate
# B1 per gate variant, as (fold about e1 in degrees, depth). g and ge: concave past decision 278's
# gate, so e1 is gated for T (T lies beyond e1, behind B1's plane); ve: convex past the gate's
# dot product but open for T (T lies in front of B1's plane); oe: convex below the gate, open;
# n: no B1, e1 is no seam. The e variants' B1 covers no texel, so that e1 never feeds T a tap.
CORNER_GATES: dict[str, tuple[float, float] | None] = {
    "g": (20.0, CORNER_DEPTH),
    "ge": (20.0, CORNER_EMPTY),
    "ve": (-20.0, CORNER_EMPTY),
    "oe": (-6.0, CORNER_EMPTY),
    "n": None,
}
# The islands' sub-texel UV translations (columns, rows), the first that keeps SIDE_MARGIN.
CORNER_SHIFTS = ((0.25, 0.25), (0.25, 0.375), (0.375, 0.25), (0.125, 0.25), (0.25, 0.125))
# T's distance from e1, searched in this order: thirty-seconds of a texel outward from 1/2.
CORNER_ACROSS = sorted((k / 32 for k in range(10, 23)), key=lambda a: (abs(a - 0.5), a))
CORNER_TARGET = (5, 4)  # T's texel in the copy's slot
# T's distances from V: across decision 294's D_g bracket [0.974615, 1.020004) and D_o bracket
# [1.075926, 1.208074), 0.90 to 1.30 (no reach is a cap); a coarse subset for the side families.
CORNER_REACHES = (
    0.90, 0.95, 0.975, 0.985, 0.995, 1.005, 1.015, 1.03, 1.06,
    1.08, 1.10, 1.12, 1.14, 1.16, 1.18, 1.20, 1.25, 1.30,
)  # fmt: skip
CORNER_COARSE = (0.95, 0.99, 1.03, 1.10, 1.18, 1.25)


class CornerCopy:
    """One corner copy: the boundary's `bend` at V (degrees), B1's `gate` (CORNER_GATES), F2's
    `facet` fold about V C, T's `reach` (texels from V) and `across` (from e1), the B quads'
    diagonal `split` (as `_quad_tris`) and the B islands' sub-texel `shift`. `tris` are F1's,
    F2's, B1's then B2's triangles in local cm with layout UVs from the slot's top-left texel;
    `faces` group them by planar piece, `hinges` are (near piece, far piece, designed signed
    angle); `target` is T's texel in the slot and `size` the UV slot."""

    def __init__(
        self,
        name: str,
        bend: float,
        reach: float,
        gate: str = "g",
        facet: float = CORNER_FACET,
        across: float = 0.5,
        split: int = 1,
        shift: tuple[float, float] = CORNER_SHIFTS[0],
    ) -> None:
        self.name, self.bend, self.reach, self.gate, self.facet = name, bend, reach, gate, facet
        self.across, self.split, self.shift = across, split, shift
        t = math.radians(bend)
        sin, cos = math.sin(t), math.cos(t)
        if bend % 90 == 0:
            sin, cos = float(round(sin)), float(round(cos))
        arm = CORNER_ARM
        v, w1 = (0.0, 0.0), (0.0, arm)
        w2 = (-arm * sin + 0.0, -arm * cos + 0.0)
        c = (-arm * math.cos(t / 2), arm * math.sin(t / 2))
        out2 = (CORNER_DEPTH * cos, -CORNER_DEPTH * sin + 0.0)
        b2 = [v, w2, (w2[0] + out2[0], w2[1] + out2[1]), out2]

        def m3(p: tuple[float, float]) -> Vec3:
            return (p[0] + 0.0, 0.0, -p[1] + 0.0)

        f2_3d, b2_3d = _hinge_turn(
            [[m3(v), m3(c), m3(w2)], [m3(p) for p in b2]], m3(v), m3(c), facet, m3(w2)
        )
        b = math.sqrt(reach * reach - across * across)
        vc, vr = CORNER_TARGET[0] + 0.5 - across, CORNER_TARGET[1] + 0.5 + b

        def layout(p: tuple[float, float], by: tuple[float, float]) -> tuple[float, float]:
            return (vc + p[0] + by[0], vr - p[1] + by[1])

        zero = (0.0, 0.0)
        self.tris: list[Tri] = [
            ([m3(v), m3(w1), m3(c)], [layout(p, zero) for p in (v, w1, c)]),
            (f2_3d, [layout(p, zero) for p in (v, c, w2)]),
        ]
        self.faces = [[0], [1]]
        self.hinges = [(0, 1, facet)]
        right = vc
        b1_shape = CORNER_GATES[gate]
        if b1_shape is not None:
            fold, depth = b1_shape
            b1 = [v, (depth, 0.0), (depth, arm), w1]
            [b1_3d] = _hinge_turn([[m3(p) for p in b1]], m3(v), (0.0, 0.0, -1.0), fold, m3(b1[1]))
            if depth == CORNER_EMPTY:  # between two texel centre columns, 1/16 texel from one
                s1 = (math.floor(vc) + CORNER_GAP + 0.5625 - vc, shift[1])
            else:
                s1 = (CORNER_GAP + shift[0], shift[1])
            self.tris += _quad_tris([_vec3(p) for p in b1_3d], [layout(p, s1) for p in b1], split)
            self.faces.append([2, 3])
            self.hinges.append((0, 2, fold))
            right = vc + s1[0] + depth
        n2 = math.ceil(right + CORNER_GAP - shift[0] - vc - min(p[0] for p in b2))
        s2 = (n2 + shift[0], shift[1])
        self.tris += _quad_tris([_vec3(p) for p in b2_3d], [layout(p, s2) for p in b2], split)
        self.faces.append([len(self.tris) - 2, len(self.tris) - 1])
        self.hinges.append((1, len(self.faces) - 1, 0.0))
        uvs = [uv for _, us in self.tris for uv in us]
        self.target = CORNER_TARGET
        self.size = (math.ceil(max(u for u, _ in uvs)), math.ceil(max(r for _, r in uvs)))

    def bounds(self) -> tuple[Vec3, Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return _vec3(low), _vec3(high)


def corner_copy(bend: float, reach: float, gate: str, facet: float = CORNER_FACET) -> CornerCopy:
    """The copy at the first `across`, diagonal and shift (CORNER_ACROSS, then split 1 and 0,
    then CORNER_SHIFTS) that keeps every texel centre SIDE_MARGIN from every edge."""
    name = f"{gate}-b{bend:g}-f{facet:g}-r{reach:.3f}"
    for across in CORNER_ACROSS:
        for split in (1, 0):
            for shift in CORNER_SHIFTS:
                copy = CornerCopy(name, bend, reach, gate, facet, across, split, shift)
                if side_margin(copy) >= SIDE_MARGIN:
                    return copy
    raise AssertionError(name)


def corner_copies() -> list[CornerCopy]:
    """Over CORNER_REACHES: the gated (g) and no-seam (n) corners bent 90, 30, 10, 2 and 0
    degrees; the empty-B1 gated (ge) and open (oe) corners bent 90, 10 and 0 degrees; the convex
    past-the-dot open corner (ve) bent 90 and 10 degrees. Over CORNER_COARSE: g and n bent 0.05,
    0.25 and 1 degree (around the collinear exemption's |sin| <= 1e-3), and g and n bent 90 and
    10 degrees with F2 folded 0 (one planar face), 2 and 20 degrees."""
    copies = [
        corner_copy(bend, r, gate)
        for gate in ("g", "n")
        for bend in (90.0, 30.0, 10.0, 2.0, 0.0)
        for r in CORNER_REACHES
    ]
    copies += [
        corner_copy(bend, r, gate)
        for gate in ("ge", "oe")
        for bend in (90.0, 10.0, 0.0)
        for r in CORNER_REACHES
    ]
    copies += [corner_copy(bend, r, "ve") for bend in (90.0, 10.0) for r in CORNER_REACHES]
    copies += [
        corner_copy(bend, r, gate)
        for gate in ("g", "n")
        for bend in (0.05, 0.25, 1.0)
        for r in CORNER_COARSE
    ]
    copies += [
        corner_copy(bend, r, gate, facet)
        for facet in (0.0, 2.0, 20.0)
        for gate in ("g", "n")
        for bend in (90.0, 10.0)
        for r in CORNER_COARSE
    ]
    return copies


def corner_layout() -> tuple[list[tuple[Any, tuple[float, float], Vec3]], tuple[float, float]]:
    return _pack(corner_copies())


def corner_reach() -> bytes:
    """The decision 298 mesh: positions as exact float32 decimals, the box fixed at
    [-256, 256] cm in x and z and [-64, 64] in y."""
    placed, anchors = corner_layout()
    data, faces = _packed_obj_lines(placed, anchors)
    return obj(
        "uzp_corner",
        f"Decision 298 corner-reach probe: {len(placed)} copies of one island corner whose seam "
        "edges meet at a bent UV corner, one of them on another planar face, the ring texel "
        "beyond the corner at 0.90 to 1.30 texel from it, the other edge gated, open or no seam.",
        [("uzp_corner", faces)],
        "".join(data),
    )


# --- Decision 293: the Normal mesh-map combination probe --------------------------------------

# Two texture sets with the same UV layout: the Normal mesh map is bound on `uzp_nc_mesh` only,
# so `uzp_nc_free` pads the mesh-free normal of the same content. Each set holds four 48 x 48
# texel islands, one centred in each quadrant of the 256 px tile, their borders on texel
# boundaries (dyadic UVs). Island (qx, qy), qx and qy 0 or 1 from the top-left: the Height ramp
# when qx = 1, the Normal-channel patch when qy = 1.
COMBINE_SETS = ("uzp_nc_mesh", "uzp_nc_free")
COMBINE_SIZE = 256
COMBINE_QUADRANT = 128
COMBINE_ISLAND = 48
COMBINE_MARGIN = 40  # texels from the quadrant's top-left corner to the island's
# The Height of a ramp island is constant on its top and left COMBINE_BAND texels: every Height
# tap that a covered texel's Sharp stencil reads outside the island (left and up) is a padded
# copy of that constant, so every covered normal is independent of the Height ring.
COMBINE_BAND = 24
COMBINE_FLOOR = -0.95  # the signed Height everywhere but a ramp island's ramp
COMBINE_RAMP = 0.0035  # the ramp's signed Height per texel squared: floor + COMBINE_RAMP u v


def combine_island(qx: int, qy: int) -> tuple[int, int]:
    """The top-left texel (column, row from the top) of island (qx, qy)."""
    return qx * COMBINE_QUADRANT + COMBINE_MARGIN, qy * COMBINE_QUADRANT + COMBINE_MARGIN


def combine_mesh() -> bytes:
    """Eight 4.8 cm quads in the XZ plane (normal +Y), one per island of each set; the free
    set's copies lie 20 cm further along z."""
    data: list[str] = ["vn 0.0 1.0 0.0\n"]
    groups: list[tuple[str, list[str]]] = []
    for index_set, name in enumerate(COMBINE_SETS):
        faces: list[str] = []
        for qy in (0, 1):
            for qx in (0, 1):
                index = index_set * 4 + qy * 2 + qx
                cx, cz, s = (qy * 2 + qx) * 6.0, index_set * 20.0, 2.4
                quad = [
                    (cx - s, 0.0, cz + s),
                    (cx + s, 0.0, cz + s),
                    (cx + s, 0.0, cz - s),
                    (cx - s, 0.0, cz - s),
                ]
                # UV corners in texels from the bottom-left, counter-clockwise like the quad.
                x0, row = combine_island(qx, qy)
                x1, y1 = x0 + COMBINE_ISLAND, COMBINE_SIZE - row
                y0 = y1 - COMBINE_ISLAND
                corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                uvs = [(x / COMBINE_SIZE, y / COMBINE_SIZE) for x, y in corners]
                lines, quad_faces = quad_obj_lines(quad, uvs, index * 4)
                data += lines
                faces += quad_faces
        groups.append((name, faces))
    return obj(
        "uzp_normal_combine",
        "Decision 293 Normal mesh-map combination probe: two texture sets (uzp_nc_mesh, "
        "uzp_nc_free) with the same four 48 x 48 texel islands at 256 px, one per quadrant.",
        groups,
        "".join(data),
    )


def _encoded(theta: float, phi: float) -> Pixel:
    """The 16-bit codes of the unit normal tilted `theta` degrees toward azimuth `phi`."""
    t, p = math.radians(theta), math.radians(phi)
    n = (math.sin(t) * math.cos(p), math.sin(t) * math.sin(p), math.cos(t))
    return tuple(code(c * 0.5 + 0.5) for c in n)


# Per quadrant (qx, qy): the mesh map's tilt at its left column and its azimuth at its top row,
# in degrees; across the quadrant the tilt grows by 20 degrees along x and the azimuth by 60
# along y, so every texel holds its own normal and no two quadrants share one.
COMBINE_MESH_TILT = {(0, 0): 15.0, (1, 0): 20.0, (0, 1): 25.0, (1, 1): 10.0}
COMBINE_MESH_AZIMUTH = {(0, 0): 0.0, (1, 0): 90.0, (0, 1): 180.0, (1, 1): 270.0}


def combine_mesh_map() -> bytes:
    """The Normal mesh map (16-bit RGB, OpenGL, n * 0.5 + 0.5): per quadrant its own smooth
    field of tilted normals."""

    def texel(x: int, y: int) -> Pixel:
        q = (x // COMBINE_QUADRANT, y // COMBINE_QUADRANT)
        fx = (x % COMBINE_QUADRANT) / (COMBINE_QUADRANT - 1)
        fy = (y % COMBINE_QUADRANT) / (COMBINE_QUADRANT - 1)
        return _encoded(COMBINE_MESH_TILT[q] + 20.0 * fx, COMBINE_MESH_AZIMUTH[q] + 60.0 * fy)

    return png16(COMBINE_SIZE, COMBINE_SIZE, 3, texel)


def combine_height_signed(x: int, y: int) -> float:
    """The signed Height (2t - 1) of texel (x, y): COMBINE_FLOOR, plus on the quadrants of the
    ramp islands (qx = 1) COMBINE_RAMP u v, with u and v the texels past COMBINE_BAND from the
    island's left and top borders (0 to 23 on the island, clamped beyond it). The Sharp gradient
    on the island's right column below the band is (-COMBINE_RAMP v, 23 COMBINE_RAMP), on its
    bottom row right of the band (-23 COMBINE_RAMP, COMBINE_RAMP u): up to 16 degrees of tilt,
    in a direction that changes from texel to texel."""
    qx, qy = x // COMBINE_QUADRANT, y // COMBINE_QUADRANT
    if qx != 1:
        return COMBINE_FLOOR
    x0, y0 = combine_island(qx, qy)
    top = COMBINE_ISLAND - COMBINE_BAND - 1
    u = min(max(x - x0 - COMBINE_BAND, 0), top)
    v = min(max(y - y0 - COMBINE_BAND, 0), top)
    return COMBINE_FLOOR + COMBINE_RAMP * u * v


def combine_height() -> bytes:
    """The Height bitmap (16-bit grey, t = (h + 1) / 2 of `combine_height_signed`)."""
    return png16(
        COMBINE_SIZE,
        COMBINE_SIZE,
        1,
        lambda x, y: (code((combine_height_signed(x, y) + 1.0) * 0.5),),
    )


def combine_channel() -> bytes:
    """The Normal-channel bitmap (16-bit RGB, n * 0.5 + 0.5): tilted 20 degrees at the top row
    of each quadrant to 35 at its bottom row, the azimuth from 45 degrees (plus 45 when qx = 1)
    at the left column, growing by 90 across the quadrant."""

    def texel(x: int, y: int) -> Pixel:
        qx = x // COMBINE_QUADRANT
        fx = (x % COMBINE_QUADRANT) / (COMBINE_QUADRANT - 1)
        fy = (y % COMBINE_QUADRANT) / (COMBINE_QUADRANT - 1)
        return _encoded(20.0 + 15.0 * fy, 45.0 + 45.0 * qx + 90.0 * fx)

    return png16(COMBINE_SIZE, COMBINE_SIZE, 3, texel)


def combine_mask() -> bytes:
    """The Normal-channel fill's mask (16-bit grey): 1 on the bottom quadrants (qy = 1), else 0,
    so the channel's coverage is exactly 1 on the patch islands and 0 on the others."""
    return png16(
        COMBINE_SIZE,
        COMBINE_SIZE,
        1,
        lambda x, y: (0xFFFF if y >= COMBINE_QUADRANT else 0,),
    )


# --- Literal export configurations (recipe_json) ----------------------------------------------


def config(
    maps: list[dict[str, Any]],
    roots: tuple[str, ...],
    parameters: dict[str, Any] | None = None,
) -> Config:
    """The recorder's preset over `maps` on `roots`, PNG 16, no dithering, infinite padding,
    changed by `parameters`."""
    return {
        "exportShaderParams": False,
        "defaultExportPreset": PROBE_PRESET,
        "exportPresets": [{"name": PROBE_PRESET, "maps": maps}],
        "exportList": [{"rootPath": root} for root in roots],
        "exportParameters": [{"parameters": {**PROBE_PARAMETERS, **(parameters or {})}}],
    }


BASE_RGB = probe_rgb("documentMap", "basecolor")
USER0_RGB = probe_rgb("documentMap", "user0")
HEIGHT_L = probe_grey("documentMap", "height")
NORMAL_GL = probe_rgb("virtualMap", "Normal_OpenGL")
ROUGH_L = probe_grey("documentMap", "specularroughness")
OPACITY_A = probe_channel("A", "L", "documentMap", "opacity")


def alpha_probes(roots: tuple[str, ...], paddings: tuple[dict[str, Any], ...]) -> dict[str, Config]:
    """R-090 P6: L + A (specularroughness, opacity) and RGB + A (user0, opacity), PNG 16 and
    OpenEXR 32f, under each padding."""
    maps = [
        probe_map("$textureSet_la", [*ROUGH_L, OPACITY_A]),
        probe_map("$textureSet_rgba", [*USER0_RGB, OPACITY_A]),
    ]
    probes: dict[str, Config] = {}
    for padding in paddings:
        name = padding["paddingAlgorithm"] + (
            f"-{padding['dilationDistance']}" if "dilationDistance" in padding else ""
        )
        probes[f"alpha-{name}-png16"] = config(maps, roots, padding)
        probes[f"alpha-{name}-exr32f"] = config(
            maps, roots, {**padding, "fileFormat": "exr", "bitDepth": "32f"}
        )
    return probes


RESIZE_ROOTS = ("s0", "s1", "s2", "s3")
RESIZE_MAPS = [
    probe_map("$textureSet_basecolor", BASE_RGB),
    probe_map("$textureSet_user0", USER0_RGB),
    probe_map("$textureSet_height", HEIGHT_L),
    probe_map("$textureSet_Normal_OpenGL", NORMAL_GL),
]
RESIZE_SIZES = ((9, 7), (7, 9), (8, 8), (8, 7), (7, 8))


def resize_probes() -> dict[str, Config]:
    """R2 and R-090 P4/P8: `sizeLog2` as [w, h] (only a literal configuration takes a pair), and
    `sizeLog2` 14 on one map of one set (accepted and written at 16384 px, or refused)."""
    probes = {
        f"size-{w}x{h}": config(RESIZE_MAPS, RESIZE_ROOTS, {"sizeLog2": [w, h]})
        for w, h in RESIZE_SIZES
    }
    probes["size-14"] = config(
        [probe_map("$textureSet_basecolor", BASE_RGB)], ("s3",), {"bitDepth": "8", "sizeLog2": 14}
    )
    return probes


def colour_space_probes() -> dict[str, Config]:
    """R5: file names holding `$colorSpace`, alone and inside a group, on every texture set."""
    roots = tuple(f"s{i}" for i in range(8))
    maps = [
        probe_map("$textureSet_basecolor_$colorSpace", BASE_RGB),
        probe_map("$textureSet_roughness(_$colorSpace)", ROUGH_L),
        probe_map("$textureSet_height_$colorSpace", HEIGHT_L),
    ]
    return {
        "colour-space-png16": config(maps, roots),
        "colour-space-png8": config(maps, roots, {"bitDepth": "8"}),
    }


STARTER_PRESETS = {
    "pbr-mr": "resource://starter_assets/PBR Metallic Roughness",
    "blender": "resource://starter_assets/Blender (Principled BSDF)",
}
PIPELINE_PARAMETERS = {
    "fileFormat": "png",
    "bitDepth": "16",
    "paddingAlgorithm": "infinite",
    "dithering": False,
}


def staff_maps(prefix: str) -> list[dict[str, Any]]:
    """The five maps of the Assets3D inline preset (`Pipeline/retopology/staff-v10/
    painter_export.py`, decision 100), with the file prefix `prefix`."""

    def doc(name: str, source: str) -> dict[str, Any]:
        channels = "RGB" if name == "BaseColor" else "L"
        return probe_map(
            f"{prefix}_{name}", [probe_channel(c, c, "documentMap", source) for c in channels]
        )

    return [
        doc("BaseColor", "basecolor"),
        doc("Roughness", "roughness"),
        doc("Metallic", "metallic"),
        doc("Height", "height"),
        probe_map(f"{prefix}_Normal", NORMAL_GL),
    ]


def preset_probes(root: str) -> dict[str, Config]:
    """R6/R7 and R8: the starter PBR Metallic Roughness and Blender presets with their own
    parameters and with the pipeline's overrides; the inline five-map preset at the fixture's
    256 px (`sizeLog2` 8) and resized (7)."""
    probes: dict[str, Config] = {}
    for key, url in STARTER_PRESETS.items():
        base: Config = {
            "exportShaderParams": False,
            "defaultExportPreset": url,
            "exportList": [{"rootPath": root}],
        }
        probes[f"{key}-own"] = base
        probes[f"{key}-pipeline"] = {
            **base,
            "exportParameters": [{"parameters": dict(PIPELINE_PARAMETERS)}],
        }
    for size in (8, 7):
        probes[f"inline-five-map-{size}"] = {
            "exportShaderParams": False,
            "defaultExportPreset": "v6",
            "exportPresets": [{"name": "v6", "maps": staff_maps("uzp_staff")}],
            "exportList": [{"rootPath": root}],
            "exportParameters": [{"parameters": {**PIPELINE_PARAMETERS, "sizeLog2": size}}],
        }
    return probes


GLTF_PRESET = "resource://starter_assets/glTF PBR Metal Roughness"


def gltf_preset_probes(root: str) -> dict[str, Config]:
    """Decision 314 (recording R-314): the glTF PBR Metal Roughness preset with its own
    parameters and with the pipeline's overrides."""
    base: Config = {
        "exportShaderParams": False,
        "defaultExportPreset": GLTF_PRESET,
        "exportList": [{"rootPath": root}],
    }
    return {
        "gltf-own": base,
        "gltf-pipeline": {**base, "exportParameters": [{"parameters": dict(PIPELINE_PARAMETERS)}]},
    }


def recipe(data: Config) -> bytes:
    """One configuration as an authored recipe (JSON, LF, sorted keys)."""
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


# --- Decision 317: subnormal float32 operands --------------------------------------------------

# Two 256 px float32 bitmaps, the lower (acc) and the upper (src) layer of decision 317's blend
# probe. Each component has its own role:
#   R: per 16 x 16 texel block (bx, by), acc = SUBNORMAL_VALUES[by] and src = SUBNORMAL_VALUES[bx]:
#      every ordered pair of the table, uniform inside its block.
#   G: per texel, decision 313's operand classes, non-negative as in its sweep: class 0 a
#      subnormal, class 1 a normal in [FLT_MIN, 2 FLT_MIN), class 2 a value k/2^24 in [0, 1);
#      acc takes class x mod 3, src class y mod 3 (x the column, y the row from the top), so
#      every pair of classes occurs.
#   B: per block i = 16 by + bx, acc = i/256 and src = (256 - i)/256: normal values that locate
#      the block and check that the path is exact on normal float32 values.
SUBNORMAL_SIZE = 256
SUBNORMAL_BLOCK = 16
SUBNORMAL_VALUES = (
    0x00000000,  # +0
    0x80000000,  # -0
    0x00000001,  # the smallest subnormal, 2^-149
    0x00000003,  # 3 2^-149 (0.7 of it rounds)
    0x00400000,  # 2^-127
    0x007FFFFF,  # the largest subnormal
    0x80000001,  # -2^-149
    0x807FFFFF,  # minus the largest subnormal
    0x00800000,  # FLT_MIN, the smallest normal, 2^-126
    0x00800001,  # FLT_MIN + 1 ulp (minus FLT_MIN: 2^-149)
    0x00C00000,  # 1.5 FLT_MIN (times 0.5 or 0.7: subnormal)
    0x80800000,  # -FLT_MIN
    0x3E800000,  # 0.25
    0x3F000000,  # 0.5
    0x3F800000,  # 1
    0xBE800000,  # -0.25
)
SUBNORMAL_LAYERS = ("acc", "src")
SUBNORMAL_SEEDS = {"acc": 20261019, "src": 20261317}


def subnormal_bits(layer: str) -> npt.NDArray[np.uint32]:
    """The float32 bit patterns of decision 317's `layer` bitmap, (row, column, R G B)."""
    n, block = SUBNORMAL_SIZE, SUBNORMAL_BLOCK
    rows, columns = np.indices((n, n), dtype=np.uint32)
    by, bx = rows // block, columns // block
    values = np.array(SUBNORMAL_VALUES, dtype=np.uint32)
    acc = layer == "acc"
    bits = np.empty((n, n, 3), dtype=np.uint32)
    bits[:, :, 0] = values[by if acc else bx]
    texel = rows * np.uint32(n) + columns
    k = texel * np.uint32(2654435761) + np.uint32(SUBNORMAL_SEEDS[layer])  # modulo 2^32
    mantissa = k & np.uint32(0x007FFFFF)
    unit = ((k >> np.uint32(8)).astype(np.float64) / 2.0**24).astype(np.float32)
    kind = (columns if acc else rows) % np.uint32(3)
    bits[:, :, 1] = np.where(
        kind == 0,
        mantissa | np.uint32(1),
        np.where(kind == 1, np.uint32(0x00800000) + mantissa, unit.view(np.uint32)),
    )
    index = (by * np.uint32(n // block) + bx).astype(np.float64)
    locator = (index if acc else n - index) / n
    bits[:, :, 2] = locator.astype(np.float32).view(np.uint32)
    return bits


def subnormal_bitmap(layer: str) -> bytes:
    return exr_float_rgb(subnormal_bits(layer).view(np.float32))
