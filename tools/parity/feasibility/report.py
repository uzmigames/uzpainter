"""Public outputs of the study: `parity/semantics/procedural-feasibility.json` (fitted formulas,
public sources, residuals) and `parity/reports/phase0/procedural-feasibility.md` (numbers only).

Both are written from one `StudyResult`, so the report's numbers are the comparison output.
"""

from __future__ import annotations

from typing import Any

from tools.parity.feasibility.cases import ASSETS, PAINTER_BUILD_ID, RESOLUTION, cases
from tools.parity.feasibility.compare import Difference
from tools.parity.feasibility.prototypes import MEW_FIT_NAMES
from tools.parity.feasibility.study import CaseResult, StudyResult
from tools.parity.schemas import REPO_ROOT

SEMANTICS_PATH = REPO_ROOT / "parity" / "semantics" / "procedural-feasibility.json"
REPORT_PATH = REPO_ROOT / "parity" / "reports" / "phase0" / "procedural-feasibility.md"
UNIT = "16-bit code value"

SOURCES: dict[str, list[dict[str, str]]] = {
    "position": [
        {"source_id": "A-HELP-GUIDE", "locator": "Effects > Generators > Position (parameters)"},
        {"source_id": "A-HELP-BAKING", "locator": "Position mesh map"},
    ],
    "metal-edge-wear": [
        {
            "source_id": "A-HELP-GUIDE",
            "locator": "Effects > Generators > Metal Edge Wear (parameters)",
        },
        {"source_id": "A-HELP-BAKING", "locator": "Curvature and Ambient Occlusion mesh maps"},
        {"source_id": "P-NOISE", "locator": "Perlin 2002 Improving Noise; fBm"},
    ],
    "leather-damaged": [
        {"source_id": "P-NOISE", "locator": "Perlin 2002 Improving Noise; fBm"},
        {"source_id": "A-HELP-BAKING", "locator": "Curvature mesh map"},
    ],
}

FORMULAS = {
    "position": (
        "acc = sum over the directions with non-zero opacity of opacity * g, combined by Linear "
        "Dodge (Add) from 0, where g is the Position map channel X (Right to Left), Y (Top to "
        "Bottom) or Z (Front to Back) in 16-bit code units, replaced by 65535 - g when that "
        "direction's Invert is on; acc = 65535 - acc when the section Invert is on. Default "
        "Balance 0.5 and Contrast 0: out = round(acc). Other Balance/Contrast pairs only at "
        "calibrated points: out = clamp(1/2 + (acc - T) g) with the fitted T and g."
    ),
    "metal-edge-wear": (
        "e = Gaussian blur, sigma = blur_sigma * Edges Smoothness, of 2 max(curvature - 1/2, 0); "
        "n = fBm(Grunge Scale cells, seed) in [0, 1]; w = edge_gain * Curvature Weight * e + "
        "grunge_gain * Grunge Amount * (n - 1/2) + bias; out = clamp((w - (1 - Wear Level)) * "
        "(1 + contrast_gain * Wear Contrast) + 1/2) * (1 - m + m * AO), m = Ambient Occlusion "
        "Masking."
    ),
    "leather-damaged": (
        "Independently designed recipe, not Painter's preset structure: per exported channel "
        "component, value = base + grain * (fBm(16 cells, seed 0, 5 octaves) - 1/2) + edge * "
        "2 max(curvature - 1/2, 0), clamped to [0, 1]; base, grain and edge fitted by least "
        "squares."
    ),
}


def asset_status(results: list[CaseResult]) -> str:
    if any(r.unsupported for r in results):
        return "gap"
    if all(r.classification == "equal" for r in results):
        return "exact"
    return "calibrated"


def verdict(status: str) -> str:
    return "go" if status == "exact" else "no-go"


