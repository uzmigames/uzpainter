"""Authored invariants of the world-offset padding probe and its far-turn models, independent of
Painter recordings."""

from __future__ import annotations

import json
import math
import types
from typing import Any

import numpy as np

from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_world_offset as wo

REF = load_module(REPO_ROOT / "tests/export/padding_reference.py", "test_world_offset_ref")
F32 = np.float32


def test_every_position_and_uv_is_exact_in_float32() -> None:
    tris, _ = wo.triangles()
    assert wo.exact(tris)


def test_translated_copies_keep_their_shape_bit_for_bit() -> None:
    by_shape: dict[str, list[wo.OffsetCopy]] = {}
    for copy in wo.copies():
        if copy.turn == "none" and copy.scale == 1:
            by_shape.setdefault(copy.shape.name, []).append(copy)
    for copies in by_shape.values():
        base = copies[0]
        for copy in copies[1:]:
            for (ps, uvs), (qs, wvs) in zip(copy.tris, base.tris, strict=True):
                assert uvs == wvs
                for p, q in zip(ps, qs, strict=True):
                    for i in range(3):
                        moved = p[i] - copy.offset[i] + base.offset[i]
                        assert float(F32(p[i] + wo.SHIFT[i])) == p[i] + wo.SHIFT[i]
                        assert moved == q[i]


def test_seams_fold_past_the_gate_and_two_bends_of_three_do() -> None:
    folded = {}
    for shape in wo.SHAPES:
        a, b, c = shape.fold
        assert a / c <= float(REF.FOLD_GATE)  # A's normal (0, 1) against J's (-s b, a) / c
        if shape.bend is not None:
            a2, b2, c2 = shape.bend
            folded[shape.name] = (a * a2 + b * b2) / (c * c2) <= float(REF.FOLD_GATE)
    assert folded == {"b37-23v": True, "b23-53v": True, "b28-37v": False}


def test_mesh_box_scale_and_centre_are_not_powers_of_two() -> None:
    _, lo, hi = REF.obj_mesh(fit.MESH_PATH, wo.MATERIAL)
    assert lo.tolist() == [-96.0, -64.0, -150.0] and hi.tolist() == [204.0, 64.0, 150.0]
    r = float(F32(1) / F32(F32(300) * F32(0.5)))
    assert not math.log2(r).is_integer()


def test_layout_is_deterministic_and_the_request_is_registered() -> None:
    from tools.parity.recorder.job import EXPORT
    from tools.parity.tier0_semantics import recording_requests as rr

    assert len(wo.copies()) == 246
    assert wo.mesh() == wo.mesh() == fit.MESH_PATH.read_bytes()
    assert rr.MESH_SETS[wo.MESH] == [wo.MATERIAL]
    golden = wo.request()
    assert golden.name == "export-padding-world-offset"
    assert golden.inputs == [wo.MESH, *rr.kernel_bitmaps(wo.RESOLUTION)]
    exports = [step["args"] for step in golden.sequence.steps if step["call"] == EXPORT]
    assert [(e["file_format"], e["bit_depth"], e["padding"]) for e in exports] == [
        ("exr", "32f", "infinite"),
        ("exr", "32f", "infinite"),
        ("exr", "32f", "passthrough"),
        ("exr", "32f", "passthrough"),
    ]


def _triangle(p: list[tuple[float, float, float]]) -> types.SimpleNamespace:
    return types.SimpleNamespace(p=p, normal=REF.face_normal(p))


def test_double_turn_through_model_corners_is_the_reference_turn() -> None:
    source = _triangle([(0.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.6, 0.8, 0.0)])
    target = _triangle([(0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, -1.0)])
    p = (0.3, 0.4, -0.25)  # in the source plane
    ref = vars(REF)
    assert far32._rotate64(ref, p, source, target, source.p[0], target.p[0]) == (
        REF.plane_rotation(p, source, target)
    )
    turned32 = far32._rodrigues32(
        ref, [F32(c) for c in p], source, target, source.p[0], target.p[0]
    )
    exact = REF.plane_rotation(p, source, target)
    assert max(abs(float(a) - b) for a, b in zip(turned32, exact, strict=True)) < 1e-6
    assert abs(exact[1]) < 1e-7  # in the target plane y = 0, to the float32 normals


def test_no_two_copies_share_a_3d_point_and_each_shape_has_one_base_at_its_origin() -> None:
    found = wo.copies()
    assert wo.overlaps(found) == []
    bases = [c for c in found if c.role == "base"]
    assert [c.shape.name for c in bases] == [s.name for s in wo.SHAPES]
    for i, c in enumerate(bases):
        assert c.offset == (0.0, 0.0, -i * wo.SHAPE_GAP) and c.turn == "none" and c.scale == 1


def test_every_copy_of_a_shape_has_the_same_topology_and_no_weld() -> None:
    placed, _ = wo.layout()
    found = fit.topology(placed)
    assert found["shared"] == 0
    for counts in found["per_shape"].values():
        assert len(counts) == 1
        assert counts[0]["charts"] == 2 and counts[0]["seams"] > 0


def _row(
    role: str, slot: list[int], taps: list[Any], fractions: list[int], bits: int
) -> dict[str, Any]:
    texel: dict[str, Any] = {
        m: {"taps": taps, "fractions": fractions, "bits": [bits]} for m in far32.MODELS
    }
    texel["undecided"] = []
    return {"role": role, "shape": "s", "slot": slot, "texels": {"1,1": texel}}


