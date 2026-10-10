"""Tier 0 polygon triangulation (phase1.4_mesh-importers, item 3.3): fixture, manifest and the
identification method on synthetic bakes. The comparison with the recorded Painter oracle runs in
`tests/mesh/test_mesh_import.py` (it needs the production importer and the owner's store)."""

from __future__ import annotations

import numpy as np

from tools.parity.polygon_triangulation.core import (
    FIXTURE_PATH,
    MANIFEST_PATH,
    POLYGONS,
    RESOLUTION,
    Codes,
    diagonals_of,
    fixture_text,
    label,
    manifest,
    polygon_domain,
    run_study,
    status,
    triangulations,
)
from tools.parity.schemas import Schema, load_json, validation_errors


def fan(n: int, corner: int) -> str:
    return label(
        frozenset(
            (min(corner, j), max(corner, j))
            for j in range(n)
            if (j - corner) % n not in (0, 1, n - 1)
        )
    )


def synthetic(truth: dict[str, str]) -> Codes:
    """A Position map of the fixture under `truth`, normalised by an affine map and quantised."""
    codes = np.zeros((RESOLUTION, RESOLUTION, 3), dtype=np.int64)
    for polygon in POLYGONS:
        domain = polygon_domain(polygon)
        xyz = domain.positions[truth[polygon.name]]
        offset, scale = np.array([1.0, 1.0, 3.0]), np.array([25.0, 2.0, 4.0])
        codes[domain.rows, domain.cols] = np.round((xyz + offset) / scale * 65535)
    return codes


def test_fixture_and_manifest_are_current() -> None:
    assert FIXTURE_PATH.read_text(encoding="utf-8") == fixture_text()
    published = load_json(MANIFEST_PATH)
    assert validation_errors(published, Schema.GOLDEN_PUBLIC) == []
    expected = manifest()
    expected["private_records"] = published["private_records"]
    assert published == expected


def test_every_triangulation_of_a_convex_polygon() -> None:
    assert [len(triangulations(n)) for n in (3, 4, 5, 6)] == [1, 2, 5, 14]
    for n in (4, 5, 6):
        labels = {label(diagonals_of(t, n)) for t in triangulations(n)}
        assert len(labels) == len(triangulations(n))
        assert all(len(t) == n - 2 for t in triangulations(n))


def test_identification_on_synthetic_bakes() -> None:
    """The method recovers the triangulation a bake was made with, and the verdict is `exact`
    only when it equals UzPainter's."""
    last = {p.name: fan(p.size, p.size - 1) for p in POLYGONS}
    first = {p.name: fan(p.size, 0) for p in POLYGONS}
    codes = synthetic(last)
    study = run_study({"r1": codes, "r2": codes}, last)
    assert study.stable and status(study) == "exact"
    for result in study.recordings:
        assert {k: v.best.triangulation for k, v in result.polygons.items()} == last
        assert all(v.identified for v in result.polygons.values())
    assert status(run_study({"r1": codes, "r2": codes}, first)) == "gap"
    other = synthetic(first)
    found = run_study({"r1": other, "r2": other}, first).recordings[0].polygons
    assert {k: v.best.triangulation for k, v in found.items()} == first
