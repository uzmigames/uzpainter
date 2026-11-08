"""The `ndc-top-left` tie rule on authored triangles; no oracle access."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.padding_coverage import ndc_coverage
from tools.parity.fit.padding_coverage_recorded import score, top_left_coverage


def square(u0: float, v0: float, u1: float, v1: float) -> np.ndarray:
    """Two triangles of the UV rectangle, wound both ways."""
    return np.array(
        [[[u0, v0], [u1, v0], [u1, v1]], [[u0, v0], [u0, v1], [u1, v1]]], dtype=np.float64
    )


def test_on_edge_centres_are_covered_on_one_side_only() -> None:
    # Texel centres of an 8 x 8 tile lie at (k + 0.5) / 8: this square's four sides pass through
    # centres of columns 1 and 5 and rows 1 and 5 (rows top first: v = 1 - (row + 0.5) / 8).
    size = 8
    tris = square(1.5 / size, 1.5 / size, 5.5 / size, 5.5 / size)
    inclusive = ndc_coverage(tris, size, size)
    rule = top_left_coverage(tris, size, size)
    assert inclusive.sum() == 25  # columns 1-5 x rows 2-6, both edge lines included
    assert rule.sum() == 16  # one vertical and one horizontal edge line dropped
    assert not (rule & ~inclusive).any()
    # One full row and one full column of the 5 x 5 block are dropped; the shared diagonal is
    # interior to the square, so no centre on it is.
    rows, cols = np.nonzero(inclusive & ~rule)
    assert len(rows) == 9
    assert sum(np.bincount(rows) == 5) == 1 and sum(np.bincount(cols) == 5) == 1


def test_score_counts_both_directions() -> None:
    truth = np.array([[True, False], [True, True]])
    rule = np.array([[True, True], [False, True]])
    assert score(rule, truth) == (3, 1, 1)