def test_a_slot_phase_change_alone_is_no_translation_change() -> None:
    base = _row("base", [0, 0], [[1.0, False, [1, 2]], [2.0, True, [5, 2]]], [7], 10)
    # Another slot: the same relative taps and fractions, other kernel values (output bits).
    moved = _row("offset", [30, 0], [[1.0, False, [31, 2]], [2.0, True, [35, 2]]], [7], 99)
    assert fit.translation_changed({"copies": [base, moved]}, "double") == {}
    reweighted = _row("offset", [30, 0], [[1.0, False, [31, 2]], [2.0, True, [35, 2]]], [8], 10)
    assert fit.translation_changed({"copies": [base, reweighted]}, "double") == {"far_fractions": 1}
    retapped = _row("offset", [30, 0], [[1.0, False, [31, 2]], [2.0, True, [36, 2]]], [7], 10)
    assert fit.translation_changed({"copies": [base, retapped]}, "double") == {"far_taps": 1}
    # The paired mask keeps the slot change and the reweighting, and drops the retapped pair.
    found = {"copies": [base, moved, reweighted, retapped]}
    assert fit.translation_pairs(found) == {
        "pairs": 2,
        "fractions_differ": dict.fromkeys(far32.MODELS, 1),
    }


def _tri(
    p: list[tuple[float, float, float]], uv: list[tuple[float, float]]
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        p=p, uv=np.array(uv, F32), normal=REF.face_normal(p), normalised=np.array(p, F32)
    )


def test_a_tap_on_the_turn_axis_is_still_turned() -> None:
    # J folded about the z axis (normal dot 0.8 with T's: past the gate); the tap texel (0, 1)'s
    # centre lies on J's edge on that axis, so the double turn leaves P where it is, and q
    # (texel (3, 1) through T) lies off the axis.
    J = _tri([(0.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.6, 0.8, 0.0)],
             [(0.125, 0.875), (0.125, 0.125), (0.875, 0.875)])  # fmt: skip
    T = _tri([(0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, -1.0)],
             [(0.625, 0.875), (0.875, 0.875), (0.625, 0.125)])  # fmt: skip
    ring = types.SimpleNamespace(tris=[J, T], width=4, height=4)
    ref = vars(REF)
    P = (0.0, 0.0, -1.0 / 3.0)
    assert REF.plane_rotation(P, J, T) == P and far32.turns(ref, J, T)
    q = (-1.0, 0.0, -1.0 / 3.0)
    got = far32.far_distance("inv32w", ref, ring, q, P, 0, 1, 0, (3, 1), (0, 1))
    qf = REF.position32(T.uv, T.normalised, 4, 4, 3, 1)
    pf = REF.position32(J.uv, J.normalised, 4, 4, 0, 1)
    back = far32._rodrigues32(ref, qf, T, J, T.normalised[0], J.normalised[0])
    assert got == float(REF.distance32(back, pf))
    assert abs(float(back[1])) > 0.5  # q turned onto J's plane, off T's


def test_far_hook_patches_compile_and_select_each_model() -> None:
    names = {m: fit.module(m).FAR_MODEL for m in far32.MODELS}
    assert names == {m: m for m in far32.MODELS}


def _scored_row(role: str, slot: list[int], bits: dict[str, int]) -> dict[str, Any]:
    texel: dict[str, Any] = {
        m: {"taps": [[1.0, True, [slot[0] + 5, 2]]], "fractions": [7], "bits": [bits.get(m, 0)]}
        for m in far32.MODELS
    }
    texel["undecided"] = []
    return {
        "copy": f"c{slot[0]}",
        "role": role,
        "shape": "s",
        "offset": [float(slot[0]), 0.0, 0.0],
        "turn": "none",
        "scale": 1,
        "slot": slot,
        "texels": {"1,1": texel},
    }


def test_the_scorer_compares_output_bits_per_set_and_follows_the_frozen_verdict() -> None:
    from tools.parity.fit import padding_world_offset_score as scorer

    # Two copies: every model predicts 0 except pos32n (5) at the translated copy.
    found = {
        "copies": [
            _scored_row("base", [0, 0], {}),
            _scored_row("offset", [30, 0], {"pos32n": 5}),
        ]
    }
    recorded = {(1, 1): [[0]] * 4, (31, 1): [[5]] * 4}
    result = scorer.score(found, lambda x, y: recorded.get((x, y)))
    assert result["sizes"]["scored"] == 2 and result["sizes"]["discriminating"] == 1
    assert result["sizes"]["mask_pairs"] == 1
    assert result["matches"]["pos32n"]["scored"] == 2
    assert result["matches"]["double"]["scored"] == 1
    assert result["matches"]["pos32n"]["mask_pairs"] == 1
    assert result["verdict"] == "candidate:pos32n"
    # One of four exports differing is a miss for every model: none fits.
    recorded[(31, 1)] = [[5], [5], [5], [6]]
    assert scorer.score(found, lambda x, y: recorded.get((x, y)))["verdict"] == "none_fits"
    # A predicted texel that is not a ring texel of the recording refuses the score.
    assert "refused" in scorer.score(found, lambda x, y: None)


def test_the_scorer_refuses_predictions_other_than_the_freeze() -> None:
    from tools.parity.fit import padding_world_offset_score as scorer

    assert (
        fit.digest(json.loads(scorer.COMPACT_PATH.read_bytes())) != scorer.FROZEN_PREDICTIONS_SHA256
    )
    problems = scorer.frozen_problems(
        {"copies": [], "mesh_sha256": "", "reference": "", "models": []}
    )
    assert problems == [
        "the predictions differ from the freeze",
        "the compact predictions differ from the predictions",
    ]
