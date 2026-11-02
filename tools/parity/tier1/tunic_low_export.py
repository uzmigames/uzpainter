r"""The Tunic v10 current round's low OBJ/MTL, `low.npz` and `highnormal.npy` (decision 300 s. 7).

    python -m tools.parity.tier1.tunic_low_export --blender <blender.exe> --assets-root <Assets3D>
        [--run NAME] [--expect <earlier run>\export-record.json] [--store DIR] [--dry-run]

Preparation for `phase2/tier1/tunic-v10-current` (contract:
`docs/analysis/tunic-v10-current-round/01-input-contract.md`, "Meshes" and "Generator
intermediates"). It is not a baseline approval (decision 300 item 8), and it bakes no AO: the AO
plan comes separately, after this extraction. Every product is a current-round input made now
from the preserved `.blend`, never the lost `normalized_low.obj` or the historical intermediates.

1. **Pins and run directory.** Front N's (`sash_low_export`) and front U2's
   (`tunic_intermediates`): the Blender executable by SHA-256, the preserved
   `18-Tunica-v10.blend` (`tunic_intermediates.SOURCE`) from Assets3D when the file there matches,
   else from the private store's blob, and a fresh `<oracle work>/<run>` (refused inside the
   repository) with Blender's temporary folders pointed into it.
2. **Private copy and hashes.** The source is copied, hash-checked and made read-only; Blender
   opens the copy and never saves. The original, the copy, the Blender executable and both
   scripts are hashed before the launch and after Blender exits (`HASH_KEYS`), and the hashes go
   into the record on success and on failure alike: any failure once the run directory exists
   writes a `refused` record before it is raised.
3. **Blender, once.** `tunic_low_blender.py export` (see that module): one evaluated low feeds the
   OBJ/MTL and the arrays; the source slot `DefaultMaterial.001` is pinned and only the exported
   copy gets a new material `DefaultMaterial` (`REMAP`, an authored name remap, not the recovered
   historical material).
4. **Checks.** The files present, the report against every pin (`report_problems`), the arrays
   against the contract (`array_problems`: keys, dtype, shape, finite values, `lt` indexes `lv`,
   `lv` indexes `co` and `lining`, one `uv` and `cn` row per loop; the donor's normal arithmetic
   redone bit for bit; the lining's crossings), the Normal's array, and the OBJ against `low.npz`
   corner by corner under `CONVENTIONS`, fixed here before any run (`obj_problems`), and the MTL.
5. **Products.** `low.npz` is packed on the host from the arrays Blender wrote, in the donor's
   member order with fixed zip metadata (front P's `npz_bytes`), so equal arrays give equal
   bytes. `highnormal.npy` is Blender's own `np.save` of the donor's decode.
6. **Record.** `export-record.json` in the run directory. With `--expect`, the run must
   reproduce an earlier record's pins, conventions, digests and every output byte for byte
   (r1 against r1-repeat); the comparison is part of the record and a difference exits 1.

`--dry-run` checks the pins and prints the plan, its conventions and its command line; it holds
local paths, so it is not public. It writes nothing and does not start Blender. The outputs
derive from a git-ignored Assets3D file, so they stay private: they reach the store as inputs
when the current round's request is written, not here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.recorder.job import pinned_assets3d_file, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.recorder.tunic import NORMAL, TUNIC_BLEND
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import sash_low_blender, tunic_intermediates_blender
from tools.parity.tier1 import sash_low_export as low_host
from tools.parity.tier1 import tunic_low_blender as side
from tools.parity.tier1.sash_intermediates import npz_bytes
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.tunic_intermediates import SOURCE
from tools.parity.tier1.tunic_low_blender import ExportError

RECORD_SCHEMA = "uzpainter/parity/tunic-low-export-record/1"
RECORD_NAME = "export-record.json"
LOG_NAME = "blender.log"
DEFAULT_RUN = "phase2__tier1__tunic-v10-current__low-r1"
TIMEOUT_S = 900
LABEL = (
    "current-round input made from the preserved .blend: low OBJ/MTL, low.npz and "
    "highnormal.npy; not the lost normalized_low.obj and not a baseline approval"
)
LOW_NPZ = "low.npz"
SCRIPT = Path(side.__file__).resolve()
HOST = Path(__file__).resolve()
OUTPUTS = frozenset(
    {
        side.SOURCE_BLEND_NAME,
        LOG_NAME,
        side.OBJ_NAME,
        side.MTL_NAME,
        side.REPORT_NAME,
        side.RAW_NORMALS,
        side.HIGHNORMAL,
        *side.LOW_FILES.values(),
    }
)
# The files a record names: what Blender wrote (but the copy and the log) and the packed npz.
RECORD_OUTPUTS = (OUTPUTS - {side.SOURCE_BLEND_NAME, LOG_NAME}) | {LOW_NPZ}
# The report names the run directory (the opened file), so a repeat compares its digests, not
# its bytes.
RUN_SPECIFIC = frozenset({side.REPORT_NAME})
HASH_KEYS = (
    "original_sha256_before",
    "copy_sha256_before",
    "blender_sha256_before",
    "blender_side_sha256_before",
    "host_sha256_before",
    "copy_sha256_after",
    "original_sha256_after",
    "blender_sha256_after",
    "blender_side_sha256_after",
    "host_sha256_after",
)
# Fixed before any run. The OBJ is compared with low.npz on every vertex and every face corner;
# indices exactly, numbers within the printed precision: half a unit in the last printed place
# plus front N's float32 margin (`sash_low_export`), never widened to make a run pass.
CONVENTIONS: dict[str, Any] = {
    "axes": "OBJ (x, y, z) = Blender (x, z, -y): forward -Z, up Y; no other transform",
    "positions": {"decimals": 6, "tolerance": low_host.COORDINATE_TOLERANCE, "against": "co"},
    "uv": {"decimals": 6, "tolerance": low_host.COORDINATE_TOLERANCE, "against": "uv[lt]"},
    "normals": {"decimals": 4, "tolerance": low_host.NORMAL_TOLERANCE, "against": "cn[lt]"},
    "faces": "face k is loop triangle k; corner c names vertex lv[lt[k, c]] + 1, exactly",
    "evaluated": "the export object's evaluated mesh equals the extracted one bit for bit",
    "donor_normals": "cn equals the donor's arithmetic on evaluated.cn bit for bit",
}
HIGHNORMAL_SHAPE = (side.NORMAL_PNG["height"], side.NORMAL_PNG["width"], 3)
DONOR = {"path": side.DONOR_PATH, "blob_sha256": side.DONOR_BLOB_SHA256}


@dataclass(frozen=True)
class Plan:
    blender: Path
    blender_sha256: str
    script_sha256: str
    host_sha256: str
    source: Path
    source_origin: str  # "assets3d" or "store"
    run_dir: Path
    command: tuple[str, ...]
    source_pin: SourcePin = SOURCE

    def as_json(self) -> dict[str, Any]:
        return {
            "mode": "export",
            "blender": {"executable": str(self.blender), "sha256": self.blender_sha256},
            "script": _script_json(self.script_sha256, self.host_sha256),
            "source": {
                **self.source_pin.as_json(),
                "resolved_from": self.source_origin,
                "path": str(self.source),
            },
            "run_dir": str(self.run_dir),
            "command": list(self.command),
            "environment": {name: str(self.run_dir) for name in low_host.TEMP_VARIABLES},
            "timeout_s": TIMEOUT_S,
            "options": side.OBJ_EXPORT_OPTIONS,
            "conventions": CONVENTIONS,
            "remap": side.REMAP,
        }


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


def _script_json(script_sha256: str, host_sha256: str) -> dict[str, Any]:
    return {
        "blender_side": SCRIPT.relative_to(REPO_ROOT).as_posix(),
        "blender_side_sha256": script_sha256,
        "host": HOST.relative_to(REPO_ROOT).as_posix(),
        "host_sha256": host_sha256,
        "donor": {"assets3d_path": side.DONOR_PATH, "blob_sha256": side.DONOR_BLOB_SHA256},
        "precedent": side.PRECEDENT,
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
        "export",
        str(run_dir),
    )


def pin_problems() -> list[str]:
    """The Blender side's literal pins against the recorder's, U2's and front N's."""
    checks: list[tuple[str, Any, Any]] = [
        ("source name", side.SOURCE_BLEND_NAME, Path(TUNIC_BLEND).name),
        ("source pin", SOURCE.assets3d_path, TUNIC_BLEND),
        ("Normal", (side.NORMAL_IMAGE, side.NORMAL_SHA256), NORMAL),
        ("low object", side.SOURCE_OBJECT, tunic_intermediates_blender.LOW_OBJECT),
        ("lining attribute", side.LINING_ATTRIBUTE, tunic_intermediates_blender.LINING_ATTRIBUTE),
        ("donor", side.DONOR_BLOB_SHA256, tunic_intermediates_blender.DONOR_BLOB_SHA256),
        ("OBJ options", side.OBJ_EXPORT_OPTIONS, sash_low_blender.OBJ_EXPORT_OPTIONS),
        ("axes", (side.FORWARD_AXIS, side.UP_AXIS), ("NEGATIVE_Z", "Y")),
    ]
    return [f"the Blender side's {what} differs from its pin" for what, a, b in checks if a != b]


def plan_export(
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
    problems = pin_problems()
    if Path(source_pin.assets3d_path).name != side.SOURCE_BLEND_NAME:
        problems.append("the Blender side's source name differs from the pinned file's")
    if problems:
        raise ExportError("; ".join(problems))
    if not low_host.RUN_NAME.fullmatch(run):
        raise ExportError(f"run name {run!r} must match {low_host.RUN_NAME.pattern}")
    run_dir = ensure_outside_repository((work if work is not None else work_root()) / run)
    if run_dir.exists():
        raise ExportError(f"{run_dir} already exists; every run gets a fresh directory")
    if not blender.is_file():
        raise ExportError(f"no Blender executable at {blender}")
    blender = blender.resolve(strict=True)
    found = sha256_file(blender)
    if found != blender_sha256:
        raise ExportError(f"{blender} has SHA-256 {found}, pinned {blender_sha256}")
    item = {
        "input_id": source_pin.input_id,
        "assets3d_path": source_pin.assets3d_path,
        "sha256": source_pin.sha256,
    }
    source = pinned_assets3d_file(item, assets_root, store)
    if source.stat().st_size != source_pin.size_bytes:
        raise ExportError(f"{source} has {source.stat().st_size} bytes, pinned {source_pin}")
    origin = "assets3d" if source == assets_root / source_pin.assets3d_path else "store"
    return Plan(
        blender=blender,
        blender_sha256=found,
        script_sha256=sha256_file(SCRIPT),
        host_sha256=sha256_file(HOST),
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


def _pinned_files(plan: Plan) -> tuple[tuple[str, Path, str], ...]:
    """(hash key stem, file, pinned SHA-256) of every file the run hashes before and after."""
    pin = plan.source_pin.sha256
    return (
        ("original", plan.source, pin),
        ("copy", plan.run_dir / side.SOURCE_BLEND_NAME, pin),
        ("blender", plan.blender, plan.blender_sha256),
        ("blender_side", SCRIPT, plan.script_sha256),
        ("host", HOST, plan.host_sha256),
    )


def _hash_all(
    plan: Plan, hashes: dict[str, str | None], when: str, stems: Sequence[str] | None = None
) -> list[str]:
    """Hash the pinned files (all, or those `stems`) into `hashes[<stem>_sha256_<when>]`; the
    ones that differ from their pin."""
    problems = []
    for stem, path, pinned in _pinned_files(plan):
        if stems is not None and stem not in stems:
            continue
        key = f"{stem}_sha256_{when}"
        hashes[key] = found = _hash_if_file(path)
        if found != pinned:
            problems.append(f"{when} the run {stem} {path} is {found}, pinned {pinned}")
    return problems


def _base_record(plan: Plan, hashes: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "schema": RECORD_SCHEMA,
        "kind": "export",
        "label": LABEL,
        "blender": {
            "executable": str(plan.blender),
            "sha256": plan.blender_sha256,
            "steam_build": low_host.BLENDER_STEAM_BUILD,
            "command": list(plan.command),
        },
        "script": _script_json(plan.script_sha256, plan.host_sha256),
        "source": {**plan.source_pin.as_json(), "resolved_from": plan.source_origin},
        "hashes": dict(hashes),
        "host": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "packing": "low.npz: zipfile stored members <name>.npy, dated 1980-01-01",
        },
        "options": side.OBJ_EXPORT_OPTIONS,
        "conventions": CONVENTIONS,
        "remap": side.REMAP,
    }


def _write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    (run_dir / RECORD_NAME).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_export(
    plan: Plan,
    runner: Runner = run_blender,
    expected: Mapping[str, Any] | None = None,
    *,
    vertices: int = side.VERTICES,
    triangles: int = side.TRIANGLES,
    normal_shape: tuple[int, int, int] = HIGHNORMAL_SHAPE,
) -> dict[str, Any]:
    """The export; any failure once the run directory exists leaves a `refused` record with the
    hashes taken so far (the after-run ones taken even then), then is raised."""
    ensure_outside_repository(plan.run_dir)  # again: a Plan can be built without plan_export
    plan.run_dir.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str | None] = dict.fromkeys(HASH_KEYS)
    try:
        record = _run(plan, runner, hashes, (vertices, triangles), normal_shape)
        if expected is not None:
            problems = compare_records(record, expected)
            record["expect"] = {"reproduced": not problems, "problems": problems}
    except BaseException as error:
        if hashes["copy_sha256_after"] is None:
            _hash_all(plan, hashes, "after")
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


def _run(
    plan: Plan,
    runner: Runner,
    hashes: dict[str, str | None],
    counts: tuple[int, int],
    normal_shape: tuple[int, int, int],
) -> dict[str, Any]:
    pin = plan.source_pin
    copy = plan.run_dir / side.SOURCE_BLEND_NAME
    # Every before-hash but the copy's is taken first, so an early refusal still records them.
    changed = _hash_all(plan, hashes, "before", ("original", "blender", "blender_side", "host"))
    if hashes["original_sha256_before"] != pin.sha256:
        raise ExportError(f"{plan.source} differs from its pin {pin.sha256} before the run")
    if changed:
        raise ExportError("; ".join(changed))
    shutil.copyfile(plan.source, copy)
    changed = _hash_all(plan, hashes, "before", ("copy",))
    if changed:
        raise ExportError("; ".join(changed))
    os.chmod(copy, stat.S_IREAD)
    env = {**os.environ, **{name: str(plan.run_dir) for name in low_host.TEMP_VARIABLES}}
    log = plan.run_dir / LOG_NAME
    try:
        code = runner(plan.command, plan.run_dir, env, log, TIMEOUT_S)
    finally:
        broken = _hash_all(plan, hashes, "after")
    if broken:
        raise ExportError("; ".join(broken))
    if code != 0:
        raise ExportError(f"Blender exited {code}; see {log}")
    present = {path.name for path in plan.run_dir.iterdir()}
    if present != OUTPUTS:
        raise ExportError(
            f"{plan.run_dir}: unexpected {sorted(present - OUTPUTS)}, "
            f"missing {sorted(OUTPUTS - present)}"
        )
    report_path = plan.run_dir / side.REPORT_NAME
    try:
        report = json.loads(report_path.read_bytes())
    except ValueError as error:
        raise ExportError(f"{report_path} is not JSON ({error})") from error
    problems = report_problems(report, copy)
    if problems:
        raise ExportError("; ".join(problems))
    arrays, raw = load_arrays(plan.run_dir)
    evaluated_cn = _load(plan.run_dir / side.RAW_NORMALS, "<f4", (3,))
    normal = _load(plan.run_dir / side.HIGHNORMAL, "<f4", normal_shape[1:])
    problems = array_problems(arrays, evaluated_cn, *counts)
    problems += normal_array_problems(normal, normal_shape)
    digests = {
        **{name: side.array_digest(a) for name, a in arrays.items()},
        "evaluated_cn": side.array_digest(evaluated_cn),
        "highnormal": side.array_digest(normal),
    }
    if digests != report["digests"]:
        problems.append("the arrays on disk differ from the report's digests")
    if problems:
        raise ExportError("; ".join(problems))
    problems = readback_problems(report["export"]["readback_digests"], arrays, evaluated_cn)
    obj_text = (plan.run_dir / side.OBJ_NAME).read_text(encoding="utf-8")
    deviation: dict[str, float] = {}
    problems += obj_problems(obj_text, arrays, deviation)
    problems += mtl_problems((plan.run_dir / side.MTL_NAME).read_text(encoding="utf-8"))
    if problems:
        raise ExportError("; ".join(problems))
    (plan.run_dir / LOW_NPZ).write_bytes(npz_bytes([(name, raw[name]) for name in side.LOW_ARRAYS]))
    return {
        **_base_record(plan, hashes),
        "status": "exported",
        "build": report["blender"],
        "selection": report["source"],
        "export": report["export"],
        "mesh": {**report["mesh"], "digests": digests},
        "lining": report["lining"],
        "normal": {
            **report["normal"],
            "array": {
                "dtype": normal.dtype.str,
                "shape": list(normal.shape),
                "min": float(normal.min()),
                "max": float(normal.max()),
            },
        },
        "obj_deviation": deviation,
        "outputs": {
            name: {
                "sha256": sha256_file(plan.run_dir / name),
                "size_bytes": (plan.run_dir / name).stat().st_size,
            }
            for name in sorted(RECORD_OUTPUTS)
        },
    }


def report_problems(report: Any, copy: Path) -> list[str]:
    """The Blender side's report against every pin: who wrote it, on which file, about what."""
    try:
        source, export, normal = report["source"], report["export"], report["normal"]
        checks: list[tuple[str, Any, Any]] = [
            ("exporter", report["exporter"], side.EXPORTER),
            ("mode", report["mode"], "export"),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(report["blend"]).resolve(), copy.resolve()),
            ("depsgraph mode", report["depsgraph_mode"], side.DEPSGRAPH_MODE),
            ("donor", report["donor"], DONOR),
            ("object", source["object"], side.SOURCE_OBJECT),
            ("source materials", source["materials"], list(side.SOURCE_MATERIALS)),
            ("modifiers", source["modifiers"], [list(m) for m in side.SOURCE_MODIFIERS]),
            ("identity", source["matrix_is_identity"], True),
            ("identity matrix", side.is_identity(source["matrix_world"]), True),
            ("uv layers", source["uv_layers"], list(side.UV_LAYERS)),
            ("remap", report["remap"], side.REMAP),
            ("export object", export["object"], side.EXPORT_OBJECT),
            ("export material", export["material"], side.TEXTURE_SET),
            ("obj", export["obj"], side.OBJ_NAME),
            ("mtl", export["mtl"], side.MTL_NAME),
            ("options", export["options"], side.OBJ_EXPORT_OPTIONS),
            ("lining attribute", report["lining"]["attribute"], ["LiningMask", "POINT", "FLOAT"]),
            ("normal image", normal["image"], side.NORMAL_IMAGE),
            ("normal SHA-256", normal["packed"]["sha256"], side.NORMAL_SHA256),
            ("normal PNG", normal["packed"]["png"], side.NORMAL_PNG),
            ("normal settings", normal["settings"], side.NORMAL_SETTINGS),
            ("normal loaded", normal["loaded"], side.NORMAL_LOADED),
            ("normal after decode", normal["after_decode"]["settings"], side.NORMAL_SETTINGS),
            ("normal loaded after", normal["after_decode"]["loaded"], side.NORMAL_LOADED),
            ("normal decode", normal["decode"], side.NORMAL_DECODE),
        ]
        problems = [
            f"report {what} is {found!r}, pinned {pinned!r}"
            for what, found, pinned in checks
            if found != pinned
        ]
        if sorted(export["readback_digests"]) != sorted(READBACK):
            problems.append("the report's export readback does not cover co, lt, lv, uv and cn")
        if sorted(report["digests"]) != sorted([*side.LOW_ARRAYS, "evaluated_cn", "highnormal"]):
            problems.append("the report's digests do not name exactly the written arrays")
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    return problems


