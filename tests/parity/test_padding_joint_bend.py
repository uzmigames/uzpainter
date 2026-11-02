"""Authored invariants of the joint-bend padding probe, independent of Painter recordings."""

import math

import pytest

from tools.parity.tier0_semantics import padding_joint_bend as jb


@pytest.mark.parametrize("bend", [1.0, 2.8, 6.0, -2.8])
@pytest.mark.parametrize("deficit", [-0.001, 0.0017, 0.0105])
def test_sample_toward_the_corner_lies_the_deficit_before_the_seam_strip(
    bend: float, deficit: float
) -> None:
    copy = jb.JointCopy(bend, 0.22, deficit)
    v, w2 = copy.tris[0][1][0], copy.tris[1][1][2]  # F1 = (V, W1, C), F2 = (V, C, W2)
    ex, ey = w2[0] - v[0], w2[1] - v[1]
    length = math.hypot(ex, ey)
    g = (copy.target[0] + 0.5, copy.target[1] + 1.5)  # one row from T toward V
    assert g[0] - v[0] == pytest.approx(0.22, abs=1e-12)
    along = ((g[0] - v[0]) * ex + (g[1] - v[1]) * ey) / length
    assert along == pytest.approx(-deficit, abs=1e-12)


def test_turned_and_mirrored_copies_keep_the_triangles_counter_clockwise() -> None:
    for turn in ("r90", "mirror"):
        copy = jb.JointCopy(2.8, 0.22, 0.0017, turn)
        for _, uvs in copy.tris:
            area = sum(
                uvs[i][0] * -uvs[(i + 1) % 3][1] - uvs[(i + 1) % 3][0] * -uvs[i][1]
                for i in range(3)
            )
            assert area > 0
        assert all(c >= 0 and r >= 0 for _, uvs in copy.tris for c, r in uvs)


def test_layout_is_deterministic_and_the_request_is_registered() -> None:
    from tools.parity.recorder.job import EXPORT
    from tools.parity.tier0_semantics import recording_requests as rr

    assert len(jb.copies()) == 470
    assert jb.mesh() == jb.mesh()
    assert rr.MESH_SETS[jb.MESH] == [jb.MATERIAL]
    assert rr.REQUEST_FIXTURES[jb.MESH][2]() == jb.mesh()
    golden = jb.request()
    assert golden.name == "export-padding-joint-bend"
    assert golden.inputs == [jb.MESH, *rr.kernel_bitmaps(jb.RESOLUTION)]
    exports = [step["args"] for step in golden.sequence.steps if step["call"] == EXPORT]
    assert [(e["file_format"], e["bit_depth"], e["padding"]) for e in exports] == [
        ("exr", "32f", "infinite"),
        ("exr", "32f", "infinite"),
        ("exr", "32f", "passthrough"),
        ("exr", "32f", "passthrough"),
    ]
