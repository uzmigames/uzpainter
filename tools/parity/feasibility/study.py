"""The comparison run of the study (task 3.1): oracle stability, fits, residuals, verdicts.

Runs on the owner's machine only: every oracle is read from the private store. The result is
numbers only (no pixel leaves this process) and feeds `report.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.feasibility.cases import FIXTURE_DIR, FIXTURE_NAMES, Case, cases
from tools.parity.feasibility.compare import (
    Codes,
    Difference,
    OracleMaps,
    comparison_domain,
    difference,
    oracle_maps,
)
from tools.parity.feasibility.fit import (
    fit_leather,
    fit_metal_edge_wear,
    fit_step_curve,
)
from tools.parity.feasibility.fixtures import MAP_NAMES, RESOLUTION, fixture_files
from tools.parity.feasibility.prototypes import (
    MEW_FIT_NAMES,
    POSITION_DEFAULTS,
    StepCurve,
    UnsupportedParameters,
    leather_damaged,
    metal_edge_wear,
    position_generator,
)
from tools.parity.store.store import OracleStore


class OracleUnavailable(RuntimeError):
    """A golden's private records are missing from this machine's store (never a pass)."""


@dataclass
class MapResult:
    map: str
    stability: Difference  # r1 against r2 (oracle stability)
    residuals: dict[str, Difference]  # recording id -> prototype against that recording

    @property
    def equal(self) -> bool:
        return all(d.max == 0 for d in self.residuals.values())


@dataclass
class CaseResult:
    case: Case
    maps: list[MapResult] = field(default_factory=list)
    unsupported: str | None = None

    @property
    def stable(self) -> bool:
        return all(m.stability.max == 0 for m in self.maps)

    @property
    def classification(self) -> str:
        if self.unsupported is not None:
            return "gap"
        if self.stable and all(m.equal for m in self.maps):
            return "equal"
        return "candidate exception or gap"


@dataclass
class StudyResult:
    cases: list[CaseResult]
    fits: dict[str, Any]


def fixture_maps() -> dict[str, dict[str, Codes]]:
    files = fixture_files(FIXTURE_DIR)
    return {
        fixture: {name: png.read(files[f"{fixture}/{name}"]).astype(np.int64) for name in MAP_NAMES}
        for fixture in FIXTURE_NAMES
    }


def load_oracles(store: OracleStore | None, selected: list[Case]) -> dict[str, OracleMaps]:
    oracles: dict[str, OracleMaps] = {}
    for case in selected:
        maps = oracle_maps(store, case)
        if maps is None:
            raise OracleUnavailable(f"{case.golden_id}: oracle_unavailable")
        oracles[case.golden_id] = maps
    return oracles


def summed_position(case: Case, position: Codes) -> Codes:
    values = {**POSITION_DEFAULTS, **dict(case.parameters)}
    total = np.zeros(position.shape[:2], np.float64)
    for axis, channel in (("rightleft", 0), ("topbottom", 1), ("frontback", 2)):
        gradient = position[..., channel].astype(np.float64)
        if values[f"position_direction_{axis}_invert"]:
            gradient = 65535 - gradient
        total += float(values[f"position_direction_{axis}_opacity"]) * gradient
    summed: Codes = total.astype(np.int64)
    return summed


def balance_contrast(case: Case) -> tuple[float, float]:
    parameters = dict(case.parameters)
    return (
        float(parameters.get("position_balance", 0.5)),
        float(parameters.get("position_contrast", 0.0)),
    )


def fit_all(
    selected: list[Case], inputs: dict[str, dict[str, Codes]], oracles: dict[str, OracleMaps]
) -> dict[str, Any]:
    """Every fitted constant of the study, from the first recording of each golden."""

    def first(case: Case) -> dict[str, Codes]:
        return oracles[case.golden_id].recordings["r1"]

    stepped = [
        c for c in selected if c.asset.asset_id == "position" and balance_contrast(c) != (0.5, 0.0)
    ]
    step_curves = []
    for key in sorted({balance_contrast(c) for c in stepped}):
        group = [c for c in stepped if balance_contrast(c) == key]
        curve = fit_step_curve(
            [
                summed_position(c, inputs[c.fixture]["position"])[comparison_domain(c.fixture)]
                for c in group
            ],
            [first(c)["specularroughness"][..., 0][comparison_domain(c.fixture)] for c in group],
        )
        step_curves.append(
            {
                "position_balance": key[0],
                "position_contrast": key[1],
                "threshold_code_units": curve.threshold,
                "gain_per_code_unit": curve.gain,
            }
        )
    mew_fit, mew_objective = fit_metal_edge_wear(
        [
            (
                inputs[c.fixture]["curvature"],
                inputs[c.fixture]["ambient_occlusion"],
                dict(c.parameters),
                first(c)["specularroughness"],
                comparison_domain(c.fixture),
            )
            for c in selected
            if c.asset.asset_id == "metal-edge-wear"
        ]
    )
    leather_fit = fit_leather(
        [
            (inputs[c.fixture]["curvature"], first(c), comparison_domain(c.fixture))
            for c in selected
            if c.asset.asset_id == "leather-damaged"
        ],
        (RESOLUTION, RESOLUTION),
    )
    return {
        "position": {"step_curves": step_curves},
        "metal-edge-wear": {**mew_fit, "objective_mean_abs_diff": mew_objective},
        "leather-damaged": leather_fit,
    }


def prototype_maps(case: Case, maps: dict[str, Codes], fits: dict[str, Any]) -> dict[str, Codes]:
    """The prototype's exported maps for one case; raises UnsupportedParameters."""
    if case.asset.asset_id == "position":
        curves = {
            (c["position_balance"], c["position_contrast"]): StepCurve(
                c["threshold_code_units"], c["gain_per_code_unit"]
            )
            for c in fits["position"]["step_curves"]
        }
        out = position_generator(maps["position"], dict(case.parameters), curves)
        return {"specularroughness": out[..., None]}
    if case.asset.asset_id == "metal-edge-wear":
        fitted = {name: fits["metal-edge-wear"][name] for name in MEW_FIT_NAMES}
        out = metal_edge_wear(
            maps["curvature"], maps["ambient_occlusion"], dict(case.parameters), fitted
        )
        return {"specularroughness": out}
    return leather_damaged(maps["curvature"], fits["leather-damaged"], (RESOLUTION, RESOLUTION))


