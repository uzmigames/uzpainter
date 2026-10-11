"""`parity/semantics/iray.json`: the first clean-room lobe fits with residuals (task item 2.4).

Every entry names its approved public sources and its fitted constants, and lists residuals of
the prototype against the admitted Iray references as numbers only (16-bit display codes, on
the held-out pixels of decision 050) against the two session-separated S references, `r1`
and `r2` (the k*S comparison is in the report). Status `calibrated` throughout: a non-zero
residual is a candidate exception, never a pass (07 §4).
"""

from __future__ import annotations

import json
from typing import Any

from tools.parity.render_fits import fit
from tools.parity.render_procedure.references import PAINTER
from tools.parity.schemas import REPO_ROOT

PATH = REPO_ROOT / "parity" / "semantics" / "iray.json"
UNIT = "16-bit display code"
GOLDEN_PREFIX = "phase0/iray-references/"


def src(source_id: str, locator: str) -> dict[str, str]:
    return {"source_id": source_id, "locator": locator}


def difference(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "max": stats["max_abs"],
        "mean": stats["mean_abs"],
        "p99": stats["p99_abs"],
        "differing": stats["differing_samples"],
        "total": stats["pixels"] * 3,
        "affected_texels": stats["differing"],
        "texels": stats["pixels"],
    }


def lattice_residuals(display_results: dict[str, Any]) -> list[dict[str, Any]]:
    """Each S recording's interior codes against the display-encoding lattice: an off-lattice
    sample is at most `max_distance_codes` away, counted at that distance."""
    out = []
    for name, recordings in display_results["per_golden"].items():
        for label in ("r1", "r2"):
            stats = recordings[label]
            total = int(stats["samples"])
            off = total - int(stats["samples_on_lattice"])
            distance = int(stats["max_distance_codes"])
            out.append(
                {
                    "golden_id": GOLDEN_PREFIX + name,
                    "map": "interior, every RGB sample",
                    "compared_against": label,
                    "unit": UNIT,
                    "difference": {
                        "max": distance,
                        "mean": off * distance / total,
                        "p99": distance if off > 0.01 * total else 0,
                        "differing": off,
                        "total": total,
                        "affected_texels": off,
                        "texels": total,
                    },
                }
            )
    return out


