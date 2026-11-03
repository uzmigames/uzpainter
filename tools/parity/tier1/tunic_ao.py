r"""The Tunic v10 current round's `ao.npy`, a NEW AO substitute (decision 300 s. 7).

    python -m tools.parity.tier1.tunic_ao control --blender <blender.exe> --assets-root <Assets3D>
        [--run NAME] [--expect <earlier ao-record.json>] [--dry-run]
    python -m tools.parity.tier1.tunic_ao ao --blender <blender.exe> --assets-root <Assets3D>
        --control <control run's ao-record.json> [--low-record <U3 r1 export-record.json>]
        [--low-repeat <U3 r1-repeat export-record.json>] [--run NAME]
        [--expect <earlier ao-record.json>] [--store DIR] [--dry-run]

Preparation for `phase2/tier1/tunic-v10-current` (contract:
`docs/analysis/tunic-v10-current-round/01-input-contract.md`, "Generator intermediates"). It is
not a baseline approval (decision 300 item 8). The product is a NEW AO substitute baked now from
the preserved High onto the validated low; it is not the lost historical AO and never claims to be.

1. **The donor runs unchanged.** `garment_blender_io.py` (`DONOR`) is read as the raw LF blob of
   Assets3D `SNAPSHOT` (`git cat-file`, never the checkout; git id, SHA-256 and size pinned),
   written into the run directory and executed there by Blender as a script, with the contract's
   arguments only. `tunic_ao_blender.py` observes around it (see that module): it sets nothing
   and passes no argument of its own.
2. **Inputs bound to front U3's accepted export.** Its r1 record and its r1-repeat record are
   pinned by SHA-256 (`LowPins`); the repeat must say it reproduced r1; `low.npz`,
   `highnormal.npy` and every loose array must hash to the records (`load_low`). The low's
   digests and the Normal's go to the Blender side (`ao-expect.json`), which compares the low
   before the donor and again in its bake state. The donor's own `low.npz` must hold exactly U3's
   loose arrays, member for member, and its `highnormal.npy` must be U3's file byte for byte.
3. **The device.** The donor's `use_gpu` swallows errors, so the Blender side refuses unless
   OptiX on the one pinned GPU is in effect before and after the bake. The host reads the GPU
   with `nvidia-smi` (a read-only query) before and after the run; its name, driver and UUID
   must be the pins (`GpuPin`) both times.
4. **Integrity.** The original `.blend`, the private copy (read-only, never saved), the Blender
   executable, the Blender side, its two helpers, the donor's copy and this host are hashed
   before the launch and after Blender exits, and the hashes go into the record on success and
   on failure alike: any failure once the run directory exists writes a `refused` record before
   it is raised.
5. **The readback control** (`control`, factory scene). Blender in background keeps no last
   operator properties, so the AO receipt calls its readback `unavailable` only with a linked
   control record of the same executable and scripts showing `retention-unavailable`. The
   control shows only whether keyword arguments are retained; it proves neither the device nor
   the bake's quality.
6. **Repeat.** With `--expect`, the run must reproduce an earlier record's pins, inputs, every
   observation and every output byte for byte (`compare_records`); only the files that name the
   run directory (the Blender report, the log) are compared through the record instead. A
   difference exits 1. The masks producer accepts the AO only with a reproduced repeat.

Budgets: one Blender process, `TIMEOUTS_S` (1 hour for the bake, 10 minutes for the control);
about 0.5 GB of disk per AO run (the private copy, the donor's `highnormal.npy`); Blender's own
memory for the 1.45M-triangle High. `--dry-run` checks the pins and prints the plan; it writes
nothing and starts no Blender.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.recorder.job import pinned_assets3d_file, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import sash_intermediates as readback_host
from tools.parity.tier1 import sash_low_export as low_options
from tools.parity.tier1 import tunic_ao_blender as side
from tools.parity.tier1 import tunic_low_blender as low_side
from tools.parity.tier1 import tunic_low_export as low_host
from tools.parity.tier1.sash_intermediates_blender import ExtractError
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.sash_masks import Source, read_source
from tools.parity.tier1.tunic_ao_blender import AoError
from tools.parity.tier1.tunic_intermediates import SOURCE

RECORD_SCHEMA = "uzpainter/parity/tunic-ao-record/1"
RECORD_NAME = "ao-record.json"
LOG_NAME = "blender.log"
RUN_PREFIX = "phase2__tier1__tunic-v10-current__"
DEFAULT_RUNS = {"ao": RUN_PREFIX + "ao-r1", "control": RUN_PREFIX + "ao-control-r1"}
TIMEOUTS_S = {"ao": 3600, "control": 600}
STATUS = {"ao": "baked", "control": "controlled"}
LABEL = {
    "ao": "NEW AO substitute: the donor's extract executed unchanged, baking the preserved "
    "18-Tunica-High-OriginalFit onto the validated low; not the lost historical AO and not a "
    "baseline approval",
    "control": "readback control: whether this Blender keeps a background call's operator "
    "properties; it proves neither the device nor the bake's quality",
}
SNAPSHOT = "f49fe67c0d26cd94622ba3f676122754bac8f4a6"  # Assets3D, the contract's donor commit
DONOR = Source(
    "garment_blender_io",
    side.DONOR_PATH,
    "27773e1b2979fae810d9f648ca63f6c721072d9e",
    side.DONOR_BLOB_SHA256,
    13_617,
)
SCRIPT = Path(side.__file__).resolve()
HOST = Path(__file__).resolve()
HELPERS = {key: SCRIPT.with_name(name) for key, name in side.HELPERS.items()}
# The helpers' bytes: U3's Blender side as its accepted records name it, and front P's.
HELPER_SHA256 = {
    "low": "9d575e1ae9b60c16f006a4017bf2cb86f4e00511818dcf982e63d9dc2b9444ed",
    "readback": "f7aef79ed4bc3dd703df2fe9f063848442161d36e8b075264a0924c1a5acd321",
}
RETENTION_UNAVAILABLE = readback_host.RETENTION_UNAVAILABLE
CONTROL_AO_FLOOR = readback_host.CONTROL_AO_FLOOR
CONTROL_CUBE_TOLERANCE = readback_host.CONTROL_CUBE_TOLERANCE

OUTPUTS = {
    "ao": frozenset(
        {
            side.SOURCE_BLEND_NAME,
            LOG_NAME,
            side.DONOR_FILE,
            side.AO_EXPECT,
            side.AO_REPORT,
            side.DONOR_OUT,
        }
    ),
    "control": frozenset({LOG_NAME, side.DONOR_FILE, side.CONTROL_REPORT}),
}
DONOR_FILES = tuple(f"{side.DONOR_OUT}/{name}" for name in sorted(side.DONOR_OUTPUTS))
# The files a record names by hash; the report names the opened file, the log is Blender's.
RECORD_OUTPUTS = {
    "ao": (side.DONOR_FILE, side.AO_EXPECT, side.AO_REPORT, *DONOR_FILES),
    "control": (side.DONOR_FILE, side.CONTROL_REPORT),
}
RUN_SPECIFIC = frozenset({side.AO_REPORT})
EXTRACT_REPORT = f"{side.DONOR_OUT}/extract_report.json"


@dataclass(frozen=True)
class LowPins:
    """Front U3's accepted export (commit bdc9d903; r1 and its byte-identical repeat)."""

    record_sha256: str = "842685dc3899b845e45635b8e70bb8378c4906294381ab073cfcb94af9ea6ce5"
    repeat_sha256: str = "beffc6103caa28c42052156eb3d1c1431da98de8ed48fa95d3084068007d82d8"
    low_npz_sha256: str = "0b034ea1213efe8e08389b4d57fabb33aeba520c4ffdf3fecf9491ded5ab6ae4"
    highnormal_sha256: str = "81620fb92606bc7a59122204073d7ebec7bbbda68d41f5291748eb1d4485441b"
    blender_side_sha256: str = HELPER_SHA256["low"]


