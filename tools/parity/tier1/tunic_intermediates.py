r"""The Tunic v10 current round's mesh and Normal inspection (decision 300 section 7).

    python -m tools.parity.tier1.tunic_intermediates inspect --blender <blender.exe>
        --assets-root <Assets3D> [--run NAME] [--store DIR] [--dry-run]

Preparation for `phase2/tier1/tunic-v10-current` (contract:
`docs/analysis/tunic-v10-current-round/01-input-contract.md`, "Meshes: to inspect on a private
copy after a prepared review"). It is not a baseline approval (decision 300 item 8), and it makes
no intermediate: no extraction, no export, no bake, no normalising or fitting toward the old OBJ.

1. **Pins and run directory.** Front N's (`sash_low_export`): the Blender executable by SHA-256
   and its options, and a fresh run directory under the oracle work root (refused inside the
   repository) with Blender's temporary folders pointed into it. The source is the preserved
   `18-Tunica-v10.blend` (`SOURCE`: the inventory's SHA-256 and its size), resolved from Assets3D
   when the file there matches, else from the private store's blob.
2. **Private copy.** Copied into the run directory, hash-checked and made read-only; Blender opens
   the copy, never the original, and never saves. The original's and the copy's SHA-256 are
   taken before and after the run and are recorded on success and on failure alike: any failure
   after the run directory exists writes a `refused` record with them before it is raised.
3. **Blender, once.** `tunic_intermediates_blender.py inspect` reads only the named low and high,
   the packed `Source_v6_HighNormal` and the exact candidate names (see that module).
4. **Checks.** The run directory holds exactly the copy, the log and the report; the report names
   the pinned inspector, Blender 5.2, the opened copy and exactly the inspected names
   (`report_problems`). What it finds is recorded, never gated or corrected.
5. **Outputs.** The report and `inspect-record.json` stay in the private run directory. Only the
   run's name and `public_summary` (hashes and counts under role labels) are printed: names,
   paths, domains, colour spaces, values and matrices stay private.

`--dry-run` checks the pins and prints the plan with its command line, for the review that comes
before any run; it holds local paths, so it is not public. It writes nothing and does not start
Blender. Just before launch the executable and the Blender side are hashed again against the
plan.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder.job import pinned_assets3d_file, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.recorder.tunic import NORMAL, TUNIC_BLEND
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import sash_low_export as low_host
from tools.parity.tier1 import tunic_intermediates_blender as side
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.tunic_intermediates_blender import InspectError

RECORD_SCHEMA = "uzpainter/parity/tunic-intermediates-record/1"
RECORD_NAME = "inspect-record.json"
LOG_NAME = "blender.log"
DEFAULT_RUN = "phase2__tier1__tunic-v10-current__inspect-r1"
TIMEOUT_S = 900
LABEL = "current-round preparation: inspection of the preserved .blend; not a baseline approval"
SOURCE = SourcePin(
    input_id="tunic-v10-blend",
    assets3d_path=TUNIC_BLEND,
    sha256="f6243a577f673c2b00e5803c256cebfbe933187810b7446f81d56827f0d92cb9",
    size_bytes=200_386_055,
)
# The preserved Normal's pin (`tunic.NORMAL`): the packed bytes the inspection hashes.
NORMAL_IMAGE, NORMAL_SHA256 = NORMAL
OUTPUTS = frozenset({side.SOURCE_BLEND_NAME, LOG_NAME, side.REPORT_NAME})
DEPSGRAPH_MODE = "VIEWPORT"  # the donor's background `evaluated_depsgraph_get()`
# Public role labels: the public summary carries no object or data-block name.
ROLES = {"low": side.LOW_OBJECT, "high": side.HIGH_OBJECT}
CANDIDATE_ROLES = dict(
    zip(("lining_attribute", "source_lining"), side.CANDIDATE_NAMES, strict=True)
)
SCRIPT = Path(side.__file__).resolve()
HASH_KEYS = (
    "original_sha256_before",
    "copy_sha256_before",
    "copy_sha256_after",
    "original_sha256_after",
)


@dataclass(frozen=True)
class Plan:
    blender: Path
    blender_sha256: str
    script_sha256: str
    source: Path
    source_origin: str  # "assets3d" or "store"
    run_dir: Path
    command: tuple[str, ...]
    source_pin: SourcePin = SOURCE

    def as_json(self) -> dict[str, Any]:
        return {
            "mode": "inspect",
            "blender": {"executable": str(self.blender), "sha256": self.blender_sha256},
            "script": _script_json(self.script_sha256),
            "source": {
                **self.source_pin.as_json(),
                "resolved_from": self.source_origin,
                "path": str(self.source),
            },
            "run_dir": str(self.run_dir),
            "command": list(self.command),
            "environment": {name: str(self.run_dir) for name in low_host.TEMP_VARIABLES},
            "timeout_s": TIMEOUT_S,
        }


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


def _script_json(script_sha256: str) -> dict[str, Any]:
    return {
        "blender_side": SCRIPT.relative_to(REPO_ROOT).as_posix(),
        "blender_side_sha256": script_sha256,
        "host": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
        "host_sha256": sha256_file(Path(__file__)),
        "donor": {"assets3d_path": side.DONOR_PATH, "blob_sha256": side.DONOR_BLOB_SHA256},
    }


def blender_command(blender: Path, script: Path, run_dir: Path) -> tuple[str, ...]:
    """Front N's pinned options; the private copy opens first; a Python error exits 1."""
    return (
        str(blender),
        *low_host.BLENDER_OPTIONS,
        str(run_dir / side.SOURCE_BLEND_NAME),
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        "inspect",
        str(run_dir),
    )


