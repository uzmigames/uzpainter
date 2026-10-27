"""The kernel-probe ring scorer's offline parts; no oracle access or production change."""

from __future__ import annotations

import itertools

import numpy as np

from tools.parity.fit import padding_corpus as corpus
from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT

REF = load_module(REPO_ROOT / "tests/export/padding_reference.py", "test_padding_corpus_ref")


def test_kernel_probes_are_the_padding_manifests_with_the_eight_kernel_maps() -> None:
    names = corpus.probes()
    assert len(names) == 29
    assert {"hinge-vary", "kernel-sphere-256", "plane-control", "tau-prism"} <= set(names)
    assert "" not in names and "bevelled-cube" not in names


def test_ring_points_wrap_columns_but_not_rows() -> None:
    covered = np.zeros((4, 6), bool)
    covered[0, 0] = True
    covered[3, 5] = True
    points = set(corpus.ring_points(covered))
    # Around (0, 0): x wraps to column 5, y does not wrap to row 3.
    assert {(1, 0), (0, 1), (1, 1), (5, 0), (5, 1)} <= points
    # Around (5, 3): x wraps to column 0 on rows 2 and 3.
    assert {(4, 3), (4, 2), (5, 2), (0, 2), (0, 3)} <= points
    assert not any(covered[y, x] for x, y in points)
    expected = {
        (x, y)
        for y in range(4)
        for x in range(6)
        if not covered[y, x]
        and any(covered[y + dy, (x + dx) % 6] for dy, dx in REF.NEIGHBOURS if 0 <= y + dy < 4)
    }
    assert points == expected


def test_levels_round_trip_through_fractions() -> None:
    for level, (_, levels) in enumerate(REF.LEVELS):
        for u in (0, 1, levels // 2, levels - 1, levels):
            t = corpus.fraction_of(level, u, REF)
            padded = [corpus.fraction_of(i, 0, REF) for i in range(level)] + [t]
            assert corpus.bins_of(padded, REF)[level] == u


def test_weights_of_recovers_affine_weights() -> None:
    rng = np.random.default_rng(7)
    values = rng.random((4, 24)).astype(np.float32)
    weights = np.array([0.5, 0.25, 0.15, 0.1])
    recorded = (weights @ values.astype(np.float64)).astype(np.float32)
    assert np.allclose(corpus.weights_of(values, recorded), weights, atol=1e-5)


def test_inverse_bins_finds_the_chain_levels_of_a_recording() -> None:
    rng = np.random.default_rng(11)
    values = (rng.integers(1, 256, (3, 24)) / 256).astype(np.float32)
    truth = [700, 90]
    t = [corpus.fraction_of(level, u, REF) for level, u in enumerate(truth)]
    recorded = np.array([REF.chain(values[:, c], t) for c in range(24)], np.float32)
    assert corpus.inverse_bins(values, recorded, [703, 88], REF) == truth
    assert corpus.inverse_bins(values, recorded + np.float32(0.5), [703, 88], REF) is None


def test_every_named_patch_applies_once_to_the_current_reference() -> None:
    text = (REPO_ROOT / "tests/export/padding_reference.py").read_text("utf-8")
    for name, edits in corpus.PATCHES.items():
        for old, _ in edits:
            assert text.count(old) == 1, name
    for a, b in itertools.combinations(sorted(corpus.PATCHES), 2):
        olds = {old for old, _ in corpus.PATCHES[a]} & {old for old, _ in corpus.PATCHES[b]}
        if olds:
            # Patches that rewrite the same line are alternatives, never combined.
            assert {a, b} <= {
                "snapwin",
                "snapcol",
                "snaprow",
                "uvwin",
                "hop",
                "hopempty",
                "hopzero",
            }, (a, b)
