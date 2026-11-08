r"""The Wand v1 rebuild-from-dump scenario (phase2.2_recipe-and-diagnostics item 2.1; P2-RECIPE).

    $env:UZP_RECIPE_REBUILD_REPORT = "parity/reports/phase2/recipe-rebuild-wand.json"  # optional
    python -m pytest tests/parity/recipe/wand_v1

`run(painter, work)` builds Wand v1 through the Assets3D pipeline adapter as the Tier 1 runner
does (`tests/parity/tier1/wand_v1/runner.py`: the three pinned scripts, create, sync and export,
each a separate `UzPainter.exe run` process), then:

1. dumps the project's recipe (`uzpainter.project.dump_recipe()`) in a further adapter call;
2. writes the project's bundle (`UzPainter.exe export-bundle`) and gathers its stored resources as
   `<sha256><ext>` files, the layout `rebuild_from_recipe` reads;
3. rebuilds a new project from the dump and those files alone, saves it in the work directory and
   leaves it as the adapter session's project;
4. exports it with the pinned `painter_export.py` unchanged, its `out` repointed to a second
   folder, and dumps its recipe.

The report (`tools.parity.recipe_rebuild`) compares the two digests and the two exports' files.
The job is the R9 request (decision 099), or the golden admitted from it once it is. An export
UzPainter refuses before writing is recorded as refused on the side it happened; any other failed
call stops the run. Each export's receipt is checked by the Tier 1 runner's `checked_receipt`
(`checked_export`): with `diagnostic` False (the default) an export marked `non_conformant` stops
the run, so the diagnostic measure export, which `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT` in the
environment turns on, is never compared by accident. With `diagnostic` True both exports are the
diagnostic measure export (decision 286), as in the Wand's Tier 1 test since decision 395: each
receipt must be marked `non_conformant` and name only the decided refusals it bypassed (decisions
245 and 259). Production keeps both refusals, so a pass then shows the rebuild reproduces the
same bytes, not a conformant delivery.
Nothing is written under the Assets3D root or into the repository except the report, when
`UZP_RECIPE_REBUILD_REPORT` names it.

`run(..., golden_id, request)` runs the same scenario on another pilot of the same three pipeline
steps, as the Tier 1 runner's `run` does: the Sash v5 (Belt v5) current round
(`tests/parity/tier1/sash_v5`, gate G2), whose caller sets the manifest's `OCIO`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.adapters.assets3d.wand import REQUEST
from tests.parity.tier1.wand_v1.runner import (
    GOLDEN_ID,
    REFUSAL,
    RunError,
    built,
    checked_export,
)
from tools.parity.recipe_rebuild import Side, report, sha256_of
from tools.parity.tier1.compare import CandidateRun
from tools.parity.verdict import resolve_golden

DUMP = """
import uzpainter
result = uzpainter.project.dump_recipe()
"""

# Rebuild in the adapter's session: the restored original is closed first (a rebuild refuses
# while a project is open), and the rebuilt project is saved so the next call can reopen it.
REBUILD = """
import substance_painter.project as project
import uzpainter
project.close()
uzpainter.project.rebuild_from_recipe(__RECIPE__, __RESOURCES__)
uzpainter.project.save_as(__TARGET__)
result = {"file": uzpainter.project.absolute_file_path()}
"""


@dataclass(frozen=True)
class Scenario:
    """The report, the two dumps it was built from and the refusal of each refused export."""

    report: dict[str, Any]
    original: dict[str, Any]
    rebuilt: dict[str, Any]
    refusals: tuple[str, ...]


def side(dump: dict[str, Any], candidate: CandidateRun, diagnostic: bool) -> Side:
    """The dump and the export's files by name, or its refusal's class; `diagnostic`: the export's
    receipt-checked mode (`run`), which the report names."""
    if candidate.refused:
        return Side(dump, None, REFUSAL, diagnostic=diagnostic)
    files = {path.name: path for path in candidate.files.values()}
    return Side(dump, files, diagnostic=diagnostic)


def resources(painter: Path, project_file: Path, work: Path) -> Path:
    """The project's stored resources as `<sha256><ext>` files, from its bundle."""
    bundle = work / "bundle"
    call = subprocess.run(
        [str(painter), "export-bundle", str(project_file), str(bundle)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if call.returncode != 0:
        raise RunError(f"export-bundle failed ({call.returncode}): {call.stdout}{call.stderr}")
    index = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    folder = work / "resources"
    folder.mkdir()
    for entry in index["resources"]:
        source = bundle / entry["file"]
        shutil.copyfile(source, folder / f"{entry['sha256']}{source.suffix}")
    return folder


def job_manifest(golden_id: str = GOLDEN_ID, request: Path = REQUEST) -> Path:
    """The golden admitted from `request` (the Wand's R9 request by default), or the request
    until it is."""
    resolved = resolve_golden(golden_id)
    return resolved.manifest_path if resolved is not None else request


def run(
    painter: Path,
    work: Path,
    diagnostic: bool = False,
    golden_id: str = GOLDEN_ID,
    request: Path = REQUEST,
) -> Scenario:
    """The original pilot (the Wand by default), its rebuild from the dump, both exports and the
    report. `diagnostic`: both exports in the diagnostic measure mode (above); `golden_id` and its
    `request` name another pilot of the same three pipeline steps."""
    manifest = job_manifest(golden_id, request)
    wand = built(painter, work / "original", manifest)
    first = checked_export(wand, diagnostic)
    original = wand.probe("dump-original", DUMP)
    recipe = work / "recipe.json"
    recipe.write_text(json.dumps(original), encoding="utf-8")
    project_file = Path(json.loads(wand.session.read_text(encoding="utf-8"))["project"])
    folder = resources(painter, project_file, work)

    target = work / "rebuilt" / project_file.name
    target.parent.mkdir()
    body = (
        REBUILD.replace("__RECIPE__", repr(str(recipe)))
        .replace("__RESOURCES__", repr(str(folder)))
        .replace("__TARGET__", repr(str(target)))
    )
    saved = wand.probe("rebuild", body)
    if Path(saved["file"]).resolve() != target.resolve():
        raise RunError(f"the rebuilt project was saved as {saved['file']}, not {target}")

    # The pinned export script again, on the rebuilt project, into a folder of its own.
    hard_coded = wand.job.export.hard_coded_args
    assert hard_coded is not None
    arguments_file = Path(wand.redirects[hard_coded])
    arguments = json.loads(arguments_file.read_text(encoding="utf-8"))
    arguments["out"] = str(work / "rebuilt" / "out")
    arguments_file.write_text(json.dumps(arguments), encoding="utf-8")
    second = checked_export(wand, diagnostic)
    rebuilt = wand.probe("dump-rebuilt", DUMP)
    document = report(
        golden_id,
        sha256_of(manifest),
        sha256_of(painter),
        side(original, first, diagnostic),
        side(rebuilt, second, diagnostic),
    )
    refusals = tuple(candidate.refusal for candidate in (first, second) if candidate.refused)
    return Scenario(document, original, rebuilt, refusals)