def plan_inspect(
    blender: Path,
    run: str,
    assets_root: Path,
    store: OracleStore | None,
    *,
    source_pin: SourcePin = SOURCE,
    blender_sha256: str = low_host.BLENDER_SHA256,
    work: Path | None = None,
) -> Plan:
    """Check every pin and fix the command; writes nothing."""
    if Path(source_pin.assets3d_path).name != side.SOURCE_BLEND_NAME:
        raise InspectError("the Blender side's source name differs from the pinned file's")
    if NORMAL_IMAGE != side.NORMAL_IMAGE:
        raise InspectError("the Blender side's Normal image differs from the recorder's pin")
    if not low_host.RUN_NAME.fullmatch(run):
        raise InspectError(f"run name {run!r} must match {low_host.RUN_NAME.pattern}")
    run_dir = ensure_outside_repository((work if work is not None else work_root()) / run)
    if run_dir.exists():
        raise InspectError(f"{run_dir} already exists; every run gets a fresh directory")
    if not blender.is_file():
        raise InspectError(f"no Blender executable at {blender}")
    blender = blender.resolve(strict=True)
    found = sha256_file(blender)
    if found != blender_sha256:
        raise InspectError(f"{blender} has SHA-256 {found}, pinned {blender_sha256}")
    item = {
        "input_id": source_pin.input_id,
        "assets3d_path": source_pin.assets3d_path,
        "sha256": source_pin.sha256,
    }
    source = pinned_assets3d_file(item, assets_root, store)
    if source.stat().st_size != source_pin.size_bytes:
        raise InspectError(f"{source} has {source.stat().st_size} bytes, pinned {source_pin}")
    origin = "assets3d" if source == assets_root / source_pin.assets3d_path else "store"
    return Plan(
        blender=blender,
        blender_sha256=found,
        script_sha256=sha256_file(SCRIPT),
        source=source,
        source_origin=origin,
        run_dir=run_dir,
        command=blender_command(blender, SCRIPT, run_dir),
        source_pin=source_pin,
    )


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
    """The file's SHA-256; None when it is absent; the read error when it cannot be read, so a
    refusal record is still written."""
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError as error:
        return f"unreadable: {error}"


def _launch_problems(plan: Plan) -> list[str]:
    """The executable and the Blender side re-hashed just before launch: what runs is what the
    plan pinned."""
    checks = (
        ("the Blender executable", plan.blender, plan.blender_sha256),
        ("the Blender side", SCRIPT, plan.script_sha256),
    )
    return [
        f"{what} {path} is {found}, planned {pinned}"
        for what, path, pinned in checks
        if (found := _hash_if_file(path)) != pinned
    ]


def _write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    (run_dir / RECORD_NAME).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _base_record(plan: Plan, hashes: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "schema": RECORD_SCHEMA,
        "kind": "inspect",
        "label": LABEL,
        "blender": {
            "executable": str(plan.blender),
            "sha256": plan.blender_sha256,
            "steam_build": low_host.BLENDER_STEAM_BUILD,
            "command": list(plan.command),
        },
        "script": _script_json(plan.script_sha256),
        "source": {**plan.source_pin.as_json(), "resolved_from": plan.source_origin, **hashes},
    }


