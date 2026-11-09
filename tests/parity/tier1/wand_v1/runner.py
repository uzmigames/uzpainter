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
export are each a separate `UzPainter.exe run` process; the backend is DX12, the verb's default,
unless `UZP_ASSETS3D_GPU_BACKEND` names another (the adapter client passes it as `--gpu-backend`;
the pilots' Tier 1 on Vulkan, phase3.1 item 3.6), and the report's run identity records it.

The golden is `phase1/tier1/wand-v1` resolved through the current envelope
(`verdict.resolve_golden`); until it is admitted the runs execute the R9 request (decision 099)
and the comparison is `oracle_unavailable`. The comparison (`tools.parity.tier1.compare`) reads
this machine's private store (`UZP_PARITY_STORE`). Regions are the stack's material group masks;
the normal map is the file the pinned `painter_export.py` exports from the virtual map
`Normal_OpenGL`, `<prefix>_Normal`.

The texture sets' UV coverage (decision 223) comes from the job's staged OBJ mesh inputs: each set
is the mesh material of its name, and the report publishes each map's covered texels and its
padding texels apart, and its Normal's island-edge texels among the covered ones. The owner withdrew
exception EXC-007 (decision 259) and approved EXC-010 (decision 395): on the Wand v1 the padding
texels of every map and the Normal's island-edge texels may differ, and every other texel is
compared exactly.

An export UzPainter refuses before writing (`NotYetSupported`, while phase1.25 item 2.7 is open:
decision 245 refuses the five-map export's virtual Normal on the Wand's UV islands, and decision
259 its `infinite` padding there; the measure mode below records both as bypassed) is reported as
the one structural failure `candidate_export_refused`, with no map compared (decision 255); the
rebuild keeps the refusal's message. Any other failed call stops the run. Nothing is written
under the Assets3D root or into the repository except the report, when `UZP_TIER1_REPORT` names
it.

A native job (decision 300 item 7; the Wand's native create, sync and config export) rebuilds the
same way. Its normal maps come from its closing configuration (`normal_maps_of`), read before any
rebuild runs: an inline preset, else the authored catalogue preset its Painter alias names (only
the Blender preset, the Tunic's), named under OCIO. Any other preset or file-name token is
refused then (`NativeSubjectRefused`), with nothing rebuilt. Painter's predefined glTF preset,
named by its URL `export-preset-generator://gltf`, resolves to the authored
`gltf-pbr-metal-roughness` (`GENERATOR_ALIASES`; the glTF pilots, phase3.1 item 3.1).

A script job closed by a config export (the glTF pilots' Wand and Sash) runs that configuration
after the script's export, in its own `UzPainter.exe run` process over the saved project, into
`closing-export` (`Wand.closing_export`); its files join the run, its receipt checked and read
like the export's, and its normal maps join the subject's.

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

`measured(painter, work)` is the diagnostic measure mode (decision 286): both
rebuilds export with `UzPainter.exe run --diagnostic-measure-export` (through the adapter client),
which writes past those two refusals: `InexactPadding::measure` over the islands, and the Normal by
Painter's recorded island rule (decision 308: the stencil on the padded Height, decision 287's ring
copy, the flood under the mesh map; src/export/virtual_maps.h). Its maps are NOT conformant (each
rebuild's receipt must say `non_conformant` and name only decided refusals as bypassed,
`DECIDED_REFUSALS`, and a conformant rebuild's receipt must not be marked). Since decision 395 the
Tier 1 test runs `reopened_compared(..., diagnostic=True)`: the owner's exception EXC-010 excepts
exactly what this mode writes inexactly on the Wand v1 (its padding and its Normal's island-edge
texels), so its report is the Tier 1 report, a pass under EXC-010 at best. `measured` returns the
report and, per map, the texels
of the first rebuild that differ from Painter's r1 (in any component), per class: `interior` (the
covered texels), `edge` (the covered texels with an uncovered 8-neighbour, a part of `interior`),
`ring` (the uncovered texels with a covered 8-neighbour, x wrapping as the ring does) and `gutter`
(every other uncovered texel).

The production mode (`compared`, `diagnostic=False`; decisions 414 and 417): production writes the
islanded five-map export under the owner's EXC-013 (the padding) and EXC-014 (the combined virtual
Normal's island edge), a conformant generation (`checked_receipt`: no `non_conformant`). Each
rebuild's receipt names, per file, the exceptions it relies on (`exceptions_relied_on`), and
`relied_exceptions` passes them to the comparison as that file's `candidate_exceptions`
(`CandidateRun.exceptions`): a production-export entry covers only the files its receipt names. The
measure mode's maps never carry them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from adapters.assets3d.client import GPU_BACKEND_ENV
from tests.adapters.assets3d import wand as wand_module
from tests.adapters.assets3d.wand import REQUEST, Call, Wand, native_ocio_sha256
from tools.parity.coverage import coverage, distance_bands, obj_materials, obj_triangles
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import load
from tools.parity.recorder.environment import video_controllers
from tools.parity.recorder.script_run import (
    NativeJob,
    is_native,
    load_manifest,
    pipeline_job_from_manifest,
    texture_set_of,
)
from tools.parity.schemas import REGISTER_PATH, REPO_ROOT, load_json
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
BACKEND = "dx12"  # `UzPainter.exe run`'s default, when `UZP_ASSETS3D_GPU_BACKEND` is unset
REFUSAL = "NotYetSupported"
NORMAL_SUFFIX = "_Normal"  # painter_export.py: f"{P}_Normal" from virtual map Normal_OpenGL
# The decided refusals of an islanded export (src/export/padding.cpp `IslandNormalRefusal` and
# `CheckPadding`): the only ones the diagnostic measure export may bypass on the Wand.
DECIDED_REFUSALS = (
    "the Height outside the UV islands; decision 245",
    "UV islands do not cover the whole tile is not exact",
)

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


def backend() -> str:
    """The backend every `UzPainter.exe run` of a rebuild uses: `UZP_ASSETS3D_GPU_BACKEND` (the
    adapter client's `--gpu-backend`), else the verb's default `BACKEND`."""
    return os.environ.get(GPU_BACKEND_ENV) or BACKEND


def wand_backend(wand: Wand) -> str:
    """The backend the adapter client passes to every `UzPainter.exe run` of `wand`: its
    environment's `UZP_ASSETS3D_GPU_BACKEND`, else the verb's default `BACKEND`."""
    return wand.env.get(GPU_BACKEND_ENV) or BACKEND


class RunError(RuntimeError):
    """A rebuild step failed other than by the export's explicit refusal."""


class NativeSubjectRefused(RuntimeError):
    """A native job whose comparison subject its configuration does not give: refused before
    any rebuild runs."""


NORMAL_VIRTUAL_MAPS = frozenset({"Normal_OpenGL", "Normal_DirectX"})
STARTER_ASSETS = "resource://starter_assets/"
# The one Painter preset a native subject resolves, as `src/export/preset_aliases.cpp` aliases it:
# its Painter name -> the authored catalogue preset and the recorded versions of its URL.
PRESET_ALIASES = {
    "Blender (Principled BSDF)": ("blender-principled-bsdf", frozenset({"13120355637414252359"})),
    # R-322's versioned URL (decision 322; the Unreal pilots, phase3.2 item 3.1, decision 422).
    "Unreal Engine (Packed)": ("unreal-engine-packed", frozenset({"8339356058946582545.spexp"})),
}
# Painter's predefined presets by the URL Painter names them (R-314, decision 314): the URL -> its
# Painter name and the authored catalogue preset (`src/export/preset_aliases.cpp`).
GENERATOR_ALIASES = {
    "export-preset-generator://gltf": ("glTF PBR Metal Roughness", "gltf-pbr-metal-roughness")
}
CATALOGUE = REPO_ROOT / "assets" / "export-presets"
# `$colorSpace` of a normal map under OCIO with Painter's substance configuration, a native job's
# only profile: Painter names it Raw (the Blender preset's provenance, `<set>_Normal_Raw`).
NORMAL_COLOUR_SPACE = "Raw"
OPTIONAL = re.compile(r"\(([^()]*)\)")
TOKEN = re.compile(r"\$([A-Za-z]+)")


def preset_maps(config: Mapping[str, Any]) -> list[Any]:
    """The maps of the configuration's default preset: an inline preset of that name first, else
    the authored catalogue's preset its Painter alias names (its URL with no query or a recorded
    version), checked against the catalogue's provenance; anything else is refused."""
    reference = str(config.get("defaultExportPreset"))
    inline = {p.get("name"): p for p in config.get("exportPresets", [])}
    if reference in inline:
        return list(inline[reference].get("maps", []))
    if reference in GENERATOR_ALIASES:
        return catalogue_maps(*GENERATOR_ALIASES[reference])
    painter, _, query = reference.removeprefix(STARTER_ASSETS).partition("?")
    if painter not in PRESET_ALIASES:
        raise NativeSubjectRefused(
            f"the preset {reference!r} is neither inline nor a preset the runner resolves "
            f"({sorted(PRESET_ALIASES)}): its normal maps are not known, refused before any rebuild"
        )
    preset_id, versions = PRESET_ALIASES[painter]
    version = query.removeprefix("version=")
    if query and (version == query or version not in versions):
        raise NativeSubjectRefused(f"the preset {reference!r}: the query {query!r} is not recorded")
    return catalogue_maps(painter, preset_id)


def catalogue_maps(painter: str, preset_id: str) -> list[Any]:
    """The maps of the authored catalogue preset `preset_id`, checked to answer to `painter`."""
    preset = json.loads((CATALOGUE / f"{preset_id}.json").read_text(encoding="utf-8"))
    provenance = json.loads(
        (CATALOGUE / f"{preset_id}.provenance.json").read_text(encoding="utf-8")
    )
    if preset.get("name") != preset_id or provenance.get("preset") != preset_id:
        raise NativeSubjectRefused(f"the catalogue preset {preset_id} is not the one it names")
    if painter not in provenance.get("answersTo", []):
        raise NativeSubjectRefused(f"the catalogue preset {preset_id} does not answer to {painter}")
    return list(preset["maps"])


def map_name(file_name: str, root: str, mesh: str | None = None) -> str:
    """A normal map's file name for the export root `root`: `$textureSet` the root, `$colorSpace`
    Raw, `$udim` empty (a native job is in the Default workflow, `src/export/EXPORT.md`), and each
    `( ... )` group kept without its parentheses, or dropped when its only tokens are `$udim`; a
    group mixing `$udim` with another token, and any other token, are refused."""

    def expand(text: str) -> str:
        def value(match: re.Match[str]) -> str:
            token = match.group(1)
            if token == "textureSet":
                return root
            if token == "mesh" and mesh is not None:
                return mesh
            if token == "colorSpace":
                return NORMAL_COLOUR_SPACE
            if token == "udim":
                return ""
            raise NativeSubjectRefused(f"the map name {file_name!r} has another token ${token}")

        return TOKEN.sub(value, text)

    def group(match: re.Match[str]) -> str:
        tokens = set(TOKEN.findall(match.group(1)))
        if "udim" in tokens and tokens != {"udim"}:
            raise NativeSubjectRefused(f"the map name {file_name!r} mixes $udim with another token")
        return "" if tokens == {"udim"} else match.group(1)

    name = expand(OPTIONAL.sub(group, file_name))
    if any(c in name for c in "$()"):
        raise NativeSubjectRefused(f"the map name {file_name!r} is not one the runner expands")
    return name


def mesh_stem(job: Any) -> str | None:
    """`$mesh` of a pipeline job: the stem of its one OBJ mesh input, the file both Painter's
    recording and the rebuild import under its Assets3D name (`stage_inputs`); None without one."""
    stems = {
        Path(str(item.assets3d_path)).stem
        for item in job.inputs.values()
        if item.kind == "mesh" and str(item.assets3d_path).lower().endswith(".obj")
    }
    return stems.pop() if len(stems) == 1 else None


def normal_maps_of(config: Mapping[str, Any], mesh: str | None = None) -> frozenset[str]:
    """The tangent-space normal maps a native job's closing configuration exports, under OCIO (a
    native job's only profile): each map of its default preset (`preset_maps`) whose every
    channel is a `Normal_OpenGL` or `Normal_DirectX` virtual map, named for each `exportList`
    root (`map_name`)."""
    maps = preset_maps(config)
    roots = []
    for entry in config.get("exportList", []):
        if set(entry) != {"rootPath"}:
            raise NativeSubjectRefused(f"the export entry {entry} names more than its rootPath")
        roots.append(str(entry["rootPath"]))
    names = set()
    for item in maps:
        channels = item.get("channels", [])
        if not channels or any(
            c.get("srcMapType") != "virtualMap" or c.get("srcMapName") not in NORMAL_VIRTUAL_MAPS
            for c in channels
        ):
            continue
        names |= {map_name(str(item["fileName"]), root, mesh) for root in roots}
    return frozenset(names)


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
    """create and sync through the adapter in `work`, a fresh directory; each step runs only
    after the one before it succeeded, so a failed create is reported as itself."""
    work.mkdir(parents=True)
    wand = Wand(painter, work, manifest)
    for step, run_step in (("create", wand.create), ("sync", wand.sync)):
        call = run_step()
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
    """The export of `rebuild` on a built `wand`, its receipt checked by `checked_receipt`; a
    production export's files carry the exceptions its receipt names for them
    (`relied_exceptions`). A script job's closing config export (`Wand.closing_export`, the glTF
    pilots) follows a written export and is checked the same way in its own directory; the run is
    both exports' files, or the first refusal."""
    out = wand.argument("export", "out")
    run = _checked(wand, wand.export(diagnostic=diagnostic), out, diagnostic)
    if run.refused:
        return run
    closing = wand.closing_export(diagnostic=diagnostic)
    if closing is None:
        return run
    more = _checked(wand, closing, wand.closing_out, diagnostic)
    if more.refused:
        return more
    if shared := sorted(set(run.files) & set(more.files)):
        raise RunError(f"the script's and the closing export both write {shared}")
    files, exceptions = {**run.files, **more.files}, {**run.exceptions, **more.exceptions}
    return CandidateRun(files, exceptions=exceptions)


def _checked(wand: Wand, call: Call, out: Path, diagnostic: bool) -> CandidateRun:
    run = exported(wand, call, out)
    if not run.refused:
        checked_receipt(wand, diagnostic, out)
        if not diagnostic:
            receipt = receipt_of(wand, out)
            run = CandidateRun(run.files, exceptions=relied_exceptions(receipt, run.files))
    return run


def relied_exceptions(
    receipt: Mapping[str, Any], files: Mapping[MapKey, Path]
) -> dict[MapKey, frozenset[str]]:
    """Per file of `files`, the exception ids `receipt`'s `exceptions_relied_on` lists for it
    (decisions 414, 417), matched by file name; a receipt naming one file name twice, or a file it
    does not list, stops the run."""
    listed = [Path(str(f["path"])).name for f in receipt["files"]]
    if len(set(listed)) != len(listed):
        raise RunError(f"the receipt lists one file name twice: {sorted(listed)}")
    if unlisted := sorted(p.name for p in files.values() if p.name not in listed):
        raise RunError(f"the receipt does not list {unlisted}")
    names: dict[str, set[str]] = {}
    for entry in receipt.get("exceptions_relied_on") or []:
        for path in entry["paths"]:
            names.setdefault(Path(str(path)).name, set()).add(str(entry["exception_id"]))
    return {key: frozenset(names.get(path.name, ())) for key, path in files.items()}


def checked_receipt(wand: Wand, diagnostic: bool, out: Path | None = None) -> None:
    """The receipt of the export `wand` last published (in `out`, default the export's) names the
    backend its run selected (`wand_backend`), is (not) the measure mode's as `diagnostic` says,
    and the measure mode bypassed only decided refusals (`DECIDED_REFUSALS`)."""
    receipt = receipt_of(wand, out)
    if receipt["backend"] != wand_backend(wand):
        raise RunError(
            f"the export's receipt names the backend {receipt['backend']!r}, "
            f"not {wand_backend(wand)!r}"
        )
    if ("non_conformant" in receipt) != diagnostic:
        raise RunError(f"the export's receipt is {'not ' * diagnostic}marked non_conformant")
    if not diagnostic:
        return
    bypassed = receipt["non_conformant"]["bypassed"]
    undecided = [b for b in bypassed if not any(k in b["refusal"] for k in DECIDED_REFUSALS)]
    if undecided:
        raise RunError(f"the measure export bypassed refusals no decision names: {undecided}")


def non_conformant(wand: Wand) -> bool:
    """Whether the generation the export published in its `out` is the diagnostic measure
    export's: its receipt holds `non_conformant` (src/export/receipt.h)."""
    return "non_conformant" in receipt_of(wand)


def receipt_of(wand: Wand, out: Path | None = None) -> dict[str, Any]:
    """The receipt of the generation the last export published in `out` (default its `out`)."""
    out = wand.argument("export", "out") if out is None else out
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


def exported(wand: Wand, call: Call, out: Path | None = None) -> CandidateRun:
    """The files of a finished export call by (texture set, map name), or its explicit refusal
    with the refusal's message; `out` is its directory (default the export's `out`)."""
    out = wand.argument("export", "out") if out is None else out
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
    return CandidateRun(files, exceptions=run.exceptions), hashes


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


def reopened(
    wand: Wand, first: CandidateRun, initial: Project, diagnostic: bool = False
) -> tuple[CandidateRun, Reopen]:
    """Item 3.3 on `wand` after its export `first` (not refused) of the project `initial`
    (`initial_project`): `first` as the copies taken before the save, and the save/reopen record.
    The export after the reopen runs in `first`'s mode (`diagnostic`). A first export whose
    receipt lists other files, a save that leaves the project needing a save, or an export after
    the reopen whose receipt fails `checked_receipt`, stops the run."""
    kept, hashes = preserved(first, wand.work / "first-export")
    project = exported_project(receipt_of(wand), kept.files, hashes)
    saving = wand.probe("save", SAVE)
    if saving["after"]["needs_saving"]:
        raise RunError(f"the project still needs saving after project.save(): {saving}")
    # `out` holds the first export, so a refusal is checked to leave it as it was, where
    # `exported` checks that it is empty.
    out = wand.argument("export", "out")
    before = contents(out)
    call = wand.export(diagnostic=diagnostic)  # a fresh process: reopens the saved project
    if call.status == 1 and REFUSAL in call.stderr:
        if contents(out) != before:
            raise RunError(f"the refused export after the reopen changed {out}: {call.stderr}")
        again = CandidateRun(refused=True, refusal=refusal(call))
    else:
        again = exported(wand, call)
    if not again.refused:
        checked_receipt(wand, diagnostic)
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
    painter: Path,
    work: Path,
    golden_id: str = GOLDEN_ID,
    request: Path = REQUEST,
    diagnostic: bool = False,
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Reopen | None]:
    """`compared` with item 3.3 on the first rebuild (above): the report, the two rebuilds (the
    first as the copies taken before its save) and the save/reopen record, None when the first
    export was refused. `diagnostic`: every export in the measure mode (above, decision 395)."""
    report, runs, _, record = _evidence(painter, work, golden_id, request, diagnostic, True)
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
    native_normals = None
    if is_native(load_json(manifest)):  # its subject comes from its configuration, before any run
        job = pipeline_job_from_manifest(load_manifest(manifest), wand_module.ASSETS3D)
        assert isinstance(job, NativeJob)
        native_ocio_sha256(job)  # OCIO only, the profile `normal_maps_of` names maps under
        native_normals = normal_maps_of(job.config_export.config, mesh_stem(job))
    record = None
    if reopen:
        wand = built(painter, work / "run-1", manifest)
        initial = initial_project(wand)
        first = checked_export(wand, diagnostic)
        if not first.refused:
            first, record = reopened(wand, first, initial, diagnostic)
    else:
        wand, first = rebuild(painter, work / "run-1", manifest, diagnostic)
    _, second = rebuild(painter, work / "run-2", manifest, diagnostic)
    stack = load_json(wand.stack)
    masks = wand.masks
    if native_normals is None:
        assert wand.job.export.arguments is not None
        normals = frozenset({f"{wand.job.export.arguments['prefix']}{NORMAL_SUFFIX}"})
        if wand.job.config_export is not None:  # its closing export's (the glTF and Unreal pilots)
            normals |= normal_maps_of(wand.job.config_export.config, mesh_stem(wand.job))
    else:
        normals = native_normals
    meshes = [
        wand.staged[item.input_id]
        for item in wand.pipeline.inputs.values()
        if item.kind == "mesh" and wand.staged[item.input_id].suffix.lower() == ".obj"
    ]
    subject = Subject(
        wand.pipeline.manifest,
        sha256_of(manifest),
        material_regions(stack, masks),
        normals,
        {m: obj_triangles(mesh, m) for mesh in meshes for m in obj_materials(mesh)},
    )
    hardware, driver = video_controllers()
    identity = RunIdentity(
        hardware,
        driver,
        backend(),
        sha256_of(painter),
        tuple(sorted({str(item["sha256"]) for item in wand.pipeline.manifest["inputs"]})),
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
