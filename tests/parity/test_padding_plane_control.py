"""Authored control invariants, independent of Painter recordings."""

import itertools

import numpy as np
import pytest

from tools.parity.tier0_semantics import padding_plane_control as control


@pytest.mark.parametrize("width", [4.0, 16.0])
@pytest.mark.parametrize("tilt", ["flat", "x90", "oblique"])
def test_endpoint_planes_match_across_hinge_counts(width: float, tilt: str) -> None:
    one = control.PlaneCopy(1, width, tilt, 1)
    two = control.PlaneCopy(2, width, tilt, 1)
    for i, j in [(0, 0), (2, 4), (4, 6)]:
        a, b = np.array(one.tris[i][0]), np.array(two.tris[j][0])
        normal = np.cross(a[1] - a[0], a[2] - a[0])
        normal /= np.linalg.norm(normal)
        assert np.max(np.abs((b - a[0]) @ normal)) < 1e-12
    # Shared far endpoint positions and UVs prevent a changed target plane from
    # masquerading as evidence for the hinge-count restriction.
    assert one.tris[2][0][0] == two.tris[4][0][0]
    assert one.tris[2][1][0] == two.tris[4][1][0]


def test_layout_is_deterministic_and_keeps_controls_in_fixed_box() -> None:
    placed, _ = control.layout()
    assert len(placed) == 32
    assert control.mesh() == control.mesh()
    for copy, _, offset in placed:
        for ps, _ in copy.tris:
            for p in ps:
                assert all(abs(p[i] + offset[i]) < limit for i, limit in enumerate((256, 64, 256)))
    for original, translated in zip(placed[:8], placed[8:16], strict=True):
        assert original[0].tris == translated[0].tris
        assert original[2] != translated[2]


def test_two_hinge_bevel_has_nonzero_parallel_hinges() -> None:
    copy = control.PlaneCopy(2, 4.0, "flat", 1)
    normals = []
    for i in (0, 2, 4):
        p = np.array(copy.tris[i][0])
        n = np.cross(p[1] - p[0], p[2] - p[0])
        normals.append(n / np.linalg.norm(n))
    for a, b in itertools.pairwise(normals):
        assert np.degrees(np.arccos(np.dot(a, b))) == pytest.approx(6.0)


def test_request_exports_all_channels_twice() -> None:
    from tools.parity.recorder.job import EXPORT
    from tools.parity.tier0_semantics import recording_requests as rr

    assert rr.MESH_SETS[control.MESH] == [control.MATERIAL]
    assert rr.REQUEST_FIXTURES[control.MESH][2]() == control.mesh()
    golden = control.request()
    assert golden.name == "export-padding-plane-control"
    assert golden.inputs == [control.MESH, *rr.kernel_bitmaps(512)]
    exports = [step["args"] for step in golden.sequence.steps if step["call"] == EXPORT]
    assert [(e["file_format"], e["bit_depth"], e["padding"]) for e in exports] == [
        ("exr", "32f", "infinite"),
        ("exr", "32f", "infinite"),
        ("exr", "32f", "passthrough"),
        ("exr", "32f", "passthrough"),
    ]
    assert all(e["maps"] == [f"documentMap/user{i}:RGB" for i in range(8)] for e in exports)
