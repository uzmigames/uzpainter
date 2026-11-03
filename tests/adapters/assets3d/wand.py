"""The wand v1 fixture runner of the Assets3D adapter (task phase1.23 item 2.5; decision 113).

It runs the three Assets3D pipeline scripts byte-unchanged through the adapter on the wand v1
inputs: `painter_create.py` through the adapter's client (`client.py execute_python`, the drop-in
for the MCP client the pipeline sends it with: since Assets3D 9a718b9 the layer-stack script's
`run` sends a route-guard probe first, which needs a saved project open), then
`painter_layer_stack.py sync` and `run painter_export.py` through
`adapters/assets3d/layer_stack.py`. The pins are those of the admitted R9 manifest
(`phase1/tier1/wand-v1`, decisions 099 and 180), loaded by the recorder's own loader: every input
resolves in Assets3D or, by hash, in the private store (decision 144) before anything runs, and
each layer-stack call passes `--pin` for the scripts it runs and imports, so the adapter refuses
a changed script before anything reaches UzPainter.

Nothing is written under the Assets3D root. The inputs are staged into `work/assets`, a mirror of
the Assets3D tree (`stage_inputs`, with the root marker the scripts find their root by), and the
scripts run from their staged copies, so the layer-stack script imports the pinned
`route_check`. The two Painter-side scripts read their arguments from a hard-coded Assets3D path;
the runner's namespace `open` maps exactly that path to a copy in which every absolute path under
the Assets3D root names the same relative path under the mirror (decision 099 adaptation (a)),
so `dst` and `out` land in the mirror at their production-relative paths. The session file lives
in the work directory too.

A native job (decision 300 item 7, the Tunic current round: `NativeJob`) has no create or export
script. Its create sends the recorder's own calls through the same client, as Painter-side code in
UzPainter's `substance_painter` API:
1. `project.create` from the staged mesh with exactly the step's six settings and no template,
   under OCIO with Painter's substance configuration only: the manifest must name it
   (`NativeColourRefused`), the environment's `OCIO` file must hash to it before the create,
   and the project's colour management must read it back after (every later check reads it
   again); never Legacy;
2. a refusal unless the project holds exactly the named texture set;
3. the Normal imported as a TEXTURE project resource under its name and group, and bound as that
   set's Normal mesh map;
4. the slot check: all ten slots read back, the Normal the only bound one, and the Normal read
   back the imported resource's identity (URL, context, name and version), else a refusal;
5. `save_as` (Full) to `work/project/native-create.spp`.
The create's reply gives that identity, the Wand's baseline. Its sync is the unchanged sync
above, then, as the recorder does (no script saves), `save_as` (Full) to the same project and the
slot check against the baseline. Its export runs the slot check again, then exports the closing
configuration only into `work/export`. Both go through the layer-stack script's `run` (as
`painter_export.py` does), each in its own `UzPainter.exe run` process. Each later check accepts
only a renumbered `projectN` context (a reopen's), as the recorder does; any other change refuses.
UzPainter itself refuses a setting it does not support yet (`NotYetSupported` in the client's
reply). Script-only parts are refused by name (`NotAScriptJob`): `job`, and any `argument` other
than the create's `dst` and the export's `out`; a sync or export before a successful create is
refused (`NativeNotCreated`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.assets3d.client import DIAGNOSTIC_ENV
from adapters.assets3d.runner import under_root
from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tools.parity.recorder.script_run import (
    IMPORT_CLOSURE,
    MESH_MAP_SLOTS,
    NORMAL_USAGE,
    NativeJob,
    ScriptJob,
    load_manifest,
    pipeline_job_from_manifest,
    stage_inputs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS3D = Path(os.environ.get("UZP_TEST_ASSETS3D", r"E:\UzmiGames\Assets3D"))
REQUEST = (
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase1/tier1/wand-v1.json"
)
ENTRY = REPO_ROOT / "adapters" / "assets3d" / "layer_stack.py"
CLIENT = REPO_ROOT / "adapters" / "assets3d" / "client.py"
# A native job's Painter-side code: this prelude (`__SPEC__`: the spec's JSON as a Python string
# literal) and its slot check, then the create, the save after the sync or the export.
NATIVE_PRELUDE = """import json
import re