@dataclass(frozen=True)
class GpuPin:
    """The one GPU `nvidia-smi` must report, before and after every run."""

    name: str = "NVIDIA GeForce RTX 4090"
    driver_version: str = "617.14"
    uuid: str = "GPU-bb5b44ae-d574-2832-66dc-16c1c35ef757"

    def as_json(self) -> dict[str, str]:
        return {"name": self.name, "driver_version": self.driver_version, "uuid": self.uuid}


LOW_RECORD = low_host.DEFAULT_RUN + "/" + low_host.RECORD_NAME
LOW_REPEAT = low_host.DEFAULT_RUN + "-repeat/" + low_host.RECORD_NAME
LOW_FILES = (
    low_host.LOW_NPZ,
    low_side.HIGHNORMAL,
    low_side.RAW_NORMALS,
    *low_side.LOW_FILES.values(),
)
NVIDIA_SMI = ("nvidia-smi", "--query-gpu=name,driver_version,uuid", "--format=csv,noheader")


def query_gpu() -> list[dict[str, str]]:
    """Every GPU as `nvidia-smi` reports it (a read-only query)."""
    done = subprocess.run(list(NVIDIA_SMI), capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AoError(f"nvidia-smi exited {done.returncode}: {done.stderr.strip()}")
    rows = [line.split(",") for line in done.stdout.splitlines() if line.strip()]
    if any(len(row) != 3 for row in rows):
        raise AoError(f"nvidia-smi printed {done.stdout!r}")
    return [{"name": n.strip(), "driver_version": d.strip(), "uuid": u.strip()} for n, d, u in rows]


def gpu_problems(found: Any, pin: GpuPin) -> list[str]:
    if found != [pin.as_json()]:
        return [f"nvidia-smi reports {found}, pinned exactly [{pin.as_json()}]"]
    return []


# --------------------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class LowInputs:
    record: Path
    repeat: Path
    record_sha256: str
    repeat_sha256: str
    digests: dict[str, str]  # the low's seven and the Normal's
    outputs: dict[str, str]  # the files next to the record, by SHA-256

    def as_json(self) -> dict[str, Any]:
        return {
            "record": str(self.record),
            "record_sha256": self.record_sha256,
            "repeat": str(self.repeat),
            "repeat_sha256": self.repeat_sha256,
            "digests": self.digests,
            "outputs": self.outputs,
        }

    def path(self, name: str) -> Path:
        return self.record.parent / name


def _json(data: bytes, what: Path) -> dict[str, Any]:
    def no_constant(name: str) -> Any:
        raise AoError(f"{what} holds the non-JSON constant {name}")

    document = json.loads(data, parse_constant=no_constant)
    if not isinstance(document, dict):
        raise AoError(f"{what} is not a JSON object")
    return document


LOW_PINS = LowPins()


def load_low(record: Path, repeat: Path, pins: LowPins = LOW_PINS) -> LowInputs:
    """Front U3's two accepted records by their pins, and every file they name next to r1."""
    documents = {}
    for path, pinned in ((record, pins.record_sha256), (repeat, pins.repeat_sha256)):
        data = path.read_bytes()
        if sha256_bytes(data) != pinned:
            raise AoError(f"{path} has SHA-256 {sha256_bytes(data)}, pinned {pinned}")
        document = _json(data, path)
        if (document.get("schema"), document.get("status")) != (low_host.RECORD_SCHEMA, "exported"):
            raise AoError(f"{path} is not an exported {low_host.RECORD_SCHEMA} record")
        if _get(document, ("script", "blender_side_sha256")) != pins.blender_side_sha256:
            raise AoError(f"{path} was made by another Blender side")
        documents[path] = document
    first, again = documents[record], documents[repeat]
    if again.get("expect") != {"reproduced": True, "problems": []}:
        raise AoError(f"{repeat} does not say it reproduced r1")
    outputs = {name: _get(first, ("outputs", name, "sha256")) for name in LOW_FILES}
    if outputs[low_host.LOW_NPZ] != pins.low_npz_sha256:
        raise AoError(f"{record} names low.npz {outputs[low_host.LOW_NPZ]}, pinned")
    if outputs[low_side.HIGHNORMAL] != pins.highnormal_sha256:
        raise AoError(f"{record} names highnormal.npy {outputs[low_side.HIGHNORMAL]}, pinned")
    for name, sha256 in outputs.items():
        if _get(again, ("outputs", name, "sha256")) != sha256:
            raise AoError(f"{repeat} has another {name} than r1")
        path = record.parent / name
        if not path.is_file() or sha256_file(path) != sha256:
            raise AoError(f"{path} is missing or does not hash to its record's {sha256}")
    digests = _get(first, ("mesh", "digests"))
    wanted = sorted([*side.LOW_DIGESTS, "highnormal"])
    if not isinstance(digests, dict) or sorted(digests) != wanted:
        raise AoError(f"{record} holds no digests for {wanted}")
    if _get(again, ("mesh", "digests")) != digests:
        raise AoError(f"{repeat} has other digests than r1")
    return LowInputs(
        record=record,
        repeat=repeat,
        record_sha256=pins.record_sha256,
        repeat_sha256=pins.repeat_sha256,
        digests=dict(digests),
        outputs={name: str(sha) for name, sha in outputs.items()},
    )


# ----------------------------------------------------------------------------------- plan
@dataclass(frozen=True)
class Plan:
    mode: str
    blender: Path
    blender_sha256: str
    run_dir: Path
    command: tuple[str, ...]
    donor_code: bytes
    scripts: dict[str, str]  # blender_side, low, readback, host: SHA-256
    source: Path | None = None
    source_origin: str | None = None  # "assets3d" or "store"
    source_pin: SourcePin = SOURCE
    gpu_pin: GpuPin = field(default_factory=GpuPin)
    donor: Source = DONOR
    snapshot: str = SNAPSHOT

    def files(self) -> tuple[tuple[str, Path, str], ...]:
        """(stem, file, pinned SHA-256) of every file the run hashes before and after."""
        found: list[tuple[str, Path, str]] = []
        if self.mode == "ao":
            assert self.source is not None
            pin = self.source_pin.sha256
            found += [("original", self.source, pin)]
            found += [("copy", self.run_dir / side.SOURCE_BLEND_NAME, pin)]
        found += [("blender", self.blender, self.blender_sha256)]
        found += [("blender_side", SCRIPT, self.scripts["blender_side"])]
        found += [(f"{key}_helper", path, self.scripts[key]) for key, path in HELPERS.items()]
        found += [("host", HOST, self.scripts["host"])]
        found += [("donor", self.run_dir / side.DONOR_FILE, self.donor.sha256)]
        return tuple(found)

    def as_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "mode": self.mode,
            "blender": {"executable": str(self.blender), "sha256": self.blender_sha256},
            "scripts": scripts_json(self.scripts),
            "donor": self.donor.as_json(self.snapshot),
            "run_dir": str(self.run_dir),
            "command": list(self.command),
            "environment": {name: str(self.run_dir) for name in low_options.TEMP_VARIABLES},
            "timeout_s": TIMEOUTS_S[self.mode],
            "gpu": self.gpu_pin.as_json(),
        }
        if self.mode == "ao":
            document["source"] = {
                **self.source_pin.as_json(),
                "resolved_from": self.source_origin,
                "path": str(self.source),
            }
            document["donor_args"] = list(side.DONOR_ARGS)
            document["bake_call"] = side.BAKE_CALL
        return document


