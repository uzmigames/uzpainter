"""Synthetic cases of the measured `infinite` padding ring (src/export/padding.h; phase1.25 item
2.7, decisions 267, 268, 270, 273 and 275), through `uzp-export-tests ring`.

Each case pads random float32 values over a small OBJ written here, and compares UzPainter's ring
texels bit for bit with a reference of the rule: on a single island this file's own (the ring
point extrapolated through the island's affine map, the covered 8-neighbours, the 4 nearest, the
exact 1/d shares quantised to 10, 8 and 6 bits, the float32 FMA lerp chain and decision 206's
rounding; equal shares ordered by decision 273's comparator, then toward +u, +v); across a UV seam
`padding_reference` (the far window of decision 275 in padding.cpp's double arithmetic). No
Painter data is read.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.padding_reference import (
    F32,
    NEIGHBOURS,
    Ring,
    box_normalised,
    chain,
    compare_distance,
    fractions,
)
from tools.parity.feasibility import png

Quad = tuple[list[tuple[float, float, float]], list[tuple[float, float]]]  # positions, UVs


class Mesh:
    """Quads (two triangles each, (0, 1, 2) and (0, 2, 3)) on a W x H tile: the OBJ, the coverage
    and the per-island maps the reference reads."""

    def __init__(self, quads: list[Quad], size: int) -> None:
        self.quads = quads
        self.size = size
        self.triangles: list[
            tuple[np.ndarray, np.ndarray]
        ] = []  # (3D (3, 3) float32, UV (3, 2) float32)
        self.island: list[int] = []
        for i, (p, uv) in enumerate(quads):
            for idx in ((0, 1, 2), (0, 2, 3)):
                self.triangles.append(
                    (np.array([p[j] for j in idx], F32), np.array([uv[j] for j in idx], F32))
                )
                self.island.append(i)
        allp = np.array([v for p, _ in quads for v in p], F32)
        lo, hi = allp.min(0), allp.max(0)
        self.normalised = [box_normalised(t, lo, hi) for t, _ in self.triangles]
        self.owner = -np.ones((size, size), int)
        for k, (_, tuv) in enumerate(self.triangles):
            uvd = tuv.astype(np.float64)
            for row in range(size):
                for col in range(size):
                    u, v = (col + 0.5) / size, 1 - (row + 0.5) / size
                    w = [
                        (uvd[(i + 1) % 3][0] - uvd[i][0]) * (v - uvd[i][1])
                        - (uvd[(i + 1) % 3][1] - uvd[i][1]) * (u - uvd[i][0])
                        for i in range(3)
                    ]
                    if (all(x >= 0 for x in w) or all(x <= 0 for x in w)) and self.owner[
                        row, col
                    ] < 0:
                        self.owner[row, col] = k

    def obj(self, path: Path) -> Path:
        lines = ["usemtl m"]
        for p, uv in self.quads:
            lines += [f"v {float(F32(a))!r} {float(F32(b))!r} {float(F32(c))!r}" for a, b, c in p]
            lines += [f"vt {float(F32(u))!r} {float(F32(v))!r}" for u, v in uv]
        for i in range(len(self.quads)):
            b = 4 * i
            lines += [
                f"f {b + 1}/{b + 1} {b + 2}/{b + 2} {b + 3}/{b + 3}",
                f"f {b + 1}/{b + 1} {b + 3}/{b + 3} {b + 4}/{b + 4}",
            ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def point(self, island: int, x: float, y: float) -> np.ndarray:
        """The 3D point of texel-space (x, y) through `island`'s affine map."""
        p, uv = self.quads[island]
        t = np.array(
            [
                [u * self.size, (1 - v) * self.size, 1.0]
                for u, v in np.array(uv, F32).astype(np.float64)
            ]
        )
        m = np.linalg.solve(t[:3], np.array(p, F32).astype(np.float64)[:3])
        result: np.ndarray = np.array([x, y, 1.0]) @ m
        return result

    def compare(self, ring: tuple[int, int], tap: tuple[int, int]) -> np.float32:
        """Decision 273's comparator distance of `tap` in its own triangle."""
        k = int(self.owner[tap[1], tap[0]])
        return compare_distance(
            self.triangles[k][1], self.normalised[k], self.size, self.size, ring, tap
        )


