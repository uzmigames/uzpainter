"""Probe validity and exact diagnostics without Painter data or a GPU."""

from __future__ import annotations

import numpy as np
import pytest

from tests.export.padding_probe_diagnostic import (
    ExportKey,
    Image,
    compare_predictions,
    validate_exports,
)


def fixture() -> tuple[Image, np.ndarray, dict[ExportKey, Image]]:
    source = np.zeros((3, 4, 24), dtype=np.float32)
    source[1, 1] = np.arange(24, dtype=np.float32) / 32
    covered = np.zeros((3, 4), dtype=np.bool_)
    covered[1, 1] = True
    images = {
        (rid, padding, step): source.copy()
        for rid in ("r1", "r2")
        for step, padding in enumerate(("infinite", "infinite", "passthrough", "passthrough"))
    }
    return source, covered, images


def test_stability_keeps_every_export_and_detects_signed_zero() -> None:
    source, covered, images = fixture()
    assert all(
        v == 0 for mode in validate_exports(source, covered, images).values() for v in mode.values()
    )
    images[("r2", "infinite", 1)][0, 0, 0] = -0.0
    images[("r1", "passthrough", 3)][0, 1, 2] = 0.5
    stability = validate_exports(source, covered, images)
    assert stability["infinite"] == {"r1/step-0": 0, "r1/step-1": 0, "r2/step-0": 0, "r2/step-1": 1}
    assert stability["passthrough"]["r1/step-3"] == 1


@pytest.mark.parametrize("key", [("r1", "infinite", 0), ("r2", "passthrough", 3)])
def test_covered_corruption_voids_probe_in_each_mode(key: ExportKey) -> None:
    source, covered, images = fixture()
    images[key][1, 1, 0] = -0.0
    with pytest.raises(ValueError, match="covered source differs"):
        validate_exports(source, covered, images)


@pytest.mark.parametrize("fault", ["missing-session", "missing-repeat", "wrong-steps", "bad-mode"])
def test_incomplete_or_misidentified_exports_refuse(fault: str) -> None:
    source, covered, images = fixture()
    if fault == "missing-session":
        images = {k: v for k, v in images.items() if k[0] == "r1"}
    elif fault == "missing-repeat":
        images.pop(("r2", "passthrough", 3))
    elif fault == "wrong-steps":
        images[("r2", "passthrough", 4)] = images.pop(("r2", "passthrough", 3))
    else:
        images[("r1", "diffusion", 0)] = images.pop(("r1", "infinite", 0))
    with pytest.raises(ValueError):
        validate_exports(source, covered, images)


@pytest.mark.parametrize("fault", ["nonfinite", "shape", "depth", "empty-coverage"])
def test_invalid_image_or_coverage_refuses(fault: str) -> None:
    source, covered, images = fixture()
    key = ("r1", "infinite", 0)
    if fault == "nonfinite":
        images[key][0, 0, 0] = np.nan
    elif fault == "shape":
        images[key] = images[key][:, :, :3]
    elif fault == "depth":
        images[key] = images[key].astype(np.float16)
    else:
        covered[:] = False
    with pytest.raises(ValueError):
        validate_exports(source, covered, images)


def test_scores_separate_regions_repeats_and_private_coordinates() -> None:
    source, covered, images = fixture()
    images[("r2", "infinite", 1)][0, 0, 0] = -0.0
    validate_exports(source, covered, images)
    predictions = {(0, 0): source[0, 0], (1, 0): source[0, 1]}
    regions = {"mixed_tau": {(0, 0)}, "single_far": {(1, 0)}, "all_ring": set(predictions)}
    scores = compare_predictions(predictions, images, regions)
    assert len(scores) == 4
    assert scores["r1/step-0"]["all_ring"] == {"tested": 2, "misses": 0, "miss_xy": []}
    assert scores["r2/step-1"]["mixed_tau"] == {"tested": 1, "misses": 1, "miss_xy": [(0, 0)]}
    assert scores["r2/step-1"]["single_far"]["misses"] == 0
    with pytest.raises(ValueError, match="prediction missing"):
        compare_predictions({}, images, regions)
    with pytest.raises(ValueError, match="outside image"):
        compare_predictions({(4, 0): source[0, 0]}, images, {"outside": {(4, 0)}})
