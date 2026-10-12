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
from typing import Any

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