def scripts_json(scripts: Mapping[str, str]) -> dict[str, Any]:
    return {
        "blender_side": SCRIPT.relative_to(REPO_ROOT).as_posix(),
        "blender_side_sha256": scripts["blender_side"],
        "helpers": {
            key: {"path": path.relative_to(REPO_ROOT).as_posix(), "sha256": scripts[key]}
            for key, path in HELPERS.items()
        },
        "host": HOST.relative_to(REPO_ROOT).as_posix(),
        "host_sha256": scripts["host"],
    }


def blender_command(blender: Path, run_dir: Path, mode: str) -> tuple[str, ...]:
    """Front N's pinned options; the private copy opens first (not for the control)."""
    opened = (str(run_dir / side.SOURCE_BLEND_NAME),) if mode == "ao" else ()
    return (
        str(blender),
        *low_options.BLENDER_OPTIONS,
        *opened,
        "--python-exit-code",
        "1",
        "--python",
        str(SCRIPT),
        "--",
        mode,
        str(run_dir),
    )


def pin_problems() -> list[str]:
    """The Blender side's literal pins against U3's, U2's and the contract's."""
    checks: list[tuple[str, Any, Any]] = [
        ("source name", side.SOURCE_BLEND_NAME, low_side.SOURCE_BLEND_NAME),
        ("low object", side.LOW_OBJECT, low_side.SOURCE_OBJECT),
        ("lining attribute", side.LINING_ATTRIBUTE, low_side.LINING_ATTRIBUTE),
        ("Normal", side.NORMAL_IMAGE, low_side.NORMAL_IMAGE),
        ("donor", side.DONOR_BLOB_SHA256, low_side.DONOR_BLOB_SHA256),
        ("donor pin", DONOR.sha256, side.DONOR_BLOB_SHA256),
        ("helpers", sorted(side.HELPERS), sorted(HELPER_SHA256)),
        ("bake call", side.BAKE_CALL, dict(zip(side.BAKE_CALL, _donor_call(), strict=True))),
        ("control call names", sorted(side.CONTROL_BAKE), sorted(side.BAKE_CALL)),
    ]
    return [f"the Blender side's {what} differs from its pin" for what, a, b in checks if a != b]


