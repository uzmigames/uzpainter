r"""Recording batch: every pending request of the current envelope, validated offline and ordered
into one prioritized, resumable plan for the next Painter slot (decision 367, front C).

    python -m tools.parity.recorder.batch plan [--out <plan.json>] [--assets-root <dir>] [--store]
    python -m tools.parity.recorder.batch check [--assets-root <dir>] [--store]
    python -m tools.parity.recorder.batch status [--inbox <dir>] [--next] [--unmatched]

Nothing here talks to Painter. `plan` and `check` read only the repository and the Assets3D root.
With `--store`, an Assets3D input missing there may be the private store's blob of its pinned hash:
the blob must exist, and the recorder's own job check then re-hashes it, as before every
recording; nothing of it is printed. `status` also reads the public `manifest.json` and `READY` of
the oracle inbox's runs, never a record or a blob. The plan holds repository paths, hashes and
counts only, so it may be committed.

**Pending.** A request is a public manifest under the current envelope's `requests/` root
(decision 099; `requests/admitted/` holds retained sources of admitted goldens and is skipped). It
is pending while the current envelope's manifest root holds no manifest of its `golden_id`. An
admitted manifest that names another Painter build than the current envelope's is `stale`
(CONTRACT.md section 3.3) and its request is pending again.

**Deduplication.** A request is not scheduled when a later version of it exists (`<name>-v<N>`,
requested or admitted under the current build: the re-authoring convention of RECORDER.md section
11.4, whose runners refuse the earlier recipe), when another path holds the same golden byte for
byte, or when another valid pending golden of the same kind has the same inputs, instruction
sequence and settings. Two different contents under one golden id are a conflict and block both.

**Validation**, each before anything is scheduled: the public schema, `private_records` empty,
the current envelope's Painter build and version, the file name equal to the golden name, every
repository input by path and SHA-256, every Assets3D input by `assets3d_path` and SHA-256 under
`--assets-root` (or, with `--store`, a store blob of that hash), the recorder's own offline job
check for the request's kind (for a pipeline script, `record-script`'s loader: a script job, or a
native job whose first step is `project.create`, each refused on its own rules), and, for texture
goldens, an `applied_settings` entry for every
export parameter the steps use (the generator's rule, `recording_requests.export_settings`).

**Order.** Wand / G1 probes first (the golden name holds `wand`, or the description cites
`phase1.25_pilot-wand` or `phase1.26_gate-g1`), then by the number of open items of the rulebook
tasks the description cites, then by path. Items are grouped into Painter sessions by colour
configuration (a Legacy session refuses an OCIO golden and the reverse, decision 099); an
owned-process runner starts its own Painter and is a session of its own. Sessions run in the order
of their first item.

**Resume.** Every item names its checkpoint: the admitted manifest and, for the recorder's own
commands, the inbox directory of its golden. `status` recomputes the plan from the repository and
marks an item, blocked ones included, `recorded` when a READY inbox run of its golden holds a
manifest that, `private_records` aside, equals the request (a refused golden writes no run, and
READY is written last): it is admitted next, never recorded again. READY runs that match no request
are listed, so an edited or superseded request's recording is not lost. An owned-process runner
keeps its own report, so its items read `see-runner-report` until admitted. An interrupted slot
runs `status --next`, which prints the next action as JSON: an admission, or a recording with its
session's preamble. `check` exits 1 while any unadmitted, not superseded request is blocked
(invalid or in conflict).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import (
    current_envelope,
    load_registry,
    manifest_root,
)
from tools.parity.recorder.defaults import check_baking_job, check_template_job
from tools.parity.recorder.iray import settings_sheet
from tools.parity.recorder.job import (
    ASSETS3D_LICENCE,
    EXPORT,
    canonical_json,
    job_from_manifest,
    sha256_file,
)
from tools.parity.recorder.migration import INTERFACE as MIGRATION_INTERFACE
from tools.parity.recorder.migration import migration_job_from_manifest
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.recorder.script_run import INTERFACE as SCRIPT_INTERFACE
from tools.parity.recorder.script_run import pipeline_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import OracleStore, StoreError, locate

PLAN_SCHEMA = "uzpainter/parity/recording-batch/1"
REQUESTS = "requests"
RETAINED = "admitted"
ASSETS = "$assets"  # the Assets3D root, a PowerShell variable as in RECORDER.md section 11
PAINTER = "$exe"  # Painter's executable
OCIO = "OCIO"
G1_TASKS = ("phase1.25_pilot-wand", "phase1.26_gate-g1")
TASK_ID = re.compile(r"phase\d+\.\d+_[a-z0-9-]+")
VERSIONED = re.compile(r"^(?P<base>.+)-v(?P<version>[0-9]+)$")
OPEN_ITEM = re.compile(r"^\s*- \[ \]", re.MULTILINE)

# Recorder kinds: the command that records a request, and its offline job check.
TEXTURE, PROBE, DEFAULTS, TEMPLATES, SCRIPT, MIGRATION = (
    "texture",
    "probe",
    "baking-defaults",
    "templates",
    "pipeline-script",
    "migration",
)
RAW_CAPABILITY, RAW_EXPORT, FILTER_CONTEXT = (
    "raw-capability",
    "raw-export",
    "filter-context",
)
OWNED = frozenset({RAW_CAPABILITY, RAW_EXPORT, FILTER_CONTEXT})  # start their own Painter
# Tier 3 Iray references (decision 385): an operator series, one fresh Painter per reference
# (`recorder iray --launch`), in Painter's substance OCIO configuration (decision 038).
IRAY = "iray-reference"
IRAY_FAMILIES = ("phase0/iray-references", "phase0/iray-stability", "tier3/render-procedure")
IRAY_STABILITY = "phase0/iray-stability"
IRAY_OCIO = r"<Painter install>\resources\ocio\substance\config.ocio"
REF_MATCH_HDRI = ASSETS + r"\Pipeline\render\HDRI\TOS-RefMatch-Skeletal-Mage.exr"

# Durations documented by earlier batches (parity/RECORDER.md section 11), by golden-name prefix:
# the mean recording time of one golden of that family, and where the figure comes from. Any
# other family is left unestimated: the recorder keeps no timing of its own.
DOCUMENTED_SECONDS: tuple[tuple[str, int, str], ...] = (
    (
        "export-padding-kernel-",
        8,
        "decision 266 batch: 13 kernel-code probes (512 and 2048 px) recorded in 92 s",
    ),
    ("export-padding-tie-sweep-", 5, "decision 272 batch: six tie-order sweeps recorded in 30 s"),
    ("export-padding-concave-", 6, "decision 278 batch: fold and shape recorded in 12 s"),
    ("phase1-srgb-uniform-decode", 540, "decision 180: each 80-colour part takes about 9 minutes"),
    ("source-substance-booleans-filter", 5, "RECORDER.md section 11.4: recording 5 s"),
)
SESSION_SECONDS = (
    105,
    "decision 266 session: Painter open 197 s for 92 s of recording (start, checks, stop)",
)


@dataclass(frozen=True)
class Request:
    path: Path
    relative: str  # under the requests root, POSIX
    manifest: dict[str, Any]
    error: str = ""  # why the file could not be read as a JSON object

    @property
    def golden_id(self) -> str:
        return str(self.manifest.get("golden_id", ""))

    @property
    def name(self) -> str:
        return self.golden_id.rsplit("/", 1)[-1]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.manifest)).hexdigest()

    @property
    def content_key(self) -> str:
        """What Painter is asked to do: inputs by hash, steps and settings (ids and prose aside)."""
        content = {
            "tier": self.manifest.get("tier"),
            "inputs": sorted(
                (str(i.get("input_id")), str(i.get("sha256")))
                for i in self.manifest.get("inputs", [])
            ),
            "instruction_sequence": self.manifest.get("instruction_sequence"),
            "applied_settings": self.manifest.get("applied_settings"),
        }
        return hashlib.sha256(canonical_json(content)).hexdigest()


@dataclass
class Item:
    request: Request
    status: str = "pending"  # pending | superseded | duplicate | conflict
    reason: str = ""
    kind: str = ""
    problems: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    open_items: int = 0
    g1: bool = False

    @property
    def priority_class(self) -> str:
        return "g1-wand" if self.g1 else ("open-items" if self.open_items else "other")

    @property
    def priority_key(self) -> tuple[int, int, str]:
        return (0 if self.g1 else 1, -self.open_items, self.request.relative)


def requests_root(root: Path) -> Path:
    return manifest_root(current_envelope(root), root).parent / REQUESTS


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_requests(root: Path) -> list[Request]:
    base = requests_root(root)
    found: list[Request] = []
    for path in sorted(base.rglob("*.json")):
        relative = path.relative_to(base).as_posix()
        if relative.split("/", 1)[0] == RETAINED:
            continue
        try:
            document = read_json(path)
        except (OSError, ValueError) as error:
            found.append(Request(path, relative, {}, f"unreadable JSON: {error}"))
            continue
        found.append(Request(path, relative, document if isinstance(document, dict) else {}))
    return found


def admitted_builds(root: Path) -> dict[str, set[str]]:
    """golden_id -> the Painter builds its admitted manifests under the current envelope name."""
    index: dict[str, set[str]] = {}
    for path in sorted(manifest_root(current_envelope(root), root).rglob("*.json")):
        document = read_json(path)
        if not isinstance(document, dict) or "golden_id" not in document:
            continue
        build = str(document.get("software", {}).get("painter", {}).get("build_id", ""))
        index.setdefault(str(document["golden_id"]), set()).add(build)
    return index


def versioned(golden_id: str) -> tuple[str, int]:
    match = VERSIONED.match(golden_id)
    return (match["base"], int(match["version"])) if match else (golden_id, 1)


def open_items(root: Path, task: str) -> int:
    path = root / ".rulebook" / "tasks" / task / "tasks.md"
    return len(OPEN_ITEM.findall(path.read_text(encoding="utf-8"))) if path.is_file() else 0


def colour_session(manifest: dict[str, Any]) -> str | None:
    """The OCIO configuration a golden names, or None for Legacy colour management."""
    for setting in manifest.get("applied_settings", []):
        if setting.get("name") == OCIO:
            return str(setting.get("value"))
    return None


def has_assets3d_inputs(manifest: dict[str, Any]) -> bool:
    return any("assets3d_path" in item for item in manifest.get("inputs", []))


def kind_of(request: Request) -> str:
    """The recorder command a request's family records with (RECORDER.md sections 4 to 11)."""
    sequence = request.manifest.get("instruction_sequence")
    interface = sequence.get("interface") if isinstance(sequence, dict) else None
    if interface == SCRIPT_INTERFACE:
        return SCRIPT
    if interface == MIGRATION_INTERFACE:
        return MIGRATION
    family = "/".join(request.relative.split("/")[:2])
    name = request.name
    if family in IRAY_FAMILIES:
        return IRAY
    if family == "tier2b/bakes":  # bake goldens (decision 384): the texture recorder bakes
        return TEXTURE
    if family == "phase3/proc-generators":  # generator goldens: they bake, then export masks
        return TEXTURE
    if family == "tier0/api-probes":
        if name.startswith("ocio16-raw-readout-"):
            return RAW_EXPORT if "-export" in name else RAW_CAPABILITY
        if name.startswith("filter-context-"):
            return FILTER_CONTEXT
        return PROBE
    if family == "tier0/defaults-templates":
        return DEFAULTS if name.startswith("baking-defaults") else TEMPLATES
    if family in ("tier0/semantics", "tier0/assets3d"):
        return TEXTURE
    return ""