def _run(plan: Plan, runner: Runner, hashes: dict[str, str | None]) -> dict[str, Any]:
    """Copy, run Blender once and check what it wrote; `hashes` is filled as it goes, and the
    after-run hashes are taken even when Blender fails or times out."""
    pin = plan.source_pin
    copy = plan.run_dir / side.SOURCE_BLEND_NAME
    hashes["original_sha256_before"] = sha256_file(plan.source)
    if hashes["original_sha256_before"] != pin.sha256:
        raise InspectError(f"{plan.source} differs from its pin {pin.sha256} before the run")
    shutil.copyfile(plan.source, copy)
    hashes["copy_sha256_before"] = sha256_file(copy)
    if hashes["copy_sha256_before"] != pin.sha256:
        raise InspectError(f"the private copy {copy} differs from its pin {pin.sha256}")
    os.chmod(copy, stat.S_IREAD)
    changed = _launch_problems(plan)
    if changed:
        raise InspectError("; ".join(changed))
    env = {**os.environ, **{name: str(plan.run_dir) for name in low_host.TEMP_VARIABLES}}
    log = plan.run_dir / LOG_NAME
    try:
        code = runner(plan.command, plan.run_dir, env, log, TIMEOUT_S)
    finally:
        hashes["copy_sha256_after"] = _hash_if_file(copy)
        hashes["original_sha256_after"] = _hash_if_file(plan.source)
    broken = [
        f"{what} is {hashes[key]}, pinned {pin.sha256}"
        for key, what in (
            ("copy_sha256_after", f"after the run the private copy {copy}"),
            ("original_sha256_after", f"after the run the source {plan.source}"),
        )
        if hashes[key] != pin.sha256
    ]
    if broken:
        raise InspectError("; ".join(broken))
    if code != 0:
        raise InspectError(f"Blender exited {code}; see {log}")
    present = {path.name for path in plan.run_dir.iterdir()}
    if present != OUTPUTS:
        raise InspectError(
            f"{plan.run_dir}: unexpected {sorted(present - OUTPUTS)}, "
            f"missing {sorted(OUTPUTS - present)}"
        )
    report_path = plan.run_dir / side.REPORT_NAME
    try:
        report = json.loads(report_path.read_bytes())
    except ValueError as error:
        raise InspectError(f"{report_path} is not JSON ({error})") from error
    problems = report_problems(report, copy)
    if problems:
        raise InspectError("; ".join(problems))
    report_file = {"file": side.REPORT_NAME, **_identity(report_path)}
    return {
        **_base_record(plan, hashes),
        "status": "inspected",
        "build": report["blender"],
        "report": report_file,
        "public": public_summary(report, hashes, report_file),
    }


def _identity(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def run_inspect(plan: Plan, runner: Runner = run_blender) -> dict[str, Any]:
    """The inspection; any failure once the run directory exists leaves a `refused` record with
    the source and copy hashes taken so far, then is raised."""
    ensure_outside_repository(plan.run_dir)  # again: a Plan can be built without plan_inspect
    plan.run_dir.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str | None] = dict.fromkeys(HASH_KEYS)
    try:
        record = _run(plan, runner, hashes)
    except BaseException as error:
        if hashes["original_sha256_after"] is None:
            hashes["original_sha256_after"] = _hash_if_file(plan.source)
        if hashes["copy_sha256_after"] is None:
            hashes["copy_sha256_after"] = _hash_if_file(plan.run_dir / side.SOURCE_BLEND_NAME)
        refused = {
            **_base_record(plan, hashes),
            "status": "refused",
            "error": f"{type(error).__name__}: {error}",
            "files": sorted(path.name for path in plan.run_dir.iterdir()),
        }
        _write_record(plan.run_dir, refused)
        raise
    _write_record(plan.run_dir, record)
    return record