def evaluate(
    selected: list[Case],
    inputs: dict[str, dict[str, Codes]],
    oracles: dict[str, OracleMaps],
    fits: dict[str, Any],
) -> list[CaseResult]:
    """Oracle stability (r1 against r2) and each prototype against both recordings."""
    results: list[CaseResult] = []
    for case in selected:
        recordings = oracles[case.golden_id].recordings
        domain = comparison_domain(case.fixture)
        result = CaseResult(case)
        prototype: dict[str, Codes] = {}
        try:
            prototype = prototype_maps(case, inputs[case.fixture], fits)
        except UnsupportedParameters as error:
            result.unsupported = str(error)
        for name in sorted(recordings["r1"]):
            stability = difference(recordings["r1"][name], recordings["r2"][name], domain)
            residuals = {
                recording_id: difference(prototype[name], maps[name], domain)
                for recording_id, maps in sorted(recordings.items())
                if name in prototype
            }
            result.maps.append(MapResult(name, stability, residuals))
        results.append(result)
    return results


def run_study(store: OracleStore | None, fits: dict[str, Any] | None = None) -> StudyResult:
    """Fit (unless `fits` is given) and evaluate every case against the private oracles."""
    selected = cases()
    inputs = fixture_maps()
    oracles = load_oracles(store, selected)
    if fits is None:
        fits = fit_all(selected, inputs, oracles)
    return StudyResult(evaluate(selected, inputs, oracles, fits), fits)