def _donor_call() -> list[Any]:
    """The bake keywords the donor passes for the contract's arguments (`DONOR_ARGS`)."""
    args = dict(zip(side.DONOR_ARGS[1::2], side.DONOR_ARGS[2::2], strict=True))
    return ["AO", True, float(args["--max-ray"]), float(args["--cage"]), 8]


def plan(
    mode: str,
    blender: Path,
    run: str,
    assets_root: Path,
    store: OracleStore | None,
    *,
    blender_sha256: str = low_options.BLENDER_SHA256,
    source_pin: SourcePin = SOURCE,
    donor: Source = DONOR,
    snapshot: str = SNAPSHOT,
    helper_sha256: Mapping[str, str] = HELPER_SHA256,
    gpu_pin: GpuPin | None = None,
    work: Path | None = None,
) -> Plan:
    """Check every pin and fix the command; writes nothing."""
    problems = pin_problems()
    for key, path in HELPERS.items():
        found = sha256_file(path)
        if found != helper_sha256[key]:
            problems.append(f"{path} has SHA-256 {found}, pinned {helper_sha256[key]}")
    if problems:
        raise AoError("; ".join(problems))
    if not low_options.RUN_NAME.fullmatch(run):
        raise AoError(f"run name {run!r} must match {low_options.RUN_NAME.pattern}")
    run_dir = ensure_outside_repository((work if work is not None else work_root()) / run)
    if run_dir.exists():
        raise AoError(f"{run_dir} already exists; every run gets a fresh directory")
    if not blender.is_file():
        raise AoError(f"no Blender executable at {blender}")
    blender = blender.resolve(strict=True)
    found = sha256_file(blender)
    if found != blender_sha256:
        raise AoError(f"{blender} has SHA-256 {found}, pinned {blender_sha256}")
    code = read_source(donor, assets_root, snapshot)
    source = origin = None
    if mode == "ao":
        item = {
            "input_id": source_pin.input_id,
            "assets3d_path": source_pin.assets3d_path,
            "sha256": source_pin.sha256,
        }
        source = pinned_assets3d_file(item, assets_root, store)
        if source.stat().st_size != source_pin.size_bytes:
            raise AoError(f"{source} has {source.stat().st_size} bytes, pinned {source_pin}")
        origin = "assets3d" if source == assets_root / source_pin.assets3d_path else "store"
    scripts = {
        "blender_side": sha256_file(SCRIPT),
        **{key: sha256_file(path) for key, path in HELPERS.items()},
        "host": sha256_file(HOST),
    }
    return Plan(
        mode=mode,
        blender=blender,
        blender_sha256=found,
        run_dir=run_dir,
        command=blender_command(blender, run_dir, mode),
        donor_code=code,
        scripts=scripts,
        source=source,
        source_origin=origin,
        source_pin=source_pin,
        gpu_pin=gpu_pin or GpuPin(),
        donor=donor,
        snapshot=snapshot,
    )


# ------------------------------------------------------------------------------------ run
Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]
GpuQuery = Callable[[], Any]


def run_blender(
    command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
) -> int:
    with log.open("xb") as stream:
        done = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    return done.returncode


def _hash_if_file(path: Path) -> str | None:
    """The file's SHA-256 (streamed); None when absent; the read error when unreadable, so a
    refusal record is still written."""
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError as error:
        return f"unreadable: {error}"


def _hash_all(
    the_plan: Plan,
    hashes: dict[str, Any],
    when: str,
    stems: Sequence[str] | None = None,
    validated: Sequence[ControlReceipt] = (),
) -> list[str]:
    """Hash the plan's files and the validated control's two files (all, or those `stems`)
    into `hashes[<stem>_sha256_<when>]`; the ones that differ from their pin."""
    problems = []
    extra = tuple(entry for receipt in validated for entry in receipt.files())
    for stem, path, pinned in (*the_plan.files(), *extra):
        if stems is not None and stem not in stems:
            continue
        key = f"{stem}_sha256_{when}"
        hashes[key] = found = _hash_if_file(path)
        if found != pinned:
            problems.append(f"{when} the run {stem} {path} is {found}, pinned {pinned}")
    return problems


def _gpu(query: GpuQuery, gpu: dict[str, Any], when: str, pin: GpuPin) -> list[str]:
    try:
        gpu[when] = found = query()
    except (AoError, OSError, subprocess.SubprocessError) as error:
        gpu[when] = f"unreadable: {error}"
        return [f"{when} the run the GPU cannot be read ({error})"]
    return [f"{when} the run {p}" for p in gpu_problems(found, pin)]


def _base_record(the_plan: Plan, hashes: Mapping[str, Any], gpu: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": the_plan.mode,
        "label": LABEL[the_plan.mode],
        "blender": {
            "executable": str(the_plan.blender),
            "sha256": the_plan.blender_sha256,
            "steam_build": low_options.BLENDER_STEAM_BUILD,
            "command": list(the_plan.command),
        },
        "scripts": scripts_json(the_plan.scripts),
        "donor": {**the_plan.donor.as_json(the_plan.snapshot), "args": list(side.DONOR_ARGS)},
        "hashes": dict(hashes),
        "gpu": {"pin": the_plan.gpu_pin.as_json(), **gpu},
    }
    if the_plan.mode == "ao":
        record["source"] = {
            **the_plan.source_pin.as_json(),
            "resolved_from": the_plan.source_origin,
        }
    return record