import substance_painter.project as project
import substance_painter.resource as resource
import substance_painter.textureset as textureset
import uzpainter

spec = json.loads(__SPEC__)


# The open project's colour profile, refused unless it is OCIO with the pinned configuration.
def check_colour():
    declared = uzpainter.colormanagement.get_color_management()
    found = (declared.get("mode"), declared.get("config_hash"))
    if found != ("ocio", spec["ocio_sha256"]):
        raise RuntimeError(f"the project's colour management is {found}, not the pinned OCIO")


# A resource as read: its URL, context, name and version.
def literal(found):
    url, context, version = found.url(), found.context, found.version
    return {"url": url, "context": context, "name": found.name, "version": version}


# A resource as a reopen must keep it: only a `projectN` context is renumbered.
def identity(found):
    value = literal(found)
    prefix = f"resource://{value['context']}/"
    if re.fullmatch(r"project[0-9]+", value["context"]) and value["url"].startswith(prefix):
        value["context"] = "projectN"
        value["url"] = "resource://projectN/" + value["url"][len(prefix) :]
    return value


# The Normal's resource, refused unless the project holds exactly the one texture set, all ten
# slots read back and the Normal is the only bound one.
def checked_normal():
    sets = [texture_set.name() for texture_set in textureset.all_texture_sets()]
    if sets != [spec["texture_set"]]:
        raise RuntimeError(f"the texture sets are {sets}, not exactly {spec['texture_set']}")
    texture_set = textureset.TextureSet.from_name(spec["texture_set"])
    slots = {
        slot: texture_set.get_mesh_map_resource(getattr(textureset.MeshMapUsage, slot))
        for slot in spec["slots"]
    }
    bound = sorted(slot for slot, found in slots.items() if found is not None)
    if bound != [spec["usage"]]:
        raise RuntimeError(f"the mesh maps bound are {bound}, not only {spec['usage']}")
    return slots[spec["usage"]]


# The colour and slot checks against the create's Normal, a reopen's renumbering allowed.
def check_baseline():
    check_colour()
    normal = identity(checked_normal())
    if normal != spec["baseline"]:
        raise RuntimeError(f"the Normal is {normal}, not the imported {spec['baseline']}")
    return normal
"""
NATIVE_CREATE_CODE = """
import hashlib
import os

given = spec["settings"]
if project.is_open():
    raise RuntimeError("a project is already open; the native create makes its own")
ocio = os.environ.get("OCIO")
if ocio:
    with open(ocio, "rb") as configuration:
        ocio = hashlib.sha256(configuration.read()).hexdigest()
if ocio != spec["ocio_sha256"]:
    raise RuntimeError(f"OCIO gives {ocio}, not the manifest's {spec['ocio_sha256']}: no create")
project.create(
    mesh_file_path=spec["mesh"],
    settings=project.Settings(
        normal_map_format=getattr(project.NormalMapFormat, given["normal_map_format"]),
        tangent_space_mode=getattr(project.TangentSpace, given["tangent_space_mode"]),
        project_workflow=getattr(project.ProjectWorkflow, given["project_workflow"]),
        default_texture_resolution=given["default_texture_resolution"],
        import_cameras=given["import_cameras"],
        mesh_unit_scale=given["mesh_unit_scale"],
    ),
)
check_colour()
sets = [texture_set.name() for texture_set in textureset.all_texture_sets()]
if sets != [spec["texture_set"]]:
    raise RuntimeError(f"the texture sets are {sets}, not exactly {spec['texture_set']}")
imported = resource.import_project_resource(
    spec["normal_path"], resource.Usage.TEXTURE, spec["normal_name"], spec["normal_group"]
)
texture_set = textureset.TextureSet.from_name(spec["texture_set"])
usage = getattr(textureset.MeshMapUsage, spec["usage"])
texture_set.set_mesh_map_resource(usage, imported.identifier())
bound, expected = literal(checked_normal()), literal(imported.identifier())
if bound != expected:  # literally the import: no renumbering in the creating process
    raise RuntimeError(f"the Normal is {bound}, not the imported {expected}")