def capability_manifest(item: Item, admit_root: str) -> str:
    """The admitted capability golden a Raw export request depends on (same state and version)."""
    family = item.request.relative.rsplit("/", 1)[0]
    return f"{admit_root}/{family}/{item.request.name.replace('-export', '-capability')}.json"


def iray_conditions(item: Item) -> list[dict[str, Any]]:
    """The `iray --condition` runs a reference needs (`iray.py`): two separate sessions and a
    k*S render; a stability probe two separate sessions, or two renders of one session."""
    if item.request.relative.startswith(IRAY_STABILITY + "/"):
        if item.request.name.endswith("--same-session"):
            return [{"condition": "same_session", "runs": 1}]
        return [{"condition": "separate_session", "runs": 2}]
    return [
        {"condition": "separate_session", "runs": 2},
        {"condition": "k_times_samples", "k": 4, "runs": 1},
    ]


def iray_command(item: Item, path: str, run: dict[str, Any] | None = None) -> list[str]:
    """The series command of one `iray_conditions` entry (the first when none is given)."""
    steps = item.request.manifest.get("instruction_sequence", {}).get("steps", [])
    hdri = any("session_environment" in s.get("args", {}) for s in steps)
    run = run or iray_conditions(item)[0]
    return [
        *("python", "-m", "tools.parity.recorder", "iray", path, "--condition", run["condition"]),
        *(("--k", str(run["k"])) if "k" in run else ()),
        *("--launch", "--operator", "ui", "--operator-id", "<operator id>"),
        *(("--session-file", REF_MATCH_HDRI) if hdri else ()),
    ]