# The export readback's buffers, flat as `foreach_get` fills them, from the arrays on disk.
READBACK: dict[str, Callable[[Mapping[str, Any], Any], Any]] = {
    "co": lambda arrays, raw_cn: arrays["co"].ravel(),  # the identity matrix: world = object
    "lt": lambda arrays, raw_cn: arrays["lt"].ravel(),
    "lv": lambda arrays, raw_cn: arrays["lv"],
    "uv": lambda arrays, raw_cn: arrays["uv"].ravel(),
    "cn": lambda arrays, raw_cn: raw_cn.ravel(),
}


def readback_problems(
    readback: Mapping[str, str], arrays: Mapping[str, Any], evaluated_cn: Any
) -> list[str]:
    """The export object's evaluated mesh, as the Blender side digested it just before the OBJ
    was written, is the extraction's: bit for bit, every buffer."""
    return [
        f"the export object's evaluated {name} differs from the extracted arrays"
        for name, flat in READBACK.items()
        if readback.get(name) != side.array_digest(flat(arrays, evaluated_cn))
    ]


def _load(path: Path, dtype: str, tail: tuple[int, ...]) -> Any:
    array = np.load(path, allow_pickle=False)
    if array.dtype.str != dtype or array.ndim != 1 + len(tail) or array.shape[1:] != tail:
        raise ExportError(
            f"{path.name} is {array.dtype.str}{list(array.shape)}, pinned {dtype}[n, *{list(tail)}]"
        )
    return array


