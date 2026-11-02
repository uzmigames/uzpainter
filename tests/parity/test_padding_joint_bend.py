"""Authored invariants of the joint-bend padding probe, independent of Painter recordings."""

import math
from typing import Any

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


def test_corner_v_is_the_corner_one_texel_from_t_under_every_turn() -> None:
    from tools.parity.fit.padding_joint_bend import corner_v

    plain = jb.JointCopy(2.8, 0.22, 0.0017)
    mirrored = jb.JointCopy(2.8, 0.22, 0.0017, "mirror")
    turned = jb.JointCopy(2.8, 0.22, 0.0017, "r90")
    (vx, vy), _ = corner_v(plain)
    (mx, my), _ = corner_v(mirrored)
    # The mirror reverses each triangle's corners; V keeps its place mirrored about T's centre.
    assert mx - (mirrored.target[0] + 0.5) == pytest.approx((plain.target[0] + 0.5) - vx)
    assert my - mirrored.target[1] == pytest.approx(vy - plain.target[1])
    for copy in (plain, mirrored, turned):
        v, w2 = corner_v(copy)
        assert v in copy.tris[0][1] and v in copy.tris[1][1] and w2 in copy.tris[1][1]
        centre = (copy.target[0] + 0.5, copy.target[1] + 0.5)
        assert math.dist(v, centre) == pytest.approx(math.dist((vx, vy), (5.5, 4.5)))


def _row(
    g: list[int], base: list[list[int]], snap: list[list[int]], snapped: int
) -> dict[str, Any]:
    def model(bits: int, samples: list[list[int]]) -> dict[str, Any]:
        return {"bits": [bits], "e2_samples": samples}

    return {
        "g": g,
        "baseline": model(0, base),
        "baseline+snap256": model(snapped, snap),
        "baseline+eps005": model(0, base),
    }


def test_phase_pairs_read_each_copys_own_g_in_its_own_slot() -> None:
    from tools.parity.fit.padding_joint_bend import phase_pairs

    i = _row([10, 10], [[10, 10]], [], 1)
    j = _row([50, 50], [[50, 50]], [[50, 50]], 0)
    assert phase_pairs({"n-b1-a0.22-d-0.0015-none-s1": [i, j]}, "baseline+snap256") == (
        ["n-b1-a0.22-d-0.0015-none-s1"],
        ["n-b1-a0.22-d-0.0015-none-s1"],
    )


def test_phase_pairs_find_an_inside_loss_whatever_the_pair_order() -> None:
    from tools.parity.fit.padding_joint_bend import phase_pairs

    taken = _row([10, 10], [[10, 10]], [], 1)
    unowned = _row([30, 30], [], [], 0)  # an eligible pair first, without the inside condition
    owned = _row([50, 50], [[50, 50]], [[50, 50]], 0)
    for members in ([taken, unowned, owned], [owned, unowned, taken]):
        family = {"n-b1-a0.22-d-0.0015-none-s1": members}
        assert phase_pairs(family, "baseline+snap256")[1] == ["n-b1-a0.22-d-0.0015-none-s1"]


def _record(material: str = "uzp_joint_bend") -> dict[str, Any]:
    """A valid authored record: r1 and r2, an RGB32F user0..7 template, steps 45-48 x 8 maps."""
    steps = {45: "infinite", 46: "infinite", 47: "passthrough", 48: "passthrough"}
    channel = {"format": "RGB32F", "bit_depth": 32, "is_floating": True}

    def recording(rid: str, condition: str) -> dict[str, Any]:
        template = {
            "kind": "template_capture",
            "values": {
                "texture_sets": {
                    material: {
                        "resolution": [512, 512],
                        "stacks": {"": {f"User{i}": dict(channel) for i in range(8)}},
                    }
                }
            },
        }
        maps = [
            {
                "kind": "exported_map",
                "texture_set": material,
                "map": f"user{i}",
                "export_settings": {"step": step, "paddingAlgorithm": mode},
            }
            for step, mode in steps.items()
            for i in range(8)
        ]
        return {"recording_id": rid, "condition": condition, "outputs": [template, *maps]}

    return {"recordings": [recording("r1", "same_session"), recording("r2", "after_save_reopen")]}


def test_the_scorer_refuses_a_capture_whose_template_or_exports_differ() -> None:
    from tools.parity.fit.padding_joint_bend_score import record_problems

    assert record_problems(_record(), "uzp_joint_bend") == []
    wrong = _record()
    stack = wrong["recordings"][0]["outputs"][0]["values"]["texture_sets"]["uzp_joint_bend"]
    stack["stacks"][""]["User3"]["format"] = "RGB16F"
    assert record_problems(wrong, "uzp_joint_bend") == ["r1: user3 not RGB32F"]
    missing = _record()
    missing["recordings"][1]["outputs"].pop()
    duplicate = _record()
    duplicate["recordings"][1]["outputs"].append(duplicate["recordings"][1]["outputs"][1])
    for record in (missing, duplicate):
        assert record_problems(record, "uzp_joint_bend") == [
            "r2: export groups differ from steps 45-48 x user0..7"
        ]


def test_the_scorer_refuses_unstable_or_incomplete_infinite_exports() -> None:
    from types import SimpleNamespace

    from tools.parity.fit.padding_joint_bend_score import stable

    four = {k: None for k in range(4)}
    assert stable(SimpleNamespace(unstable=0, recorded=four))
    assert not stable(SimpleNamespace(unstable=1, recorded=four))
    assert not stable(SimpleNamespace(unstable=0, recorded={k: None for k in range(3)}))