def command(item: Item, path: str, admit_root: str) -> list[str]:
    """The recording command of an item whose request lies at `path` (repository-relative)."""
    recorder = ["python", "-m", "tools.parity.recorder"]
    owned = ["--manifest", path, "--painter-exe", PAINTER, "--output-prefix", "<private prefix>"]
    assets = ["--assets-root", ASSETS] if has_assets3d_inputs(item.request.manifest) else []
    commands: dict[str, list[str]] = {
        TEXTURE: [*recorder, "record", path, *assets],
        PROBE: ["python", "-m", "tools.parity.recorder.probes", "record", path, *assets],
        DEFAULTS: [*recorder, "record-defaults", path],
        TEMPLATES: [*recorder, "record-templates", path],
        SCRIPT: [*recorder, "record-script", path, "--assets-root", ASSETS],
        MIGRATION: [*recorder, "record-migration", path, "--assets-root", ASSETS],
        RAW_CAPABILITY: ["python", "-m", "tools.parity.recorder.raw_capability_capture", *owned],
        RAW_EXPORT: [
            "python",
            "-m",
            "tools.parity.recorder.raw_export_capture",
            *owned,
            "--capability-manifest",
            capability_manifest(item, admit_root),
        ],
        FILTER_CONTEXT: ["python", "-m", "tools.parity.recorder.filter_context_run", *owned],
    }
    if item.kind == IRAY:
        return iray_command(item, path)
    return commands[item.kind]


