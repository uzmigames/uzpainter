r"""The Wand v1 Tier 1 runner (phase1.25 item 2.4; decision 124).

    $env:UZP_TIER1_REPORT = "parity/reports/phase1/tier1-wand-v1.json"   # optional
    python -m pytest tests/parity/tier1/wand_v1

`run(painter, work)` returns the comparison report, `compared` the report and the two rebuilds,
`reopened_compared` those and the save/reopen record of item 3.3 (below); the local tests
(`test_wand_v1.py`) build UzPainter, run it once, write the report to `UZP_TIER1_REPORT` when that
is set, and pass only on equality with every map, byte-identical rebuilds and a reopened project
that exports the first export's bytes. It runs under pytest, whose rootdir import finds this
repository's `tests` folder even where an installed package named `tests` shadows it for
`python -m`.

Rebuilds Wand v1 twice through the Assets3D pipeline adapter (`adapters/assets3d/`) with the
phase1.23 wand fixture (`tests/adapters/assets3d/wand.py`): the three pipeline scripts run
byte-unchanged, each pinned by SHA-256 from the golden's manifest (`--pin`: the adapter refuses a
changed script before anything reaches UzPainter), on the same staged inputs and external mesh
maps the Painter recording used. Each rebuild has its own work directory, and create, sync and
export are each a separate `UzPainter.exe run` process; the backend is DX12, the verb's default
(the adapter names none).

The golden is `phase1/tier1/wand-v1` resolved through the current envelope
(`verdict.resolve_golden`); until it is admitted the runs execute the R9 request (decision 099)
and the comparison is `oracle_unavailable`. The comparison (`tools.parity.tier1.compare`) reads
this machine's private store (`UZP_PARITY_STORE`). Regions are the stack's material group masks;
the normal map is the file the pinned `painter_export.py` exports from the virtual map
`Normal_OpenGL`, `<prefix>_Normal`.

The texture sets' UV coverage (decision 223) comes from the job's staged OBJ mesh inputs: each set
is the mesh material of its name, and the report publishes each map's covered texels and its
padding texels apart. Both are compared exactly: the owner withdrew exception EXC-007, which had
excepted the padding texels (decision 259).

An export UzPainter refuses before writing (`NotYetSupported`, while phase1.25 item 2.7 is open:
decision 245 refuses the five-map export's virtual Normal on the Wand's UV islands, and decision
259 its `infinite` padding there) is reported as
the one structural failure `candidate_export_refused`, with no map compared (decision 255); the
rebuild keeps the refusal's message. Any other failed call stops the run. Nothing is written
under the Assets3D root or into the repository except the report, when `UZP_TIER1_REPORT` names
it.

Item 3.3, save/reopen (`reopened_compared` only): between the first rebuild's sync and its export,
an adapter call reads the project's file and UUID, and the file must be the create step's `dst`.
After the export, its files are copied with their SHA-256 into `run-1/first-export` before
anything else runs (the next export publishes into the same `out` and may overwrite or clean it),
and those copies are the first rebuild the comparison reads; the export's receipt, checked to list
those files with those hashes, gives the project file name the export read. An adapter call then
reads the project's file and UUID, saves it (`project.save()`) and reads them again; the pinned
`painter_export.py` runs again unchanged, in a fresh `UzPainter.exe run` process that reopens the
saved project from the adapter session; a last call reads the reopened project's file and UUID.
The `Reopen` record holds the five identities and both exports' hashes: 3.3 holds when one file
and UUID run from before the first export through the save to the reopen, the receipt names that
file, and every file's bytes are equal. A refused first export
gives no 3.3 evidence (no record). The second rebuild, in its own work directory, stays the 3.2
evidence.

`measured(painter, work)` is the diagnostic measure mode (decision 286), never the test's: both
rebuilds export with `UzPainter.exe run --diagnostic-measure-export` (through the adapter client),
which writes past those two refusals: `InexactPadding::measure` over the islands, and the Normal by
Painter's recorded island rule (decision 308: the stencil on the padded Height, decision 287's ring
copy, the flood under the mesh map; src/export/virtual_maps.h). Its maps are NOT conformant (each
rebuild's receipt must say `non_conformant`, and a conformant rebuild's must not), so its report is
no verdict and is never written as the Tier 1 report. It returns the report and, per map, the texels
of the first rebuild that differ from Painter's r1 (in any component), per class: `interior` (the
covered texels), `edge` (the covered texels with an uncovered 8-neighbour, a part of `interior`),
`ring` (the uncovered texels with a covered 8-neighbour, x wrapping as the ring does) and `gutter`
(every other uncovered texel).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tests.adapters.assets3d.wand import REQUEST, Call, Wand
from tools.parity.coverage import coverage, distance_bands, obj_materials, obj_triangles
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import load
from tools.parity.recorder.environment import video_controllers
from tools.parity.recorder.script_run import texture_set_of
from tools.parity.schemas import REGISTER_PATH, load_json
from tools.parity.store.store import locate
from tools.parity.tier1.compare import (
    FIRST,
    CandidateRun,
    MapKey,
    RunIdentity,
    Subject,
    compare,
    material_regions,
)
from tools.parity.verdict import resolve_golden

GOLDEN_ID = "phase1/tier1/wand-v1"
BACKEND = "dx12"  # `UzPainter.exe run`'s default; the adapter passes no --gpu-backend
REFUSAL = "NotYetSupported"
NORMAL_SUFFIX = "_Normal"  # painter_export.py: f"{P}_Normal" from virtual map Normal_OpenGL

# Item 3.3: the open project's identity, read by an adapter call (IDENTITY), and by the call that
# saves it both before and after its save (SAVE).
_IMPORTS = "import substance_painter.project as project\nimport uzpainter\n"
_READ = (
    '{"file": uzpainter.project.absolute_file_path(), "uuid": str(project.get_uuid()), '
    '"needs_saving": project.needs_saving()}'
)
IDENTITY = f"{_IMPORTS}result = {_READ}\n"
SAVE = (
    f'{_IMPORTS}before = {_READ}\nproject.save()\nresult = {{"before": before, "after": {_READ}}}\n'
)


class RunError(RuntimeError):
    """A rebuild step failed other than by the export's explicit refusal."""


