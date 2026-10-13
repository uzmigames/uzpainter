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