def assets3d_problems(
    manifest: dict[str, Any], assets_root: Path | None, store: OracleStore | None
) -> list[str]:
    """Every Assets3D input by path and SHA-256 under the root; with a store, a blob of the pinned
    hash stands in (only its existence is checked here)."""
    problems: list[str] = []
    for item in manifest.get("inputs", []):
        if "assets3d_path" not in item:
            continue
        where = f"input {item.get('input_id')}"
        if item.get("provenance", {}).get("licence") != ASSETS3D_LICENCE:
            problems.append(f"{where}: an Assets3D input needs the licence {ASSETS3D_LICENCE}")
            continue
        file = assets_root / str(item["assets3d_path"]) if assets_root is not None else None
        if file is not None and file.is_file() and sha256_file(file) == item.get("sha256"):
            continue
        if store is not None and store_holds(store, str(item.get("sha256"))):
            continue
        state = (
            "no --assets-root given"
            if file is None
            else (
                f"{item['assets3d_path']} "
                + ("differs from the pin" if file.is_file() else "is missing")
            )
        )
        problems.append(
            f"{where}: {state}"
            + ("" if store is not None else " (pass --store to accept the private store's copy)")
        )
    return problems


def store_holds(store: OracleStore, sha256: str) -> bool:
    try:
        return store.blob_path(sha256).is_file()
    except StoreError:
        return False


def job_problems(
    item: Item, root: Path, assets_root: Path | None, store: OracleStore | None
) -> list[str]:
    """The recorder's own offline check of the request's kind (no Painter is touched). An
    owned-process runner re-checks its exact authored recipe when it starts; offline its request
    gets the probe loader's check."""
    manifest = item.request.manifest
    checks: dict[str, Callable[[], object]] = {
        # Without a root, an Assets3D pin found only in the store resolves through the store.
        TEXTURE: lambda: job_from_manifest(manifest, root, assets_root or root),
        PROBE: lambda: probe_job_from_manifest(manifest, root, assets_root or root),
        DEFAULTS: lambda: check_baking_job(job_from_manifest(manifest, root)),
        TEMPLATES: lambda: template_check(job_from_manifest(manifest, root)),
        SCRIPT: lambda: pipeline_job_from_manifest(manifest, assets_root or root, store, root),
        MIGRATION: lambda: migration_job_from_manifest(manifest, assets_root or root, store, root),
        IRAY: lambda: settings_sheet(job_from_manifest(manifest, root)),
    }
    check = checks.get(item.kind, lambda: probe_job_from_manifest(manifest, root))
    try:
        check()
    except (RecorderError, KeyError, TypeError, ValueError, OSError) as error:
        return [f"recorder job check: {error}"]
    return []


def template_check(job: Any) -> None:
    problems = check_template_job(job)
    if problems:
        raise RecorderError("; ".join(problems))


def export_setting_problems(manifest: dict[str, Any]) -> list[str]:
    """Each export parameter a step uses must be named in `applied_settings`."""
    applied = {
        (s.get("name"), json.dumps(s.get("value"))) for s in manifest.get("applied_settings", [])
    }
    missing: list[str] = []
    for step in manifest.get("instruction_sequence", {}).get("steps", []):
        if step.get("call") != EXPORT:
            continue
        args = step.get("args", {})
        for name, value in (
            (f"export.{args.get('file_format', 'png')}.bit_depth", args.get("bit_depth")),
            ("export.padding", args.get("padding")),
            ("export.dithering", args.get("dithering")),
            ("export.dilation", args.get("dilation")),
            ("export.size_log2", args.get("size_log2")),
        ):
            entry = f"{name}={json.dumps(value)}"
            if (
                value is not None
                and (name, json.dumps(value)) not in applied
                and entry not in missing
            ):
                missing.append(entry)
    return [f"export setting not in applied_settings: {entry}" for entry in missing]