def _write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    text = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial = run_dir / (RECORD_NAME + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, run_dir / RECORD_NAME)


def run(
    the_plan: Plan,
    runner: Runner = run_blender,
    *,
    low: LowInputs | None = None,
    control: Path | None = None,
    gpu: GpuQuery = query_gpu,
    expected: Mapping[str, Any] | None = None,
    expected_sha256: str | None = None,
    counts: tuple[int, int] = (low_side.VERTICES, low_side.TRIANGLES),
) -> dict[str, Any]:
    """The run; any failure once the run directory exists leaves a `refused` record with the
    hashes and GPU reads taken so far (the after-run ones taken even then), then is raised."""
    ensure_outside_repository(the_plan.run_dir)  # again: a Plan can be built without `plan`
    the_plan.run_dir.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, Any] = {
        f"{stem}_sha256_{when}": None
        for stem, _, _ in the_plan.files()
        for when in ("before", "after")
    }
    reads: dict[str, Any] = {"before": None, "after": None}
    validated: list[ControlReceipt] = []  # filled once the control is validated
    try:
        record = _run(the_plan, runner, hashes, reads, gpu, low, control, counts, validated)
        if expected is not None:
            problems = compare_records(record, expected)
            record["expect"] = {
                "of_record_sha256": expected_sha256,
                "reproduced": not problems,
                "problems": problems,
            }
    except BaseException as error:
        if hashes.get("blender_sha256_after") is None:
            _hash_all(the_plan, hashes, "after", validated=validated)
        if reads["after"] is None:
            _gpu(gpu, reads, "after", the_plan.gpu_pin)
        refused = {
            **_base_record(the_plan, hashes, reads),
            "status": "refused",
            "error": f"{type(error).__name__}: {error}",
            "files": sorted(path.name for path in the_plan.run_dir.iterdir()),
        }
        _write_record(the_plan.run_dir, refused)
        raise
    _write_record(the_plan.run_dir, record)
    return record


def _run(
    the_plan: Plan,
    runner: Runner,
    hashes: dict[str, Any],
    reads: dict[str, Any],
    gpu: GpuQuery,
    low: LowInputs | None,
    control: Path | None,
    counts: tuple[int, int],
    validated: list[ControlReceipt],
) -> dict[str, Any]:
    mode, run_dir = the_plan.mode, the_plan.run_dir
    # The files that exist and the GPU are read first, so any refusal below still records them.
    stems = [stem for stem, _, _ in the_plan.files() if stem not in ("copy", "donor")]
    problems = _hash_all(the_plan, hashes, "before", stems)
    problems += _gpu(gpu, reads, "before", the_plan.gpu_pin)
    if problems:
        raise AoError("; ".join(problems))
    checked_control = None
    if mode == "ao":
        if low is None or control is None:
            raise AoError("the AO needs front U3's accepted records and a control record")
        checked_control = load_control(control, the_plan)
        validated.append(checked_control)
        # From here the control's two files are hashed with the plan's: before, after, on error.
        problems = _hash_all(
            the_plan, hashes, "before", ("control_record", "control_report"), validated
        )
        if problems:
            raise AoError("; ".join(problems))
    (run_dir / side.DONOR_FILE).write_bytes(the_plan.donor_code)
    stems = ["donor"]
    if mode == "ao":
        assert the_plan.source is not None and low is not None
        shutil.copyfile(the_plan.source, run_dir / side.SOURCE_BLEND_NAME)
        stems.append("copy")
    problems = _hash_all(the_plan, hashes, "before", stems)
    if problems:
        raise AoError("; ".join(problems))
    if mode == "ao":
        assert low is not None
        os.chmod(run_dir / side.SOURCE_BLEND_NAME, stat.S_IREAD)
        side.write_json(
            run_dir / side.AO_EXPECT,
            {
                "low_digests": {k: low.digests[k] for k in side.LOW_DIGESTS},
                "highnormal_digest": low.digests["highnormal"],
                "low_record_sha256": low.record_sha256,
                "low_repeat_sha256": low.repeat_sha256,
            },
        )
    env = {**os.environ, **{name: str(run_dir) for name in low_options.TEMP_VARIABLES}}
    log = run_dir / LOG_NAME
    try:
        code = runner(the_plan.command, run_dir, env, log, TIMEOUTS_S[mode])
    finally:
        broken = _hash_all(the_plan, hashes, "after", validated=validated)
        broken += _gpu(gpu, reads, "after", the_plan.gpu_pin)
    if reads["after"] != reads["before"]:
        broken.append("the GPU changed during the run")
    if broken:
        raise AoError("; ".join(broken))
    if code != 0:
        raise AoError(f"Blender exited {code}; see {log}")
    present = {path.name for path in run_dir.iterdir()}
    if present != OUTPUTS[mode]:
        raise AoError(
            f"{run_dir}: unexpected {sorted(present - OUTPUTS[mode])}, "
            f"missing {sorted(OUTPUTS[mode] - present)}"
        )
    base = _base_record(the_plan, hashes, reads)
    if mode == "control":
        report = _json((run_dir / side.CONTROL_REPORT).read_bytes(), run_dir)
        outcome, notes = control_outcome(report, the_plan.scripts)
        return {
            **base,
            "status": STATUS[mode],
            "outcome": outcome,
            "notes": notes,
            "control": {name: report.get(name) for name in ("blender", "cube", "bake")},
            "outputs": _outputs(run_dir, RECORD_OUTPUTS[mode]),
        }
    assert low is not None and checked_control is not None
    donor_dir = run_dir / side.DONOR_OUT
    found = {path.name for path in donor_dir.iterdir()} if donor_dir.is_dir() else set()
    if found != side.DONOR_OUTPUTS:
        raise AoError(f"the donor wrote {sorted(found)}, not {sorted(side.DONOR_OUTPUTS)}")
    report = _json((run_dir / side.AO_REPORT).read_bytes(), run_dir)
    ao = np.load(donor_dir / side.AO_NAME, allow_pickle=False)
    problems = ao_report_problems(
        report,
        run_dir / side.SOURCE_BLEND_NAME,
        low,
        the_plan.scripts,
        checked_control.outcome,
        the_plan.donor.sha256,
    )
    problems += ao_problems(ao, report)
    problems += donor_output_problems(donor_dir, low, counts)
    if problems:
        raise AoError("; ".join(problems))
    return {
        **base,
        "status": STATUS[mode],
        "low_inputs": low.as_json(),
        "control": {
            "record": str(checked_control.record),
            "record_sha256": checked_control.record_sha256,  # the bytes validated, unchanged
            "report_sha256": checked_control.report_sha256,
            "outcome": checked_control.outcome,
        },
        "ao": {key: value for key, value in report.items() if key != "blend"},
        "outputs": _outputs(run_dir, RECORD_OUTPUTS[mode]),
    }