def load_arrays(run_dir: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Every `low.npz` member Blender wrote, with its dtype and trailing shape checked, and its
    raw `.npy` bytes for the packing."""
    arrays: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name, (dtype, tail) in side.LOW_ARRAYS.items():
        path = run_dir / side.LOW_FILES[name]
        arrays[name] = _load(path, dtype, tail)
        raw[name] = path.read_bytes()
    return arrays, raw


def array_problems(
    arrays: Mapping[str, Any],
    evaluated_cn: Any,
    vertices: int = side.VERTICES,
    triangles: int = side.TRIANGLES,
) -> list[str]:
    """The contract's checks on `low.npz` before any generator reads it: finite values, the
    pinned counts, the cross-indexing, the donor's normal arithmetic and the lining."""
    co, lt, lv, uv, cn, lining = (arrays[name] for name in side.LOW_ARRAYS)
    problems = [
        f"{name} holds non-finite values"
        for name, array in (*arrays.items(), ("evaluated_cn", evaluated_cn))
        if array.dtype.kind == "f" and not np.isfinite(array).all()
    ]
    if (len(co), len(lt)) != (vertices, triangles):
        problems.append(f"{len(co)} vertices and {len(lt)} triangles, pinned {vertices}")
    if len(lining) != len(co):
        problems.append(f"{len(lining)} lining values for {len(co)} vertices")
    if len(uv) != len(lv) or len(cn) != len(lv) or len(evaluated_cn) != len(lv):
        problems.append(f"{len(lv)} loops, but {len(uv)} UVs and {len(cn)} corner normals")
    if lt.size and (lt.min() < 0 or lt.max() >= len(lv)):
        problems.append("a loop triangle names a loop out of range")
    if lv.size and (lv.min() < 0 or lv.max() >= len(co)):
        problems.append("a loop names a vertex out of range")
    if problems:
        return problems
    if not np.array_equal(lt, np.arange(3 * len(lt), dtype=np.int32).reshape(-1, 3)):
        problems.append("the loop triangles are not the polygons' loops in order")
    donor = side.donor_normals(evaluated_cn, np.eye(3))
    if not np.array_equal(donor.view(np.uint32), cn.view(np.uint32)):
        problems.append("cn is not the donor's arithmetic on the evaluated corner normals")
    problems += side.lining_problems(lining, len(co), lv[lt])
    return problems


def normal_array_problems(normal: Any, shape: tuple[int, int, int] = HIGHNORMAL_SHAPE) -> list[str]:
    if normal.shape != shape:
        return [f"highnormal.npy is {list(normal.shape)}, pinned {list(shape)}"]
    if not np.isfinite(normal).all():
        return ["highnormal.npy holds non-finite values"]
    return []


def parse_obj(text: str) -> tuple[dict[str, Any], list[str]]:
    """The OBJ's names, numbers and face corners, with every line it should not have."""
    lines = text.splitlines()
    major, minor = side.BLENDER_VERSION
    problems: list[str] = []
    if not lines or not lines[0].startswith(f"# Blender {major}.{minor}"):
        problems.append("the OBJ does not start with the pinned Blender's header")
    found: dict[str, Any] = {"o": [], "usemtl": [], "mtllib": [], "v": [], "vt": [], "vn": []}
    found["f"] = []
    sizes = {"v": 3, "vt": 2, "vn": 3}
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        try:
            if key in sizes:
                found[key].append(_floats(rest, sizes[key]))
            elif key == "f":
                found["f"].append([_corner(corner) for corner in rest.split()])
            elif key in ("o", "usemtl", "mtllib"):
                found[key].append(rest.strip())
            elif key != "s":
                problems.append(f"OBJ line {number}: unexpected {key!r}")
        except ValueError as error:
            problems.append(f"OBJ line {number}: {error}")
    return found, problems


def _floats(text: str, size: int) -> tuple[float, ...]:
    values = tuple(float(part) for part in text.split())
    if len(values) != size or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{text!r} is not {size} finite numbers")
    return values


def _corner(text: str) -> tuple[int, int, int]:
    parts = text.split("/")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"face corner {text!r} is not v/vt/vn")
    return int(parts[0]), int(parts[1]), int(parts[2])


