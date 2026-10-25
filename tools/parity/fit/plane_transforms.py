"""Authored rigid supporting-plane transforms for CPU padding diagnostics.

Both constructions map the source plane to the target plane by the same rotation
in exact arithmetic. The intersection construction uses Rodrigues' formula; the
Householder construction reflects first in the source plane, then in the angle
bisector. The latter avoids solving for a point on the intersection line.

The normalisation, fold gate and degenerate fallback preserve the existing
generic J/tau diagnostic. This module selects no mesh path or taps and certifies
no Painter behaviour. It reads no oracle and changes no production padding rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

Vector = tuple[float, float, float]
Construction = Literal["intersection", "householder"]
Mode = Literal["gate", "all", "none"]
FOLD_GATE = float(np.float32(0.985))
PARALLEL_LIMIT = 1e-10


@dataclass(frozen=True)
class Plane:
    """A supporting plane, with an oriented normal and one point on it."""

    normal: Vector
    point: Vector


def _vector(value: Vector) -> npt.NDArray[np.float64]:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError("plane transforms require finite three-component vectors")
    return result


def _normal(value: Vector) -> npt.NDArray[np.float64]:
    result = _vector(value)
    length = float(np.linalg.norm(result))
    if length == 0.0 or not np.isfinite(length):
        raise ValueError("plane transforms require finite nonzero normal lengths")
    return result / length


def rotate_between_planes(
    point: Vector,
    source: Plane,
    target: Plane,
    *,
    construction: Construction = "householder",
    mode: Mode = "gate",
) -> Vector:
    """Rotate a point rigidly from source to target, preserving off-plane offsets.

    Parallel and antiparallel normals keep the original point, including when
    their planes are displaced: this diagnostic does not introduce translation
    as a replacement for the established degenerate fallback.
    """
    if construction not in ("intersection", "householder") or mode not in ("gate", "all", "none"):
        raise ValueError("unknown plane transform construction or mode")
    p = _vector(point)
    n, m = _normal(target.normal), _normal(source.normal)
    source_point, target_point = _vector(source.point), _vector(target.point)
    axis = np.cross(m, n)
    sine = float(np.linalg.norm(axis))
    cosine = float(np.dot(m, n))
    if sine < PARALLEL_LIMIT or mode == "none" or (mode == "gate" and cosine > FOLD_GATE):
        return float(p[0]), float(p[1]), float(p[2])

    dn, dm = float(np.dot(n, target_point)), float(np.dot(m, source_point))
    if construction == "intersection":
        axis = axis / sine
        origin = np.linalg.solve(np.array([n, m, axis]), np.array([dn, dm, 0.0]))
        v = p - origin
        moved = (
            origin + v * cosine + np.cross(axis, v) * sine + axis * np.dot(axis, v) * (1 - cosine)
        )
    else:
        bisector = m + n
        length = float(np.linalg.norm(bisector))
        bisector = bisector / length
        offset = (dm + dn) / length
        reflected = p - 2 * m * (np.dot(m, p) - dm)
        moved = reflected - 2 * bisector * (np.dot(bisector, reflected) - offset)
    return float(moved[0]), float(moved[1]), float(moved[2])