def residuals(results: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        held = results["held_out"][name]
        part = "interior held-out half" if held["held_out"] == "chessboard half" else "interior"
        for against, label in (("s1", "r1"), ("s2", "r2")):
            out.append(
                {
                    "golden_id": GOLDEN_PREFIX + name,
                    "map": f"{part}, every {fit.STEP}th px",
                    "compared_against": label,
                    "unit": UNIT,
                    "difference": difference(held[against]),
                }
            )
    return out


def signed_note(results: dict[str, Any], names: tuple[str, ...]) -> str:
    parts = []
    for name in names:
        k = results["held_out"][name]["k"]
        parts.append(f"{name} {k['mean_signed']:+.0f} +- {k['mean_signed_se']:.0f}")
    return "Mean signed (prototype - k*S), 16-bit codes: " + "; ".join(parts) + "."


def entries(results: dict[str, Any]) -> list[dict[str, Any]]:
    variant = results["fits"]["variant"]
    scale = results["fits"]["environment_scale"]
    lattice = results["display"]["interior"]
    bump = results["bump"]["strength"]
    filt = results["pixel_filter"]
    metal = fit.METAL_GOLDENS
    dielectric = fit.DIELECTRIC_GOLDENS
    edge_rows = [r for r in filt["rows"] if r["filter"] == filt["chosen"]]
    return [
        {
            "entry_id": "display-encoding",
            "subject": "Save Render 16-bit PNG under OCIO Default - sRGB (fixed pipeline)",
            "status": "calibrated",
            "formula": (
                "code = round(65535 encode(binary16(clamp(L, 0, 1)))) per RGB channel, L the "
                "linear render, binary16 IEEE 754 half precision (round to nearest even), encode "
                "the IEC 61966-2-1 sRGB encoding. Empirical model of the observed codes: it "
                "states which codes an Iray render can contain, not how Iray computes them."
            ),
            "public_sources": [
                src("S-SRGB", "IEC 61966-2-1:1999 §5.2 encoding"),
                src("S-OCIO", "display/view transform of an OCIO project"),
                src("S-EXR", "binary16 (half) pixel type"),
            ],
            "parameters": [{"name": "intermediate", "value": "binary16", "origin": "fitted"}],
            "residuals": lattice_residuals(results["display"]),
            "notes": (
                f"{lattice['samples_on_lattice']} of {lattice['samples']} interior RGB samples "
                f"of the 66 fixture renders ({lattice['fraction_on_lattice']:.4f}) lie on the "
                f"model's {lattice['lattice_codes']}-code lattice; every other sample is within "
                f"{lattice['max_distance_codes']} code of it."
            ),
        },
        {
            "entry_id": "environment-mapping",
            "subject": "Latitude-longitude environment orientation, lookup and intensity",
            "status": "calibrated",
            "formula": (
                "Direction d (Y up) to texel: u = frac(atan2(-d.x, d.z) / (2 pi) + 1/4 + "
                "rotation / 360), v = acos(d.y) / pi (row 0 = +Y); bilinear on texel centres; "
                "radiance = file value x 2^exposure x s, exposure 0, s fitted once for all "
                "goldens. Orientation fitted on the mirror sphere (the eight sign/offset "
                "candidates differ by more than 13x in mean |delta|)."
            ),
            "public_sources": [
                src("P-PBRT", "4th ed. §12.5 image infinite lights"),
                src("A-HELP-VIEWER", "environment map, rotation, exposure"),
            ],
            "parameters": [
                {"name": "u_offset", "value": 0.25, "origin": "fitted", "unit": "turn"},
                {"name": "intensity_scale", "value": round(scale, 5), "origin": "fitted"},
            ],
            "residuals": residuals(
                results,
                (
                    "neutral-reflective",
                    "neutral-reflective--ref-match-000",
                    "neutral-reflective--ref-match-180",
                ),
            ),
            "notes": signed_note(
                results,
                (
                    "neutral-reflective",
                    "neutral-reflective--ref-match-000",
                    "neutral-reflective--ref-match-180",
                ),
            ),
        },
        {
            "entry_id": "camera-and-pixel-filter",
            "subject": "Perspective camera of decision 046 and the pixel filter",
            "status": "calibrated",
            "formula": (
                "Pinhole at +Z 60 looking along -Z, +Y up, 40 degrees across the square "
                "1200 x 1200 image; sample positions drawn from the pixel filter "
                f"({filt['chosen']}; one-pixel box = uniform over the pixel square), each pixel "
                "the mean of its own samples."
            ),
            "public_sources": [
                src("P-PBRT", "4th ed. §5.2 projective cameras, §8.8 filters"),
                src("A-PYDOC", "display.Camera"),
            ],
            "parameters": [{"name": "filter", "value": filt["chosen"], "origin": "fitted"}],
            "residuals": residuals(
                results, ("neutral-grey-diffuse", "plane-mid-grey", "cube-mid-grey")
            ),
            "notes": "Edge band mean |delta| per golden: "
            + "; ".join(f"{r['golden']} {r['edge_mean_abs']:.0f}" for r in edge_rows)
            + " (16-bit codes, 256 samples).",
        },
        {
            "entry_id": "channel-quantisation",
            "subject": "Material channels as stored by Painter and read by the shader",
            "status": "calibrated",
            "formula": (
                "BaseColor: sRGB8 code = floor(255 c + 1/2) of the sRGB value c, decoded by "
                "IEC 61966-2-1; BaseMetalness and SpecularRoughness: L8 UNORM (truncate to 12 "
                "fractional bits, nearest, ties down), read as code / 255."
            ),
            "public_sources": [
                src("S-SRGB", "decoding"),
                src("X-D3D12", "FLOAT to UNORM conversion"),
            ],
            "parameters": [{"name": "srgb8_ties", "value": "up", "origin": "fitted"}],
            "residuals": residuals(results, ("neutral-reflective", "metal1-rough010")),
            "notes": (
                "The tie rule of sRGB 0.5 and 0.9 was chosen on the mirror sphere (code 230 "
                "fits better than 229); the L8 rule is Tier 0's (quantisation-profile.json)."
            ),
        },
        {
            "entry_id": "metal-lobe",
            "subject": "open-pbr base at metalness 1 (default shader, decision 042)",
            "status": "calibrated",
            "formula": (
                "f = F_schlick(o.h; F0 = base colour) D_GGX G2 / (4 cos_o cos_i) + "
                "F0 (1 - E1(mu_o)) (1 - E1(mu_i)) / (pi (1 - E1_avg)); alpha = roughness^2; "
                "G2 height-correlated Smith; E1 the lobe's albedo with F = 1 (tabulated). "
                "The multiple-scattering lobe is tinted by F0 (MDL multiscatter_tint)."
            ),
            "public_sources": [
                src("P-WALTER", "GGX distribution"),
                src("P-HEITZ", "2014 height-correlated G2; 2018 VNDF"),
                src("P-SCHLICK", "Fresnel approximation"),
                src("S-OPENPBR", "metal: F82-tint with white specular_color"),
                src("N-MDL-SPEC", "microfacet BSDF multiscatter_tint"),
                src("P-KULLA", "albedo-based multiple-scattering lobe"),
            ],
            "parameters": [
                {"name": "roughness_map", "value": variant["roughness_map"], "origin": "fitted"},
                {"name": "multiscatter", "value": variant["multiscatter"], "origin": "fitted"},
            ],
            "residuals": residuals(results, metal),
            "notes": signed_note(results, metal),
        },
        {
            "entry_id": "dielectric-lobe",
            "subject": "open-pbr base at metalness 0 (specular IOR 1.5 over diffuse)",
            "status": "calibrated",
            "formula": (
                f"f = f_s + layer f_d; f_s: GGX as the metal with Fresnel "
                f"'{variant['dielectric_fresnel']}' for IOR {variant['ior']}, multiple "
                f"scattering '{variant['dielectric_multiscatter']}'; f_d: "
                f"'{variant['diffuse']}' with the base colour; layering "
                f"'{variant['layering']}' (albedo_oi_raw: (1 - E_s(mu_o)) (1 - E_s(mu_i)), "
                "E_s the specular lobe's directional albedo). Metalness mixes metal and "
                "dielectric linearly."
            ),
            "public_sources": [
                src("S-OPENPBR", "dielectric base, albedo scaling"),
                src("N-MDL-SPEC", "df::fresnel_layer"),
                src("P-SCHLICK", "Fresnel approximation"),
                src("P-PBRT", "4th ed. §9.3 dielectric Fresnel, §14.3 layers"),
                src("P-BURLEY2012", "diffuse variant (rejected)"),
                src("S-GLTF", "Appendix B fresnel_mix (rejected)"),
            ],
            "parameters": [
                {"name": k, "value": variant[k], "origin": "fitted"}
                for k in (
                    "dielectric_fresnel",
                    "diffuse",
                    "layering",
                    "dielectric_multiscatter",
                    "ior",
                )
            ],
            "residuals": residuals(results, dielectric),
            "notes": signed_note(results, dielectric)
            + (
                " The low and mid roughness goldens keep a bias well outside the noise floor: "
                "the dielectric is not reproduced (an open lobe question for phase3.5)."
            ),
        },
        {
            "entry_id": "normal-and-bump",
            "subject": "Normal-map and height (bump) perturbation",
            "status": "calibrated",
            "formula": (
                "Tangent-space normal n_t = 2c - 1 (bitmap sampled bilinearly in UV) in the frame "
                "(T, B, N): T from the UV derivatives averaged per vertex and orthogonalised, "
                "B = N x T; height h = 2t - 1 bumped as n_t = normalize(-k dh/du, -k dh/dv, 1) "
                "with one-texel backward differences of the 256-px bitmap; where the perturbed "
                "normal faces away from the viewer the interpolated normal is kept."
            ),
            "public_sources": [
                src("S-MIKK", "tangent frame"),
                src("P-PBRT", "4th ed. §10.5 bump and normal mapping"),
            ],
            "parameters": [
                {
                    "name": "bump_strength",
                    "value": bump,
                    "origin": "fitted",
                    "unit": "per unit height per texel",
                }
            ],
            "residuals": residuals(results, ("normal-ridges", "height-stripes")),
            "notes": signed_note(results, ("normal-ridges", "height-stripes")),
        },
        {
            "entry_id": "ignored-channels",
            "subject": "Emission colour and opacity under the default shader",
            "status": "calibrated",
            "formula": (
                "Ignored: emission luminance 0, alpha test and alpha blending off (decision 042); "
                "the goldens render as metal0-rough050."
            ),
            "public_sources": [src("S-OPENPBR", "emission_luminance, geometry_opacity")],
            "parameters": [],
            "residuals": residuals(results, ("emission", "opacity-stripes")),
            "notes": signed_note(results, ("emission", "opacity-stripes", "metal0-rough050")),
        },
        {
            "entry_id": "geometry-and-ref-match",
            "subject": "Held-out geometry (plane, cube) and the ref_match environment",
            "status": "calibrated",
            "formula": (
                "The fitted model without change on the flat-faced meshes and under the "
                "ref_match HDRI at rotations 0 and 180."
            ),
            "public_sources": [src("P-PBRT", "4th ed. §6.5 triangle meshes")],
            "parameters": [],
            "residuals": residuals(
                results,
                (
                    "plane-mid-grey",
                    "cube-mid-grey",
                    "neutral-grey-diffuse--ref-match-000",
                    "neutral-grey-diffuse--ref-match-180",
                    "cube-saturated--ref-match-000",
                    "cube-saturated--ref-match-180",
                ),
            ),
            "notes": signed_note(
                results,
                (
                    "plane-mid-grey",
                    "cube-mid-grey",
                    "neutral-grey-diffuse--ref-match-000",
                    "neutral-grey-diffuse--ref-match-180",
                    "cube-saturated--ref-match-000",
                    "cube-saturated--ref-match-180",
                ),
            ),
        },
        {
            "entry_id": "transport",
            "subject": "Light transport of the prototype under the fixed pipeline",
            "status": "calibrated",
            "formula": (
                "Unidirectional path tracing, NEE toward the environment and a BSDF sample per "
                "vertex combined by the power heuristic, Russian roulette after depth 3, at most "
                "8 vertices, RGB in float64, Owen-scrambled Sobol under a fixed seed; a direction "
                "below the facet is absorbed. On one convex mesh under an infinite environment "
                "no light-carrying path has a second vertex."
            ),
            "public_sources": [
                src("P-KAJIYA", "rendering equation"),
                src("P-VEACH", "§9.2 power heuristic"),
                src("P-PBRT", "4th ed. §13.1, §13.4 path tracing"),
                src("P-BURLEY2020", "hash-based Owen scrambling"),
            ],
            "parameters": [
                {"name": "max_depth", "value": 8, "origin": "authored"},
                {"name": "rr_depth", "value": 3, "origin": "authored"},
            ],
            "residuals": residuals(results, ("neutral-grey-diffuse",)),
            "notes": (
                "Spectral transport, caustic paths and the maximum path depth are not "
                "identified by these goldens; see iray-noise-floor.md §5."
            ),
        },
    ]


def document(results: dict[str, Any]) -> dict[str, Any]:
    corpus = sorted(GOLDEN_PREFIX + name for name in results["held_out"])
    return {
        "schema": "uzpainter/parity/semantics/1",
        "record_class": "public_semantics",
        "semantics_id": "iray",
        "description": (
            "First clean-room lobe fits of the render feasibility prototype "
            "(tools/parity/render_fits, task phase0.8_render-reference-fits, decisions 050-052) "
            "against the admitted Iray references of the fixed render pipeline (decision 046): "
            "formulas with their public sources, fitted constants and residuals in 16-bit "
            "display codes on held-out pixels. NO LOBE IS REPRODUCED: every residual lies far "
            "outside the noise floor of parity/reports/phase0/iray-noise-floor.md, and it may "
            "come from the lobes, the environment handling or the geometry. The support is "
            "unequal: the display encoding and the environment orientation are tight, the "
            "metal lobe close, the dielectric, bump and filter first guesses."
        ),
        "painter_build_id": PAINTER["build_id"],
        "corpus": corpus,
        "entries": entries(results),
    }


def write(results: dict[str, Any]) -> str:
    PATH.write_text(json.dumps(document(results), indent=1) + "\n", encoding="utf-8", newline="\n")
    return str(PATH)