def to_obj_axes(points: Any) -> Any:
    """Blender (Z up) to the OBJ's pinned axes (forward -Z, up Y): (x, y, z) -> (x, z, -y)."""
    values = np.asarray(points, np.float64)
    return np.stack([values[..., 0], values[..., 2], -values[..., 1]], axis=-1)


def obj_problems(text: str, arrays: Mapping[str, Any], deviation: dict[str, float]) -> list[str]:
    """The OBJ against `low.npz` under `CONVENTIONS`: every position, and per face corner its
    vertex, its UV and its normal; the largest deviations go into `deviation`."""
    found, problems = parse_obj(text)
    for key, pinned in (
        ("mtllib", side.MTL_NAME),
        ("o", side.EXPORT_OBJECT),
        ("usemtl", side.TEXTURE_SET),
    ):
        if found[key] != [pinned]:
            problems.append(f"OBJ {key} is {found[key]}, pinned [{pinned!r}]")
    co, lt, lv, uv, cn = (arrays[name] for name in ("co", "lt", "lv", "uv", "cn"))
    if len(found["v"]) != len(co):
        problems.append(f"OBJ has {len(found['v'])} vertices, low.npz {len(co)}")
    faces = found["f"]
    if len(faces) != len(lt) or any(len(face) != 3 for face in faces):
        problems.append(f"OBJ has {len(faces)} faces, not {len(lt)} triangles")
    if problems:
        return problems
    corners = np.asarray(faces, np.int64) - 1  # (faces, 3 corners, v/vt/vn)
    counts = (len(found["v"]), len(found["vt"]), len(found["vn"]))
    if corners.min() < 0 or any((corners[..., i] >= n).any() for i, n in enumerate(counts)):
        return ["an OBJ face names an index out of range"]
    wrong = np.flatnonzero((corners[..., 0] != lv[lt]).any(axis=1))
    if wrong.size:
        problems.append(f"{wrong.size} OBJ faces name other vertices, first face {wrong[0] + 1}")
    measured = {
        "positions": np.abs(np.asarray(found["v"], np.float64) - to_obj_axes(co)),
        "uv": np.abs(np.asarray(found["vt"], np.float64)[corners[..., 1]] - uv[lt]),
        "normals": np.abs(
            np.asarray(found["vn"], np.float64)[corners[..., 2]] - to_obj_axes(cn[lt])
        ),
    }
    for name, error in measured.items():
        deviation[name] = float(error.max(initial=0.0))
        over = int((error > CONVENTIONS[name]["tolerance"]).any(axis=-1).sum())
        if over:
            problems.append(
                f"{over} OBJ {name} entries differ from low.npz beyond "
                f"{CONVENTIONS[name]['tolerance']} (largest {deviation[name]:.3g})"
            )
    return problems


