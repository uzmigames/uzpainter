"""UzmiGames-authored fixtures of the Phase 1 recording requests (decision 100).

The recording plan of 2026-10-12 (R1-R8) merged with the phase1.16 request R-090
(`parity/reports/phase1/export-processing-encoders.md` section 5) needs meshes with separated UV
islands, slow ramps for dithering, an impulse texel, half-step codes, an 8-bit sRGB-tagged ramp
and the authored export configurations (`recipe_json`) of the literal export probes. Conventions
as in `fixtures.py`: OBJ in centimetres, +Y up; bitmap texel (x, y) is column x, row y from the
top row; a UV `(u, v)` covers texel column `u * N`, row `(1 - v) * N` of an N px texture.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.tier0_semantics.fixtures import (
    PROBE_PARAMETERS,
    PROBE_PRESET,
    Config,
    Pixel,
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


def recipe(data: Config) -> bytes:
    """One configuration as an authored recipe (JSON, LF, sorted keys)."""
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