@dataclass(frozen=True)
class Project:
    """An open project's identity: its absolute file and its UUID."""

    file: Path
    uuid: str


@dataclass(frozen=True)
class Reopen:
    """Item 3.3: the first rebuild's project saved, reopened in a fresh process and exported again.
    `initial` is the project read before the first export (its file the create step's `dst`);
    `exported` the project file name the first export's receipt names; `unsaved`, `saved` and
    `reopened` the project read before the save, after it (one call) and after the reopen.
    `first` and `again` are the SHA-256 of each export's files by (texture set, map name), `first`
    taken before the save; `refusal` is the message of a refused export after the reopen."""

    initial: Project
    exported: str
    unsaved: Project
    saved: Project
    reopened: Project
    first: Mapping[MapKey, str]
    again: Mapping[MapKey, str]
    refusal: str = ""

    @property
    def same_project(self) -> bool:
        """One file and UUID from before the first export through the save to the reopen, and the
        receipt names that file."""
        return (
            self.initial == self.unsaved == self.saved == self.reopened
            and self.initial.file.name == self.exported
        )

    @property
    def differing(self) -> list[MapKey]:
        """The maps missing from either export or whose bytes differ."""
        keys = set(self.first) | set(self.again)
        return sorted(k for k in keys if self.first.get(k) != self.again.get(k))

    @property
    def equal(self) -> bool:
        """3.3 holds: the same project, exported again without refusal, to the same bytes."""
        return not self.refusal and self.same_project and not self.differing


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def built(painter: Path, work: Path, manifest: Path) -> Wand:
    """create and sync through the adapter in `work`, a fresh directory."""
    work.mkdir(parents=True)
    wand = Wand(painter, work, manifest)
    for step, call in (("create", wand.create()), ("sync", wand.sync())):
        if call.status != 0:
            raise RunError(f"{step} failed ({call.status}): {call.stdout}{call.stderr}")
    return wand