TEXTURE_KEYS = ("map_", "bump", "disp", "decal", "refl", "norm")


def mtl_problems(text: str) -> list[str]:
    """One material, `DefaultMaterial`, and no texture path."""
    lines = [line.strip() for line in text.splitlines()]
    problems: list[str] = []
    if not lines or not lines[0].startswith("# Blender"):
        problems.append("the MTL does not start with Blender's header")
    materials = [line.partition(" ")[2].strip() for line in lines if line.startswith("newmtl ")]
    if materials != [side.TEXTURE_SET]:
        problems.append(f"MTL materials are {materials}, pinned [{side.TEXTURE_SET!r}]")
    textures = [line for line in lines if line.lower().startswith(TEXTURE_KEYS)]
    if textures:
        problems.append(f"the MTL names textures: {textures}")
    return problems


# What a repeat must reproduce; `outputs` is compared for every file but the run-specific one.
REPEAT_FIELDS = (
    ("schema",),
    ("kind",),
    ("status",),
    ("blender", "sha256"),
    ("script",),
    ("source", "sha256"),
    ("options",),
    ("conventions",),
    ("remap",),
    ("selection",),
    ("mesh",),
    ("lining",),
    ("normal",),
    ("obj_deviation",),
    ("outputs",),
)


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """The pins, the facts and every output byte for byte, except the report, which names its
    run directory (its digests are compared through `mesh`)."""
    problems = []
    for path in REPEAT_FIELDS:
        found, wanted = _get(record, path), _get(expected, path)
        if path == ("outputs",):
            found, wanted = (
                {k: v for k, v in (d or {}).items() if k not in RUN_SPECIFIC}
                for d in (found, wanted)
            )
        if found is None or found != wanted:
            problems.append(f"{'.'.join(path)} is {found!r}, the earlier run's {wanted!r}")
    return problems


