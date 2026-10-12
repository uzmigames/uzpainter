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
UzPainter refuses before writing (while phase1.25 item 2.7 is open) is recorded as refused on the
side it happened; any other failed call stops the run. Nothing is written under the Assets3D root
or into the repository except the report, when `UZP_RECIPE_REBUILD_REPORT` names it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.adapters.assets3d.wand import REQUEST, Call
from tests.parity.tier1.wand_v1.runner import GOLDEN_ID, REFUSAL, RunError, built, exported
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


def side(dump: dict[str, Any], candidate: CandidateRun) -> Side:
    """The dump and the export's files by name, or its refusal's class."""
    if candidate.refused:
        return Side(dump, None, REFUSAL)
    return Side(dump, {path.name: path for path in candidate.files.values()})


def refusal(call: Call) -> str:
    """The message of a refused export: the error of the adapter's JSON reply on standard error,
    which also names this run's paths, or else the line naming the refusal."""
    line = next(line.strip() for line in call.stderr.splitlines() if REFUSAL in line)
    try:
        return str(json.loads(line)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return line


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


def job_manifest() -> Path:
    """The golden admitted from the R9 request, or the request until it is."""
    resolved = resolve_golden(GOLDEN_ID)
    return resolved.manifest_path if resolved is not None else REQUEST


def run(painter: Path, work: Path) -> Scenario:
    """The original wand, its rebuild from the dump, both exports and the report."""
    manifest = job_manifest()
    wand = built(painter, work / "original", manifest)
    first_call = wand.export()
    first = exported(wand, first_call)
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
    second_call = wand.export()
    second = exported(wand, second_call)
    rebuilt = wand.probe("dump-rebuilt", DUMP)
    document = report(
        GOLDEN_ID,
        sha256_of(manifest),
        sha256_of(painter),
        side(original, first),
        side(rebuilt, second),
    )
    refusals = tuple(
        refusal(call)
        for call, candidate in ((first_call, first), (second_call, second))
        if candidate.refused
    )
    return Scenario(document, original, rebuilt, refusals)
