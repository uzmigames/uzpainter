r"""The Wand v1 Tier 1 runner (phase1.25 item 2.4; decision 124).

    $env:UZP_TIER1_REPORT = "parity/reports/phase1/tier1-wand-v1.json"   # optional
    python -m pytest tests/parity/tier1/wand_v1

`run(painter, work)` returns the comparison report, `compared` the report and the two rebuilds;
the local test (`test_wand_v1.py`) builds UzPainter, runs it, writes the report to
`UZP_TIER1_REPORT` when that is set, and passes only on equality with every map and byte-identical
rebuilds. It runs under pytest, whose rootdir import finds this repository's `tests` folder even
where an installed package named `tests` shadows it for `python -m`.

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

`measured(painter, work)` is the diagnostic measure mode (decision 286), never the test's: both
rebuilds export with `UzPainter.exe run --diagnostic-measure-export` (through the adapter client),
which writes past those two refusals: `InexactPadding::measure` over the islands, and the Normal as
the evaluator gives it, padded as its stored values. Its maps are NOT conformant (each rebuild's
receipt must say `non_conformant`, and a conformant rebuild's must not), so its report is no
verdict and is never written as the Tier 1 report. It returns the report and, per map, the texels
of the first rebuild that differ from Painter's r1 (in any component), per class: `interior` (the
covered texels), `edge` (the covered texels with an uncovered 8-neighbour, a part of `interior`),
`ring` (the uncovered texels with a covered 8-neighbour, x wrapping as the ring does) and `gutter`
(every other uncovered texel).
"""

from __future__ import annotations

import hashlib
import json
import re
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


class RunError(RuntimeError):
    """A rebuild step failed other than by the export's explicit refusal."""


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
    run = exported(wand, wand.export(diagnostic=diagnostic))
    if not run.refused and non_conformant(wand) != diagnostic:
        raise RunError(f"the export's receipt is {'not ' * diagnostic}marked non_conformant")
    return wand, run


def non_conformant(wand: Wand) -> bool:
    """Whether the generation the export published in its `out` is the diagnostic measure
    export's: its receipt holds `non_conformant` (src/export/receipt.h)."""
    out = wand.argument("export", "out")
    current = json.loads((out / "current.json").read_text(encoding="utf-8"))
    receipt = json.loads((out / current["receipt"]).read_text(encoding="utf-8"))
    return "non_conformant" in receipt


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


def _compared(
    painter: Path, work: Path, golden_id: str, request: Path, diagnostic: bool
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Subject]:
    resolved = resolve_golden(golden_id)
    manifest = resolved.manifest_path if resolved is not None else request
    wand, first = rebuild(painter, work / "run-1", manifest, diagnostic)
    _, second = rebuild(painter, work / "run-2", manifest, diagnostic)
    stack = load_json(wand.stack)
    masks = wand.staged[wand.job.sync.args["masks"][0]].parent
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
    return report, (first, second), subject


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