def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def load_expected(path: Path) -> dict[str, Any]:
    """An earlier record to reproduce: an exported one of this schema."""
    expected = json.loads(path.read_text(encoding="utf-8"))
    if (_get(expected, ("schema",)), _get(expected, ("status",))) != (RECORD_SCHEMA, "exported"):
        raise ExportError(f"{path} is not an exported {RECORD_SCHEMA} record")
    return dict(expected)


def summary(record: Mapping[str, Any], run: str) -> dict[str, Any]:
    """What the CLI prints: hashes, counts and the comparison, no path."""
    return {
        "run": run,
        "status": record["status"],
        "outputs": record["outputs"],
        "mesh": {k: record["mesh"][k] for k in ("vertices", "triangles", "loops")},
        "lining_crossings": record["lining"]["crossings_triangle_edges"],
        "obj_deviation": record["obj_deviation"],
        "expect": record.get("expect"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.tunic_low_export",
        description="Export the Tunic v10 low and its low.npz/highnormal.npy (decision 300).",
    )
    parser.add_argument("--blender", type=Path, required=True, help="the pinned blender.exe")
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's export-record.json")
    parser.add_argument("--store", type=Path, help="private store root (default: located)")
    parser.add_argument("--dry-run", action="store_true", help="check pins, print the plan")
    args = parser.parse_args(argv)
    try:
        expected = load_expected(args.expect) if args.expect is not None else None
        store = OracleStore.open(args.store) if args.store is not None else locate()
        plan = plan_export(args.blender, args.run, args.assets_root, store)
        if args.dry_run:
            print(json.dumps(plan.as_json(), indent=2))
            return 0
        record = run_export(plan, expected=expected)
    except (
        ExportError,
        RecorderError,
        StoreError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"tunic_low_export: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary(record, plan.run_dir.name), indent=2, sort_keys=True))
    problems = _get(record, ("expect", "problems")) or []
    for problem in problems:
        print(f"tunic_low_export: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