def reference(
    mesh: Mesh, values: np.ndarray, ring: tuple[int, int]
) -> tuple[list[tuple[int, int]], np.ndarray]:
    """The taps (tap order) and value of ring texel `ring` = (x, y) of an island without seams."""
    x, y = ring
    size = mesh.size
    own = [
        (x + dx, y + dy)
        for dy, dx in NEIGHBOURS
        if 0 <= y + dy < size and 0 <= x + dx < size and mesh.owner[y + dy, x + dx] >= 0
    ]
    island = mesh.island[max(int(mesh.owner[ty, tx]) for tx, ty in own)]
    q = mesh.point(island, x + 0.5, y + 0.5)
    cands = [
        (float(np.linalg.norm(q - mesh.point(island, tx + 0.5, ty + 0.5))), False, (tx, ty))
        for tx, ty in own
    ]

    def key(c: tuple[float, bool, tuple[int, int]]) -> tuple[Any, ...]:
        return (float(mesh.compare(ring, c[2])), -c[2][0], c[2][1])

    cands.sort(key=lambda c: c[0])
    ordered: list[tuple[float, bool, tuple[int, int]]] = []
    while cands:
        group = [c for c in cands if c[0] <= cands[0][0] * (1 + 1e-9)]
        cands = cands[len(group) :]
        ordered += sorted(group, key=key) if len(group) > 1 else group
    taps = ordered[:1] if ordered[0][0] <= 1e-6 * min(c[0] for c in ordered) else ordered[:4]
    t = fractions([c[0] for c in taps])
    out = np.array(
        [
            chain([F32(values[ty, tx, c]) for _, _, (tx, ty) in taps], t)
            for c in range(values.shape[2])
        ],
        F32,
    )
    return [c[2] for c in taps], out