def _outputs(run_dir: Path, names: Sequence[str]) -> dict[str, Any]:
    return {
        name: {"sha256": sha256_file(run_dir / name), "size_bytes": (run_dir / name).stat().st_size}
        for name in sorted(names)
    }


# ------------------------------------------------------------------------------- checks
def _readbacks(bake: Mapping[str, Any], outcome: str | None) -> list[str]:
    """The readback before and after the call, re-derived from their own evidence; `unavailable`
    only with the control's proof and unchanged across the call; values compared with the pins."""
    try:
        before = readback_host.rederived_readback(bake.get("readback_before"), side.BAKE_CALL)
        after = readback_host.rederived_readback(bake.get("readback"), side.BAKE_CALL)
    except ExtractError as error:
        return [str(error)]
    problems = []
    if after["status"] == "unavailable":
        if outcome != RETENTION_UNAVAILABLE:
            problems.append(f"the readback is unavailable but the control shows {outcome}")
        if before["status"] != "unavailable" or (before["values"], before["set"]) != (
            after["values"],
            after["set"],
        ):
            problems.append("the readback changed across the call yet claims no call state")
    used = after["used"]
    if used is not None:
        problems += [
            f"object.bake ran with {name} {used.get(name)!r}, pinned {value!r}"
            for name, value in side.BAKE_CALL.items()
            if not readback_host._same_option(used.get(name), value)
        ]
    return problems


def ao_report_problems(
    report: Mapping[str, Any],
    copy: Path,
    low: LowInputs,
    scripts: Mapping[str, str],
    outcome: str | None,
    donor_sha256: str = DONOR.sha256,
) -> list[str]:
    """The Blender side's observations against every pin."""
    expect = {k: low.digests[k] for k in side.LOW_DIGESTS}
    try:
        bake, normal = report["bake"], report["normal"]
        checks: list[tuple[str, Any, Any]] = [
            ("extractor", report["extractor"], side.EXTRACTOR),
            ("mode", report["mode"], "ao"),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(report["blend"]).resolve(), copy.resolve()),
            ("helpers", report["helpers"], {key: scripts[key] for key in side.HELPERS}),
            ("donor", report["donor"]["blob_sha256"], donor_sha256),
            ("donor args", report["donor"]["args"], list(side.DONOR_ARGS)),
            ("low", report["low"]["name"], side.LOW_OBJECT),
            ("low before the donor", report["low"]["first_read"], expect),
            ("low in its bake state", bake["bake_state_read"], expect),
            ("normal SHA-256", normal["packed"]["sha256"], low_side.NORMAL_SHA256),
            ("normal PNG", normal["packed"]["png"], low_side.NORMAL_PNG),
            ("normal settings", normal["settings"], low_side.NORMAL_SETTINGS),
            ("normal after", normal["after_donor"]["settings"], low_side.NORMAL_SETTINGS),
            ("normal loaded after", normal["after_donor"]["loaded"], low_side.NORMAL_LOADED),
            ("high", report["high"]["name"], side.HIGH_OBJECT),
            (
                "high counts",
                [report["high"]["vertices"], report["high"]["triangles"]],
                [side.HIGH_VERTICES, side.HIGH_TRIANGLES],
            ),
            ("bake call", bake["call"], side.BAKE_CALL),
            ("bake result", bake["result"], ["FINISHED"]),
            ("engine and samples", bake["engine_samples"], ["CYCLES", side.AO_SAMPLES]),
            ("device before the bake", side.device_problems(bake["device_before_bake"]), []),
            ("device after the bake", side.device_problems(bake["device_after_bake"]), []),
            (
                "selection",
                bake["selection"],
                {
                    "selected": sorted([side.HIGH_OBJECT, side.LOW_OBJECT]),
                    "active": side.LOW_OBJECT,
                },
            ),
            ("image", bake["image"]["name"], side.AO_IMAGE),
            ("image colour space", bake["image"]["colorspace"], side.AO_COLORSPACE),
            ("image size", bake["image"]["size"], [side.AO_RESOLUTION] * 2),
            ("image float", bake["image"]["is_float"], True),
            ("pixels finite", bake["pixels"]["finite"], True),
            ("pixels in [0, 1]", bake["pixels"]["in_unit_range"], True),
        ]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    problems = [f"report {w} is {f!r}, pinned {p!r}" for w, f, p in checks if f != p]
    return problems + _readbacks(bake, outcome)