def validate(
    item: Item,
    root: Path,
    entry: dict[str, Any],
    assets_root: Path | None,
    store: OracleStore | None,
    admit_root: str,
) -> list[str]:
    manifest = item.request.manifest
    if item.request.error:
        return [item.request.error]
    problems = [f"schema: {error}" for error in validation_errors(manifest, Schema.GOLDEN_PUBLIC)]
    if problems:
        return problems
    if manifest["private_records"]:
        problems.append("a request names no private records (decision 099)")
    painter = manifest["software"]["painter"]
    if painter["build_id"] != entry["painter_build"]:
        problems.append(
            f"names Painter build {painter['build_id']}, the current envelope is "
            f"{entry['painter_build']}: regenerate it under the current envelope"
        )
    if painter["version"] != entry["painter_version"]:
        problems.append(
            f"names Painter version {painter['version']}, not {entry['painter_version']}"
        )
    if Path(item.request.relative).stem != item.request.name:
        problems.append(f"the file name differs from the golden name {item.request.name}")
    if not item.kind:
        problems.append(f"no recorder command records the family of {item.request.relative}")
        return problems
    if item.kind == RAW_EXPORT and not (root / capability_manifest(item, admit_root)).is_file():
        problems.append(
            f"its capability golden is not admitted: {capability_manifest(item, admit_root)}"
        )
    missing_inputs = assets3d_problems(manifest, assets_root, store)
    problems += missing_inputs
    if item.kind == TEXTURE:
        problems += export_setting_problems(manifest)
    if not missing_inputs:
        problems += job_problems(item, root, assets_root, store)
    return problems


def supersede(items: list[Item], requests: list[Request], admitted: set[str]) -> None:
    """Mark each item that a later `-v<N>` of its golden (requested, or admitted under the current
    build) replaces."""
    latest: dict[str, tuple[int, str]] = {}
    for golden_id in {r.golden_id for r in requests} | admitted:
        base, version = versioned(golden_id)
        if version > latest.get(base, (0, ""))[0]:
            latest[base] = (version, golden_id)
    for item in items:
        if not item.request.golden_id:
            continue
        base, version = versioned(item.request.golden_id)
        if latest[base][0] > version:
            item.status, item.reason = "superseded", f"{latest[base][1]} replaces it"


def deduplicate(items: list[Item]) -> None:
    """One recording per golden id and per content. A golden id whose requests differ is a
    conflict; otherwise the first valid copy is kept. Content duplicates are looked for among
    valid items only, so an invalid copy never hides a valid one."""
    by_id: dict[str, list[Item]] = {}
    for item in items:
        if item.status == "pending" and item.request.golden_id:
            by_id.setdefault(item.request.golden_id, []).append(item)
    for same in by_id.values():
        if len({item.request.sha256 for item in same}) > 1:
            for item in same:
                item.status = "conflict"
                item.reason = "another request of this golden id differs: " + ", ".join(
                    other.request.relative for other in same if other is not item
                )
            continue
        keep = next((item for item in same if not item.problems), same[0])
        for item in same:
            if item is not keep:
                item.status, item.reason = "duplicate", f"same golden as {keep.request.relative}"
                item.problems = []
    first: dict[str, Item] = {}
    for item in items:
        # A stability repeat keeps its parent's scene on purpose (decision 062).
        if item.status != "pending" or item.problems or item.kind == IRAY:
            continue
        key = f"{item.kind}:{item.request.content_key}"
        if key in first:
            item.status = "duplicate"
            item.reason = f"same kind, inputs, steps and settings as {first[key].request.golden_id}"
        else:
            first[key] = item


def estimate(name: str) -> tuple[int | None, str]:
    for prefix, seconds, basis in DOCUMENTED_SECONDS:
        if name.startswith(prefix):
            return seconds, basis
    return None, "no documented timing for this family; the recorder keeps none"


def expected_artifacts(item: Item) -> dict[str, Any]:
    """What a successful recording leaves: one READY inbox run of the golden's recordings."""
    steps = item.request.manifest.get("instruction_sequence", {}).get("steps", [])
    exports = [s for s in steps if s.get("call") == EXPORT]
    recordings = {
        SCRIPT: ["r1", "r1-repeat", "r2"],
        MIGRATION: ["r1", "r2"],
        DEFAULTS: ["r1", "r2", "r3"],
    }.get(item.kind, ["r1", "r2"])
    artifacts: dict[str, Any] = {
        "inbox_run": ["record.json", "manifest.json", "blobs/", "READY"],
        "recordings": recordings,
        "export_steps": len(exports),
        "exported_maps_per_recording": sum(len(s.get("args", {}).get("maps", [])) for s in exports),
    }
    if item.kind in OWNED:
        artifacts["inbox_run"] = "the runner's own private output prefix and report"
    if item.kind == IRAY:
        artifacts["recordings"] = []
        artifacts["iray_conditions"] = iray_conditions(item)
    return artifacts