def report_problems(report: Any, copy: Path) -> list[str]:
    """The Blender side's report against the pins: who wrote it, on which file, about what."""
    try:
        checks: list[tuple[str, Any, Any]] = [
            ("inspector", report["inspector"], side.INSPECTOR),
            ("mode", report["mode"], "inspect"),
            ("depsgraph mode", report["depsgraph_mode"], DEPSGRAPH_MODE),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(report["blend"]).resolve(), copy.resolve()),
            ("objects", sorted(report["objects"]), sorted(side.OBJECTS)),
            ("images", sorted(report["images"]), [side.NORMAL_IMAGE]),
            ("lookups", sorted(report["lookups"]), sorted(side.CANDIDATE_NAMES)),
        ]
        problems = [
            f"report {what} is {found!r}, pinned {pinned!r}"
            for what, found, pinned in checks
            if found != pinned
        ]
        for name in side.OBJECTS:
            entry = report["objects"].get(name, {})
            if entry.get("name") != name or not isinstance(entry.get("present"), bool):
                problems.append(f"report object {name!r} is not an entry for that name")
            elif entry["present"] and entry.get("type") == "MESH":
                for part in ("authored", "evaluated"):
                    if not isinstance(entry.get(part, {}).get("counts"), dict):
                        problems.append(f"report object {name!r} has no {part} counts")
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    return problems


LINING_COUNTS = (
    "count",
    "finite",
    "distinct",
    "below",
    "at",
    "above",
    "crossings_mesh_edges",
    "crossings_triangle_edges",
)


def _lining_counts(found: Any) -> dict[str, Any]:
    if found is None:
        return {"present": False}
    values = found.get("values")
    counts = {"present": True, "size": found["size"], "read": values is not None}
    if values is not None:
        counts.update({key: values[key] for key in LINING_COUNTS})
    return counts


def _object_counts(entry: Mapping[str, Any]) -> dict[str, Any]:
    if not entry["present"]:
        return {"present": False}
    counts: dict[str, Any] = {
        "present": True,
        "modifiers": len(entry["modifiers"]),
        "constraints": len(entry["constraints"]),
        "material_slots": len(entry["materials"]["slots"]),
    }
    if entry.get("type") != "MESH":
        return counts
    counts["shape_keys"] = len((entry["shape_keys"] or {}).get("blocks", []))
    counts["vertex_groups"] = len(entry["vertex_groups"])
    for part in ("authored", "evaluated"):
        mesh = entry[part]
        counts[part] = {
            **mesh["counts"],
            "uv_layers": len(mesh["uv"]["names"]),
            "attributes": len(mesh["attributes"]),
            "material_indices_used": len(mesh["material_indices"]),
            "lining": _lining_counts(mesh["lining"]),
        }
    return counts


def public_summary(
    report: Mapping[str, Any], hashes: Mapping[str, str | None], report_file: Mapping[str, Any]
) -> dict[str, Any]:
    """What may be quoted publicly: hashes and counts (and whether a hash equals its pin), under
    fixed role labels; no name, path, domain, colour space or value."""
    normal = report["images"][side.NORMAL_IMAGE]
    packed = None if normal is None else normal["packed"]
    return {
        "source_sha256": dict(hashes),
        "report": {key: report_file[key] for key in ("sha256", "size_bytes")},
        "objects": {role: _object_counts(report["objects"][name]) for role, name in ROLES.items()},
        "normal": {
            "present": normal is not None,
            "packed": packed is not None,
            "sha256": None if packed is None else packed["sha256"],
            "sha1": None if packed is None else packed["sha1"],
            "size_bytes": None if packed is None else packed["size_bytes"],
            "sha256_equals_pin": packed is not None and packed["sha256"] == NORMAL_SHA256,
        },
        "lookups": {
            role: {
                "data_blocks": len(report["lookups"][name]["data_blocks"]),
                "on_objects": len(report["lookups"][name]["on_objects"]),
            }
            for role, name in CANDIDATE_ROLES.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.tunic_intermediates",
        description="Inspect the Tunic v10 preserved .blend for the current round (decision 300).",
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    inspect = modes.add_parser("inspect", help="the bounded mesh and Normal inspection")
    inspect.add_argument("--blender", type=Path, required=True, help="the pinned blender.exe")
    inspect.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    inspect.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    inspect.add_argument("--store", type=Path, help="private store root (default: located)")
    inspect.add_argument("--dry-run", action="store_true", help="check pins, print the plan")
    args = parser.parse_args(argv)
    try:
        store = OracleStore.open(args.store) if args.store is not None else locate()
        plan = plan_inspect(args.blender, args.run, args.assets_root, store)
        if args.dry_run:
            print(json.dumps(plan.as_json(), indent=2))
            return 0
        record = run_inspect(plan)
    except (
        InspectError,
        RecorderError,
        StoreError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"tunic_intermediates: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"run": plan.run_dir.name, **record["public"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
