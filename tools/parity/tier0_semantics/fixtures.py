"""UzmiGames-authored Tier 0 fixtures: synthetic meshes (OBJ) and 16-bit (one 8-bit) bitmaps
(PNG).

Every byte is computed here from closed-form definitions, so the fixtures are reproducible and
carry no third-party data. Conventions: OBJ in centimetres, +Y up, counter-clockwise faces;
bitmap texel (x, y) is column x, row y counted from the top row of the PNG.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Callable, Sequence

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
