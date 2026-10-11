"""Generated parts of `parity/reports/phase0/iray-references.md` (task
`phase0.7_render-reference-captures` items 2.5 and 2.6).

Three blocks between markers, rewritten by `python -m tools.parity.render_procedure noise`:

- `references`: every reference golden with its manifest, preset and the SHA-256 of each
  private record the store holds (the aggregate view of the per-golden manifests);
- `noise-table`: the noise terms per fixture and region, in 1e-4 of full scale;
- `noise`: the full numbers as JSON, one golden per line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.parity.recorder.iray import settings_sheet
from tools.parity.recorder.job import load_job
from tools.parity.render_procedure.noise import NoiseError, measure, summary_rows
from tools.parity.render_procedure.references import reference_manifests
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

REPORT = REPO_ROOT / "parity" / "reports" / "phase0" / "iray-references.md"
K = 4


def replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- {name}:begin -->\n).*?(<!-- {name}:end -->)", flags=re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"the report has no {name} block")
    return pattern.sub(lambda m: m.group(1) + body + m.group(2), text)


def reference_rows(manifests: list[Path]) -> list[str]:
    rows = [
        "| Golden | Manifest | Preset | Golden record | Renders (s, s, k) |",
        "|---|---|---|---|---|",
    ]
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        records = {r["record_id"]: r["sha256"] for r in manifest["private_records"]}
        renders = [f"`{records[r]}`" for r in sorted(records) if r.endswith("render-reference")]
        background = next(
            s["value"]
            for s in manifest["applied_settings"]
            if s["name"] == "capture.background_srgb8"
        )
        preset = "ref_match" if background == "141,142,148" else "v2"
        rows.append(
            f"| `{manifest['golden_id']}` | `{path.relative_to(REPO_ROOT).as_posix()}` | "
            f"{preset} | `{records.get('golden-record', 'not admitted')}` | "
            f"{'<br>'.join(renders) or '-'} |"
        )
    return rows


def write_noise_report(
    store: OracleStore | None = None, manifests: list[Path] | None = None, report: Path = REPORT
) -> int:
    store = store if store is not None else locate()
    paths = manifests if manifests is not None else reference_manifests()
    results: list[dict[str, Any]] = []
    failed = 0
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        samples = settings_sheet(load_job(path)).samples
        try:
            results.append(measure(store, manifest, samples, K))
        except NoiseError as error:
            print(f"{path}: {error}", file=sys.stderr)
            failed += 1
    text = report.read_text(encoding="utf-8")
    text = replace_block(text, "references", "\n".join(reference_rows(paths)) + "\n")
    text = replace_block(text, "noise-table", "\n".join(summary_rows(results)) + "\n")
    lines = ",\n".join(json.dumps(r, sort_keys=True) for r in results)
    text = replace_block(text, "noise", f"```json\n[\n{lines}\n]\n```\n")
    report.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(results)} goldens measured, {failed} not admitted")
    return 1 if failed else 0
