"""Generated blocks of `parity/reports/phase0/iray-noise-floor.md` (task item 2.7).

`write(results, probes)` replaces the blocks between `<!-- name:begin -->` and
`<!-- name:end -->` markers with tables built from `pipeline.run`'s numbers; the prose around
them is maintained by hand. Units: 16-bit display codes unless a column says otherwise
(1e-4 of full scale = 6.55 codes; one 8-bit code = 257 codes).
"""

from __future__ import annotations

import math
from typing import Any

from tools.parity.render_fits.pipeline import ALL_GOLDENS, FACE_GOLDENS
from tools.parity.render_procedure.noise import FULL_SCALE
from tools.parity.render_procedure.report import replace_block
from tools.parity.schemas import REPO_ROOT

REPORT = REPO_ROOT / "parity" / "reports" / "phase0" / "iray-noise-floor.md"
REGIONS = ("interior", "edge", "background")


def c(value: float | None, digits: int = 0) -> str:
    """A fraction of full scale as 16-bit codes."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value * FULL_SCALE:.{digits}f}"


def n(value: float | None, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.{digits}f}"


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def display_block(results: dict[str, Any]) -> str:
    d = results["display"]["interior"]
    return table(
        [
            "Interior RGB samples",
            "On the lattice",
            "Fraction",
            "Distinct codes",
            "Off-lattice codes",
            "Largest distance",
            "Lattice size",
        ],
        [
            [
                str(d["samples"]),
                str(d["samples_on_lattice"]),
                f"{d['fraction_on_lattice']:.4f}",
                str(d["distinct_codes"]),
                str(d["distinct_codes_off_lattice"]),
                f"{d['max_distance_codes']} code",
                str(d["lattice_codes"]),
            ]
        ],
    )


def stability_block(results: dict[str, Any]) -> str:
    rows = []
    for name in ALL_GOLDENS:
        s = results["stability"][name]["interior"]["half_steps"]
        rows.append(
            [
                f"`{name}`",
                str(s["differing_samples"]),
                s["steps"]["1"],
                s["steps"]["2"],
                s["steps"]["3"],
                str(s["more_than_3"]),
                str(s["max_steps"]),
                f"{s['one_step_fraction']:.3f}",
            ]
        )
    rows = [[str(x) for x in r] for r in rows]
    return table(
        [
            "Golden",
            "(a) differing samples",
            "1 step",
            "2 steps",
            "3 steps",
            "> 3 steps",
            "Max steps",
            "One-step fraction",
        ],
        rows,
    )


def faces_block(results: dict[str, Any]) -> str:
    rows = []
    for name in FACE_GOLDENS:
        for label, face in results["stability"][name].get("faces", {}).items():
            a = face["run_to_run"]
            b = face["mc_error_at_s"]
            rows.append(
                [
                    f"`{name}`",
                    label,
                    str(face["pixels"]),
                    f"{a['differing_pixels'] / max(face['pixels'], 1):.3f}",
                    c(a["rms"], 1),
                    c(b["rms"], 1),
                    f"{(a['rms'] / b['rms']) ** 2 / 2:.3f}" if b["rms"] else "-",
                    f"{face['half_steps']['one_step_fraction']:.2f}",
                ]
            )
    return table(
        [
            "Golden",
            "Face (facet normal)",
            "Pixels",
            "(a) differing fraction",
            "(a) rms",
            "(b) rms",
            "rms(a)^2 / 2 rms(b)^2",
            "One-step fraction",
        ],
        rows,
    )


def sequence_block(results: dict[str, Any]) -> str:
    rows = []
    for name in ALL_GOLDENS:
        st = results["stability"][name]["interior"]
        q = st["sequence"]
        rows.append(
            [
                f"`{name}`",
                n(q["sigma_s"], 1),
                n(q["sigma_k"], 1),
                n(q["variance_ratio"], 3),
                n(q["rms_s_minus_k"], 1),
                n(q["nested_prediction"], 1),
                n(q["independent_prediction"], 1),
                n(st["jensen_predicted"], 2),
                " / ".join(n(v, 2) for v in st["mean_signed_s_minus_k"]),
            ]
        )
    return table(
        [
            "Golden",
            "sigma S (high-pass)",
            "sigma K",
            "sigma_K^2 / sigma_S^2",
            "rms(S - K)",
            "nested prediction",
            "independent prediction",
            "Jensen-predicted S - K",
            "observed S - K (s1 / s2)",
        ],
        rows,
    )


def noise_block(results: dict[str, Any]) -> str:
    rows = []
    for name in ALL_GOLDENS:
        ab = results["noise_ab"][name]
        cc = results["noise_c"][name]
        for region in REGIONS:
            a = ab["run_to_run"][region]
            if not a.get("pixels"):
                continue
            b = ab["mc_error_at_s"][0][region]
            pc = cc["c"][0][region]
            if region == "background" and not pc.get("pixels"):
                pc = {}
            rows.append(
                [
                    f"`{name}`",
                    region,
                    str(a["pixels"]),
                    c(a["mean_abs"], 1),
                    c(a["p99_abs"]),
                    c(b["mean_abs"], 1),
                    c(b["p99_abs"]),
                    f"{c(b['mean_signed'], 2)} ± {c(b['mean_signed_se'], 2)}",
                    str(pc.get("pixels", "-")),
                    c(pc.get("mean_abs"), 1),
                    c(pc.get("p99_abs")),
                    f"{c(pc.get('mean_signed'), 2)} ± {c(pc.get('mean_signed_se'), 2)}"
                    if pc
                    else "-",
                    " / ".join(c(b["downsampled"][f]["mean_abs"], 1) for f in ("2", "4", "8")),
                    " / ".join(c(pc["downsampled"][f]["mean_abs"], 1) for f in ("2", "4", "8"))
                    if pc
                    else "-",
                ]
            )
    return table(
        [
            "Golden",
            "Region",
            "Pixels",
            "(a) mean abs",
            "(a) p99",
            "(b) mean abs",
            "(b) p99",
            "(b) mean signed ± se",
            "(c) crop pixels",
            "(c) mean abs",
            "(c) p99",
            "(c) mean signed ± se",
            "(b) 2x/4x/8x mean abs",
            "(c) 2x/4x/8x mean abs",
        ],
        rows,
    )


def fits_block(results: dict[str, Any]) -> str:
    rows = []
    for name in ALL_GOLDENS:
        h = results["held_out"][name]
        k = h["k"]
        rows.append(
            [
                f"`{name}`",
                h["held_out"],
                str(k["pixels"]),
                f"{k['mean_signed']:+.0f} ± {k['mean_signed_se']:.0f}",
                " / ".join(f"{v:+.0f}" for v in k["mean_signed_per_channel"]),
                f"{k['mean_abs']:.0f}",
                f"{k['p99_abs']:.0f}",
                f"{k['rms']:.0f}",
                f"{h['s1']['mean_signed']:+.0f} / {h['s2']['mean_signed']:+.0f}",
            ]
        )
    return table(
        [
            "Golden",
            "Pixels used",
            "Pixels",
            "Mean signed vs k*S ± se",
            "Per channel (R / G / B)",
            "Mean abs",
            "p99 abs",
            "rms",
            "Mean signed vs S1 / S2",
        ],
        rows,
    )


def ranking_block(results: dict[str, Any]) -> str:
    f = results["fits"]
    rows = []
    for r in f["ranking"][:10]:
        m, d = r["metal"], r["dielectric"]
        rows.append(
            [
                f"{m['roughness_map']}",
                m["multiscatter"],
                d["dielectric_fresnel"],
                d["diffuse"],
                d["layering"],
                d["dielectric_multiscatter"],
                n(r["score_unit_scale"], 0),
                n(r["scale"], 4),
                n(r["score"], 0),
            ]
        )
    head = (
        f"{f['candidates']} metal x dielectric combinations scored; chosen environment "
        f"scale {f['environment_scale']:.4f}.\n\n"
    )
    return head + table(
        [
            "Roughness map",
            "Metal multiscatter",
            "Dielectric Fresnel",
            "Diffuse",
            "Layering",
            "Dielectric multiscatter",
            "Score at scale 1",
            "Fitted scale",
            "Score",
        ],
        rows,
    )


def filter_block(results: dict[str, Any]) -> str:
    rows = [
        [
            f"`{r['golden']}`",
            r["filter"],
            n(r["edge_mean_abs"], 0),
            n(r["edge_rms"], 0),
            n(r["edge_mean_signed"], 0),
        ]
        for r in results["pixel_filter"]["rows"]
    ]
    bump = results["bump"]
    lines = table(["Golden", "Filter", "Edge mean abs", "Edge rms", "Edge mean signed"], rows)
    lines += "\n" + table(
        ["Bump strength"] + [n(k, 2) for k in bump["grid"]],
        [["rms vs k*S (fit half)"] + [n(v, 0) for v in bump["rms"]]],
    )
    return lines


def flip_block(results: dict[str, Any]) -> str:
    rows = []
    for name in ALL_GOLDENS:
        flip = results["noise_c"][name].get("flip")
        if not flip:
            continue
        for region in ("interior", "edge"):
            rows.append(
                [
                    f"`{name}`",
                    region,
                    n(flip["iray_s_vs_k"].get(region), 4),
                    n(flip["prototype_s_vs_prototype_k"].get(region), 4),
                    n(flip["prototype_s_vs_iray_k"].get(region), 4),
                ]
            )
    return table(
        [
            "Golden",
            "Region",
            "Iray S vs Iray k*S",
            "Prototype S vs prototype k*S",
            "Prototype S vs Iray k*S",
        ],
        rows,
    )


def transport_block(results: dict[str, Any]) -> str:
    t = results["transport"]
    rows = []
    for name, runs in t["below_facet"].items():
        for label, data in runs.items():
            v = data["vs_absorb_depth8"]
            k = data["vs_iray_k"]
            rows.append(
                [
                    f"`{name}`",
                    label,
                    f"{v['mean_signed']:+.1f}",
                    f"{v['max_abs']:.0f}",
                    str(v["differing"]),
                    f"{k['mean_signed']:+.0f} ± {k['mean_signed_se']:.0f}",
                    f"{k['rms']:.0f}",
                ]
            )
    out = table(
        [
            "Golden",
            "Run",
            "Mean signed vs absorb/8",
            "Max abs vs absorb/8",
            "Differing pixels",
            "Mean signed vs k*S ± se",
            "rms vs k*S",
        ],
        rows,
    )
    srows = []
    for name, s in t["spectral"].items():
        d = s["spectral_minus_rgb"]
        srows.append(
            [
                f"`{name}`",
                " / ".join(f"{v:.4f}" for v in s["base_color_linear"]),
                f"{s['environment_chroma_spread']:.3f}",
                " / ".join(f"{v:+.1f}" for v in d["mean_signed_per_channel"]),
                f"{d['max_abs']:.0f}",
                f"{s['rgb_vs_iray_k']['mean_signed']:+.0f}",
                f"{s['spectral_vs_iray_k']['mean_signed']:+.0f}",
                f"{s['upsampling_round_trip_max']:.1e}",
            ]
        )
    out += "\n" + table(
        [
            "Golden",
            "Base colour (linear)",
            "Env chroma spread (p99)",
            "Spectral - RGB per channel",
            "Max abs",
            "RGB vs k*S",
            "Spectral vs k*S",
            "Upsampling round trip",
        ],
        srows,
    )
    return out


def defects_block(results: dict[str, Any]) -> str:
    rows = []
    for defect, d in results["defects"].items():
        for region in ("interior", "edge"):
            fitted, broken, shift = (
                d["fitted"][region],
                d["defect"][region],
                d["defect_vs_fitted"][region],
            )
            if not fitted.get("pixels"):
                continue
            floor = results["noise_c"][d["golden"]]
            b_se = floor["b_crop"][0][region]["mean_signed_se"] or 0.0
            c_se = floor["c"][0][region]["mean_signed_se"] or 0.0
            combined = math.sqrt(b_se**2 + c_se**2)
            change = shift["mean_signed"]
            ds_f = fitted["downsampled"]["8"]["mean_abs"]
            ds_b = broken["downsampled"]["8"]["mean_abs"]
            outside = abs(change) > 3 * combined or (
                ds_f is not None and ds_b is not None and ds_b > ds_f + 3 * combined
            )
            rows.append(
                [
                    defect,
                    f"`{d['golden']}`",
                    region,
                    f"{c(fitted['mean_signed'], 1)} ± {c(fitted['mean_signed_se'], 1)}",
                    f"{c(broken['mean_signed'], 1)} ± {c(broken['mean_signed_se'], 1)}",
                    c(change, 1),
                    c(combined, 2),
                    c(ds_f, 1),
                    c(ds_b, 1),
                    "outside" if outside else "inside",
                ]
            )
    return table(
        [
            "Defect",
            "Golden",
            "Region",
            "Fitted vs k*S ± se",
            "Defect vs k*S ± se",
            "Mean signed shift",
            "Combined se (b, c)",
            "Fitted 8x mean abs",
            "Defect 8x mean abs",
            "Verdict",
        ],
        rows,
    )


def repeatability_block(results: dict[str, Any]) -> str:
    r = results["repeatability"]
    return table(
        ["Pixels", "Samples", "Run 1 SHA-256", "Run 2 SHA-256", "Identical"],
        [
            [
                str(r["pixels"]),
                str(r["samples"]),
                f"`{r['sha256'][0]}`",
                f"`{r['sha256'][1]}`",
                "yes" if r["identical"] else "no",
            ]
        ],
    )


def probes_block(probes: dict[str, Any]) -> str:
    env = probes["environment"]
    head = (
        f"`UzPainter.exe selftest` started {probes['started_utc']}, result "
        f"`{probes['result']}`; {env.get('os_product', '')} build {env.get('os_build', '')}, "
        f"{env.get('cpu', '')}, Zig {env.get('zig', '')} {env.get('build_mode', '')}.\n\n"
    )
    rows = []
    for probe in probes["probes"]:
        if probe["probe"] not in ("dx12-ray-query", "vulkan-ray-query"):
            continue
        for check in probe["executed_checks"]:
            rows.append(
                [
                    f"`{probe['probe']}`",
                    probe["adapter"],
                    probe["driver"],
                    check["check"],
                    check["result"],
                    check["detail"],
                ]
            )
    return head + table(["Probe", "Adapter", "Driver", "Check", "Result", "Detail"], rows)


def write(results: dict[str, Any], probes: dict[str, Any] | None = None) -> str:
    text = REPORT.read_text(encoding="utf-8")
    blocks = {
        "display": display_block(results),
        "half-steps": stability_block(results),
        "faces": faces_block(results),
        "sequence": sequence_block(results),
        "noise-floor": noise_block(results),
        "flip": flip_block(results),
        "fits": fits_block(results),
        "ranking": ranking_block(results),
        "filter": filter_block(results),
        "transport": transport_block(results),
        "defects": defects_block(results),
        "repeatability": repeatability_block(results),
    }
    if probes is not None:
        blocks["probes"] = probes_block(probes)
    for name, body in blocks.items():
        text = replace_block(text, name, body)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    return str(REPORT)


def short(label: str) -> str:
    """`golden/recording` with the recording id only (the golden is in the row)."""
    return label.split("/", 1)[1]


def probe_captures_block(probe: dict[str, Any]) -> str:
    rows = []
    for name, golden in probe["goldens"].items():
        key = golden.get("key_equals_parent")
        for capture in golden["captures"]:
            rows.append(
                [
                    f"`{name}`",
                    capture["condition"],
                    f"`{capture['recording_id']}`",
                    capture["recorded_at"][:19] + "Z",
                    f"`{capture['render_sha256']}`",
                    f"`{capture['staged_sha256']}`",
                    "-" if key is None else ("yes" if key else "no"),
                ]
            )
    return table(
        [
            "Golden",
            "Condition",
            "Recording",
            "Recorded (UTC)",
            "Render SHA-256",
            "Staged recording SHA-256",
            "Key equals parent",
        ],
        rows,
    )


def probe_pair_row(entry: dict[str, Any]) -> list[str]:
    return [
        str(entry["pixels"]),
        f"{entry['differing_fraction']:.4f}",
        f"{entry['rms_codes']:.1f}",
        str(entry["half_steps"]["max_steps"]),
        f"{entry['half_steps']['one_step_fraction']:.2f}",
        entry["class"],
    ]


def probe_faces_block(probe: dict[str, Any]) -> str:
    rows = []
    for name, golden in probe["goldens"].items():
        result = golden["pair"]
        for label, face in result["faces"].items():
            rows.append([f"`{name}`", label, *probe_pair_row(face), result["class"]])
    return table(
        [
            "Golden",
            "Facet",
            "Pixels",
            "(a) differing fraction",
            "(a) rms",
            "Max steps",
            "One-step fraction",
            "Facet class",
            "Pair class",
        ],
        rows,
    )


def probe_clusters_block(probe: dict[str, Any]) -> str:
    parts = []
    for name, found in probe["clusters"].items():
        classes = "; ".join(
            "{" + ", ".join(f"`{short(label)}`" for label in group) + "}"
            for group in found["classes"]
        )
        parts.append(
            f"`{name}`: {len(found['renders'])} S renders, one golden key: "
            f"{'yes' if found['same_key'] else 'no'}; classes: {classes}; consistent with a "
            f"binary choice: {'yes' if found['binary_consistent'] else 'no'}.\n"
        )
        rows = []
        for item in found["pairs"]:
            interior = item["regions"]["interior"]
            faces = list(item["faces"].values()) or [interior]
            worst = max(faces, key=lambda f: f["differing_fraction"])
            rows.append(
                [
                    f"`{item['a']}`",
                    f"`{short(item['b'])}`",
                    "yes" if item["same_session"] else "no",
                    "yes" if item["pixel_identical"] else "no",
                    *probe_pair_row(worst)[1:-1],
                    item["class"],
                ]
            )
        parts.append(
            table(
                [
                    "Render",
                    "Render",
                    "Same session",
                    "Pixel identical",
                    "(a) differing fraction (worst facet)",
                    "(a) rms",
                    "Max steps",
                    "One-step fraction",
                    "Class",
                ],
                rows,
            )
        )
    return "\n".join(parts)


def reproducibility_block(probe: dict[str, Any]) -> str:
    rep = probe["reproducibility"]
    head = (
        f"Scene `{rep['scene']}`. k*S render `{rep['k_render']}` (`{rep['k_render_sha256']}`, "
        f"high-pass sigma {rep['k_highpass_sigma_codes']:.1f} codes). Of {rep['pairs']} pairs of "
        f"S renders, {rep['byte_identical_pairs']} are byte-identical and "
        f"{rep['pixel_identical_pairs']} pixel-identical.\n\n"
    )
    rows = [
        [
            f"`{r['render']}`",
            r["condition"],
            r["recorded_at"][:19] + "Z",
            f"`{r['render_sha256']}`",
            f"{r['rendering_time_s']:g}",
            f"{r['highpass_sigma_codes']:.1f}",
            f"{r['b_rms_codes']:.1f}",
            f"{r['b_mean_signed_codes']:+.2f}",
        ]
        for r in rep["renders"]
    ]
    return head + table(
        [
            "Render",
            "Condition",
            "Recorded (UTC)",
            "Render SHA-256",
            "Rendering time (s)",
            "High-pass sigma",
            "(b) rms vs k*S",
            "(b) mean signed",
        ],
        rows,
    )


def observability_block(probe: dict[str, Any]) -> str:
    rows = [
        [
            row["setting"],
            str(row["value"]),
            row["set_by"],
            row["read_back"],
            row["confirmed"],
            f"`{row['row']}`",
            f"`{row['status']}`",
        ]
        for row in probe["observability"]
    ]
    return table(
        [
            "Setting",
            "Value",
            "Set by",
            "Read back on each capture",
            "Captures confirming",
            "Procedure row",
            "Row status (phase0.6)",
        ],
        rows,
    )


def write_probe(probe: dict[str, Any]) -> str:
    """The generated blocks of the capture request and the reproducibility probe (decision 062)."""
    text = REPORT.read_text(encoding="utf-8")
    blocks = {
        "probe-captures": probe_captures_block(probe),
        "probe-faces": probe_faces_block(probe),
        "probe-clusters": probe_clusters_block(probe),
        "reproducibility": reproducibility_block(probe),
        "observability": observability_block(probe),
    }
    for name, body in blocks.items():
        text = replace_block(text, name, body)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    return str(REPORT)