def ao_problems(ao: Any, report: Mapping[str, Any]) -> list[str]:
    shape = (side.AO_RESOLUTION, side.AO_RESOLUTION)
    if ao.dtype.str != "<f2" or ao.shape != shape:
        return [f"ao.npy is {ao.dtype.str}{list(ao.shape)}, pinned <f2{list(shape)}"]
    if not np.isfinite(ao).all() or ao.min() < 0 or ao.max() > 1:
        return ["ao.npy holds values outside [0, 1]"]
    if side.array_digest(ao) != _get(report, ("bake", "digest")):
        return ["ao.npy is not the float16 cast of the values the bake checked"]
    return []


def donor_output_problems(donor_dir: Path, low: LowInputs, counts: tuple[int, int]) -> list[str]:
    """The donor's own re-extraction is U3's: `low.npz` member for member and `highnormal.npy`
    byte for byte; its report names the lining, the Normal and the contract's AO arguments."""
    problems = []
    with zipfile.ZipFile(donor_dir / low_host.LOW_NPZ) as archive:
        names = [info.filename for info in archive.infolist()]
        wanted = [f"{name}.npy" for name in low_side.LOW_ARRAYS]
        if names != wanted:
            return [f"the donor's low.npz holds {names}, not {wanted}"]
        for name in low_side.LOW_ARRAYS:
            data = archive.read(f"{name}.npy")
            if sha256_bytes(data) != low.outputs[low_side.LOW_FILES[name]]:
                problems.append(f"the donor's low.npz member {name} is not U3's array")
    if sha256_file(donor_dir / low_side.HIGHNORMAL) != low.outputs[low_side.HIGHNORMAL]:
        problems.append("the donor's highnormal.npy is not U3's, byte for byte")
    report = _json((donor_dir / "extract_report.json").read_bytes(), donor_dir)
    checks: list[tuple[str, Any, Any]] = [
        ("low", report.get("low"), side.LOW_OBJECT),
        ("counts", [report.get("vertices"), report.get("triangles")], list(counts)),
        ("uv map", report.get("uv_map"), low_side.UV_MAP),
        ("lining attribute", report.get("lining_attribute"), side.LINING_ATTRIBUTE),
        (
            "normal image",
            report.get("normal_image"),
            {
                "name": side.NORMAL_IMAGE,
                "size": [low_side.NORMAL_PNG["width"], low_side.NORMAL_PNG["height"]],
                "colorspace": low_side.NORMAL_SETTINGS["colorspace"],
            },
        ),
        (
            "ao",
            {k: v for k, v in (report.get("ao") or {}).items() if k != "mean"},
            {
                "high": side.HIGH_OBJECT,
                "resolution": side.AO_RESOLUTION,
                "samples": side.AO_SAMPLES,
                "cage_m": side.BAKE_CALL["cage_extrusion"],
                "max_ray_m": side.BAKE_CALL["max_ray_distance"],
            },
        ),
    ]
    return problems + [
        f"the donor's extract_report {w} is {f!r}, pinned {p!r}" for w, f, p in checks if f != p
    ]


# ----------------------------------------------------------------------- readback control
def control_outcome(report: Mapping[str, Any], scripts: Mapping[str, str]) -> tuple[str, list[str]]:
    """`retention-unavailable` only when both calls took effect (the cube's size and location;
    an AO-valued bake) while their readbacks re-derive `unavailable`, unchanged across the call;
    `retention-observed` when any readback holds call state; else `inconclusive`."""
    notes: list[str] = []
    statuses: list[str] = []
    try:
        if (report["extractor"], report["mode"]) != (side.EXTRACTOR, "control"):
            return "inconclusive", ["not a control report"]
        if report["helpers"] != {key: scripts[key] for key in side.HELPERS}:
            notes.append("the control ran other helpers")
        for name, call in (("cube", side.CONTROL_CUBE), ("bake", side.CONTROL_BAKE)):
            entry = report[name]
            if entry["call"] != call or entry["result"] != ["FINISHED"]:
                notes.append(f"the {name} call is not the control's, or did not finish")
            before = readback_host.rederived_readback(entry["before"], call)
            after = readback_host.rederived_readback(entry["after"], call)
            statuses += [before["status"], after["status"]]
            if (before["values"], before["set"]) != (after["values"], after["set"]):
                notes.append(f"the {name} readback changed across the call")
        cube = report["cube"]["effect"]
        size, location = side.CONTROL_CUBE["size"], side.CONTROL_CUBE["location"]
        if any(abs(d - size) > CONTROL_CUBE_TOLERANCE for d in cube["dimensions"]) or any(
            abs(a - b) > CONTROL_CUBE_TOLERANCE
            for a, b in zip(cube["location"], location, strict=True)
        ):
            notes.append(f"the cube call did not take effect ({cube})")
        bake = report["bake"]["effect"]
        if not 0.0 <= bake["min"] <= bake["max"] <= 1.0 or bake["max"] < CONTROL_AO_FLOOR:
            notes.append(f"the control bake is not an AO bake ({bake})")
        notes += [f"control device: {p}" for p in side.device_problems(report["bake"]["device"])]
    except (KeyError, TypeError, ValueError, ExtractError) as error:
        return "inconclusive", [*notes, f"the control report is malformed ({error})"]
    if "readback" in statuses:
        return "retention-observed", notes
    if notes:
        return "inconclusive", notes
    return RETENTION_UNAVAILABLE, notes


