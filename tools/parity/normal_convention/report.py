"""Public outputs of the normal-convention fixture: `parity/semantics/tangent-frame.json` (verdicts,
public sources, residuals) and `parity/reports/phase0/normal-convention.md` (numbers only).

Both are written from one study document (`study.run_study`), so the report's numbers are the
comparison output. The consumer section comes from
`tools/parity/normal_convention/uzengine-consumer.json`, the record of the UzEngine run.
"""

from __future__ import annotations

from typing import Any

from tools.parity.normal_convention.cases import BAKED_MAP, CASES, PAINTER_BUILD_ID
from tools.parity.normal_convention.fixtures import RESOLUTION
from tools.parity.schemas import REPO_ROOT, load_json

SEMANTICS_PATH = REPO_ROOT / "parity" / "semantics" / "tangent-frame.json"
REPORT_PATH = REPO_ROOT / "parity" / "reports" / "phase0" / "normal-convention.md"
CONSUMER_PATH = REPO_ROOT / "tools" / "parity" / "normal_convention" / "uzengine-consumer.json"
UNIT = "16-bit code value"
PREFIX = "phase0/normal-convention/"

MIKK = {"source_id": "S-MIKK", "locator": "mikktspace.h: setTSpaceBasic, normal-map sampler"}
GLTF = {
    "source_id": "S-GLTF",
    "locator": "Materials, additional textures: normalTexture (+X right, +Y up)",
}
PYDOC_FORMAT = {"source_id": "A-PYDOC", "locator": "substance_painter.project.NormalMapFormat"}
PYDOC_TANGENT = {"source_id": "A-PYDOC", "locator": "substance_painter.project.TangentSpace"}
PYDOC_BAKING = {"source_id": "A-PYDOC", "locator": "substance_painter.baking.bake_async"}


def residual_entries(study: dict[str, Any], golden_id: str, domain: str) -> list[dict[str, Any]]:
    return [
        {
            "golden_id": r["golden_id"],
            "map": f"{BAKED_MAP}/{r['candidate']}",
            "compared_against": r["recording"],
            "unit": UNIT,
            "difference": r["difference"],
        }
        for r in study["residuals"]
        if r["golden_id"] == golden_id and r["domain"] == domain
    ]


def status_of(residuals: list[dict[str, Any]], identified: bool = True) -> str:
    if residuals and all(r["difference"]["max"] == 0 for r in residuals):
        return "exact"
    return "calibrated" if identified else "gap"


def green_sign(direction: dict[str, float]) -> int:
    """+1 when green rises towards +v and falls towards -v, -1 for the reverse, else 0."""
    if direction["green_plus_v"] > 0 > direction["green_minus_v"]:
        return 1
    if direction["green_plus_v"] < 0 < direction["green_minus_v"]:
        return -1
    return 0


def oracle_green_sign(study: dict[str, Any], golden_id: str) -> int:
    signs = {
        green_sign(value)
        for key, value in study["directions"][golden_id].items()
        if key.startswith("oracle_")
    }
    return signs.pop() if len(signs) == 1 else 0