def fitted_parameters(asset_id: str, fits: dict[str, Any]) -> list[dict[str, Any]]:
    """Fitted constants as named parameters; `fits_from_semantics` reads them back."""
    if asset_id == "position":
        parameters: list[dict[str, Any]] = []
        for index, curve in enumerate(fits["position"]["step_curves"]):
            prefix = f"step_curve[{index}]."
            parameters += [
                {
                    "name": prefix + "position_balance",
                    "value": curve["position_balance"],
                    "origin": "authored",
                },
                {
                    "name": prefix + "position_contrast",
                    "value": curve["position_contrast"],
                    "origin": "authored",
                },
                {
                    "name": prefix + "threshold",
                    "value": curve["threshold_code_units"],
                    "origin": "fitted",
                    "unit": "code units",
                },
                {
                    "name": prefix + "gain",
                    "value": curve["gain_per_code_unit"],
                    "origin": "fitted",
                    "unit": "per code unit",
                },
            ]
        return parameters
    if asset_id == "metal-edge-wear":
        return [
            {"name": name, "value": fits["metal-edge-wear"][name], "origin": "fitted"}
            for name in (*MEW_FIT_NAMES, "objective_mean_abs_diff")
        ]
    return [
        {"name": f"{channel}.{term}", "value": values, "origin": "fitted"}
        for channel, terms in fits["leather-damaged"].items()
        for term, values in terms.items()
    ]


def fits_from_semantics(document: dict[str, Any]) -> dict[str, Any]:
    """The study's fits as written by `semantics_document` (to re-run the comparison)."""
    values = {
        entry["entry_id"]: {p["name"]: p["value"] for p in entry["parameters"]}
        for entry in document["entries"]
    }
    position = values["position-prototype"]
    curves = []
    index = 0
    while f"step_curve[{index}].threshold" in position:
        prefix = f"step_curve[{index}]."
        curves.append(
            {
                "position_balance": position[prefix + "position_balance"],
                "position_contrast": position[prefix + "position_contrast"],
                "threshold_code_units": position[prefix + "threshold"],
                "gain_per_code_unit": position[prefix + "gain"],
            }
        )
        index += 1
    leather: dict[str, dict[str, Any]] = {}
    for name, value in values["leather-damaged-prototype"].items():
        channel, term = name.split(".")
        leather.setdefault(channel, {})[term] = value
    return {
        "position": {"step_curves": curves},
        "metal-edge-wear": dict(values["metal-edge-wear-prototype"]),
        "leather-damaged": leather,
    }


def residual_entries(results: list[CaseResult]) -> list[dict[str, Any]]:
    entries = []
    for result in results:
        for item in result.maps:
            for recording_id, diff in item.residuals.items():
                entries.append(
                    {
                        "golden_id": result.case.golden_id,
                        "map": item.map,
                        "compared_against": recording_id,
                        "unit": UNIT,
                        "difference": diff.as_dict(),
                    }
                )
    return entries


def by_asset(study: StudyResult) -> dict[str, list[CaseResult]]:
    grouped: dict[str, list[CaseResult]] = {asset_id: [] for asset_id in ASSETS}
    for result in study.cases:
        grouped[result.case.asset.asset_id].append(result)
    return grouped


def semantics_document(study: StudyResult) -> dict[str, Any]:
    entries = []
    for asset_id, results in by_asset(study).items():
        asset = ASSETS[asset_id]
        entries.append(
            {
                "entry_id": f"{asset_id}-prototype",
                "subject": f"{asset.painter_name} ({asset.family}), feasibility prototype",
                "status": asset_status(results),
                "formula": FORMULAS[asset_id],
                "public_sources": SOURCES[asset_id],
                "parameters": fitted_parameters(asset_id, study.fits),
                "residuals": residual_entries(results),
            }
        )
    return {
        "schema": "uzpainter/parity/semantics/1",
        "record_class": "public_semantics",
        "semantics_id": "procedural-feasibility",
        "description": (
            "Procedural feasibility study (phase0.6_procedural-feasibility, P0-FEAS-PROC): "
            "clean-room prototypes of the Position and Metal Edge Wear generators and of an "
            "independently designed stand-in for the Leather Damaged smart material, fitted "
            "black-box to private Painter oracles on the authored sphere and rounded cube at "
            f"{RESOLUTION} px. Residuals are |Δ| in 16-bit code values over the comparison "
            "domain (UV-covered texels eroded by one texel), against both recordings."
        ),
        "painter_build_id": PAINTER_BUILD_ID,
        "corpus": [case.golden_id for case in cases()],
        "entries": entries,
    }


