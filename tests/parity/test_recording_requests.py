"""Requested Tier 0 goldens of Phase 1 (decision 100): manifests prepared before the Painter
session under the current envelope's `requests/` root, and their authored fixtures."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.guard.guard import load_index, run_guard, worktree_snapshot
from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.job import load_job
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR
from tools.parity.tier0_semantics.recording_requests import (
    OCIO_SETTING,
    REQUEST_FIXTURES,
    ocio_goldens,
    probe_groups,
    request_dir,
    request_root,
    requested_goldens,
)


def request_paths() -> list[Path]:
    return sorted(request_dir(REPO_ROOT).glob("*.json"))


def test_every_requested_golden_is_committed_once() -> None:
    assert sorted(p.stem for p in request_paths()) == sorted(g.name for g in requested_goldens())
    assert ocio_goldens() == {"export-ocio-encode", "export-presets-ocio"}


@pytest.mark.parametrize("path", request_paths(), ids=lambda p: p.stem)
def test_request_validates_names_no_record_and_is_a_recorder_job(path: Path) -> None:
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["private_records"] == []
    assert manifest["golden_id"] == f"tier0/semantics/{path.stem}"
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    job = load_job(path)
    assert job.exports or job.export_probes
    ocio = OCIO_SETTING in manifest["applied_settings"]
    assert ocio == (path.stem in ocio_goldens())


def test_requests_live_beside_the_envelope_manifests() -> None:
    root = request_root(REPO_ROOT)
    assert root.name == "requests"
    assert (root.parent / "manifests").is_dir()


def obj_uvs(name: str) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[str]]:
    text = (REPO_ROOT / FIXTURE_DIR / "meshes" / f"{name}.obj").read_text(encoding="ascii")
    lines = text.splitlines()
    vertices = [tuple(float(v) for v in ln.split()[1:]) for ln in lines if ln.startswith("v ")]
    uvs = [tuple(float(v) for v in ln.split()[1:]) for ln in lines if ln.startswith("vt ")]
    return vertices, uvs, [ln for ln in lines if ln.startswith("f ")]


def test_islands_mesh_has_the_requested_gaps() -> None:
    """R1: one island on the left border, gaps of 1 and 3 texels, a turned island ~20 away."""
    _, uvs, faces = obj_uvs("islands")
    assert len(uvs) == 16 and len(faces) == 8
    texels = [(u * 256.0, v * 256.0) for u, v in uvs]
    boxes = [
        (min(x for x, _ in q), max(x for x, _ in q), min(y for _, y in q), max(y for _, y in q))
        for q in (texels[i : i + 4] for i in range(0, 16, 4))
    ]
    assert boxes[0][0] == 0.0
    assert math.isclose(boxes[1][0] - boxes[0][1], 1.0, abs_tol=1e-4)
    assert math.isclose(boxes[2][0] - boxes[1][1], 3.0, abs_tol=1e-4)
    assert 19.0 < boxes[0][2] - boxes[3][3] < 22.0
    assert all(0.0 <= x <= 256.0 and 0.0 <= y <= 256.0 for x, y in texels)


def test_seam_mesh_shares_one_3d_edge_across_two_islands() -> None:
    """R-090 P9: two quads share two vertices; their UVs form two disjoint islands, A on the
    tile's left border, B turned 90 degrees at another scale."""
    vertices, uvs, faces = obj_uvs("seam")
    assert len(vertices) == 6 and len(uvs) == 8 and len(faces) == 4
    corners = [
        {int(c.split("/")[0]) for f in faces[i : i + 2] for c in f.split()[1:]} for i in (0, 2)
    ]
    shared = corners[0] & corners[1]
    assert len(shared) == 2 and all(vertices[i - 1][0] == 10.0 for i in shared)
    a, b = uvs[:4], uvs[4:]
    assert min(u for u, _ in a) == 0.0
    assert max(u for u, _ in a) < min(u for u, _ in b)
    assert max(u for u, _ in a) < rf.SEAM_SIDE_COLUMN / 256.0 < min(u for u, _ in b)
    span = (
        max(u for u, _ in a) - min(u for u, _ in a),
        max(u for u, _ in b) - min(u for u, _ in b),
    )
    assert span == pytest.approx((0.375, 0.25))


def bitmap(name: str) -> tuple[int, int, int, list[tuple[int, ...]]]:
    path = REPO_ROOT / FIXTURE_DIR / "bitmaps" / f"{name}.png"
    image = decode_png(path)
    depth = path.read_bytes()[24]  # IHDR bit depth
    return image.width, image.height, depth, [tuple(t) for t in image.pixels]


def test_slow_ramps_cross_only_a_few_8bit_steps() -> None:
    """R3: R spans about four 8-bit steps across the tile; B stays inside one step."""
    width, height, depth, texels = bitmap("slow-ramp")
    assert (width, height, depth) == (256, 256, 16)
    reds = [t[0] for t in texels[:256]]
    assert 3 <= (max(reds) - min(reds)) / 257 <= 5
    assert {t[2] // 257 for t in texels} == {127}
    _, _, _, grey = bitmap("slow-ramp-grey")
    assert [g[0] for g in grey] == [t[0] for t in texels]


def test_impulse_half_steps_and_srgb8_ramp() -> None:
    _, _, _, impulse = bitmap("impulse-texel")
    hits = [i for i, t in enumerate(impulse) if t != (0, 0, 0)]
    x, y = rf.IMPULSE_TEXEL
    assert hits == [y * 256 + x] and impulse[hits[0]] == (65535, 65535, 65535)
    _, _, _, half = bitmap("half-steps")
    assert half[10] == (10 * 257 + 128, 10 * 257 + 129, 0)
    width, _, depth, ramp = bitmap("srgb8-ramp")
    assert (width, depth) == (256, 8) and ramp[257] == (1, 1, 254)


def test_probe_configurations_leave_the_export_path_to_the_recorder() -> None:
    for group, probes in probe_groups().items():
        for probe, config in probes.items():
            data = (REPO_ROOT / REQUEST_FIXTURES[f"probe-{group}-{probe}"][1]).read_bytes()
            assert json.loads(data) == config
            assert "exportPath" not in config
            assert config["exportList"]


def test_the_requests_and_their_fixtures_pass_the_guard() -> None:
    snapshot = worktree_snapshot(
        REPO_ROOT,
        (request_root(REPO_ROOT).relative_to(REPO_ROOT).as_posix(), FIXTURE_DIR),
    )
    assert snapshot.checked
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []
