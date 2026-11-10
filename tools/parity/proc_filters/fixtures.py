"""Authored content bitmaps of the filter goldens (`phase3.2_proc-filter-families`).

The filters read layer content, not mesh maps or seeds. Every golden fills its User channels with
one of these periodic 256 x 256 16-bit bitmaps, tiled by its UV projection so that one bitmap
texel lands on one texture texel at every resolution. The case input is the content channel as
Painter exported it, so the bitmaps only need to be rich: per 64 x 64 cell a different kind of
signal (pseudo-random codes, hard steps, one-texel checkers, smooth ramps, constants, the two
ends of the range).

    python -m tools.parity.proc_filters fixtures
"""

from __future__ import annotations

import math
from collections.abc import Callable

from tools.parity.tier0_semantics.fixtures import png16

SIZE = 256
CELL = 64
TOP = 0xFFFF


def _lcg(seed: int) -> Callable[[], int]:
    state = [seed]

    def nxt() -> int:
        state[0] = (state[0] * 1664525 + 1013904223) % (1 << 32)
        return state[0] >> 16

    return nxt


def _cells(seed: int) -> list[list[int]]:
    """One grey plane: a 4 x 4 arrangement of cell kinds."""
    rnd = _lcg(seed)
    noise = [[rnd() for _ in range(SIZE)] for _ in range(SIZE)]
    levels = [rnd() for _ in range(16)]
    plane = [[0] * SIZE for _ in range(SIZE)]
    for y in range(SIZE):
        for x in range(SIZE):
            cx, cy = x // CELL, y // CELL
            u, v = x % CELL, y % CELL
            kind = (cx + 3 * cy + seed) % 8
            a, b = levels[(cx + 4 * cy) % 16], levels[(cx * 5 + cy + 7) % 16]
            if kind == 0:
                value = noise[y][x]
            elif kind == 1:  # hard vertical and horizontal steps between two levels
                value = a if (u < 32) != (v < 20) else b
            elif kind == 2:  # one-texel checker
                value = a if (u + v) % 2 else b
            elif kind == 3:  # ramp along x
                value = round(u * TOP / (CELL - 1))
            elif kind == 4:  # smooth radial bump
                r = math.hypot(u - 31.5, v - 31.5) / 32.0
                value = round(TOP * max(0.0, 1.0 - r * r))
            elif kind == 5:  # range ends: black square on white with a one-texel grey line
                value = 0 if 16 <= u < 48 and 16 <= v < 48 else TOP
                value = a if u == 40 else value
            elif kind == 6:  # constant
                value = a
            else:  # sparse impulses on a mid level
                value = TOP if (u * 7 + v * 13) % 29 == 0 else (TOP if noise[y][x] < 2000 else b)
            plane[y][x] = value
    return plane


def content_grey() -> bytes:
    """The grey content of the Sharpen and Levels goldens."""
    plane = _cells(20261110)
    return png16(SIZE, SIZE, 1, lambda x, y: (plane[y][x],))


def content_rgb() -> bytes:
    """The RGB content of the diagnostic golden (Blur, Grayscale Conversion, Sharpen on RGB)."""
    planes = [_cells(20261110 + c) for c in range(3)]
    return png16(SIZE, SIZE, 3, lambda x, y: tuple(p[y][x] for p in planes))
