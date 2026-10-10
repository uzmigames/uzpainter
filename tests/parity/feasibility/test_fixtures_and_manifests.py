"""Authored fixtures and public manifests of the procedural feasibility study (task 2.1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tools.parity.feasibility import png
from tools.parity.feasibility.cases import FIXTURE_DIR, MANIFEST_DIR, cases, manifest
from tools.parity.feasibility.fixtures import (
    CUBE_RADIUS,
    CURVATURE_REFERENCE_RADIUS,
    MAP_NAMES,
    fixture_files,
    rounded_cube_mesh,
    rounded_cube_texels,
    sphere_mesh,
    write_fixtures,
)
from tools.parity.recorder.job import load_job
from tools.parity.schemas import Schema, validation_errors


def test_png_round_trip_at_native_depth(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    for depth, high in ((16, 65536), (8, 256)):
        for channels in (1, 2, 3, 4):
            samples = rng.integers(0, high, (7, 5, channels), dtype=np.int64)
            path = tmp_path / f"r{depth}-{channels}.png"
            png.write(path, samples, depth)
            assert np.array_equal(png.read(path), samples)


@pytest.mark.parametrize("row_filter", [0, 1, 2, 3, 4])
def test_png_decoder_undoes_every_row_filter(tmp_path: Path, row_filter: int) -> None:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "uzp_feasibility_fake_png",
        Path(__file__).parents[1] / "recorder" / "fake_painter.py",
    )
    assert spec is not None and spec.loader is not None
    fake = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fake
    spec.loader.exec_module(fake)
    pixels = [
        (x * 4099 % 65536, y * 911 % 65536, (x * y * 37) % 65536)
        for y in range(6)
        for x in range(9)
    ]
    path = tmp_path / "filtered.png"
    fake.write_png(path, 9, 6, pixels, 16, filters=[row_filter] * 6)
    decoded = png.read(path)
    assert decoded.reshape(-1, 3).tolist() == [list(p) for p in pixels]


def test_committed_fixtures_are_reproduced_byte_for_byte(tmp_path: Path) -> None:
    regenerated = write_fixtures(tmp_path)
    committed = fixture_files(FIXTURE_DIR)
    for key, path in regenerated.items():
        assert path.read_bytes() == committed[key].read_bytes(), key


def test_mesh_map_conventions() -> None:
    files = fixture_files(FIXTURE_DIR)
    sphere = {name: png.read(files[f"sphere/{name}"]) for name in MAP_NAMES}
    # A unit sphere at the origin: normalised position equals the encoded normal.
    assert np.array_equal(sphere["position"], sphere["world_space_normal"])
    assert np.all(sphere["ambient_occlusion"] == 65535)
    assert np.all(sphere["normal"] == np.array([32768, 32768, 65535]))
    flat, edge, corner = (
        round((0.5 + 0.5 * h * CURVATURE_REFERENCE_RADIUS) * 65535)
        for h in (0.0, 0.5 / CUBE_RADIUS, 1.0 / CUBE_RADIUS)
    )
    cube_curvature = png.read(files["rounded-cube/curvature"])
    assert set(np.unique(cube_curvature).tolist()) == {flat, edge, corner}
    surface = rounded_cube_texels(64)
    assert np.allclose(np.linalg.norm(surface.normal, axis=-1), 1.0)


def test_meshes_are_closed_form_and_outward() -> None:
    for mesh in (sphere_mesh(), rounded_cube_mesh()):
        a, b, c = (mesh.positions[mesh.triangles[:, k]] for k in range(3))
        cross = np.cross(b - a, c - a)
        normals = mesh.normals[mesh.triangles].sum(axis=1)
        assert np.all(np.einsum("ij,ij->i", cross, normals) > 0)
        assert np.allclose(mesh.sdf(mesh.positions), 0.0, atol=1e-9)


def test_manifests_are_public_valid_and_twice_recorded() -> None:
    on_disk = sorted(MANIFEST_DIR.glob("*.json"))
    assert on_disk == sorted(case.manifest_path for case in cases())
    for case in cases():
        document = json.loads(case.manifest_path.read_text(encoding="utf-8"))
        assert validation_errors(document, Schema.GOLDEN_PUBLIC) == []
        expected = manifest(case)
        expected["private_records"] = document["private_records"]
        assert document == expected
        kinds = [ref["kind"] for ref in document["private_records"]]
        assert kinds.count("private_oracle_record") == 1
        maps = {
            ref["record_id"].split("-", 1)[1]
            for ref in document["private_records"]
            if ref["kind"] == "exported_map"
        }
        for map_id in maps:
            ids = {ref["record_id"] for ref in document["private_records"]}
            assert {f"r1-{map_id}", f"r2-{map_id}"} <= ids
        for item in document["inputs"]:
            data = (FIXTURE_DIR.parents[2] / item["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
        load_job(case.manifest_path)
