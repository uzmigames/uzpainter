"""Answers to the "not confirmed" rows of 07-preview-and-render-parity.md §2.1 (and §3.3).

The answers live in the report `parity/reports/phase0/iray-capture-procedure.md`, as a JSON
block between `<!-- answers:begin -->` and `<!-- answers:end -->` (the repository guard admits no
other JSON data under `parity/`), with a summary table rendered from it between
`<!-- answers-table:begin -->` and `<!-- answers-table:end -->`. Each row has a status
(`documented`, `confirmed_by_probe`, `uncontrolled`, or `pending_probe` until the probe session
has run), the answer in UzmiGames' words, and its evidence by SHA-256: public documentation as
retrieved, or private probe files, never their content. `merge_probe` folds a probe's answers
in; `pending` lists what is still open (acceptance needs it empty).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT

REPORT_PATH = REPO_ROOT / "parity" / "reports" / "phase0" / "iray-capture-procedure.md"
SCHEMA = "uzpainter/parity/iray-capture-answers/1"
STATUSES = ("documented", "confirmed_by_probe", "uncontrolled", "pending_probe")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BLOCK = re.compile(r"(<!-- answers:begin -->\n```json\n)(.*?)(\n```\n<!-- answers:end -->)", re.S)
TABLE = re.compile(r"(<!-- answers-table:begin -->\n)(.*?)(<!-- answers-table:end -->)", re.S)

# Row id -> the row of 07 §2.1 (or §3.3) it answers.
ROWS = {
    "colour_lut": "Colour LUT: where Iray applies it in the display chain",
    "display_view_transform": "Colour-management mode: the selected display/view transform",
    "iray_settings": (
        "Min Sample, Max Sample, Max Time, Caustic Sampler, Firefly Filter, override "
        "resolution: persistence and readback"
    ),
    "readiness": "Convergence state (Status, Iterations, Rendering time): programmatic readiness",
    "viewer_mdl_settings": "Environment exposure and rotation, dome, ground (Viewer and MDL)",
    "display_settings": "Which display settings shared with the viewport change the Iray image",
    "default_mdl_parameters": "Default-MDL material parameters per material instance",
    "denoiser": "Denoiser: does it affect the saved render, can it be disabled",
    "random_seed": "Random seed: are repeated renders bit-identical",
    "save_render": "Save Render: format, bit depth, display transform baked in",
    "stale_frame": "Save Render: stale-frame behaviour",
    "height": "Height applied as bump or displacement (§3.3)",
    "camera_projection": "Camera conventions behind silhouette verification (§2.2 step 5)",
    "pixel_route": "Pixel route: Save Render or the external 1:1 observation fallback",
}


def load_answers(report: Path = REPORT_PATH) -> dict[str, Any]:
    match = BLOCK.search(report.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{report}: no answers block")
    data: dict[str, Any] = json.loads(match.group(2))
    return data


def table(data: dict[str, Any]) -> str:
    lines = ["| Row (07 §2.1, §3.3) | Status | Evidence |", "|---|---|---|"]
    for row, setting in ROWS.items():
        entry = data["rows"].get(row, {"status": "missing", "evidence": []})
        sources = ", ".join(e["source"] for e in entry["evidence"]) or "none"
        lines.append(f"| `{row}`: {setting} | `{entry['status']}` | {sources} |")
    return "\n".join(lines) + "\n"


def write_answers(data: dict[str, Any], report: Path = REPORT_PATH) -> None:
    text = report.read_text(encoding="utf-8")
    block = json.dumps(data, indent=2, ensure_ascii=False)
    text = BLOCK.sub(lambda m: m.group(1) + block + m.group(3), text)
    text = TABLE.sub(lambda m: m.group(1) + table(data) + m.group(3), text)
    report.write_text(text, encoding="utf-8")


def table_in_report(report: Path = REPORT_PATH) -> str:
    match = TABLE.search(report.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{report}: no answers table")
    return match.group(2)


def uncontrolled(data: dict[str, Any]) -> list[str]:
    return sorted(
        row for row, entry in data.get("rows", {}).items() if entry.get("status") == "uncontrolled"
    )


def problems(data: dict[str, Any]) -> list[str]:
    """Structural problems: missing or unknown rows, bad status, settled rows without evidence."""
    found: list[str] = []
    if data.get("schema") != SCHEMA:
        found.append(f"schema must be {SCHEMA}")
    rows = data.get("rows", {})
    for row in sorted(set(ROWS) - set(rows)):
        found.append(f"{row}: no answer")
    for row in sorted(set(rows) - set(ROWS)):
        found.append(f"{row}: not a row of 07 §2.1")
    for row, entry in sorted(rows.items()):
        if entry.get("status") not in STATUSES:
            found.append(f"{row}: status {entry.get('status')!r} not in {STATUSES}")
        if not entry.get("answer"):
            found.append(f"{row}: empty answer")
        evidence = entry.get("evidence", [])
        if entry.get("status") != "pending_probe" and not evidence:
            found.append(f"{row}: settled without evidence")
        for item in evidence:
            if not SHA256.match(str(item.get("sha256", ""))) or not item.get("source"):
                found.append(f"{row}: evidence {item!r} needs a source and a SHA-256")
    if sorted(data.get("uncontrolled", [])) != uncontrolled(data):
        found.append("`uncontrolled` must list exactly the rows with status uncontrolled")
    return found


def pending(data: dict[str, Any]) -> list[str]:
    return sorted(row for row, entry in data["rows"].items() if entry["status"] == "pending_probe")


def merge_probe(data: dict[str, Any], probe_file: Path) -> dict[str, Any]:
    """Fold the probe's answers in; evidence names become (source, SHA-256) pairs."""
    probe = json.loads(probe_file.read_text(encoding="utf-8"))
    probe_sha = sha256_file(probe_file)
    files = probe["files"]
    merged: dict[str, Any] = json.loads(json.dumps(data))
    for row, result in probe["answers"].items():
        if row not in ROWS:
            raise ValueError(f"probe answers an unknown row {row!r}")
        details = {k: v for k, v in result.items() if k not in ("status", "answer", "evidence")}
        evidence = [
            {
                "source": f"probe:{name}",
                "sha256": probe_sha if name == "probe.json" else files[name]["sha256"],
            }
            for name in result["evidence"]
        ]
        merged["rows"][row] = {
            "status": result["status"],
            "answer": result["answer"],
            "evidence": evidence,
            "details": details,
        }
    merged["probe"] = {
        "probe_json_sha256": probe_sha,
        "painter_build": probe["painter_build"],
        "session_id": probe["session_id"],
        "finished_at": probe["finished_at"],
    }
    merged["uncontrolled"] = uncontrolled(merged)
    return merged
