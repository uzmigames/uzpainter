"""Black-box fitting of the prototypes' free constants to the private oracles.

Only outputs are used: oracle maps decoded from the private store, compared over the comparison
domain. The fitted constants (numbers, never pixels) are public in
`parity/semantics/procedural-feasibility.json`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility.prototypes import (
    FULL,
    LEATHER_CHANNELS,
    MEW_FIT_NAMES,
    Codes,
    StepCurve,
    fbm,
    metal_edge_wear,
    unit,
)

Mask = npt.NDArray[np.bool_]


def nelder_mead(
    objective: Callable[[npt.NDArray[np.float64]], float],
    start: Sequence[float],
    step: Sequence[float],
    iterations: int = 200,
) -> tuple[npt.NDArray[np.float64], float]:
    """Nelder-Mead simplex minimisation (Nelder and Mead 1965), standard coefficients."""
    points = [np.array(start, np.float64)]
    for index, delta in enumerate(step):
        point = np.array(start, np.float64)
        point[index] += delta
        points.append(point)
    values = [objective(p) for p in points]
    for _ in range(iterations):
        order = np.argsort(values)
        points = [points[i] for i in order]
        values = [values[i] for i in order]
        centroid = np.mean(points[:-1], axis=0)
        reflected = centroid + (centroid - points[-1])
        reflected_value = objective(reflected)
        if values[0] <= reflected_value < values[-2]:
            points[-1], values[-1] = reflected, reflected_value
            continue
        if reflected_value < values[0]:
            expanded = centroid + 2.0 * (centroid - points[-1])
            expanded_value = objective(expanded)
            if expanded_value < reflected_value:
                points[-1], values[-1] = expanded, expanded_value
            else:
                points[-1], values[-1] = reflected, reflected_value
            continue
        contracted = centroid + 0.5 * (points[-1] - centroid)
        contracted_value = objective(contracted)
        if contracted_value < values[-1]:
            points[-1], values[-1] = contracted, contracted_value
            continue
        for index in range(1, len(points)):
            points[index] = points[0] + 0.5 * (points[index] - points[0])
            values[index] = objective(points[index])
    best = int(np.argmin(values))
    return points[best], float(values[best])


def fit_step_curve(summed: Sequence[Codes], observed: Sequence[Codes]) -> StepCurve:
    """A hard step out = clamp(1/2 + (x - T) g) through the oracle's transition texels.

    The gain is one full output range per code unit (the observed transition is one code wide);
    the threshold is placed so the transition texels' values are reproduced (mean over them).
    """
    gain = 1.0
    xs, ys = [], []
    below, above = [], []
    for x, y in zip(summed, observed, strict=True):
        middle = (y > 0) & (y < FULL)
        xs.append(x[middle])
        ys.append(y[middle])
        below.append(x[y == 0])
        above.append(x[y == FULL])
    x_mid, y_mid = np.concatenate(xs), np.concatenate(ys)
    if x_mid.size:
        threshold = float(np.mean(x_mid - (y_mid / FULL - 0.5) / gain))
    else:
        threshold = (float(np.concatenate(below).max()) + float(np.concatenate(above).min())) / 2
    return StepCurve(threshold, gain)


def fit_metal_edge_wear(
    samples: Sequence[tuple[Codes, Codes, Mapping[str, float], Codes, Mask]],
    iterations: int = 160,
) -> tuple[dict[str, float], float]:
    """Fit MEW_FIT_NAMES minimising mean |Δ| (code units) over every sample's domain.

    `samples`: (curvature, ambient occlusion, parameters, oracle, domain) per case; every
    second texel of the domain in each direction is used.
    """
    thin = [
        (curvature, occlusion, parameters, oracle[..., 0], domain & checker(domain.shape))
        for curvature, occlusion, parameters, oracle, domain in samples
    ]

    def objective(vector: npt.NDArray[np.float64]) -> float:
        fitted = dict(zip(MEW_FIT_NAMES, vector, strict=True))
        if fitted["blur_sigma"] < 0.0:
            return float("inf")
        total, count = 0.0, 0
        for curvature, occlusion, parameters, oracle, domain in thin:
            prototype = metal_edge_wear(curvature, occlusion, parameters, fitted)[..., 0]
            total += float(np.abs(prototype - oracle)[domain].sum())
            count += int(domain.sum())
        return total / count

    best, value = nelder_mead(
        objective,
        start=(1.5, 4.0, 1.0, 0.0, 4.0),
        step=(0.5, 2.0, 0.5, 0.2, 2.0),
        iterations=iterations,
    )
    return dict(zip(MEW_FIT_NAMES, (float(v) for v in best), strict=True)), value


def checker(shape: tuple[int, ...]) -> Mask:
    mask = np.zeros(shape[:2], np.bool_)
    mask[::2, ::2] = True
    return mask


def fit_leather(
    samples: Sequence[tuple[Codes, Mapping[str, Codes], Mask]], shape: tuple[int, int]
) -> dict[str, dict[str, list[float]]]:
    """Least-squares base, grain share and edge share per channel component.

    `samples`: (curvature, oracle maps by channel, domain) per fixture.
    """
    grain = fbm(shape, 16, 0, 5) - 0.5
    fitted: dict[str, dict[str, list[float]]] = {}
    for channel in LEATHER_CHANNELS:
        design_rows, targets = [], []
        for curvature, oracle, domain in samples:
            convex = np.maximum(unit(curvature[..., 0]) - 0.5, 0.0) * 2.0
            design_rows.append(
                np.stack([np.ones(int(domain.sum())), grain[domain], convex[domain]], 1)
            )
            targets.append(unit(oracle[channel])[domain])
        design = np.vstack(design_rows)
        target = np.vstack(targets)
        solution, *_ = np.linalg.lstsq(design, target, rcond=None)
        fitted[channel] = {
            "base": [float(v) for v in solution[0]],
            "grain": [float(v) for v in solution[1]],
            "edge": [float(v) for v in solution[2]],
        }
    return fitted