def cell(diff: Difference) -> str:
    return (
        f"{diff.max} | {diff.mean:.2f} | {diff.p99} | {diff.differing} | "
        f"{diff.affected_texels} / {diff.texels}"
    )


def parameters_text(result: CaseResult) -> str:
    return ", ".join(f"`{k}` = {v}" for k, v in result.case.parameters) or "defaults"


def report_markdown(study: StudyResult, run_note: str) -> str:
    grouped = by_asset(study)
    status = {asset_id: asset_status(results) for asset_id, results in grouped.items()}
    lines = [
        "# Procedural feasibility — residual report (P0-FEAS-PROC)",
        "",
        "Task `phase0.6_procedural-feasibility` (`docs/dag.md` P0-FEAS-PROC, implements D4). "
        "Numbers only: every oracle is a private Painter recording in the owner's store; this "
        "report, the manifests and `parity/semantics/procedural-feasibility.json` hold "
        "statistics, fitted constants and hashes. Generated by `python -m "
        "tools.parity.feasibility run` from one comparison run; do not edit by hand.",
        "",
        "## 1. Go / no-go for `phase3.3_procedural-families` (P3-PROC)",
        "",
        "Rule (Q1, decision 017): an asset is **go** only when its prototype equals both oracle "
        "recordings on every evaluated case (max |Δ| 0) and the oracle is stable; any non-zero "
        "residual is a candidate exception or gap, never equal, and makes the asset **no-go** "
        "for exact parity. A family is go only for its go members.",
        "",
        "| Family | Asset (compatibility alias) | Cases | Equal cases | Worst max \\|Δ\\| | "
        "Prototype status | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for asset_id, results in grouped.items():
        asset = ASSETS[asset_id]
        worst = max(
            (d.max for r in results for m in r.maps for d in m.residuals.values()), default=0
        )
        equal = sum(1 for r in results if r.classification == "equal")
        lines.append(
            f"| {asset.family} | {asset.painter_name} | {len(results)} | {equal} | {worst} | "
            f"{status[asset_id]} | **{verdict(status[asset_id])}** |"
        )
    lines += [
        "",
        "Per family: **mesh-map generators** — go for Position (the gradient generator from "
        "the Position map is reproduced on every evaluated case, including a calibrated "
        "balance/contrast step). No-go for Metal Edge Wear: it is equal only where the result "
        "saturates (sphere, no grunge); on the rounded cube without grunge (boundary-a) the "
        "edge falloff of the prototype differs, and every case with grunge differs over a large "
        "share of texels because a clean-room seeded noise does not reproduce Painter's grunge "
        "texel for texel (the fit drives the grunge share towards 0). The **grunges and "
        "noises** family it relies on is therefore no-go for exact parity on this evidence. "
        "**Smart materials** — no-go for Leather Damaged: the independently designed stand-in "
        "matches the metalness (0) and normal (flat) channels but differs on every texel of "
        "base colour, roughness and height, and Painter's preset structure is not publishable "
        "(05 §3). The no-go assets stay visible capability gaps (05 §5) unless the owner "
        "approves exceptions with the residuals below as evidence.",
        "",
        "## 2. Scope",
        "",
        "- **Generators selected (task 2.2)** from the 05 §3 mesh-map generator list: "
        "**Position** (a deterministic gradient from the Position map) and **Metal Edge Wear** "
        "(edges from Curvature, seeded grunge, AO masking). Together they bracket the family: a "
        "closed-form generator and a noise-driven one. **Leather Damaged** is the smart "
        "material.",
        "- **Evaluated subset of the 05 §6 matrix:** meshes {unit sphere, rounded (bevelled) "
        f"cube}} x resolution {{{RESOLUTION}}} x parameter sets {{defaults, two authored boundary "
        "sets} x seeds {default, 1} (Metal Edge Wear). Not evaluated: the hat v6 low mesh, "
        "resolutions 2048 and 4096, each recipe's recorded parameter set; Leather Damaged at "
        "defaults only (a smart material exposes no parameters to `set_parameters`).",
        "- **Fixtures:** `parity/fixtures/feasibility/` (UzmiGames-authored, Apache-2.0): two "
        "OBJ meshes and six analytic 16-bit mesh maps each (position, world-space normal, flat "
        "tangent normal, AO, curvature, thickness), assigned in Painter with "
        "`TextureSet.set_mesh_map_resource`, so residuals measure the generator, not a baker. "
        "Conventions: `tools/parity/feasibility/fixtures.py`.",
        "- **Manifests:** one public manifest per golden under "
        "`parity/manifests/phase0/procedural-feasibility/` (a public manifest describes one "
        "golden, so the single file named in the proposal became this folder).",
        "- **Parameters** were discovered through the documented `Property` API (private "
        "readback, task 2.3); only names, labels, ranges, the documented default values the "
        "prototypes start from (Property metadata, like the ranges) and the authored values "
        "appear here.",
        "- **Comparison domain:** texels whose centre lies in a UV triangle, eroded by one "
        "texel. Texels outside it are export padding (`passthrough`), which Painter leaves "
        "undefined and which differs between recordings.",
        "",
        f"Comparison run: {run_note}",
        "",
        "## 3. Oracle stability (r1 same session against r2 after save and reopen)",
        "",
        "| Asset | Fixture | Set | Map | max \\|Δ\\| | differing values | domain texels |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in study.cases:
        for item in result.maps:
            lines.append(
                f"| {result.case.asset.painter_name} | {result.case.fixture} | "
                f"{result.case.parameter_set} | {item.map} | {item.stability.max} | "
                f"{item.stability.differing} | {item.stability.texels} |"
            )
    lines += [
        "",
        "## 4. Residuals (prototype against each recording; 16-bit code values)",
        "",
        "Columns per recording: max \\|Δ\\| | mean \\|Δ\\| | p99 \\|Δ\\| | differing values | "
        "affected texels / domain texels.",
        "",
        "| Asset | Fixture | Set (parameters) | Map | vs r1: max | mean | p99 | differing | "
        "affected | vs r2: max | mean | p99 | differing | affected | Classification |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in study.cases:
        for item in result.maps:
            if result.unsupported:
                row = "unsupported | | | | | unsupported | | | |"
            else:
                row = f"{cell(item.residuals['r1'])} | {cell(item.residuals['r2'])}"
            lines.append(
                f"| {result.case.asset.painter_name} | {result.case.fixture} | "
                f"{result.case.parameter_set} ({parameters_text(result)}) | {item.map} | {row} | "
                f"{result.classification} |"
            )
    lines += [
        "",
        "## 5. Fits and provenance",
        "",
        "Formulas, public sources per formula, fitted constants and every residual above: "
        "`parity/semantics/procedural-feasibility.json`. Prototype code: "
        "`tools/parity/feasibility/prototypes.py` (provenance note per formula), fits: "
        "`tools/parity/feasibility/fit.py`. Sources: A-HELP-GUIDE (generator help pages: "
        "parameter meaning), A-HELP-BAKING (mesh-map meaning), P-NOISE (gradient noise and "
        "fBm); constants not given by a public source are fitted black-box.",
        "",
        "Fit summary:",
        "",
    ]
    for curve in study.fits["position"]["step_curves"]:
        lines.append(
            f"- Position, balance {curve['position_balance']} / contrast "
            f"{curve['position_contrast']}: hard step at T = {curve['threshold_code_units']:.4f} "
            f"code units, g = {curve['gain_per_code_unit']} per code unit (calibrated point only)."
        )
    mew = study.fits["metal-edge-wear"]
    lines.append(
        "- Metal Edge Wear: "
        + ", ".join(f"{name} = {mew[name]:.4f}" for name in MEW_FIT_NAMES)
        + f"; fit objective (mean |Δ|, every second texel) {mew['objective_mean_abs_diff']:.1f}."
    )
    lines.append(
        "- Leather Damaged stand-in: per-channel base, grain and edge shares (least squares), "
        "listed in the semantics file."
    )
    lines += [
        "",
        "## 6. What stayed private",
        "",
        "Every exported map, the Property readbacks of the generators, the Leather Damaged "
        "structure readback (`GroupLayerNode.sub_layers` walk) and the private records are in "
        "the owner's store only, named in the manifests by SHA-256. The repository guard "
        "(`python -m tools.parity.guard`) checks that none of them is in the repository.",
        "",
    ]
    return "\n".join(lines)