def checkpoint(item: Item, admit_root: str) -> dict[str, Any]:
    """Where a resumed slot looks: the admitted manifest, and (recorder kinds) the inbox."""
    return {
        "admitted_manifest": f"{admit_root}/{item.request.relative}",
        "inbox_dir": None if item.kind in OWNED else item.request.golden_id.replace("/", "__"),
    }


def plan_item(order: int, item: Item, request_root: str, admit_root: str) -> dict[str, Any]:
    seconds, basis = estimate(item.request.name)
    request = f"{request_root}/{item.request.relative}"
    mark = checkpoint(item, admit_root)
    artifacts = expected_artifacts(item)
    for run in artifacts.get("iray_conditions", []):
        run["command"] = iray_command(item, request, run)
    return {
        "order": order,
        "golden_id": item.request.golden_id,
        "request": request,
        "request_sha256": item.request.sha256,
        "kind": item.kind,
        "priority": {
            "class": item.priority_class,
            "cited_tasks": item.tasks,
            "open_items": item.open_items,
        },
        "command": command(item, request, admit_root),
        "admit": [
            "python",
            "-m",
            "tools.parity.store",
            "record",
            mark["admitted_manifest"],
            "--run",
            "<run>",
        ],
        "expected_artifacts": artifacts,
        "estimated_seconds": seconds,
        "estimate_basis": basis,
        "checkpoint": mark,
    }


def preamble(colour: str | None, owned: bool, first_request: str, iray: bool = False) -> list[str]:
    if iray:
        return [
            "close any other Painter: the series starts and stops one fresh Painter per reference",
            f'$env:OCIO = "{IRAY_OCIO}"',
            "run each command of an item's iray_conditions `runs` times, one Painter each (a "
            "series skips a condition already staged); the operator applies the settings sheet",
        ]
    if owned:
        return ["the runner starts, checks and stops its own Painter; close any other Painter"]
    if colour is None:
        return [
            "close Painter first if it runs: the colour configuration is fixed at its start",
            "Remove-Item Env:OCIO, Env:PAINTER_ACE_CONFIG -ErrorAction SilentlyContinue",
            f"& {PAINTER} --enable-remote-scripting  # wait until no project is open",
            "python -m tools.parity.envelope check  # must exit 0",
        ]
    return [
        "close Painter first if it runs: the colour configuration is fixed at its start",
        f'$env:OCIO = "{colour}"',
        f"& {PAINTER} --enable-remote-scripting  # wait until no project is open",
        f"python -m tools.parity.envelope check --request {first_request}  # must exit 0",
    ]


def stale_tier3(root: Path, entry: dict[str, Any], known: set[str]) -> list[dict[str, str]]:
    """Tier 3 references of a superseded envelope (the drift report's `stale_tier3`) that the
    current envelope neither requests nor holds: re-captured only from a new request."""
    report = entry.get("drift_report")
    if not report or not (root / report).is_file():
        return []
    return [
        {
            "golden_id": golden_id,
            "reason": "Tier 3 reference of a superseded envelope (CONTRACT.md section 5); "
            "no current-envelope request",
        }
        for golden_id in read_json(root / report).get("stale_tier3", [])
        if golden_id not in known
    ]


def superseded_requests(root: Path, known: set[str]) -> list[dict[str, str]]:
    """Requests of superseded envelopes whose golden the current envelope neither requests nor
    holds."""
    document = load_registry(root)
    missing: list[dict[str, str]] = []
    for entry in document["envelopes"]:
        if entry["envelope_id"] == document["current"]:
            continue
        base = manifest_root(entry, root).parent / REQUESTS
        for path in sorted(base.rglob("*.json")) if base.is_dir() else []:
            golden_id = str(read_json(path).get("golden_id", ""))
            if golden_id and golden_id not in known:
                missing.append(
                    {
                        "golden_id": golden_id,
                        "reason": f"request of the superseded envelope {entry['envelope_id']}; "
                        "regenerate it under the current envelope",
                    }
                )
    return missing


def public_text(text: str, places: dict[str, str]) -> str:
    """A diagnostic with each local directory replaced by its placeholder (the plan is public)."""
    for path, placeholder in places.items():
        text = text.replace(path, placeholder)
    return text