def run(
    exe: Path, tmp: Path, mesh: Mesh, name: str, seed: int
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    size = mesh.size
    values = np.random.default_rng(seed).random((size, size, 3)).astype(F32)
    (tmp / f"{name}.f32").write_bytes(values.tobytes())
    case = {
        "mesh": str(mesh.obj(tmp / f"{name}.obj")),
        "material": "m",
        "width": size,
        "height": size,
        "channels": 3,
        "values": str(tmp / f"{name}.f32"),
        "out": str(tmp / f"{name}.out"),
    }
    (tmp / f"{name}.json").write_text(json.dumps([case]), encoding="utf-8")
    proc = subprocess.run(
        [str(exe), "ring", str(tmp / f"{name}.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = np.frombuffer((tmp / f"{name}.out").read_bytes(), F32).reshape(size, size, 3)
    return values, out, json.loads(proc.stdout)["ring"]


def flat_square(lo: float, hi: float, scale: float) -> Quad:
    """A UV square [lo, hi]^2 on the plane y = 0, x and z = (uv - 1/2) scale."""
    corners = [(lo, lo), (hi, lo), (hi, hi), (lo, hi)]
    return [((u - 0.5) * scale, 0.0, (v - 0.5) * scale) for u, v in corners], corners


def bits(x: Any) -> int:
    return int(np.array([x], F32).view(np.uint32)[0])


def test_straight_edge_ring_is_decision_273s_chain(export_tests: Path, tmp_path: Path) -> None:
    """A dyadic square island: each straight-edge ring texel takes its side tap (code 224 of 1023,
    t = 0x3ED41505) and the two diagonals (code 64 of 255, t = 0x3F002AD6; the shares tie exactly,
    so the strong diagonal is +x on horizontal edges, -row on vertical ones), each outer corner
    copies its diagonal (through decision 206's rounding), and every ring value equals the
    reference bit for bit."""
    mesh = Mesh([flat_square(0.25, 0.75, 4.0)], 16)
    values, out, ring = run(export_tests, tmp_path, mesh, "square", 1)
    assert len(ring) == 4 * 8 + 4
    edges = 0
    for r in ring:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        expected_taps, expected = reference(mesh, values, (x, y))
        assert taps == expected_taps, (x, y)
        assert out[y, x].view(np.uint32).tolist() == expected.view(np.uint32).tolist(), (x, y)
        if 5 <= x <= 10 and y in (3, 12):
            side = 4 if y == 3 else 11
            assert taps == [(x, side), (x + 1, side), (x - 1, side)]
        elif 5 <= y <= 10 and x in (3, 12):
            side = 4 if x == 3 else 11
            assert taps == [(side, y), (side, y - 1), (side, y + 1)]
        elif x in (3, 12) and y in (3, 12):
            copied = (F32(1) - (F32(1) - values[taps[0][1], taps[0][0]])).astype(
                F32
            )  # decision 206's rounding
            assert r["taps"] == 1 and out[y, x].tolist() == copied.tolist()
            continue
        else:
            continue
        edges += 1
        assert r["fractions"] == [0x3ED41505, 0x3F002AD6]
    assert edges == 4 * 6


def test_equal_diagonal_shares_follow_the_comparator(export_tests: Path, tmp_path: Path) -> None:
    """A square island on non-dyadic UVs and positions: the two diagonals' shares are equal, and the
    strong one is decision 273's comparator's nearer one (an exact float32 tie: +x, -row)."""
    mesh = Mesh([flat_square(0.15, 0.85, 2.9)], 20)
    values, out, ring = run(export_tests, tmp_path, mesh, "square-odd", 2)
    away = 0
    for r in ring:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        expected_taps, expected = reference(mesh, values, (x, y))
        assert taps == expected_taps, (x, y)
        assert out[y, x].view(np.uint32).tolist() == expected.view(np.uint32).tolist(), (x, y)
        if r["taps"] == 3 and taps[1][0] != taps[2][0]:
            away += taps[1][0] < taps[2][0]
        elif r["taps"] == 3:
            away += taps[1][1] > taps[2][1]
    assert away > 0  # the comparator, not the fixed direction, decided some


@pytest.mark.parametrize("offset", [0.0, 0.3])
def test_seam_ring_reads_the_far_island(export_tests: Path, tmp_path: Path, offset: float) -> None:
    """Two islands A and B, 4 x 4 texels each, sharing a 3D edge (a UV seam). The ring of A
    beyond the seam takes the 4 nearest of its covered neighbours and the far window of B
    (decision 275: B's covered texels in the 3 x 3 block of columns floor(f_u - 1/2) +- 1, rows
    ceil(f_v - 1/2) +- 1 around the ring point f folded into B), equal to `padding_reference` on
    every seam texel: with B aligned (offset 0) each such ring texel copies the B texel at
    distance 0; offset by 0.3 texel it blends far and own taps. Folding B by 90 degrees about the
    edge gives the same ring there (decision 270's unfolding)."""
    s = 1 / 32
    a_uv = [(4 * s, 16 * s), (8 * s, 16 * s), (8 * s, 20 * s), (4 * s, 20 * s)]
    b_uv = [
        (16 * s, (16 + offset) * s),
        (20 * s, (16 + offset) * s),
        (20 * s, (20 + offset) * s),
        (16 * s, (20 + offset) * s),
    ]
    a = ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)], a_uv)
    flat = Mesh(
        [a, ([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (1.0, 0.0, 1.0)], b_uv)], 32
    )
    folded = Mesh(
        [a, ([(1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0), (1.0, 0.0, 1.0)], b_uv)], 32
    )
    values, out, ring = run(export_tests, tmp_path, flat, f"seam-{offset}", 3)
    _, out_folded, ring_folded = run(export_tests, tmp_path, folded, f"seam-folded-{offset}", 3)
    for name, outcome, texels in (("seam", out, ring), ("seam-folded", out_folded, ring_folded)):
        expected = {
            (x, y): (cands, taps)
            for x, y, cands, taps in Ring(tmp_path / f"{name}-{offset}.obj", "m", 32, 32).texels()
        }
        assert sorted(expected) == sorted((r["x"], r["y"]) for r in texels)
        for r in texels:
            x, y = r["x"], r["y"]
            cands, n = expected[(x, y)]
            assert [(c[0], c[1]) for c in r["candidates"][: r["taps"]]] == [
                c[2] for c in cands[:n]
            ], (name, x, y)
            t = fractions([c[0] for c in cands[:n]])
            chosen = [values[ty, tx] for _, _, (tx, ty) in cands[:n]]
            value = [chain([v[c] for v in chosen], t) for c in range(3)]
            assert (
                outcome[y, x].view(np.uint32).tolist()
                == np.array(value, F32).view(np.uint32).tolist()
            ), (name, x, y)
    seam = [r for r in ring if r["x"] == 8]
    assert len(seam) == 6
    for r in seam:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        assert out_folded[y, x].view(np.uint32).tolist() == out[y, x].view(np.uint32).tolist(), (
            x,
            y,
        )
        if offset == 0.0 and 12 <= y <= 15:
            assert r["taps"] == 1 and taps == [(16, y)] and r["candidates"][0][3] is True
        if offset != 0.0 and 12 <= y <= 15:
            assert r["taps"] == 4 and any(c[3] for c in r["candidates"][:4])
            assert any(not c[3] for c in r["candidates"][:4])


def _source_table(path: str, name: str) -> list[int]:
    """The integer table `name` of the C++ source `path` (repo root relative)."""
    text = (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")
    body = text[text.index(name) :]
    body = body[body.index("{") + 1 : body.index("};")]
    return [int(x.rstrip("uU"), 0) for x in re.findall(r"0x[0-9A-Fa-f]+u?|\d+u?", body)]


def _unorm_write(v: np.ndarray, bits: int) -> np.ndarray:
    """arith::WriteUnorm: v clamped to [0, 1], j = floor(v 2^(n+4)), then
    (j (2^n - 1) + 2^(n+3) - 1) >> (n+4)."""
    c = np.clip(np.nan_to_num(v.astype(F32)), 0, 1).astype(F32)
    j = (c * F32(1 << (bits + 4))).astype(np.int64)
    return (j * ((1 << bits) - 1) + (1 << (bits + 3)) - 1) >> (bits + 4)


def _half_toward_zero(v: np.ndarray) -> np.ndarray:
    h = v.astype(np.float16)
    over = np.abs(h.astype(F32)) > np.abs(v)
    h[over] = np.nextafter(h[over], np.float16(0))
    return h.astype(F32)


@pytest.mark.parametrize("domain", ["L8", "sRGB8-ocio", "L16F-height"])
def test_padding_runs_in_the_document_format(
    export_tests: Path, tmp_path: Path, domain: str
) -> None:
    """Decision 274: a documentMap channel is padded on its document operands, each filled texel
    stored as its format stores it (L8: the 8-bit UNORM write; sRGB8: the GPU's float-to-sRGB8
    conversion; L16F: the half toward zero) and then written as the file writes the channel (PNG
    16: the UNORM write, the OCIO sRGB8 code table, a Height's v * 0.5 + 0.5). Synthetic codes over
    two islands sharing a seam: `process` with `document_format` equals `ring`'s padding of the
    operands passed through that store and write on every texel; the same codes padded as UNORM
    operands of the file's codes (decision 223's domain) differ from it."""
    s = 1 / 32
    a = (
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
        [(4 * s, 16 * s), (8 * s, 16 * s), (8 * s, 20 * s), (4 * s, 20 * s)],
    )
    b = (
        [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (1.0, 0.0, 1.0)],
        [(16 * s, 16.3 * s), (20 * s, 16.3 * s), (20 * s, 20.3 * s), (16 * s, 20.3 * s)],
    )
    mesh = Mesh([a, b], 32)
    rng = np.random.default_rng(274)
    channels = 3 if domain == "sRGB8-ocio" else 1
    shape = (32, 32, channels)
    case: dict[str, Any] = {"format": "png", "bit_depth": "16"}
    if domain == "L8":
        k = rng.integers(0, 256, shape)
        operands = (k / 255.0).astype(F32)
        codes = k * 257

        def store_and_write(p: np.ndarray) -> np.ndarray:
            return _unorm_write(p, 8) * 257

        case["document_format"] = "L8"
    elif domain == "sRGB8-ocio":
        arith = "src/evaluator/arith.cpp"
        decode = np.array(_source_table(arith, "kSrgb8DecodeBits[256]"), np.uint32).view(F32)
        thresholds = np.array(_source_table(arith, "kSrgb8ThresholdBits[255]"), np.uint32)
        thresholds = thresholds.view(F32).astype(np.float64)
        table = np.array(_source_table("src/export/encode.cpp", "kOcioSrgbPng16[256]"), np.int64)
        k = rng.integers(0, 256, shape)
        operands = decode[k]
        codes = table[k]

        def store_and_write(p: np.ndarray) -> np.ndarray:
            c = np.clip(np.nan_to_num(p.astype(F32)), 0, 1).astype(np.float64)
            return table[np.searchsorted(thresholds, c, side="right")]

        case.update(document_format="sRGB8", srgb8_material=True, ocio=True)
    else:
        operands = _half_toward_zero(rng.uniform(0.5, 1.0, shape).astype(F32))
        codes = _unorm_write((operands * F32(0.5) + F32(0.5)).astype(F32), 16)

        def store_and_write(p: np.ndarray) -> np.ndarray:
            return _unorm_write((_half_toward_zero(p) * F32(0.5) + F32(0.5)).astype(F32), 16)

        case.update(document_format="L16F", height=True)
    obj = mesh.obj(tmp_path / "mesh.obj")
    (tmp_path / "operands.f32").write_bytes(operands.astype(F32).tobytes())
    ring_case = {
        "mesh": str(obj),
        "material": "m",
        "width": 32,
        "height": 32,
        "channels": channels,
        "values": str(tmp_path / "operands.f32"),
        "out": str(tmp_path / "padded.f32"),
    }
    (tmp_path / "ring.json").write_text(json.dumps([ring_case]), encoding="utf-8")
    proc = subprocess.run(
        [str(export_tests), "ring", str(tmp_path / "ring.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    padded = np.frombuffer((tmp_path / "padded.f32").read_bytes(), F32).reshape(shape)
    covered = mesh.owner >= 0
    expected = np.where(covered[..., None], codes, store_and_write(padded))

    source = tmp_path / "source.png"
    png.write(source, codes.astype(np.int64), 16)
    common = {"source": str(source), "target": str(source), "mesh": str(obj), "material": "m"}
    cases = [
        dict(case, **common, out=str(tmp_path / "document.png")),
        {
            **common,
            "format": "png",
            "bit_depth": "16",
            "out": str(tmp_path / "codes.png"),
            **({"height": True} if domain == "L16F-height" else {}),
        },
    ]
    (tmp_path / "process.json").write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run(
        [str(export_tests), "process", str(tmp_path / "process.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    document = png.read(tmp_path / "document.png").astype(np.int64).reshape(shape)
    by_codes = png.read(tmp_path / "codes.png").astype(np.int64).reshape(shape)
    assert 0 < covered.sum() < covered.size
    assert np.array_equal(document, expected)
    assert not np.array_equal(by_codes[~covered], expected[~covered])
