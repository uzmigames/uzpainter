"""Synthetic geometry pins weight quantisation after box-normalised float32 distances."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.export.padding_reference import (
    F32,
    NEIGHBOURS,
    Ring,
    chain,
    compare_distance,
    fractions,
    tap_count,
)

CASES = [
    (2.0, 42.0, 320.0, 0.0, 1060162611),
    (2.0, 42.0, 256.0, 0.0, 1060174911),
    (2.0, 42.0, 256.0, 256.0, 1060174911),
    (0.75, 0.0, 320.0, 0.0, 1059055610),
    (0.75, 2.0, 320.0, 0.0, 1059067910),
]


def precision_mesh(
    tmp_path: Path,
    vertical: float,
    base: float,
    extent: float,
    offset: float,
    *,
    positive_box: bool = False,
) -> Path:
    """A small right triangle, plus another material fixing the whole mesh's box."""
    low = 0.0 if positive_box else -extent
    points = [
        (base, 0.0, base + 8 * vertical),
        (base + 8, 0.0, base),
        (base, 0.0, base),
        (low, low, low),
        (extent, low, extent),
        (low, extent, extent),
    ]
    lines = [f"v {x + offset} {y} {z + offset}" for x, y, z in points]
    lines += ["vt 0.28125 0.96875", "vt 0.53125 0.71875", "vt 0.28125 0.71875"]
    lines += ["usemtl m", "f 1/1 2/2 3/3", "usemtl bounds", "f 4/1 5/2 6/3"]
    path = tmp_path / "precision.obj"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


@pytest.mark.parametrize("vertical,base,extent,offset,weight_bits", CASES)
def test_same_triangle_weights_use_normalised_positions(
    tmp_path: Path, vertical: float, base: float, extent: float, offset: float, weight_bits: int
) -> None:
    mesh = precision_mesh(tmp_path, vertical, base, extent, offset)
    ring = Ring(mesh, "m", 32, 32)
    x, y = (8, 8) if vertical == 2.0 else (16, 9)
    own = [(x + dx, y + dy) for dy, dx in NEIGHBOURS if ring.owner[y + dy, x + dx] >= 0]
    candidates, flags = ring.candidates(x, y, own, ring.tau(x, y, own))
    chosen = candidates[: tap_count(candidates)]
    assert len(chosen) == 2 and not flags and all(not c[1] for c in chosen)
    before = list(chosen)
    weights = ring.chain_fractions(x, y, chosen)
    assert [int(w.view(np.uint32)) for w in weights] == [weight_bits]
    assert chosen == before
    # A far tap leaves the single-triangle rule; its geometric distances stay authoritative.
    mixed = [(c[0], i == 0, c[2]) for i, c in enumerate(chosen)]
    assert ring.chain_fractions(x, y, mixed) == fractions([c[0] for c in mixed])


def test_collapsed_normalised_distances_keep_geometric_weights(tmp_path: Path) -> None:
    mesh = precision_mesh(tmp_path, 2.0, 42.0, 1e10, 0.0, positive_box=True)
    ring = Ring(mesh, "m", 32, 32)
    x, y = 8, 8
    own = [(x + dx, y + dy) for dy, dx in NEIGHBOURS if ring.owner[y + dy, x + dx] >= 0]
    tau = ring.tau(x, y, own)
    candidates, _ = ring.candidates(x, y, own, tau)
    chosen = candidates[: tap_count(candidates)]
    triangle = ring.tris[tau]
    assert all(
        compare_distance(triangle.uv, triangle.normalised, 32, 32, (x, y), c[2]) == 0
        for c in chosen
    )
    assert ring.chain_fractions(x, y, chosen) == fractions([c[0] for c in chosen])


def _check_native_precision(
    export_tests: Path,
    tmp_path: Path,
    vertical: float,
    base: float,
    extent: float,
    offset: float,
    weight_bits: int,
    *,
    positive_box: bool = False,
) -> None:
    mesh = precision_mesh(tmp_path, vertical, base, extent, offset, positive_box=positive_box)
    values = np.random.default_rng(731).random((32, 32, 24)).astype(F32)
    cases = tmp_path / "cases.json"
    inputs, outputs = [], []
    for first in range(0, 24, 3):
        raw, output = tmp_path / f"values-{first}.f32", tmp_path / f"result-{first}.f32"
        raw.write_bytes(values[:, :, first : first + 3].tobytes())
        outputs.append(output)
        inputs.append(
            dict(
                mesh=str(mesh),
                material="m",
                width=32,
                height=32,
                channels=3,
                values=str(raw),
                out=str(output),
            )
        )
    cases.write_text(json.dumps(inputs), encoding="ascii")
    process = subprocess.run(
        [str(export_tests), "ring", str(cases)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    x, y = (8, 8) if vertical == 2.0 else (16, 9)
    rings = [json.loads(line)["ring"] for line in process.stdout.splitlines()]
    assert len(rings) == len(outputs)
    for ring in rings:
        texel = next(r for r in ring if (r["x"], r["y"]) == (x, y))
        assert texel["taps"] == 2 and not texel["undecided"]
        assert texel["fractions"] == [weight_bits]
    taps = [values[c[1], c[0]] for c in texel["candidates"][:2]]
    weight = np.array([weight_bits], np.uint32).view(F32)[0]
    expected = np.array([chain([v[c] for v in taps], [weight]) for c in range(24)], F32)
    actual = np.concatenate(
        [np.frombuffer(output.read_bytes(), F32).reshape(32, 32, 3)[y, x] for output in outputs]
    )
    assert np.array_equal(actual.view(np.uint32), expected.view(np.uint32))


@pytest.mark.parametrize("vertical,base,extent,offset,weight_bits", CASES)
def test_native_same_triangle_weight_precision(
    export_tests: Path,
    tmp_path: Path,
    vertical: float,
    base: float,
    extent: float,
    offset: float,
    weight_bits: int,
) -> None:
    _check_native_precision(export_tests, tmp_path, vertical, base, extent, offset, weight_bits)


def test_native_collapsed_normalised_distances(export_tests: Path, tmp_path: Path) -> None:
    _check_native_precision(
        export_tests, tmp_path, 2.0, 42.0, 1e10, 0.0, 1060174911, positive_box=True
    )