def build_plan(
    root: Path = REPO_ROOT,
    assets_root: Path | None = None,
    store: OracleStore | None = None,
) -> dict[str, Any]:
    entry = current_envelope(root)
    request_root = requests_root(root).relative_to(root).as_posix()
    admit_root = manifest_root(entry, root).relative_to(root).as_posix()
    requests = load_requests(root)
    admitted = admitted_builds(root)
    build = str(entry["painter_build"])
    items = [Item(r) for r in requests if build not in admitted.get(r.golden_id, set())]
    supersede(items, requests, {g for g, builds in admitted.items() if build in builds})
    places = {str(p): name for p, name in ((root, "<repository>"), (assets_root, ASSETS)) if p}
    if store is not None:
        places[str(store.root)] = "<store>"
    for item in items:
        item.kind = kind_of(item.request)
        item.tasks = sorted(set(TASK_ID.findall(str(item.request.manifest.get("description")))))
        item.open_items = sum(open_items(root, task) for task in item.tasks)
        item.g1 = "wand" in item.request.name or any(t in item.tasks for t in G1_TASKS)
        if item.status == "pending":
            problems = validate(item, root, entry, assets_root, store, admit_root)
            item.problems = [public_text(p, places) for p in problems]
    deduplicate(items)
    scheduled = sorted(
        (i for i in items if i.status == "pending" and not i.problems), key=lambda i: i.priority_key
    )
    groups: dict[str, list[Item]] = {}
    for item in scheduled:
        colour = colour_session(item.request.manifest)
        key = f"owned:{item.request.relative}" if item.kind in OWNED else f"colour:{colour}"
        key = IRAY if item.kind == IRAY else key
        groups.setdefault(key, []).append(item)
    sessions: list[dict[str, Any]] = []
    order = 0
    for members in groups.values():  # insertion order is the order of each session's first item
        colour = colour_session(members[0].request.manifest)
        iray = members[0].kind == IRAY
        owned = members[0].kind in OWNED or iray
        colour = IRAY_OCIO if iray else colour
        entries = []
        for item in members:
            order += 1
            entries.append(plan_item(order, item, request_root, admit_root))
        known_seconds = [e["estimated_seconds"] for e in entries if e["estimated_seconds"]]
        sessions.append(
            {
                "session": len(sessions) + 1,
                "colour_management": "legacy" if colour is None else "ocio",
                "ocio_configuration": colour,
                "owned_process": owned,
                "preamble": preamble(colour, owned, entries[0]["request"], iray),
                "items": entries,
                "estimated_seconds": (0 if owned else SESSION_SECONDS[0]) + sum(known_seconds),
                "unestimated_items": len(entries) - len(known_seconds),
            }
        )
    counts: dict[str, int] = {}
    for item in scheduled:
        counts[item.priority_class] = counts.get(item.priority_class, 0) + 1
    blocked = [i for i in items if i.problems or i.status == "conflict"]
    known = {r.golden_id for r in requests} | set(admitted)
    return {
        "schema": PLAN_SCHEMA,
        "envelope_id": entry["envelope_id"],
        "painter_build": entry["painter_build"],
        "requests_root": request_root,
        "summary": {
            "requests": len(requests),
            "admitted": len(requests) - len(items),
            "scheduled": len(scheduled),
            "scheduled_by_priority": counts,
            "blocked": len(blocked),
            "not_scheduled": sum(1 for i in items if i.status not in ("pending", "conflict")),
            "sessions": len(sessions),
            "estimated_seconds": sum(s["estimated_seconds"] for s in sessions),
            "unestimated_items": sum(s["unestimated_items"] for s in sessions),
            "estimate_note": f"session overhead {SESSION_SECONDS[0]} s ({SESSION_SECONDS[1]}); "
            "unestimated items are not counted",
        },
        "sessions": sessions,
        "blocked": [
            {
                "golden_id": i.request.golden_id,
                "request": f"{request_root}/{i.request.relative}",
                "status": "invalid" if i.problems else i.status,
                "problems": i.problems or [i.reason],
                "checkpoint": checkpoint(i, admit_root),
            }
            for i in blocked
        ],
        "not_scheduled": [
            {
                "request": f"{request_root}/{i.request.relative}",
                "status": i.status,
                "reason": i.reason,
            }
            for i in items
            if i.status not in ("pending", "conflict")
        ],
        "needs_request": stale_tier3(root, entry, known) + superseded_requests(root, known),
    }


def ready_runs(inbox: Path, inbox_dir: str) -> list[Path]:
    directory = inbox / inbox_dir
    runs = sorted(directory.iterdir(), reverse=True) if directory.is_dir() else []
    return [run for run in runs if (run / "READY").is_file() and (run / "manifest.json").is_file()]