def rebuild(
    painter: Path, work: Path, manifest: Path, diagnostic: bool = False
) -> tuple[Wand, CandidateRun]:
    """create, sync and export through the adapter in `work`; the exported files by (texture set,
    map name), or the export's refusal. `diagnostic`: the measure mode (above)."""
    wand = built(painter, work, manifest)
    return wand, checked_export(wand, diagnostic)


def checked_export(wand: Wand, diagnostic: bool = False) -> CandidateRun:
    """The export of `rebuild` on a built `wand`, its receipt checked to be (not) the measure
    mode's as `diagnostic` says."""
    run = exported(wand, wand.export(diagnostic=diagnostic))
    if not run.refused and non_conformant(wand) != diagnostic:
        raise RunError(f"the export's receipt is {'not ' * diagnostic}marked non_conformant")
    return run


def non_conformant(wand: Wand) -> bool:
    """Whether the generation the export published in its `out` is the diagnostic measure
    export's: its receipt holds `non_conformant` (src/export/receipt.h)."""
    return "non_conformant" in receipt_of(wand)


def receipt_of(wand: Wand) -> dict[str, Any]:
    """The receipt of the generation the last export published in its `out`."""
    out = wand.argument("export", "out")
    current = json.loads((out / "current.json").read_text(encoding="utf-8"))
    receipt: dict[str, Any] = json.loads((out / current["receipt"]).read_text(encoding="utf-8"))
    return receipt


