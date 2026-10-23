"""Shared offline kernel-probe checks for phase1.25's private padding diagnostics.

No admission or production policy changes. Arrays and mismatch coordinates remain
private; callers must apply the existing private-report destination guard.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

import numpy as np
import numpy.typing as npt

type Image = npt.NDArray[np.float32]
type Point = tuple[int, int]
type ExportKey = tuple[str, str, int]
type Images = Mapping[ExportKey, Image]


def _float32(values: Image, shape: tuple[int, ...], label: str) -> None:
    if values.dtype != np.float32 or values.shape != shape:
        raise ValueError(f"{label}: expected float32 shape {shape}")
    if not np.isfinite(values).all():
        raise ValueError(f"{label}: non-finite samples")


def validate_exports(
    source: Image, covered: npt.NDArray[np.bool_], images: Images
) -> dict[str, dict[str, int]]:
    """Check all eight RGB32F channels, both sessions and repeated export modes.

    Covered source corruption makes the probe void. Uncovered differences remain
    measured stability diagnostics; they never silently become an exact match.
    Comparisons use stored float32 bits, including the sign of zero.
    """
    if source.ndim != 3 or source.shape[-1] != 24:
        raise ValueError("source: expected eight RGB channels")
    _float32(source, source.shape, "source")
    if covered.dtype != np.bool_ or covered.shape != source.shape[:2] or not covered.any():
        raise ValueError("coverage: expected a nonempty boolean image matching source")
    if {key[0] for key in images} != {"r1", "r2"}:
        raise ValueError("expected separate r1 and r2 recordings")
    if {key[1] for key in images} != {"infinite", "passthrough"}:
        raise ValueError("expected infinite and passthrough exports")
    groups = {
        (rid, padding): {step for r, p, step in images if (r, p) == (rid, padding)}
        for rid in ("r1", "r2")
        for padding in ("infinite", "passthrough")
    }
    if any(len(steps) != 2 for steps in groups.values()):
        raise ValueError("expected two exports of each padding mode in each recording")
    for padding in ("infinite", "passthrough"):
        if groups[("r1", padding)] != groups[("r2", padding)]:
            raise ValueError("export steps differ between recordings")
    if groups[("r1", "infinite")] & groups[("r1", "passthrough")]:
        raise ValueError("export step reused across padding modes")
    source_bits = source.view(np.uint32)
    for key, actual in images.items():
        _float32(actual, source.shape, str(key))
        if np.any(actual.view(np.uint32)[covered] != source_bits[covered]):
            raise ValueError(f"{key}: covered source differs; probe void")
    stability: dict[str, dict[str, int]] = {}
    for padding in ("infinite", "passthrough"):
        exports = sorted((key, value) for key, value in images.items() if key[1] == padding)
        baseline = exports[0][1].view(np.uint32)
        stability[padding] = {
            f"{key[0]}/step-{key[2]}": int(
                np.count_nonzero(np.any(value.view(np.uint32) != baseline, axis=-1))
            )
            for key, value in exports
        }
    return stability


def compare_predictions(
    predictions: Mapping[Point, Image], images: Images, regions: Mapping[str, Set[Point]]
) -> dict[str, dict[str, dict[str, int | list[Point]]]]:
    """Score current or candidate ring policies against every infinite export.

    Call validate_exports first. Region membership is authored geometry; this
    function returns private mismatch coordinates, never an acceptance verdict.
    """
    scores: dict[str, dict[str, dict[str, int | list[Point]]]] = {}
    if not regions or any(not points for points in regions.values()):
        raise ValueError("expected nonempty diagnostic regions")
    points = set().union(*regions.values())
    if not points <= predictions.keys():
        raise ValueError("prediction missing for a region texel")
    targets = sorted((key, image) for key, image in images.items() if key[1] == "infinite")
    if not targets:
        raise ValueError("no infinite exports to compare")
    for key, image in targets:
        for x, y in points:
            if not (0 <= x < image.shape[1] and 0 <= y < image.shape[0]):
                raise ValueError("region texel outside image")
            _float32(predictions[(x, y)], (image.shape[2],), "prediction")
        misses: dict[str, dict[str, int | list[Point]]] = {}
        for label, region in regions.items():
            xy = sorted(
                (x, y)
                for x, y in region
                if not np.array_equal(
                    predictions[(x, y)].view(np.uint32), image[y, x].view(np.uint32)
                )
            )
            misses[label] = {"tested": len(region), "misses": len(xy), "miss_xy": xy}
        scores[f"{key[0]}/step-{key[2]}"] = misses
    return scores
