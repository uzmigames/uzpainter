"""UzmiGames-authored Tier 0 fixtures: synthetic meshes (OBJ), 16-bit (one 8-bit) bitmaps (PNG)
and the export probes' configurations (JSON recipes).

Every byte is computed here from closed-form definitions, so the fixtures are reproducible and
carry no third-party data. Conventions: OBJ in centimetres, +Y up, counter-clockwise faces;
bitmap texel (x, y) is column x, row y counted from the top row of the PNG.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from collections.abc import Callable, Sequence
from typing import Any

HEADER = "# UzPainter Tier 0 semantics fixture, authored by UzmiGames (Apache-2.0).\n"

Pixel = tuple[int, ...]


def png16(
    width: int, height: int, channels: int, texel: Callable[[int, int], Pixel], bits: int = 16
) -> bytes:
    """A 16-bit (or, with `bits=8`, 8-bit) grey (1 channel) or RGB (3 channels) PNG, no
    ancillary chunks, filter 0."""
    color_type = {1: 0, 3: 2}[channels]
    pack, top = {16: (">H", 0xFFFF), 8: (">B", 0xFF)}[bits]
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            values = texel(x, y)
            if len(values) != channels:
                raise ValueError(f"texel ({x}, {y}) has {len(values)} values, not {channels}")
            for value in values:
                if not 0 <= value <= top:
                    raise ValueError(f"texel ({x}, {y}) value {value} is not a {bits}-bit code")
                raw += struct.pack(pack, value)

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, bits, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def code(value: float) -> int:
    """A value in [0, 1] as the nearest 16-bit code."""
    return round(min(max(value, 0.0), 1.0) * 0xFFFF)


# --- Bitmaps (256 x 256 unless stated) -------------------------------------------------------


def field_a() -> bytes:
    """RGB: R ramps with x, G with y (8-bit lattice codes), B takes every 16-bit code once."""
    return png16(256, 256, 3, lambda x, y: (x * 257, y * 257, x * 256 + y))


def field_b() -> bytes:
    """RGB: R ramps with y, G falls with x (8-bit lattice codes), B every 16-bit code reversed."""
    return png16(256, 256, 3, lambda x, y: (y * 257, (255 - x) * 257, 0xFFFF - (y * 256 + x)))


def grey_a() -> bytes:
    """Grey ramp along x on the 8-bit lattice."""
    return png16(256, 256, 1, lambda x, y: (x * 257,))


def grey_b() -> bytes:
    """Grey ramp along y on the 8-bit lattice."""
    return png16(256, 256, 1, lambda x, y: (y * 257,))


def mask_codes() -> bytes:
    """Grey: every 16-bit code exactly once (row-major), for mask precision."""
    return png16(256, 256, 1, lambda x, y: (y * 256 + x,))


# The 8-bit lattice codes of AO_Mixed's missed operands (recording R-092, decision 093), plus 0
# and 255 as controls: each is one constant grey bitmap.
AO_CONSTANTS = (0, 33, 127, 143, 173, 224, 240, 254, 255)


def constant_grey(code8: int) -> bytes:
    """Grey holding the 8-bit lattice code `code8` (16-bit code `code8 * 257`) at every texel."""
    return png16(256, 256, 1, lambda x, y: (code8 * 257,))


def pattern64() -> bytes:
    """RGB 64 x 64 deterministic pseudo-random codes (32-bit LCG), for resampling kernels."""
    state = [20261010]

    def nxt() -> int:
        state[0] = (state[0] * 1664525 + 1013904223) % (1 << 32)
        return state[0] >> 16

    values = [(nxt(), nxt(), nxt()) for _ in range(64 * 64)]
    return png16(64, 64, 3, lambda x, y: values[y * 64 + x])


IMPULSE_TEXELS = ((16, 16), (48, 16), (16, 48), (48, 48))


def impulse64() -> bytes:
    """RGB 64 x 64 for direct kernel reads (`compositor-resample-gaps.md` section 3): R 65535 at
    four isolated texels on 0, G 49152 at the same texels on 16384, B 65535 for x < 32 (a step)."""

    def texel(x: int, y: int) -> Pixel:
        hit = (x, y) in IMPULSE_TEXELS
        return (0xFFFF if hit else 0, 49152 if hit else 16384, 0xFFFF if x < 32 else 0)

    return png16(64, 64, 3, texel)


# hue-grid (`compositor-blend-gaps.md` section 3.3, decision 067): chromas in 16-bit codes, the
# six sectors as (max, mid) channel indices (rising, then falling), the six tie types as (the
# equal pair, whether the pair is the maximum), and the generator of the widening cases.
HUE_CHROMAS = (1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 1024, 4096)
HUE_SECTORS = ((0, 1), (1, 2), (2, 0), (0, 2), (1, 0), (2, 1))
HUE_TIES = (
    ((0, 1), True),
    ((0, 1), False),
    ((1, 2), True),
    ((1, 2), False),
    ((0, 2), True),
    ((0, 2), False),
)
HUE_STRUCTURED = len(HUE_SECTORS) * len(HUE_CHROMAS) * 7  # 504
HUE_GREY = HUE_STRUCTURED + len(HUE_TIES) * len(HUE_CHROMAS)  # 576
HUE_SEED, HUE_LCG_A, HUE_LCG_C = 20261011, 1664525, 1013904223
HUE_MAX_CHROMA = 8192


def hue_texel(centre: int, sector: tuple[int, int], d: int, u: int) -> Pixel:
    """Min = centre - d//2, max = min + d, mid = min + u, placed by the sector."""
    low = centre - d // 2
    texel = [low, low, low]
    texel[sector[0]] = low + d
    texel[sector[1]] = low + u
    return tuple(texel)