def refusal(call: Call) -> str:
    """The message of a refused export: the error of the adapter's JSON reply on standard error,
    which also names this run's paths. The pinned `painter_layer_stack.py` keeps only the reply's
    last 3000 characters, so a long reply arrives cut and the message is the last line of its
    traceback (`NotYetSupported: <message>`); else the line naming the refusal."""
    line = next(line.strip() for line in call.stderr.splitlines() if REFUSAL in line)
    try:
        return str(json.loads(line)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        pass
    raised = re.findall(rf"{REFUSAL}: (.*?)\\n", line)  # the JSON escape of a line break
    if not raised:
        return line
    try:
        return str(json.loads(f'"{raised[-1]}"'))
    except ValueError:
        return str(raised[-1])


def exported(wand: Wand, call: Call) -> CandidateRun:
    """The files of a finished export call by (texture set, map name), or its explicit refusal
    with the refusal's message."""
    out = wand.argument("export", "out")
    if call.status != 0:
        written = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
        if call.status == 1 and REFUSAL in call.stderr and not written:
            return CandidateRun(refused=True, refusal=refusal(call))
        raise RunError(f"export failed ({call.status}), wrote {written}: {call.stderr}")
    result: dict[str, Any] = call.document()
    if str(result.get("status", "")).rsplit(".", 1)[-1] != "Success":
        raise RunError(f"export {result.get('status')}: {result.get('message')}")
    files = {
        (texture_set_of(key), Path(name).stem): Path(name)
        for key, names in result["files"].items()
        for name in names
    }
    return CandidateRun(files)


def preserved(run: CandidateRun, folder: Path) -> tuple[CandidateRun, dict[MapKey, str]]:
    """Copies of `run`'s files in `folder`, a new directory, and their SHA-256: the run as its
    copies. A copy whose bytes differ from its source's stops the run."""
    folder.mkdir()
    files: dict[MapKey, Path] = {}
    hashes: dict[MapKey, str] = {}
    for key, path in sorted(run.files.items()):
        copy = folder / path.name
        if copy.exists():
            raise RunError(f"two exported files are named {path.name}")
        digest = sha256_of(path)
        shutil.copyfile(path, copy)
        if sha256_of(copy) != digest:
            raise RunError(f"the copy of {path} differs from it")
        files[key], hashes[key] = copy, digest
    return CandidateRun(files), hashes


def contents(folder: Path) -> dict[str, str | None]:
    """Every path under `folder`, relative, with its file's SHA-256 (None for a directory)."""
    return {
        p.relative_to(folder).as_posix(): sha256_of(p) if p.is_file() else None
        for p in folder.rglob("*")
    }


def project_of(found: Mapping[str, Any]) -> Project:
    """An identity an IDENTITY or SAVE call read."""
    return Project(Path(str(found["file"])), str(found["uuid"]))


def exported_project(
    receipt: Mapping[str, Any], files: Mapping[MapKey, Path], hashes: Mapping[MapKey, str]
) -> str:
    """The project file name `receipt` names, once it is verified to list every file of `files`,
    by file name, with its hash in `hashes`."""
    listed = {Path(str(f["path"])).name: str(f["sha256"]) for f in receipt["files"]}
    unlisted = sorted(p.name for key, p in files.items() if listed.get(p.name) != hashes[key])
    if unlisted:
        raise RunError(f"the first export's receipt does not list {unlisted} with their hashes")
    return str(receipt["manifest_files"]["project"]["path"])


def initial_project(wand: Wand) -> Project:
    """The project of a built `wand` before its first export, its file checked to be the create
    step's `dst`."""
    project = project_of(wand.probe("built", IDENTITY))
    dst = wand.argument("create", "dst")
    if project.file.resolve() != dst.resolve():
        raise RunError(f"the built project is {project.file}, not the create step's {dst}")
    return project


def reopened(wand: Wand, first: CandidateRun, initial: Project) -> tuple[CandidateRun, Reopen]:
    """Item 3.3 on `wand` after its export `first` (not refused) of the project `initial`
    (`initial_project`): `first` as the copies taken before the save, and the save/reopen record.
    A first export whose receipt lists other files, a save that leaves the project needing a save,
    or a conformant export after the reopen marked `non_conformant`, stops the run."""
    kept, hashes = preserved(first, wand.work / "first-export")
    project = exported_project(receipt_of(wand), kept.files, hashes)
    saving = wand.probe("save", SAVE)
    if saving["after"]["needs_saving"]:
        raise RunError(f"the project still needs saving after project.save(): {saving}")
    # `out` holds the first export, so a refusal is checked to leave it as it was, where
    # `exported` checks that it is empty.
    out = wand.argument("export", "out")
    before = contents(out)
    call = wand.export()  # a fresh process, which reopens the saved project
    if call.status == 1 and REFUSAL in call.stderr:
        if contents(out) != before:
            raise RunError(f"the refused export after the reopen changed {out}: {call.stderr}")
        again = CandidateRun(refused=True, refusal=refusal(call))
    else:
        again = exported(wand, call)
    if not again.refused and non_conformant(wand):
        raise RunError("the export after the reopen is marked non_conformant")
    record = Reopen(
        initial,
        project,
        project_of(saving["before"]),
        project_of(saving["after"]),
        project_of(wand.probe("reopened", IDENTITY)),
        hashes,
        {key: sha256_of(path) for key, path in again.files.items()},
        again.refusal,
    )
    return kept, record


def run(
    painter: Path, work: Path, golden_id: str = GOLDEN_ID, request: Path = REQUEST
) -> dict[str, Any]:
    """Two rebuilds and the comparison report; `golden_id` and its `request` name another pilot
    of the same three pipeline steps (the Belt v5 runner)."""
    return compared(painter, work, golden_id, request)[0]


def compared(
    painter: Path, work: Path, golden_id: str = GOLDEN_ID, request: Path = REQUEST
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun]]:
    """The comparison report of `run` and the two rebuilds it compared, each with its files or
    its refusal's message."""
    report, runs, _ = _compared(painter, work, golden_id, request, diagnostic=False)
    return report, runs


def reopened_compared(
    painter: Path, work: Path, golden_id: str = GOLDEN_ID, request: Path = REQUEST
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Reopen | None]:
    """`compared` with item 3.3 on the first rebuild (above): the report, the two rebuilds (the
    first as the copies taken before its save) and the save/reopen record, None when the first
    export was refused."""
    report, runs, _, record = _evidence(painter, work, golden_id, request, False, True)
    return report, runs, record