def recorded_runs(row: dict[str, Any], inbox: Path, root: Path) -> list[Path]:
    """The READY inbox runs, newest first, whose public manifest, `private_records` aside, is
    exactly the request (a refused golden writes no run; READY is written last). An unreadable
    run manifest matches nothing."""
    inbox_dir = row["checkpoint"]["inbox_dir"]
    if inbox_dir is None:
        return []
    try:
        request = read_json(root / str(row["request"]))
    except (OSError, ValueError):
        return []
    found: list[Path] = []
    for run in ready_runs(inbox, str(inbox_dir)):
        try:
            manifest = read_json(run / "manifest.json")
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict) and {**manifest, "private_records": []} == request:
            found.append(run)
    return found


def status(plan: dict[str, Any], inbox: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    """Each scheduled and blocked item of a freshly built plan with its checkpoint state, and the
    READY inbox runs that match none of them (an edited or superseded request's recording)."""
    rows: list[dict[str, Any]] = []
    for session in plan["sessions"]:
        for item in session["items"]:
            rows.append({**item, "session": session["session"], "state": "pending"})
    rows += [{**row, "session": None, "state": "blocked"} for row in plan["blocked"]]
    matched: set[Path] = set()
    for row in rows:
        runs = recorded_runs(row, inbox, root)
        if row["checkpoint"]["inbox_dir"] is None and row["state"] == "pending":
            row["state"] = "see-runner-report"
        if runs:
            row["state"], row["run"] = "recorded", str(runs[0])
            matched.update(runs)
    unmatched = (
        [
            str(run)
            for directory in sorted(inbox.iterdir())
            for run in ready_runs(inbox, directory.name)
            if run not in matched
        ]
        if inbox.is_dir()
        else []
    )
    return {"rows": rows, "unmatched_runs": unmatched}


def next_action(plan: dict[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
    """The first thing a resumed slot does: admit a recorded run (never one of a golden whose
    requests conflict), else record the next pending item, with its session's preamble; an
    owned-process runner's item asks for its report to be read first."""
    for row in report["rows"]:
        if row["state"] == "recorded" and row.get("status") != "conflict":
            manifest = row["checkpoint"]["admitted_manifest"]
            admit = ["python", "-m", "tools.parity.store", "record", manifest, "--run", row["run"]]
            return {"action": "admit", "golden_id": row["golden_id"], "command": admit}
    for row in report["rows"]:
        if row["state"] in ("pending", "see-runner-report"):
            session = plan["sessions"][row["session"] - 1]
            pending = row["state"] == "pending"
            return {
                "action": "record" if pending else "read the runner's report, then record",
                "golden_id": row["golden_id"],
                "session": row["session"],
                "preamble": session["preamble"],
                "command": row["command"],
            }
    return None


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.batch")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "check", "status"):
        sub = commands.add_parser(name)
        sub.add_argument("--assets-root", type=Path, default=None, help="the Assets3D root")
        sub.add_argument(
            "--store", action="store_true", help="accept a private-store blob of a pinned hash"
        )
        if name == "plan":
            sub.add_argument("--out", type=Path, help="write the plan there (public data only)")
        if name == "status":
            sub.add_argument(
                "--inbox", type=Path, help="the oracle inbox (default UZP_ORACLE_INBOX)"
            )
            sub.add_argument("--next", action="store_true", help="print only the next action")
            sub.add_argument("--unmatched", action="store_true", help="list unmatched READY runs")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    store = locate() if args.store else None
    plan = build_plan(REPO_ROOT, args.assets_root, store)
    if args.command == "plan":
        text = json.dumps(plan, indent=1) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8", newline="\n")
            print(f"plan: {args.out}")
        else:
            print(text, end="")
        return 0
    if args.command == "check":
        for row in plan["blocked"]:
            print(f"{row['request']}: {row['status']}: " + "; ".join(row["problems"]))
        print(json.dumps(plan["summary"], indent=1))
        return 1 if plan["blocked"] else 0
    from tools.parity.recorder.output import inbox_root

    report = status(plan, args.inbox or inbox_root())
    if args.next:
        print(json.dumps(next_action(plan, report), indent=1))
        return 0
    for row in report["rows"]:
        where = f"s{row['session']}" if row["session"] else "--"
        line = f"{row.get('order', '-'):>3} {where} {row['state']:<17} {row['golden_id']}"
        print(line + (f"  run: {row['run']}" if row.get("run") else ""))
    unmatched = report["unmatched_runs"]
    for run in unmatched if args.unmatched else []:
        print(f"unmatched READY run: {run}")
    if unmatched and not args.unmatched:
        print(
            f"{len(unmatched)} READY inbox runs equal no pending request (admitted earlier, or of "
            "an edited or superseded request); --unmatched lists them"
        )
    left = sum(1 for row in report["rows"] if row["state"] != "recorded")
    print(f"{left} of {len(report['rows'])} not yet recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