project.save_as(spec["project"], project.ProjectSaveMode.Full)
normal = identity(imported.identifier())  # the baseline of the later processes
result = {"texture_sets": sets, "normal": normal, "project": project.file_path()}
"""
NATIVE_SAVE_CODE = """
project.save_as(spec["project"], project.ProjectSaveMode.Full)
result = {"normal": check_baseline(), "project": project.file_path()}
"""
NATIVE_EXPORT_CODE = """
import substance_painter.export

check_baseline()
exported = substance_painter.export.export_project_textures(spec["config"])
result = {
    "status": str(exported.status),
    "message": exported.message,
    "files": {str(key): list(files) for key, files in exported.textures.items()},
}
"""


class NotAScriptJob(RuntimeError):
    """A script-only part of the Wand asked of a native job, which has no create or export
    script: refused by name, never answered from another step."""


class NativeNotCreated(RuntimeError):
    """A native job's sync or export before its create succeeded: there is no Normal to check
    the project against."""


class NativeColourRefused(RuntimeError):
    """A native job whose manifest does not name OCIO with Painter's substance configuration: its
    project is never created under another profile, Legacy included."""


PAINTER_OCIO = "resources/ocio/substance/config.ocio"  # the configuration a manifest names


def native_ocio_sha256(job: NativeJob) -> str:
    """The SHA-256 of the colour configuration the native job's project is created under: the
    manifest must name exactly `OCIO` (by environment variable) as Painter's substance
    configuration, the one profile UzPainter pins; anything else is refused."""
    named = [
        setting["value"]
        for setting in job.manifest["applied_settings"]
        if setting["applied_by"] == "environment_variable" and setting["name"] == "OCIO"
    ]
    if named != [PAINTER_OCIO]:
        raise NativeColourRefused(
            f"{job.golden_id}: a native round runs under OCIO with {PAINTER_OCIO} only, never "
            f"Legacy; the manifest names {named}"
        )
    return PAINTER_OCIO_CONFIG_SHA256


@dataclass(frozen=True)
class Call:
    """One adapter call: exit status, standard output and error."""

    status: int
    stdout: str
    stderr: str

    def document(self, marker: str | None = None) -> Any:
        """The JSON the script printed: after `marker` (`SYNC_DONE`), else all of stdout."""
        text = self.stdout
        if marker is not None:
            line = next(x for x in text.splitlines() if x.startswith(marker + " "))
            text = line[len(marker) + 1 :]
        return json.loads(text)


def repoint(value: Any, root: Path) -> Any:
    """`value` with an absolute path under the Assets3D root moved under `root`."""
    if isinstance(value, str):
        relative = under_root(value, str(ASSETS3D)) if os.path.isabs(value) else None
        if relative is not None:
            return str(root.joinpath(*relative.split("/")))
    return value


class Wand:
    """The wand v1 inputs staged in `work`, and the adapter calls over them. Any pipeline-script
    manifest of the same three steps loads the same way (the Belt v5 Tier 1 runner, decision 192),
    and so does a native job (the module's docstring).
    """

    def __init__(
        self, painter: Path, work: Path, manifest: Path = REQUEST, repo_root: Path = REPO_ROOT
    ) -> None:
        """`manifest`: the R9 request, or the golden admitted from it (the Tier 1 runner), or a
        native job's; `repo_root` holds a closing config export's configuration."""
        self.pipeline: ScriptJob | NativeJob = pipeline_job_from_manifest(
            load_manifest(manifest), ASSETS3D, repo_root=repo_root
        )
        self.ocio_sha256: str | None = None  # a native job's colour configuration
        if isinstance(self.pipeline, NativeJob):
            self.ocio_sha256 = native_ocio_sha256(self.pipeline)  # refused before staging
        self.work = work
        self.root = work / "assets"
        self.staged = stage_inputs(self.pipeline, self.root)
        self.session = work / "session.json"
        self.state = work / "sync-state.json"
        redirects = {}
        if isinstance(self.pipeline, ScriptJob):
            for step in (self.pipeline.create, self.pipeline.export):
                assert step.arguments is not None and step.hard_coded_args is not None
                copy = work / "arguments" / Path(step.hard_coded_args).name
                copy.parent.mkdir(parents=True, exist_ok=True)
                arguments = {key: repoint(v, self.root) for key, v in step.arguments.items()}
                copy.write_text(json.dumps(arguments), encoding="utf-8")
                redirects[step.hard_coded_args] = str(copy)
        self.redirects = redirects
        self.baseline: dict[str, Any] | None = None  # a native job's Normal, from its create
        self.env = {
            **os.environ,
            "UZPAINTER_EXE": str(painter),
            "UZP_ASSETS3D_SESSION": str(self.session),
            "UZP_ASSETS3D_ROOT": str(self.root),
            "UZP_ASSETS3D_DIAGNOSTIC_IMPORT": "1",
            "UZP_ASSETS3D_PRODUCTION_REQUEST": "",
            "UZP_ASSETS3D_SCRATCH": str(self.work),
            "UZP_ASSETS3D_OPEN_REDIRECTS": json.dumps(redirects),
            "PYTHONIOENCODING": "utf-8",  # the test decodes the scripts' output as UTF-8
        }

    @property
    def job(self) -> ScriptJob:
        """The script job; a native job's is refused (`NotAScriptJob`): use `pipeline`."""
        if isinstance(self.pipeline, NativeJob):
            raise NotAScriptJob(
                f"{self.pipeline.golden_id} is a native job: it has no create or export script"
            )
        return self.pipeline

    @property
    def native(self) -> dict[tuple[str, str], Path]:
        """A native job's two outputs that `argument` names: the create's project and the
        export's directory (empty for a script job)."""
        if not isinstance(self.pipeline, NativeJob):
            return {}
        return {
            ("create", "dst"): self.work / "project" / "native-create.spp",
            ("export", "out"): self.work / "export",
        }

    def script(self, input_id: str) -> Path:
        """The pinned script as the pipeline runs it: its staged copy in the mirror."""
        return self.staged[input_id]

    def pins(self) -> list[str]:
        out = []
        for item in self.pipeline.inputs.values():
            if item.kind == "pipeline_script":
                out += ["--pin", f"{self.staged[item.input_id]}={item.sha256}"]
        return out

    def imports(self) -> list[str]:
        """`--import` for each module of the sync's pinned import closure, dependencies first
        (decision 300 item 7): the adapter loads them from their pinned bytes and refuses any
        other import, as the recorder runs them. None without a closure: the script then imports
        from the staged mirror, as it always did."""
        if IMPORT_CLOSURE not in self.pipeline.sync.args:
            return []
        out = []
        for item in self.pipeline.sync.load_order:
            out += ["--import", f"{self.staged[item.input_id]}={item.sha256}"]
        return out

    def call(
        self, *arguments: str, pins: list[str] | None = None, diagnostic: bool = False
    ) -> Call:
        """`python layer_stack.py --pin ... [--import ...] <painter_layer_stack.py> <arguments>`
        (`pins` replaces the pins only); `diagnostic`
        runs UzPainter with `--diagnostic-measure-export` (adapter client, decision 286): its
        exports are NOT conformant."""
        process = subprocess.run(
            [
                sys.executable,
                str(ENTRY),
                "--diagnostic-import",
                *(self.pins() if pins is None else pins),
                *self.imports(),
                str(self.script("painter-layer-stack-py")),
                *arguments,
            ],
            cwd=self.work,
            env={**self.env, DIAGNOSTIC_ENV: "1"} if diagnostic else self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        return Call(process.returncode, process.stdout, process.stderr)

    def create(self) -> Call:
        """`painter_create.py`'s pinned bytes through the client, or a native job's create (the
        module's docstring); stdout is the client's reply."""
        if isinstance(self.pipeline, NativeJob):
            self.baseline = None
            call = self.execute_python(self.native_code(NATIVE_CREATE_CODE), "native-create.json")
            if call.status == 0:
                self.baseline = call.document()["data"]["normal"]
            return call
        script = self.job.inputs["painter-create-py"]
        assert script.data is not None
        return self.execute_python(script.data.decode("utf-8"), "painter-create.json")

    def native_code(self, body: str, **extra: Any) -> str:
        """A native job's Painter-side code: the prelude, then `body`, over the staged mesh and
        Normal, the project and `extra` (the baseline, the configuration)."""
        assert isinstance(self.pipeline, NativeJob)
        step = self.pipeline.create
        spec = {
            "mesh": str(self.staged[step.mesh.input_id]),
            "settings": step.settings,
            "texture_set": step.args["texture_set"],
            "normal_path": str(self.staged[step.normal.input_id]),
            "normal_name": step.args["normal_name"],
            "normal_group": step.args["normal_group"],
            "usage": NORMAL_USAGE,
            "slots": sorted(MESH_MAP_SLOTS),
            "project": str(self.native["create", "dst"]),
            "ocio_sha256": self.ocio_sha256,
            **extra,
        }
        return NATIVE_PRELUDE.replace("__SPEC__", repr(json.dumps(spec))) + body

    def checked_baseline(self) -> dict[str, Any]:
        """The create's Normal, refused (`NativeNotCreated`) before a successful create."""
        if self.baseline is None:
            raise NativeNotCreated(f"{self.pipeline.golden_id}: the native create has not run")
        return self.baseline

    def execute_python(self, code: str, name: str) -> Call:
        """`code` through the client (`client.py execute_python`), its arguments in `work/name`."""
        arguments = self.work / name
        arguments.write_text(json.dumps({"code": code}), encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(CLIENT), "execute_python", str(arguments)],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        return Call(process.returncode, process.stdout, process.stderr)

    @property
    def stack(self) -> Path:
        """The staged stack JSON the sync step names (`wand-stack`, `belt-stack`)."""
        return self.staged[self.pipeline.sync.args["stack"]]

    @property
    def masks(self) -> Path:
        """The staged folder of the sync's bitmaps (`--masks`): the job's validated masks, from
        the `masks` list or the `mask_folder`."""
        return self.staged[self.pipeline.sync.masks[0].input_id].parent

    def sync(self, *extra: str) -> Call:
        """The recorder's sync command line: `--stack --masks --state`, then the step's typed
        options in order (`--resource-prefix`, `--resource-group`, `--texture-set`; none for a
        legacy sync), then `extra`. A native job's sync is then saved and checked against its
        create's Normal (the module's docstring): the save's call when that fails."""
        baseline = self.checked_baseline() if isinstance(self.pipeline, NativeJob) else None
        call = self.call(
            "sync",
            "--stack",
            str(self.stack),
            "--masks",
            str(self.masks),
            "--state",
            str(self.state),
            *(part for option in self.pipeline.sync.options for part in option),
            *extra,
        )
        if baseline is None or call.status != 0:
            return call
        code = self.work / "native-save.py"
        code.write_text(self.native_code(NATIVE_SAVE_CODE, baseline=baseline), encoding="utf-8")
        saved = self.call("run", str(code))
        return call if saved.status == 0 else saved

    def export(self, diagnostic: bool = False) -> Call:
        """`painter_export.py`, or a native job's slot check and closing config export into
        `argument("export", "out")`; `diagnostic`: the non-conformant measure export (`call`)."""
        if isinstance(self.pipeline, NativeJob):
            baseline = self.checked_baseline()
            out = self.native["export", "out"]
            out.mkdir(parents=True, exist_ok=True)
            config = {**self.pipeline.config_export.config, "exportPath": out.as_posix()}
            code = self.work / "native-export.py"
            code.write_text(
                self.native_code(NATIVE_EXPORT_CODE, baseline=baseline, config=config),
                encoding="utf-8",
            )
            return self.call("run", str(code), diagnostic=diagnostic)
        return self.call("run", str(self.script("painter-export-py")), diagnostic=diagnostic)

    def run_file(self, path: Path) -> Call:
        """A test's own Painter-side file through the script's `run` command."""
        return self.call("run", str(path))

    def probe(self, name: str, body: str) -> Any:
        """Runs `body` (it assigns `result`) through `run`; its result."""
        path = self.work / f"{name}.py"
        path.write_text(body, encoding="utf-8")
        call = self.run_file(path)
        assert call.status == 0, call.stdout + call.stderr
        return call.document()

    def argument(self, step: str, key: str) -> Path:
        """A repointed argument (`dst` of create, `out` of export); for a native job, its own
        project or export directory, and nothing else (`NotAScriptJob`)."""
        if isinstance(self.pipeline, NativeJob):
            if (step, key) not in self.native:
                raise NotAScriptJob(f"a native job has no {step} argument {key!r}")
            return self.native[step, key]
        hard_coded = getattr(self.job, step).hard_coded_args
        copy = json.loads(Path(self.redirects[hard_coded]).read_text(encoding="utf-8"))
        return Path(copy[key])
