"""Authored fixtures and public manifests of the normal-convention fixture (task 2.1)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools.parity.normal_convention.cases import CASES, FIXTURE_DIR, manifest
from tools.parity.normal_convention.fixtures import (
    CAP_FOOTPRINT_RADIUS,
    RESOLUTION,
    SHELL_SCALE,
    analytic_field,
    face_normals,
    fixture_files,
    pairs,
    plane_tangent_normal,
    read_corners,
    write_fixtures,
)
from tools.parity.recorder.job import load_job
from tools.parity.schemas import Schema, validation_errors


def test_fixture_files_are_reproducible(tmp_path: Path) -> None:
    """The committed OBJ files are exactly what the generator writes."""
    written = write_fixtures(tmp_path)
    committed = fixture_files(FIXTURE_DIR)
    for key, path in written.items():
        assert path.read_bytes() == committed[key].read_bytes(), key


def test_high_meshes_are_faceted_and_outward() -> None:
    """Every high triangle carries its geometric normal at its three corners, facing outwards."""
    for name in pairs():
        high = read_corners(fixture_files(FIXTURE_DIR)[f"{name}/high"])
        geometric = face_normals(high.positions)
        assert high.uvs is None
        for corner in range(3):
            assert np.allclose(high.normals[:, corner], geometric, atol=1e-8), name
        assert np.all(geometric[:, 1] > -1e-9), name  # nothing faces down (-Y)


def test_low_meshes() -> None:
    files = fixture_files(FIXTURE_DIR)
    plane = read_corners(files["plane-dome/low"])
    assert plane.uvs is not None
    assert np.allclose(plane.normals, [0.0, 1.0, 0.0])
    # u = (x + 1) / 2, v = (1 - z) / 2: +u is +X and +v is -Z.
    assert np.allclose(plane.uvs[..., 0], (plane.positions[..., 0] + 1) / 2)
    assert np.allclose(plane.uvs[..., 1], (1 - plane.positions[..., 2]) / 2)
    hemisphere = read_corners(files["hemisphere/low"])
    assert hemisphere.uvs is not None
    radial = hemisphere.positions / np.linalg.norm(hemisphere.positions, axis=-1, keepdims=True)
    assert np.allclose(hemisphere.normals, radial, atol=1e-8)
    shell = read_corners(files["hemisphere/high"])
    assert np.allclose(shell.positions, hemisphere.positions * SHELL_SCALE, atol=1e-8)


def test_analytic_field_of_the_plane_dome() -> None:
    files = fixture_files(FIXTURE_DIR)
    field = analytic_field(
        "plane-dome", read_corners(files["plane-dome/low"]), read_corners(files["plane-dome/high"])
    )
    assert field.world_normal.shape == (RESOLUTION, RESOLUTION, 3)
    hit = field.domain & (field.high_face >= 0)
    tangent = plane_tangent_normal(field.world_normal)
    centres = (np.arange(RESOLUTION) + 0.5) / RESOLUTION
    u, v = np.meshgrid(centres, 1 - centres)
    radius = np.hypot(2 * u - 1, 1 - 2 * v)
    assert np.all(radius[field.high_face >= 0] <= CAP_FOOTPRINT_RADIUS + 1e-9)
    # Image top half (v > 1/2, world -Z) leans towards +v: positive tangent y.
    top = hit & (v > 0.55)
    bottom = hit & (v < 0.45)
    assert np.all(tangent[..., 1][top] > 0) and np.all(tangent[..., 1][bottom] < 0)
    assert np.all(tangent[..., 2][hit] > 0.85)


def test_manifests_are_current_and_valid() -> None:
    for case in CASES:
        document = json.loads(case.manifest_path.read_text(encoding="utf-8"))
        assert validation_errors(document, Schema.GOLDEN_PUBLIC) == [], case.golden_id
        expected = manifest(case)
        expected["private_records"] = document["private_records"]
        assert document == expected, case.golden_id
        assert document["uncontrolled_settings"] == ["preferences.bake_backend"]


def test_manifests_are_recorder_jobs() -> None:
    """The recorder accepts every manifest as a job: inputs hashed, bake steps in vocabulary."""
    for case in CASES:
        job = load_job(case.manifest_path)
        assert job.golden_id == case.golden_id
        assert len(job.exports) == 1
        assert [m.map_type for m in job.exports[0].maps] == ["meshMap"]