def hue_cases() -> list[list[Pixel]]:
    """Per row group r (level (r + 1)/17, centre code 3855 (r + 1)) the 4 096 cases in the
    order of the in-group texel index t = (y mod 16) * 256 + x."""
    state = HUE_SEED

    def draw() -> int:
        nonlocal state
        state = (state * HUE_LCG_A + HUE_LCG_C) % (1 << 32)
        return state >> 8

    groups: list[list[Pixel]] = []
    for r in range(16):
        centre = 3855 * (r + 1)
        cases: list[Pixel] = []
        for sector in HUE_SECTORS:
            for d in HUE_CHROMAS:
                for u in (0, 1, d // 4, d // 2, 3 * d // 4, d - 1, d):
                    cases.append(hue_texel(centre, sector, d, u))
        for (a, b), pair_is_max in HUE_TIES:
            (other,) = {0, 1, 2} - {a, b}
            for d in HUE_CHROMAS:
                low = centre - d // 2
                texel = [low + d if pair_is_max else low] * 3
                texel[other] = low if pair_is_max else low + d
                cases.append(tuple(texel))
        cases.append((centre, centre, centre))
        limit = min(HUE_MAX_CHROMA, 2 * min(centre, 0xFFFF - centre))
        while len(cases) < 4096:
            sector = HUE_SECTORS[draw() % 6]
            d = 1 + draw() % limit
            cases.append(hue_texel(centre, sector, d, draw() % (d + 1)))
        groups.append(cases)
    return groups


def hue_grid(transposed: bool = False, grey: bool = False) -> bytes:
    """RGB 256 x 256 hue cases (row group y // 16); `transposed` swaps x and y, `grey` keeps the
    red component as a grey image (the L channel's source, decision 048)."""
    groups = hue_cases()

    def texel(x: int, y: int) -> Pixel:
        if transposed:
            x, y = y, x
        value = groups[y // 16][(y % 16) * 256 + x]
        return value[:1] if grey else value

    return png16(256, 256, 1 if grey else 3, texel)


def height_ramps() -> bytes:
    """Grey height field in four quadrants: a linear ramp in x, a cone, steps, a sine ridge."""

    def texel(x: int, y: int) -> Pixel:
        qx, qy = x // 128, y // 128
        u, v = (x % 128) / 127.0, (y % 128) / 127.0
        if (qx, qy) == (0, 0):
            value = u
        elif (qx, qy) == (1, 0):
            value = max(0.0, 1.0 - 2.0 * math.hypot(u - 0.5, v - 0.5))
        elif (qx, qy) == (0, 1):
            value = math.floor(u * 4.0) / 4.0
        else:
            value = 0.5 + 0.5 * math.sin(2.0 * math.pi * 3.0 * v)
        return (code(value),)

    return png16(256, 256, 1, texel)


def normal_field(kind: str, bits: int = 16) -> bytes:
    """RGB tangent-space normals encoded as n * 0.5 + 0.5: bumps (`a`) or a tilted wave (`b`).
    The 8-bit copy (`bits=8`, decision 077) holds the 8-bit code nearest each 16-bit code c,
    round(c / 257) (never a tie: 257 is odd)."""

    def texel(x: int, y: int) -> Pixel:
        u, v = (x + 0.5) / 256.0, (y + 0.5) / 256.0
        if kind == "a":
            du = 0.6 * math.cos(2.0 * math.pi * 2.0 * u) * math.sin(2.0 * math.pi * 2.0 * v)
            dv = 0.6 * math.sin(2.0 * math.pi * 2.0 * u) * math.cos(2.0 * math.pi * 2.0 * v)
        else:
            du = 0.8 * math.sin(2.0 * math.pi * 3.0 * (u + v))
            dv = 0.3
        length = math.sqrt(du * du + dv * dv + 1.0)
        n = (-du / length, -dv / length, 1.0 / length)
        codes = tuple(code(c * 0.5 + 0.5) for c in n)
        return codes if bits == 16 else tuple(round(c / 257) for c in codes)

    return png16(256, 256, 3, texel, bits)


# --- Meshes -----------------------------------------------------------------------------------


def obj(name: str, description: str, groups: Sequence[tuple[str, list[str]]], data: str) -> bytes:
    lines = [HEADER, f"# {description}\n", f"o {name}\n", data]
    for material, faces in groups:
        lines.append(f"usemtl {material}\n")
        lines.extend(faces)
    return "".join(lines).encode("ascii")


def fmt(*values: float) -> str:
    return " ".join(f"{v:.6f}" for v in values)


def grid(columns: int, rows: int) -> bytes:
    """`columns x rows` separate 10 cm quads in the XZ plane, normal +Y, one material each
    (`s0`, `s1`, ... row-major), every quad with the full 0..1 UV square."""
    data: list[str] = ["vt 0.0 0.0\nvt 1.0 0.0\nvt 1.0 1.0\nvt 0.0 1.0\nvn 0.0 1.0 0.0\n"]
    groups: list[tuple[str, list[str]]] = []
    for index in range(columns * rows):
        cx, cz = (index % columns) * 12.0, (index // columns) * 12.0
        for dx, dz in ((-5.0, 5.0), (5.0, 5.0), (5.0, -5.0), (-5.0, -5.0)):
            data.append(f"v {fmt(cx + dx, 0.0, cz + dz)}\n")
        b = index * 4
        groups.append(
            (
                f"s{index}",
                [
                    f"f {b + 1}/1/1 {b + 2}/2/1 {b + 3}/3/1\n",
                    f"f {b + 1}/1/1 {b + 3}/3/1 {b + 4}/4/1\n",
                ],
            )
        )
    return obj(
        f"uzp_grid{columns}x{rows}",
        f"{columns * rows} quads, one texture set each (s0..s{columns * rows - 1}).",
        groups,
        "".join(data),
    )


def sphere(segments: int = 32, rings: int = 16, radius: float = 10.0) -> bytes:
    """UV sphere: longitude to u, latitude to v (seam duplicated at u = 1), smooth normals."""
    data: list[str] = []
    for ring in range(rings + 1):
        theta = math.pi * ring / rings
        for seg in range(segments + 1):
            phi = 2.0 * math.pi * seg / segments
            n = (math.sin(theta) * math.cos(phi), math.cos(theta), -math.sin(theta) * math.sin(phi))
            data.append(f"v {fmt(*(radius * c for c in n))}\n")
            data.append(f"vt {fmt(seg / segments, 1.0 - ring / rings)}\n")
            data.append(f"vn {fmt(*n)}\n")
    faces: list[str] = []

    def idx(ring: int, seg: int) -> int:
        return ring * (segments + 1) + seg + 1

    for ring in range(rings):
        for seg in range(segments):
            a, b = idx(ring, seg), idx(ring + 1, seg)
            c, d = idx(ring + 1, seg + 1), idx(ring, seg + 1)
            if ring != 0:
                faces.append(f"f {a}/{a}/{a} {b}/{b}/{b} {d}/{d}/{d}\n")
            if ring != rings - 1:
                faces.append(f"f {b}/{b}/{b} {c}/{c}/{c} {d}/{d}/{d}\n")
    return obj(
        "uzp_sphere",
        f"UV sphere, radius {radius} cm, {segments} segments x {rings} rings.",
        [("uzp_sphere", faces)],
        "".join(data),
    )


def bevelled_cube(half: float = 10.0, bevel: float = 2.0, cells: int = 8) -> bytes:
    """Cube of 20 cm with rounded (radius 2 cm) edges and corners: each face is a `cells` grid
    whose points are pushed onto the rounded box; UVs in a 3 x 2 atlas, one island per face."""
    inner = half - bevel
    faces_def = (
        ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
        ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    )
    data: list[str] = []
    faces: list[str] = []
    count = 0
    margin = 0.02
    for face, (normal, tangent, bitangent) in enumerate(faces_def):
        u0, v0 = (face % 3) / 3.0 + margin, (face // 3) / 2.0 + margin
        du, dv = 1.0 / 3.0 - 2.0 * margin, 0.5 - 2.0 * margin
        base = count
        for j in range(cells + 1):
            for i in range(cells + 1):
                s, t = -1.0 + 2.0 * i / cells, -1.0 + 2.0 * j / cells
                p = [half * (normal[k] + s * tangent[k] + t * bitangent[k]) for k in range(3)]
                c = [min(max(v, -inner), inner) for v in p]
                d = [p[k] - c[k] for k in range(3)]
                length = math.sqrt(sum(v * v for v in d))
                n = [v / length for v in d]
                q = [c[k] + bevel * n[k] for k in range(3)]
                data.append(f"v {fmt(*q)}\n")
                data.append(f"vt {fmt(u0 + du * i / cells, v0 + dv * j / cells)}\n")
                data.append(f"vn {fmt(*n)}\n")
                count += 1
        for j in range(cells):
            for i in range(cells):
                a = base + j * (cells + 1) + i + 1
                b, c2, d2 = a + 1, a + cells + 2, a + cells + 1
                faces.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c2}/{c2}/{c2}\n")
                faces.append(f"f {a}/{a}/{a} {c2}/{c2}/{c2} {d2}/{d2}/{d2}\n")
    return obj(
        "uzp_bevelled_cube",
        f"Cube {2 * half} cm, rounded edges radius {bevel} cm, {cells} x {cells} cells a face.",
        [("uzp_bevelled_cube", faces)],
        "".join(data),
    )


# ── Export probe configurations (recording request R-085, decision 087) ─────
#
# Each probe of `parity/reports/phase1/export-plan-compiler.md` section 4 is one documented
# `json_config` without `exportPath` (the recorder sets a fresh private directory): the recorder's
# preset `uzp_recorder` with PNG 16, no dithering, infinite padding, on the root paths s0 and s1,
# changed only as the probe says. Every variant of a probe is its own configuration, so a
# ValueError of one cannot hide another's outcome.

PROBE_PRESET = "uzp_recorder"
PROBE_ROOTS = ("s0", "s1")
PROBE_PARAMETERS = {
    "fileFormat": "png",
    "bitDepth": "16",
    "dithering": False,
    "paddingAlgorithm": "infinite",
}
Config = dict[str, Any]


def probe_channel(dest: str, src: str, map_type: str, name: str) -> dict[str, str]:
    return {"destChannel": dest, "srcChannel": src, "srcMapType": map_type, "srcMapName": name}


def probe_rgb(map_type: str, name: str) -> list[dict[str, str]]:
    return [probe_channel(c, c, map_type, name) for c in "RGB"]


def probe_grey(map_type: str, name: str) -> list[dict[str, str]]:
    return [probe_channel("L", "L", map_type, name)]


def probe_map(file_name: str, channels: list[dict[str, str]], **extra: Any) -> dict[str, Any]:
    return {"fileName": file_name, "channels": channels, **extra}


def probe_config(
    maps: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
    filters: dict[int, dict[str, Any]] | None = None,
    roots: Sequence[str] = PROBE_ROOTS,
) -> Config:
    """The base configuration over `maps`; `rules` follow the base parameter rule and
    `filters` gives an `exportList` entry (by index) its filter."""
    export_list: list[dict[str, Any]] = [{"rootPath": root} for root in roots]
    for index, entry_filter in (filters or {}).items():
        export_list[index]["filter"] = entry_filter
    return {
        "exportShaderParams": False,
        "defaultExportPreset": PROBE_PRESET,
        "exportPresets": [{"name": PROBE_PRESET, "maps": maps}],
        "exportList": export_list,
        "exportParameters": [{"parameters": dict(PROBE_PARAMETERS)}, *(rules or [])],
    }


BASE_RGB = probe_rgb("documentMap", "basecolor")
ROUGH_L = probe_grey("documentMap", "specularroughness")


def naming_probes() -> dict[str, Config]:
    """P1-P4 and P9 (with a non-colliding control of the two sources the collisions use)."""
    base = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    probes: dict[str, Config] = {
        "p0-control": probe_config(
            [
                probe_map("$textureSet_ctl_basecolor", BASE_RGB),
                probe_map("$textureSet_ctl_roughness", ROUGH_L),
            ]
        ),
        "p1-mesh": probe_config([probe_map("$mesh_$textureSet_a", BASE_RGB)]),
        "p1-project": probe_config([probe_map("$project_$textureSet_b", BASE_RGB)]),
        "p1-scene-material": probe_config([probe_map("$textureSet_$sceneMaterial_c", BASE_RGB)]),
        "p2-udim": probe_config([probe_map("$textureSet_$udim_d", BASE_RGB)]),
        "p2-colour-space": probe_config([probe_map("$textureSet_$colorSpace_e", BASE_RGB)]),
        "p3-group-no-wildcard": probe_config([probe_map("$textureSet(_v2)", BASE_RGB)]),
        "p3-group-nested": probe_config([probe_map("$textureSet((_$udim))", BASE_RGB)]),
        "p3-group-unclosed": probe_config([probe_map("$textureSet(_$udim", BASE_RGB)]),
        "p4-filter-tile-0-0": {
            **base,
            "exportList": [{"rootPath": "s0", "filter": {"uvTiles": [[0, 0]]}}, {"rootPath": "s1"}],
        },
        "p4-filter-tile-1-0": {
            **base,
            "exportList": [{"rootPath": "s0", "filter": {"uvTiles": [[1, 0]]}}, {"rootPath": "s1"}],
        },
        "p4-rule-tile-0-0": probe_config(
            [probe_map("$textureSet_basecolor", BASE_RGB)],
            rules=[{"filter": {"uvTiles": [[0, 0]]}, "parameters": {"bitDepth": "8"}}],
        ),
        "p9-same-name": probe_config(
            [
                probe_map("$textureSet_collide", BASE_RGB),
                probe_map("$textureSet_collide", ROUGH_L),
            ]
        ),
        "p9-case-only": probe_config(
            [probe_map("$textureSet_A", BASE_RGB), probe_map("$textureSet_a", ROUGH_L)]
        ),
    }
    return probes


def channel_probes() -> dict[str, Config]:
    """P5-P8 and P12."""
    return {
        "p5-luminance": probe_config(
            [probe_map("$textureSet_lum", [probe_channel("L", "L", "documentMap", "basecolor")])]
        ),
        "p6-alpha-of-roughness": probe_config(
            [
                probe_map(
                    "$textureSet_rgba_rough",
                    [*BASE_RGB, probe_channel("A", "A", "documentMap", "specularroughness")],
                )
            ]
        ),
        "p6-alpha-of-basecolor": probe_config(
            [
                probe_map(
                    "$textureSet_rgba_base",
                    [*BASE_RGB, probe_channel("A", "A", "documentMap", "basecolor")],
                )
            ]
        ),
        "p7-absent-alpha": probe_config(
            [
                probe_map(
                    "$textureSet_rgba_opacity",
                    [*BASE_RGB, probe_channel("A", "L", "documentMap", "opacity")],
                )
            ]
        ),
        "p8-black-l": probe_config(
            [probe_map("$textureSet_black_l", probe_grey("defaultMap", "black"))]
        ),
        "p8-black-rgb": probe_config(
            [probe_map("$textureSet_black_rgb", probe_rgb("defaultMap", "black"))]
        ),
        "p12-unbound-curvature": probe_config(
            [probe_map("$textureSet_curvature", probe_grey("meshMap", "curvature"))]
        ),
    }


def config_probes() -> dict[str, Config]:
    """P10 and P11, with the valid configuration they change as the control."""
    base = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    integer_depth = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    integer_depth["exportParameters"][0]["parameters"]["bitDepth"] = 16
    return {
        "p0-control": base,
        "p10-top-level-key": {**base, "exportPathh": "x"},
        "p10-map-key": probe_config([probe_map("$textureSet_basecolor", BASE_RGB, comment="x")]),
        "p11-integer-bit-depth": integer_depth,
    }


# P13: the legacy names never observed, and each template's own channels by their lower-case
# ChannelType names (the direct controls the aliases are paired against).
LEGACY_ALIASES = (
    "sheencolor",
    "sheenroughness",
    "sheenopacity",
    "coatopacity",
    "translucency",
    "absorptioncolor",
    "scatteringcolor",
    "specularedgecolor",
)
# Template -> its channels other than Normal, Height and CoatNormal (the base-values goldens'
# template captures), filled with distinct uniform values in s0.
ALIAS_TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "coat": (
        "templates/OpenPBR - Coat.spt",
        (
            "BaseColor",
            "BaseMetalness",
            "SpecularRoughness",
            "CoatColor",
            "CoatRoughness",
            "CoatWeight",
        ),
    ),
    "fuzz": (
        "templates/OpenPBR - Fuzz.spt",
        (
            "BaseColor",
            "BaseMetalness",
            "SpecularRoughness",
            "FuzzColor",
            "FuzzRoughness",
            "FuzzWeight",
        ),
    ),
    "subsurface": (
        "templates/OpenPBR - Subsurface Scattering.spt",
        (
            "BaseColor",
            "BaseMetalness",
            "SpecularRoughness",
            "SubsurfaceColor",
            "SubsurfaceRadiusScale",
            "SubsurfaceWeight",
        ),
    ),
}
# Distinct, well separated uniform values (Working): colours per colour channel, greys per L
# channel, all different within a template.
ALIAS_COLOURS = {
    "BaseColor": (0.8, 0.3, 0.1),
    "CoatColor": (0.2, 0.6, 0.9),
    "FuzzColor": (0.2, 0.6, 0.9),
    "SubsurfaceColor": (0.2, 0.6, 0.9),
    "SubsurfaceRadiusScale": (0.5, 0.9, 0.4),
}
ALIAS_GREYS = {
    "BaseMetalness": 0.15,
    "SpecularRoughness": 0.35,
    "CoatRoughness": 0.55,
    "FuzzRoughness": 0.55,
    "CoatWeight": 0.75,
    "FuzzWeight": 0.75,
    "SubsurfaceWeight": 0.75,
}


def alias_probes(template: str) -> dict[str, Config]:
    _, channels = ALIAS_TEMPLATES[template]
    probes = {
        f"p13-{alias}": probe_config(
            [probe_map(f"$textureSet_{alias}", probe_rgb("documentMap", alias))]
        )
        for alias in LEGACY_ALIASES
    }
    for channel in channels:
        name = channel.lower()
        probes[f"p13-direct-{name}"] = probe_config(
            [probe_map(f"$textureSet_{name}", probe_rgb("documentMap", name))]
        )
    return probes


# ── The cases decision 091 still refuses (recording request R-091, decision 093) ──────────

CONTROL = probe_config(
    [
        probe_map("$textureSet_ctl_basecolor", BASE_RGB),
        probe_map("$textureSet_ctl_roughness", ROUGH_L),
    ]
)


def r091_naming_probes() -> dict[str, Config]:
    """Groups holding an empty and a non-empty wildcard, stray `)`, three equal paths, the
    case-only collision in reversed order, and equal paths from two exportList entries."""
    collide = "$textureSet_collide"
    return {
        "p0-control": CONTROL,
        "p3-group-udim-mesh": probe_config([probe_map("$textureSet(_$udim$mesh)", BASE_RGB)]),
        "p3-group-mesh-colour-space": probe_config(
            [probe_map("$textureSet(_$mesh_$colorSpace)", BASE_RGB)]
        ),
        "p3-stray-close": probe_config([probe_map("$textureSet_x)", BASE_RGB)]),
        "p3-stray-close-after-group": probe_config([probe_map("$textureSet(_$udim))", BASE_RGB)]),
        "p9-three-equal": probe_config(
            [
                probe_map(collide, BASE_RGB),
                probe_map(collide, ROUGH_L),
                probe_map(collide, probe_grey("documentMap", "height")),
            ]
        ),
        "p9-case-only-reversed": probe_config(
            [probe_map("$textureSet_a", ROUGH_L), probe_map("$textureSet_A", BASE_RGB)]
        ),
        "p9-entries-same-root": probe_config(
            [probe_map("$textureSet_basecolor", BASE_RGB)], roots=("s0", "s0")
        ),
        "p9-entries-fixed-name": probe_config([probe_map("fixed_name", BASE_RGB)]),
        "p9-entries-fixed-name-reversed": probe_config(
            [probe_map("fixed_name", BASE_RGB)], roots=("s1", "s0")
        ),
    }


def r091_mix_probes() -> dict[str, Config]:
    """Black mixed with white, other present and absent source mixes, and a map whose export
    raises next to a map that is written."""

    def constant(dest: str, src: str, name: str) -> dict[str, str]:
        return probe_channel(dest, src, "defaultMap", name)

    absent = [probe_channel(c, "L", "documentMap", "opacity") for c in "RGB"]
    written = probe_map("$textureSet_basecolor", BASE_RGB)
    unbound = probe_map("$textureSet_curvature", probe_grey("meshMap", "curvature"))
    alias = probe_map("$textureSet_sheencolor", probe_rgb("documentMap", "sheencolor"))
    return {
        "p0-control": CONTROL,
        "p8-black-rgb": probe_config(
            [probe_map("$textureSet_black_rgb", probe_rgb("defaultMap", "black"))]
        ),
        "p8-white-l": probe_config(
            [probe_map("$textureSet_white_l", probe_grey("defaultMap", "white"))]
        ),
        "p8-black-white-rgb": probe_config(
            [
                probe_map(
                    "$textureSet_black_white_rgb",
                    [
                        constant("R", "R", "black"),
                        constant("G", "G", "white"),
                        constant("B", "B", "black"),
                    ],
                )
            ]
        ),
        "p8-black-rgb-white-alpha": probe_config(
            [
                probe_map(
                    "$textureSet_black_white_a",
                    [*probe_rgb("defaultMap", "black"), constant("A", "L", "white")],
                )
            ]
        ),
        "p7-absent-red": probe_config(
            [
                probe_map(
                    "$textureSet_absent_r",
                    [probe_channel("R", "L", "documentMap", "opacity"), *BASE_RGB[1:]],
                )
            ]
        ),
        "p7-absent-rgb-present-alpha": probe_config(
            [
                probe_map(
                    "$textureSet_absent_rgb",
                    [*absent, probe_channel("A", "L", "documentMap", "specularroughness")],
                )
            ]
        ),
        "p7-absent-only": probe_config([probe_map("$textureSet_absent_only", absent)]),
        "p12-unbound-with-written": probe_config([written, unbound]),
        "p12-unbound-with-written-reversed": probe_config([unbound, written]),
        "p13-alias-with-written": probe_config([written, alias]),
        "p13-alias-with-written-reversed": probe_config([alias, written]),
    }


def r091_key_probes() -> dict[str, Config]:
    """One undocumented key in each place decision 091 still refuses one."""
    channel_key = probe_config(
        [probe_map("$textureSet_basecolor", [{**BASE_RGB[0], "comment": "x"}, *BASE_RGB[1:]])]
    )
    entry_key = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    entry_key["exportList"][0]["comment"] = "x"
    filter_key = probe_config(
        [probe_map("$textureSet_basecolor", BASE_RGB)],
        filters={0: {"uvTiles": [[0, 0]], "comment": "x"}},
    )
    parameters_key = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    parameters_key["exportParameters"][0]["parameters"]["comment"] = "x"
    rule_key = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    rule_key["exportParameters"][0]["comment"] = "x"
    preset_key = probe_config([probe_map("$textureSet_basecolor", BASE_RGB)])
    preset_key["exportPresets"][0]["comment"] = "x"
    return {
        "p0-control": probe_config([probe_map("$textureSet_basecolor", BASE_RGB)]),
        "p10-channel-key": channel_key,
        "p10-entry-key": entry_key,
        "p10-filter-key": filter_key,
        "p10-parameters-key": parameters_key,
        "p10-rule-key": rule_key,
        "p10-preset-key": preset_key,
    }


# srcChannel A at partial coverage: s0 full, s1 at opacity 0.5, s2 masked, s3 empty.
ALPHA_ROOTS = ("s0", "s1", "s2", "s3")


def r091_alpha_probes() -> dict[str, Config]:
    def alpha_of(name: str) -> Config:
        return probe_config(
            [
                probe_map(
                    f"$textureSet_rgba_{name}",
                    [*BASE_RGB, probe_channel("A", "A", "documentMap", name)],
                )
            ],
            roots=ALPHA_ROOTS,
        )

    return {
        "p0-control": probe_config(
            [
                probe_map("$textureSet_ctl_basecolor", BASE_RGB),
                probe_map("$textureSet_ctl_roughness", ROUGH_L),
            ],
            roots=ALPHA_ROOTS,
        ),
        "p6-alpha-of-roughness": alpha_of("specularroughness"),
        "p6-alpha-of-basecolor": alpha_of("basecolor"),
    }


def r091_dotted_probes() -> dict[str, Config]:
    """`$mesh` and `$project` of a mesh file and a project file whose names hold two dots."""
    return {
        "p0-control": probe_config([probe_map("$textureSet_basecolor", BASE_RGB)]),
        "p1-mesh": probe_config([probe_map("$mesh_$textureSet_a", BASE_RGB)]),
        "p1-project": probe_config([probe_map("$project_$textureSet_b", BASE_RGB)]),
    }


# The name Painter's UI gives s0 (`Texture Set List/Name (s0)`, the recorder's UI operator).
RENAMED_SET = "renamed0"


def r091_renamed_probes() -> dict[str, Config]:
    """`$textureSet` and `$sceneMaterial` of a texture set renamed in Painter's UI, the export
    root named by the new and by the original name."""
    named = probe_map("$textureSet_$sceneMaterial_c", BASE_RGB)
    return {
        "p0-control": probe_config(
            [probe_map("$textureSet_basecolor", BASE_RGB)], roots=(RENAMED_SET, "s1")
        ),
        "p1-scene-material-new-root": probe_config([named], roots=(RENAMED_SET, "s1")),
        "p1-scene-material-old-root": probe_config([named], roots=("s0", "s1")),
    }


def export_probes() -> dict[str, dict[str, Config]]:
    """Probe group -> probe id -> configuration."""
    groups = {"naming": naming_probes(), "channels": channel_probes(), "config": config_probes()}
    groups |= {f"aliases-{template}": alias_probes(template) for template in ALIAS_TEMPLATES}
    groups |= {
        "r091-naming": r091_naming_probes(),
        "r091-mixes": r091_mix_probes(),
        "r091-keys": r091_key_probes(),
        "r091-alpha": r091_alpha_probes(),
        "r091-dotted": r091_dotted_probes(),
        "r091-renamed": r091_renamed_probes(),
    }
    return groups


def export_probe(group: str, probe: str) -> bytes:
    """One probe configuration as an authored recipe (JSON, LF, sorted keys)."""
    return (json.dumps(export_probes()[group][probe], indent=2, sort_keys=True) + "\n").encode()
