"""The island-edge coverage near-tie's vertex rule (decision 401,
`tools/parity/fit/padding_coverage.py`) and the coverage decision 408 adopts
(`tools/parity/coverage.py`); offline, no oracle access."""

from __future__ import annotations

import numpy as np

from tools.parity.coverage import coverage, ndc_vertex, snapped
from tools.parity.fit import padding_coverage as pc

F32 = np.float32
SIZE = 4096
# A float32 u below 1/4 whose exact texel x, 235582.515625 / 256, lies 1/64 of a step past a
# 1/256 rounding tie: 2 u - 1 rounds in float32 onto the tie, which rounds to even, below.
U = float.fromhex("0x1.cc1f420000000p-3")
TRIANGLE = np.array(
    [
        [
            [U, 0.75],
            [float.fromhex("0x1.cc6c0e0000000p-3"), float.fromhex("0x1.6700000000000p-1")],
            [float.fromhex("0x1.b31f420000000p-3"), float.fromhex("0x1.7380000000000p-1")],
        ]
    ]
)


def test_the_device_round_trip_is_exact_from_one_half_up() -> None:
    t = np.array([0.5, 0.75, 0.999999940395355, 1.0], F32)
    assert np.array_equal(ndc_vertex(t, SIZE), t.astype(np.float64) * SIZE)


def test_the_device_round_trip_moves_a_small_coordinate_onto_a_tie() -> None:
    assert U * SIZE * 256 == 235582.515625
    assert ndc_vertex(F32(U), SIZE) * 256 == 235582.5
    vertex = snapped(TRIANGLE, SIZE, SIZE)[0, 0]
    assert vertex[0] == 235582 / 256  # ties to even; decision 281's exact rule gives 235583 / 256
    assert vertex[1] == SIZE - 0.75 * SIZE  # v = 3/4: exact, rows flipped after the snap


def test_the_candidate_drops_one_near_tie_texel_and_keeps_the_rest() -> None:
    old = pc.coverage_281(TRIANGLE, SIZE, SIZE)
    new = pc.ndc_coverage(TRIANGLE, SIZE, SIZE)
    assert [tuple(int(i) for i in p) for p in np.argwhere(old != new)] == [(1109, 920)]
    assert old[1109, 920] and not new[1109, 920]
    assert pc.compare(TRIANGLE, SIZE, SIZE) == (1, 0)


def test_the_candidate_equals_decision_281_on_exact_coordinates() -> None:
    # Every vertex on the 1/256 grid from one half up: both rules snap it to itself.
    rng = np.random.default_rng(401)
    k = rng.integers(SIZE * 256 // 2, SIZE * 256, size=(40, 3, 2))
    triangles = (k / (SIZE * 256)).astype(F32).astype(np.float64)
    assert np.array_equal(
        pc.coverage_281(triangles, SIZE // 16, SIZE // 16),
        pc.ndc_coverage(triangles, SIZE // 16, SIZE // 16),
    )


def test_the_adopted_coverage_is_the_candidate_with_the_top_left_rule() -> None:
    # The near-tie triangle has no on-edge centre: decision 408 equals the candidate there.
    assert np.array_equal(coverage(TRIANGLE, SIZE, SIZE), pc.ndc_coverage(TRIANGLE, SIZE, SIZE))
    # A square from texel 0.5 to 4.5 on both axes of an 8 x 8 tile, split along a diagonal: every
    # centre of its four sides and of the diagonal lies on an edge. Decision 281 covers all 25
    # centres; the top-left rule (dy < 0, rows top first) keeps the left side, the side at the
    # larger row (the lower v) and the shared diagonal.
    lo, hi = 0.5 / 8, 4.5 / 8
    square = np.array(
        [[[lo, 1 - lo], [hi, 1 - lo], [hi, 1 - hi]], [[lo, 1 - lo], [hi, 1 - hi], [lo, 1 - hi]]]
    )
    assert int(pc.coverage_281(square, 8, 8).sum()) == 25
    covered = coverage(square, 8, 8)
    expected = np.zeros((8, 8), dtype=bool)
    expected[1:5, 0:4] = True
    assert np.array_equal(covered, expected)
    # The winding does not matter.
    assert np.array_equal(coverage(square[:, ::-1], 8, 8), expected)