def _compared(
    painter: Path, work: Path, golden_id: str, request: Path, diagnostic: bool
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Subject]:
    report, runs, subject, _ = _evidence(painter, work, golden_id, request, diagnostic, False)
    return report, runs, subject


def _evidence(
    painter: Path, work: Path, golden_id: str, request: Path, diagnostic: bool, reopen: bool
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Subject, Reopen | None]:
    resolved = resolve_golden(golden_id)
    manifest = resolved.manifest_path if resolved is not None else request
    record = None
    if reopen:
        wand = built(painter, work / "run-1", manifest)
        initial = initial_project(wand)
        first = checked_export(wand, diagnostic)
        if not first.refused:
            first, record = reopened(wand, first, initial)
    else:
        wand, first = rebuild(painter, work / "run-1", manifest, diagnostic)
    _, second = rebuild(painter, work / "run-2", manifest, diagnostic)
    stack = load_json(wand.stack)
    masks = wand.masks
    assert wand.job.export.arguments is not None
    meshes = [
        wand.staged[item.input_id]
        for item in wand.job.inputs.values()
        if item.kind == "mesh" and wand.staged[item.input_id].suffix.lower() == ".obj"
    ]
    subject = Subject(
        wand.job.manifest,
        sha256_of(manifest),
        material_regions(stack, masks),
        frozenset({f"{wand.job.export.arguments['prefix']}{NORMAL_SUFFIX}"}),
        {m: obj_triangles(mesh, m) for mesh in meshes for m in obj_materials(mesh)},
    )
    hardware, driver = video_controllers()
    identity = RunIdentity(
        hardware,
        driver,
        BACKEND,
        sha256_of(painter),
        tuple(sorted({str(item["sha256"]) for item in wand.job.manifest["inputs"]})),
    )
    entries = load_json(REGISTER_PATH)["entries"]
    report = compare(subject, resolved, locate(), (first, second), identity, entries)
    return report, (first, second), subject, record


def texel_classes(covered: npt.NDArray[np.bool_]) -> dict[str, npt.NDArray[np.bool_]]:
    """The classes of `measured` (above) over the coverage `covered`."""
    ring = ~covered & (distance_bands(covered, 1) == 1)
    edge = covered & (distance_bands(~covered, 1) == 1)
    return {"interior": covered, "edge": edge, "ring": ring, "gutter": ~covered & ~ring}


def measured(
    painter: Path, work: Path, golden_id: str = GOLDEN_ID, request: Path = REQUEST
) -> tuple[dict[str, Any], dict[str, dict[str, dict[str, int]]]]:
    """The diagnostic measure mode (above, decision 286): the report of two non-conformant
    rebuilds, and per map (`<texture set>/<map>`) and class the texels that differ from r1 and the
    class's texel count."""
    report, (first, _), subject = _compared(painter, work, golden_id, request, diagnostic=True)
    if first.refused:
        raise RunError(f"the diagnostic measure export was refused: {first.refusal}")
    resolved = resolve_golden(golden_id)
    assert resolved is not None
    golden = load(locate(), resolved.manifest_path)
    split: dict[str, dict[str, dict[str, int]]] = {}
    for output_id, output in sorted(golden.recordings[FIRST].outputs.items()):
        key = (str(output.get("texture_set")), str(output.get("map")))
        if output.get("kind") != "exported_map" or key not in first.files:
            continue
        if key[0] not in subject.uv_triangles:
            continue
        oracle = golden.map(FIRST, output_id).values
        candidate = decode(first.files[key].read_bytes()).values
        differs = oracle != candidate
        if differs.ndim == 3:
            differs = differs.any(axis=2)
        height, width = differs.shape
        classes = texel_classes(coverage(subject.uv_triangles[key[0]], width, height))
        split[f"{key[0]}/{key[1]}"] = {
            name: {"differing": int((differs & mask).sum()), "texels": int(mask.sum())}
            for name, mask in classes.items()
        }
    return report, split
