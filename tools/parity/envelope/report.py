"""Published oracle-envelope results and `parity/reports/phase0/oracle-envelope.md`.

Every published file holds numbers, identifiers and hashes only (`parity/schema/` files
`oracle-envelope.json` and `envelope-registry.json`); environment fields stay in the private
records. The Markdown report is generated from the registry and the JSON results; with no
results it states what has not run.
Regenerate: `python -m tools.parity.envelope report`.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import RegistryError, load_registry
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors

REPORT_DIR = Path("parity") / "reports" / "phase0"
REPORT_MD = REPORT_DIR / "oracle-envelope.md"
DRAFTS_JSON = REPORT_DIR / "oracle-envelope-register-drafts.json"
STUDY_PREFIX = "oracle-envelope-study-"
DRIFT_PREFIX = "oracle-envelope-drift-"


class ReportError(Exception):
    """A result document is invalid and is not published."""


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Validate against `oracle-envelope.json`, then replace the file atomically."""
    problems = result_problems(dict(document))
    if problems:
        raise ReportError(f"{path.name}: refusing to publish an invalid result: {problems[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(temporary, path)


def draft_problems(draft: Mapping[str, Any]) -> list[str]:
    """A prepared register entry is a valid `exceptions.json` entry once the owner's approval
    fields are added, and it never carries them itself (decision 017)."""
    if "approved_by" in draft or "approved_on" in draft:
        return ["a prepared entry must not carry the owner's approval fields"]
    entry = {**draft, "approved_by": "owner", "approved_on": "2000-01-01"}
    return validation_errors(
        {"schema": "uzpainter/parity/exceptions/1", "entries": [entry]}, Schema.EXCEPTIONS
    )


def result_problems(document: Any) -> list[str]:
    """Schema violations of a published result, plus every prepared entry's problems."""
    problems = validation_errors(document, Schema.ORACLE_ENVELOPE)
    if problems or not isinstance(document, dict) or "drafts" not in document:
        return problems
    for index, draft in enumerate(document["drafts"]):
        problems += [f"drafts/{index}: {p}" for p in draft_problems(draft)]
    return problems


def study_path(study_id: str, repo_root: Path = REPO_ROOT) -> Path:
    return repo_root / REPORT_DIR / f"{STUDY_PREFIX}{study_id}.json"


def drift_path(scope: str, envelope_id: str, repo_root: Path = REPO_ROOT) -> Path:
    return repo_root / REPORT_DIR / f"{DRIFT_PREFIX}{scope}-{envelope_id}.json"


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def short(sha: str | None) -> str:
    return f"`{sha[:16]}`" if sha else "—"


def registry_section(repo_root: Path) -> list[str]:
    lines = ["## 1. Envelopes", ""]
    try:
        registry = load_registry(repo_root)
    except RegistryError as error:
        return [*lines, f"The envelope registry cannot be read: {error}", ""]
    lines += [
        f"Current envelope (the acceptance oracle, decision 037): `{registry['current']}`.",
        "",
    ]
    candidate = registry["candidate"]
    if candidate is None:
        lines += ["No candidate envelope is being recorded.", ""]
    else:
        lines += [
            f"Candidate being recorded: `{candidate['envelope_id']}` (Painter build "
            f"`{candidate['painter_build']}`, started {candidate['started_on']}); until it is "
            f"promoted, `{registry['current']}` stays current.",
            "",
        ]
    lines += [
        "| Envelope | Status | Painter build | Manifest root | Envelope SHA-256 | Environment "
        "known | Promoted | Superseded | Drift report |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in registry["envelopes"]:
        lines.append(
            f"| `{entry['envelope_id']}` | {entry['status']} | `{entry['painter_build']}` | "
            f"`{entry['manifest_root']}` | {short(entry['envelope_sha256'])} | "
            f"{'yes' if entry['environment_known'] else 'no'} | "
            f"{entry['promoted_on']} | {fmt(entry['superseded_on'])} | "
            f"{('`' + entry['drift_report'] + '`') if entry['drift_report'] else '—'} |"
        )
    lines.append("")
    if registry["quarantine"]:
        lines += ["Quarantined candidates (partial outputs kept in the private quarantine):", ""]
        lines += ["| Candidate | Painter build | Quarantined | Reason |", "|---|---|---|---|"]
        for item in registry["quarantine"]:
            lines.append(
                f"| `{item['envelope_id']}` | `{item['painter_build']}` | "
                f"{item['quarantined_on']} | {item['reason']} |"
            )
        lines.append("")
    return lines


def pair_cell(pair: Mapping[str, Any]) -> str:
    if pair["status"] == "equal":
        return f"{pair['left']}~{pair['right']}: equal"
    worst = pair.get("worst_map")
    detail = (
        f"max {fmt(worst['max'])} ({worst['storage']})"
        if worst
        else f"{pair['other_outputs_differing']} readback(s)"
    )
    return (
        f"{pair['left']}~{pair['right']}: {pair['status']}, {pair['maps_differing']} map(s), "
        f"{pair['values_differing']} value(s), {detail}"
    )


def difference_rows(goldens: list[Mapping[str, Any]]) -> list[str]:
    rows = [
        "| Golden | Pair | Output | Storage | Blob SHA-256 (left, right) | max \\|Δ\\| | mean "
        "\\|Δ\\| | p99 \\|Δ\\| | Differing values / compared | Differing texels / texels |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for golden in goldens:
        for output in golden["differing_outputs"]:
            diff = output.get("difference")
            shas = output.get("sha256")
            rows.append(
                f"| `{golden['golden_id']}` | {output['pair']} | `{output['output_id']}` | "
                f"{output.get('storage', output['kind'])} | "
                f"{(short(shas[0]) + ', ' + short(shas[1])) if shas else '—'} | "
                + (
                    f"{fmt(diff['max'])} | {fmt(diff['mean'])} | {fmt(diff['p99'])} | "
                    f"{diff['differing']} / {diff['total']} | "
                    f"{diff['affected_texels']} / {diff['texels']} |"
                    if diff
                    else f"— | — | — | {output['status']} | — |"
                )
            )
    return rows if len(rows) > 2 else []


def study_section(repo_root: Path) -> list[str]:
    lines = ["## 2. Stability study (decision 034 (b))", ""]
    studies = sorted((repo_root / REPORT_DIR).glob(f"{STUDY_PREFIX}*.json"))
    if not studies:
        return [
            *lines,
            "Not yet run. `python -m tools.parity.recorder stability-study parity/manifests/tier0 "
            "--launch` records every Tier 0 golden five times (two runs in one Painter session: "
            "r1/r2 each, then one run in a freshly started process) and publishes the result here.",
            "",
        ]
    study = load_json(studies[-1])
    lines += [
        f"Study `{study['study_id']}` on envelope `{study['envelope_id']}` (Painter build "
        f"`{study['painter_build']}`), generated {study['generated_on']}. Environment SHA-256 of "
        f"the sessions: {', '.join(short(s) for s in study['environment_sha256']) or '—'}.",
        "",
        "Recordings per golden: run `a` and run `b` in one Painter process (`r1` same session, "
        "`r2` after save and reopen each), run `c` in a freshly started process. Pairs: each "
        "run's `r2` against its `r1` (save_reopen), `b.r1` against `a.r1` (same_session) and "
        "`c.r1` against `a.r1` (fresh_process). Exact equality only; under decision 032 and "
        "034 (c) `r1` stays the exact target and nothing is averaged.",
        "",
        "| Classification | Goldens |",
        "|---|---|",
    ]
    for key, value in study["summary"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "| Golden | Classification | Run record SHA-256 (a, b, c) | Pairs |",
        "|---|---|---|---|",
    ]
    for golden in study["goldens"]:
        runs = ", ".join(
            f"{r['role']}: {short(r.get('record_sha256'))}"
            if r["status"] == "recorded"
            else f"{r['role']}: {r['status']}"
            for r in golden["runs"]
        )
        pairs = "; ".join(pair_cell(p) for p in golden["pairs"]) or "—"
        lines.append(f"| `{golden['golden_id']}` | {golden['classification']} | {runs} | {pairs} |")
    rows = difference_rows(study["goldens"])
    if rows:
        lines += ["", "Differing outputs:", "", *rows]
    lines.append("")
    return lines


def drift_section(repo_root: Path) -> list[str]:
    lines = ["## 3. Canary and envelope drift (decisions 034 (d), 037)", ""]
    drifts = sorted((repo_root / REPORT_DIR).glob(f"{DRIFT_PREFIX}*.json"))
    if not drifts:
        return [
            *lines,
            "Not yet run. The canary (`python -m tools.parity.recorder canary`) and every "
            "envelope refresh publish their drift against the previous envelope here.",
            "",
        ]
    for path in drifts:
        drift = load_json(path)
        summary = ", ".join(f"{k} {v}" for k, v in drift["summary"].items())
        lines += [
            f"### {drift['scope']}: `{drift['envelope_id']}` against "
            f"`{drift['previous_envelope_id']}`",
            "",
            f"`{path.relative_to(repo_root).as_posix()}`, generated {drift['generated_on']}; "
            f"Painter build `{drift['painter_build']}` against "
            f"`{drift['previous_painter_build']}`; "
            f"envelope SHA-256 {short(drift['envelope_sha256'])}. Goldens: {summary}.",
            "",
            "- Divergence candidates (UzPainter verdicts to re-establish): "
            + (", ".join(f"`{g}`" for g in drift["divergence_candidates"]) or "none"),
            "- New evaluator profile needed (a Tier 0 semantics golden changed): "
            + ("yes" if drift["new_evaluator_profile_needed"] else "no"),
            "- Stale Tier 3 references (never pass until re-recorded): "
            + (", ".join(f"`{g}`" for g in drift["stale_tier3"]) or "none"),
            "- Fits to re-check: "
            + (
                ", ".join(f"`{f['semantics']}` ({f['reason']})" for f in drift["fits_to_recheck"])
                or "none"
            ),
            "",
            "| Golden | Status | Previous record | New record | Changed recordings |",
            "|---|---|---|---|---|",
        ]
        for golden in drift["goldens"]:
            lines.append(
                f"| `{golden['golden_id']}` | {golden['status']} | "
                f"{short(golden.get('previous_record_sha256'))} | "
                f"{short(golden.get('record_sha256'))} | "
                f"{', '.join(golden['changed_recordings']) or '—'} |"
            )
        rows = difference_rows(drift["goldens"])
        if rows:
            lines += ["", *rows]
        lines.append("")
    return lines


def drafts_section(repo_root: Path) -> list[str]:
    lines = ["## 4. Prepared register entries (decisions 017, 034 (c))", ""]
    path = repo_root / DRAFTS_JSON
    if not path.is_file():
        studied = any((repo_root / REPORT_DIR).glob(f"{STUDY_PREFIX}*.json"))
        reason = (
            "the stability study found no fresh-process-unstable golden"
            if studied
            else "the stability study has not run"
        )
        return [*lines, f"None prepared: {reason}.", ""]
    drafts = load_json(path)
    lines += [
        f"`{DRAFTS_JSON.as_posix()}` (study `{drafts['study_id']}`): "
        f"{len(drafts['drafts'])} draft(s), status `{drafts['status']}`. They are not in force: "
        "each needs the owner's approval before it is moved into `parity/exceptions.json`.",
        "",
    ]
    for draft in drafts["drafts"]:
        lines.append(
            f"- {draft['exception_id']} (provisional): `{draft['domain']['selector']}`, bounds "
            + ", ".join(f"{b['metric']} ≤ {fmt(b['max'])}" for b in draft["bounds"])
        )
    lines.append("")
    return lines


def render(repo_root: Path = REPO_ROOT) -> str:
    lines = [
        "# Oracle envelope (phase0.9_oracle-envelope)",
        "",
        "Decisions 034 (envelope, stability study, canary) and 037 (rolling oracle: the acceptance "
        "oracle is the newest promoted envelope). Numbers and hashes only: environment records, "
        "recorded outputs and runs stay in the owner's private store and inbox. Generated by "
        "`python -m tools.parity.envelope report`; do not edit by hand. Procedures: "
        "`parity/RECORDER.md` §10.",
        "",
        *registry_section(repo_root),
        *study_section(repo_root),
        *drift_section(repo_root),
        *drafts_section(repo_root),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(repo_root: Path = REPO_ROOT) -> Path:
    path = repo_root / REPORT_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(repo_root), encoding="utf-8", newline="\n")
    return path