@dataclass(frozen=True)
class ControlReceipt:
    """A validated control: the outcome derived from these exact bytes, and their SHA-256, so
    the AO run can prove that the files it cites are still what it validated."""

    record: Path
    record_sha256: str
    report: Path
    report_sha256: str
    outcome: str

    def files(self) -> tuple[tuple[str, Path, str], ...]:
        return (
            ("control_record", self.record, self.record_sha256),
            ("control_report", self.report, self.report_sha256),
        )


def load_control(path: Path, the_plan: Plan) -> ControlReceipt:
    """A control record of this Blender and these scripts, its outcome re-derived; each file is
    read once, and what is validated is those bytes."""
    data = path.read_bytes()
    record = _json(data, path)
    if (record.get("schema"), record.get("kind"), record.get("status")) != (
        RECORD_SCHEMA,
        "control",
        STATUS["control"],
    ):
        raise AoError(f"{path} is not a {RECORD_SCHEMA} control record")
    if _get(record, ("blender", "sha256")) != the_plan.blender_sha256:
        raise AoError(f"{path} ran on another Blender")
    if _get(record, ("scripts",)) != scripts_json(the_plan.scripts):
        raise AoError(f"{path} ran another Blender side or other helpers")
    report_path = path.parent / side.CONTROL_REPORT
    report = report_path.read_bytes()
    if sha256_bytes(report) != _get(record, ("outputs", side.CONTROL_REPORT, "sha256")):
        raise AoError(f"{report_path} is not the report its record names")
    outcome, _ = control_outcome(_json(report, report_path), the_plan.scripts)
    if outcome != record.get("outcome"):
        raise AoError(f"{path}: its outcome re-derives as {outcome}")
    return ControlReceipt(path, sha256_bytes(data), report_path, sha256_bytes(report), outcome)


# ------------------------------------------------------------------------------- repeats
REPEAT_FIELDS = (
    ("schema",),
    ("kind",),
    ("status",),
    ("blender", "sha256"),
    ("scripts",),
    ("donor",),
    ("source", "sha256"),
    ("gpu",),
    ("low_inputs",),
    ("control",),
    ("outcome",),
    ("notes",),
    ("ao",),
    ("outputs",),
)
# Where a record names its run: the receipts' paths and the report that names the opened file
# (its content is compared through `ao`, without that path). Nothing else is left out.
RUN_PATHS: dict[tuple[str, ...], frozenset[str]] = {
    ("low_inputs",): frozenset({"record", "repeat"}),
    ("control",): frozenset({"record"}),
    ("outputs",): RUN_SPECIFIC,
}


def _without_run(path: tuple[str, ...], value: Any) -> Any:
    names = RUN_PATHS.get(path)
    if names is None or not isinstance(value, Mapping):
        return value
    return {k: v for k, v in value.items() if k not in names}


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """What a repeat must reproduce: every pin, input, observation and output byte for byte;
    only the run's paths (`RUN_PATHS`) are left out."""
    problems = []
    for path in REPEAT_FIELDS:
        found = _without_run(path, _get(record, path))
        wanted = _without_run(path, _get(expected, path))
        if found != wanted:
            problems.append(f"{'.'.join(path)} is {found!r}, the earlier run's {wanted!r}")
    return problems


def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def load_expected(path: Path, mode: str) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    expected = _json(data, path)
    if (expected.get("schema"), expected.get("kind"), expected.get("status")) != (
        RECORD_SCHEMA,
        mode,
        STATUS[mode],
    ):
        raise AoError(f"{path} is not a {STATUS[mode]} {RECORD_SCHEMA} {mode} record")
    if "expect" in expected:
        raise AoError(f"{path} is a repeat; a repeat compares against the first run")
    return expected, sha256_bytes(data)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.tunic_ao",
        description="The Tunic v10 current round's NEW AO substitute and its readback control.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("control", "ao"):
        p = sub.add_parser(mode)
        p.add_argument("--blender", type=Path, required=True, help="the pinned blender.exe")
        p.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
        p.add_argument("--run", default=DEFAULT_RUNS[mode], help="run directory name")
        p.add_argument("--expect", type=Path, help="an earlier run's ao-record.json")
        p.add_argument("--dry-run", action="store_true", help="check pins, print the plan")
    ao = sub.choices["ao"]
    ao.add_argument("--control", type=Path, required=True, help="a control run's ao-record.json")
    ao.add_argument("--low-record", type=Path, help="front U3's r1 export-record.json")
    ao.add_argument("--low-repeat", type=Path, help="front U3's r1-repeat export-record.json")
    ao.add_argument("--store", type=Path, help="private store root (default: located)")
    args = parser.parse_args(argv)
    try:
        expected, expected_sha256 = (
            load_expected(args.expect, args.mode) if args.expect is not None else (None, None)
        )
        low = None
        store = None
        if args.mode == "ao":
            store = OracleStore.open(args.store) if args.store is not None else locate()
            low = load_low(
                args.low_record or work_root() / LOW_RECORD,
                args.low_repeat or work_root() / LOW_REPEAT,
            )
        the_plan = plan(args.mode, args.blender, args.run, args.assets_root, store)
        if args.mode == "ao":
            load_control(args.control, the_plan)
        if args.dry_run:
            print(json.dumps(the_plan.as_json(), indent=2))
            return 0
        record = run(
            the_plan,
            low=low,
            control=getattr(args, "control", None),
            expected=expected,
            expected_sha256=expected_sha256,
        )
    except (
        AoError,
        ExtractError,
        RecorderError,
        StoreError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"tunic_ao: {error}", file=sys.stderr)
        return 2
    summary = {
        "run": the_plan.run_dir.name,
        "status": record["status"],
        "outcome": record.get("outcome"),
        "outputs": record["outputs"],
        "expect": record.get("expect"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    problems = _get(record, ("expect", "problems")) or []
    for problem in problems:
        print(f"tunic_ao: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