def convention_entries(study: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for fmt, flip in (("opengl", False), ("directx", True)):
        golden_id = f"{PREFIX}plane-dome/{fmt}"
        residuals = residual_entries(study, golden_id, "hit")
        sign = oracle_green_sign(study, golden_id)
        expected = -1 if flip else 1
        formula = (
            "On the plane-dome pair the low frame is T = +u direction, B = +v direction "
            "(sign +1), N = the plane normal at every texel, so the baked value is the hit "
            "triangle's normal n expressed as t = (n.T, n.B, n.N). Encoding: code = "
            "floor(65535 (t / 2 + 1/2) + 1/2) per channel, RGB = (x, y, z)"
        )
        if flip:
            formula += (
                "; DirectX conversion: the green code becomes 65535 - green (y negated), red "
                "and blue unchanged."
            )
        else:
            formula += "; OpenGL: green encodes +y, i.e. +v (up in UV space)."
        entries.append(
            {
                "entry_id": f"green-channel-{fmt}",
                "subject": (
                    f"Green channel of Painter's baked tangent-space normal, {fmt.capitalize()} "
                    "normal map format (plane-dome pair, hit texels)"
                    if fmt == "opengl"
                    else "Green channel of Painter's baked tangent-space normal, DirectX "
                    "normal map format (plane-dome pair, hit texels)"
                ),
                "status": status_of(residuals, sign == expected),
                "formula": formula,
                "public_sources": [GLTF, PYDOC_FORMAT, MIKK],
                "parameters": [
                    {"name": "normal_map_format", "value": fmt, "origin": "authored"},
                    {
                        "name": "expected_green_sign_towards_plus_v",
                        "value": expected,
                        "origin": "public_documentation",
                    },
                    {
                        "name": "observed_green_sign_towards_plus_v",
                        "value": sign,
                        "origin": "fitted",
                    },
                ],
                "residuals": residuals,
            }
        )
    miss = residual_entries(study, f"{PREFIX}plane-dome/opengl", "miss")
    if miss:
        entries.append(
            {
                "entry_id": "no-hit-texels",
                "subject": "Texels whose bake ray hits no high-poly triangle (plane-dome pair)",
                "status": status_of(miss),
                "formula": (
                    "A texel inside the low UV triangles whose ray hits no high triangle is "
                    "left empty: code 0 in every channel. The bake's dilation (DilationWidth, "
                    "default 32 px) then fills empty texels near hit texels; only texels more "
                    "than 40 texels from every hit texel are compared."
                ),
                "public_sources": [PYDOC_BAKING, MIKK],
                "parameters": [],
                "residuals": miss,
            }
        )
    return entries


def frame_entries(study: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    settings = {
        "per-fragment": "PerFragment",
        "per-vertex": "PerVertex",
        "project-default": "the project default (not set)",
    }
    for variant, setting in settings.items():
        golden_id = f"{PREFIX}hemisphere/{variant}"
        verdict = study["frames"][golden_id]
        residuals = residual_entries(study, golden_id, "hit")
        best = [r for r in residuals if r["map"].endswith(verdict["best_candidate"])]
        status = "exact" if verdict["equal"] else ("calibrated" if verdict["identified"] else "gap")
        entries.append(
            {
                "entry_id": f"tangent-frame-{variant}",
                "subject": (
                    f"Tangent frame of Painter's baked normal with tangent space {setting} "
                    "(hemisphere pair, OpenGL, hit texels)"
                ),
                "status": status if best else "gap",
                "formula": (
                    "Per-corner MikkTSpace frames (t_i, sign_i) of the low mesh "
                    "(genTangSpaceDefault), interpolated at the texel centre with the UV "
                    "barycentric weights w_i: vT = sum w_i t_i, vN = sum w_i n_i (unnormalized). "
                    "PerVertex: vB = sum w_i sign_i cross(n_i, t_i); PerFragment: vB = sign "
                    "cross(vN, vT). inverse: t = normalize(s (n.cross(vB, vN), n.cross(vN, vT), "
                    "n.cross(vT, vB))), s = sign of vT.cross(vB, vN); projection: t = "
                    "normalize(n.T, n.B, n.N) with T, B, N normalized. Closest: "
                    f"{verdict['best_candidate']}."
                ),
                "public_sources": [MIKK, PYDOC_TANGENT],
                "parameters": [
                    {"name": "identified_mode", "value": verdict["best_mode"], "origin": "fitted"},
                    {
                        "name": "closest_candidate",
                        "value": verdict["best_candidate"],
                        "origin": "fitted",
                    },
                    {
                        "name": "best_mean_abs_difference",
                        "value": verdict["best_mean"],
                        "origin": "fitted",
                        "unit": UNIT,
                    },
                    {
                        "name": "other_mode_best_mean_abs_difference",
                        "value": verdict["other_mode_best_mean"],
                        "origin": "fitted",
                        "unit": UNIT,
                    },
                    {"name": "identification_ratio", "value": 0.1, "origin": "authored"},
                ],
                "residuals": residuals,
            }
        )
    return entries


def semantics_document(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/semantics/1",
        "record_class": "public_semantics",
        "semantics_id": "tangent-frame",
        "description": (
            "Normal-map convention and tangent frame of Painter's baked tangent-space normal "
            "(P0-NORMAL): green-channel direction for the OpenGL and DirectX formats, and which "
            "MikkTSpace frame mode (PerVertex or PerFragment) and sampler transform the UzPainter "
            "prototype must use to equal Painter's bake, with residuals against the "
            "normal-convention goldens."
        ),
        "painter_build_id": PAINTER_BUILD_ID,
        "corpus": sorted(case.golden_id for case in CASES),
        "entries": convention_entries(study) + frame_entries(study),
    }


# ---------------------------------------------------------------- report


def fmt_diff(d: dict[str, Any]) -> str:
    return (
        f"{d['max']} | {d['mean']:.2f} | {d['p99']} | {d['differing']} | "
        f"{d['affected_texels']} / {d['texels']}"
    )


def report_markdown(study: dict[str, Any], environment: dict[str, str]) -> str:
    semantics = semantics_document(study)
    entries = {e["entry_id"]: e for e in semantics["entries"]}
    lines = [
        "# Normal convention fixture — report (P0-NORMAL)",
        "",
        "Task `phase0.9_normal-convention-fixture` (`docs/dag.md` P0-NORMAL, implements D11 and "
        "D6). Numbers only: every oracle is a private Painter recording in the owner's store; "
        "this report, the manifests and `parity/semantics/tangent-frame.json` hold statistics "
        "and hashes. Generated by `python -m tools.parity.normal_convention run`; do not edit "
        "by hand.",
        "",
        "## 1. Verdicts",
        "",
        "| Entry | Status | Finding |",
        "|---|---|---|",
    ]
    for entry_id, entry in entries.items():
        lines.append(f"| `{entry_id}` | {entry['status']} | {finding(entry_id, entry)} |")
    lines += [
        "",
        "Rule (Q1, decision 017): `exact` only when the prototype equals both recordings on every "
        "domain texel (max |Δ| 0). A non-zero residual is never a pass: a mode that is "
        "identified but not equal is `calibrated` (a candidate exception or a fix for P1-MESH), "
        "an unidentified one is a `gap`. A mode is *identified* when the best mean |Δ| of its "
        "candidates is at most a tenth of the other mode's.",
        "",
        "## 2. Scope",
        "",
        f"- Fixtures (`parity/fixtures/normal-convention/`, UzmiGames-authored, Apache-2.0; "
        "conventions in `tools/parity/normal_convention/fixtures.py`): `plane-dome` (flat "
        "low plane, faceted spherical cap as high) and `hemisphere` (coarse smooth hemisphere "
        "as low, its faceted copy scaled by 1.002 as high). Every high triangle is faceted, so "
        f"the baked world normal is constant per high triangle. Bake and texture set {RESOLUTION} "
        "px; other baking parameters at Painter's defaults except `MaxHeight` 0.2 on the "
        "plane-dome pair.",
        "- Goldens (`parity/manifests/phase0/normal-convention/`): "
        + ", ".join(f"`{c.golden_id.removeprefix(PREFIX)}`" for c in CASES)
        + "; each recorded twice (`r1` same session, `r2` after save and reopen). The bake "
        "backend is an uncontrolled setting (not readable through the documented API).",
        "- Prototype: `uzp-normal-prototype.exe` (`src/prototype/normal_prototype.cpp`, "
        "`zig build normal-prototype`), MikkTSpace from `thirdparty/mikktspace/`.",
        "- Domain texels: "
        + "; ".join(
            f"{pair}: " + ", ".join(f"{name} {count}" for name, count in counts.items())
            for pair, counts in study["domain_texels"].items()
        )
        + ".",
        "",
        "Comparison run: " + ", ".join(f"{k} {v}" for k, v in environment.items()) + ".",
        "",
        "## 3. Oracle stability (r1 against r2)",
        "",
        "| Golden | Domain | max \\|Δ\\| | mean | p99 | differing values | affected texels |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in study["stability"]:
        lines.append(
            f"| {s['golden_id'].removeprefix(PREFIX)} | {s['domain']} | "
            f"{fmt_diff(s['difference'])} |"
        )
    lines += [
        "",
        "## 4. Residuals (Painter recording against prototype map; 16-bit codes)",
        "",
        "| Golden | Recording | Prototype map | Domain | max \\|Δ\\| | mean | p99 | differing "
        "values | affected texels |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in study["residuals"]:
        lines.append(
            f"| {r['golden_id'].removeprefix(PREFIX)} | {r['recording']} | {r['candidate']} | "
            f"{r['domain']} | {fmt_diff(r['difference'])} |"
        )
    lines += [
        "",
        "## 5. Frame mode",
        "",
        "| Golden | Closest candidate | its mean \\|Δ\\| | other mode's best mean \\|Δ\\| | "
        "Identified mode | Equal |",
        "|---|---|---|---|---|---|",
    ]
    for golden_id, v in study["frames"].items():
        lines.append(
            f"| {golden_id.removeprefix(PREFIX)} | {v['best_candidate']} | {v['best_mean']:.2f} | "
            f"{v['other_mode_best_mean']:.2f} | {v['best_mode'] or 'none'} | "
            f"{'yes' if v['equal'] else 'no'} |"
        )
    lines += [
        "",
        "Project default (`hemisphere/project-default`, r1) against the explicit settings (r1):",
        "",
        "| Against | max \\|Δ\\| | mean | p99 | differing values | affected texels |",
        "|---|---|---|---|---|---|",
    ]
    for other, d in study["project_default_vs"].items():
        lines.append(f"| hemisphere/{other} | {fmt_diff(d)} |")
    lines += [
        "",
        "## 6. Direction check (task 3.3)",
        "",
        "Mean code minus 32768 on the plane-dome hit texels whose analytic tangent-space normal "
        "leans towards +v / -v (green) and +u / -u (red, control).",
        "",
        "| Golden | Map | green +v | green -v | red +u | red -u |",
        "|---|---|---|---|---|---|",
    ]
    for golden_id, d in study["directions"].items():
        for key, values in d.items():
            if key == "normal_map_format":
                continue
            lines.append(
                f"| {golden_id.removeprefix(PREFIX)} | {key} | {values['green_plus_v']:.1f} | "
                f"{values['green_minus_v']:.1f} | {values['red_plus_u']:.1f} | "
                f"{values['red_minus_u']:.1f} |"
            )
    lines += [
        "",
        "## 7. Prototype analytic check (task 3.1)",
        "",
        "Largest angle between the high-poly normal and the normal reconstructed from the "
        "tangent-space value by the matching shading transform (`exact`: before quantisation; "
        "`coded`: from the 16-bit codes).",
        "",
        "| Pair | Candidate | exact (°) | coded (°) |",
        "|---|---|---|---|",
    ]
    for pair, summary in study["prototype_summaries"].items():
        for name, errors in summary["round_trip_degrees"].items():
            lines.append(f"| {pair} | {name} | {errors['exact']:.3g} | {errors['coded']:.3g} |")
    lines += ["", *consumer_section(), ""]
    return "\n".join(lines)


def finding(entry_id: str, entry: dict[str, Any]) -> str:
    params = {p["name"]: p["value"] for p in entry["parameters"]}
    worst = max((r["difference"]["max"] for r in entry["residuals"]), default=0)
    if entry_id.startswith("green-channel-"):
        sign = params["observed_green_sign_towards_plus_v"]
        direction = {1: "+v", -1: "-v", 0: "no consistent direction"}[sign]
        return f"green rises towards {direction}; worst max \\|Δ\\| {worst}"
    if entry_id == "no-hit-texels":
        return f"worst max \\|Δ\\| against empty texels (code 0) {worst}"
    mode = params["identified_mode"] or "not identified"
    closest = params["closest_candidate"]
    worst_closest = max(
        r["difference"]["max"] for r in entry["residuals"] if r["map"].endswith(closest)
    )
    return f"mode {mode}, closest `{closest}`; worst max \\|Δ\\| of the closest {worst_closest}"


def consumer_section() -> list[str]:
    lines = ["## 8. External consumer: UzEngine (task 2.6)", ""]
    if not CONSUMER_PATH.exists():
        return [*lines, "No consumer run is recorded."]
    record = load_json(CONSUMER_PATH)
    lines += [str(line) for line in record["summary"]]
    if record.get("measurements"):
        lines += [
            "",
            "| Render | Light from | Normal map | -Z half | +Z half | -X half | +X half |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in record["measurements"]:
            lines.append(
                f"| {m['render']} | {m['light_from']} | {m['normal_map']} | {m['minus_z']:.4g} | "
                f"{m['plus_z']:.4g} | {m['minus_x']:.4g} | {m['plus_x']:.4g} |"
            )
    return lines
