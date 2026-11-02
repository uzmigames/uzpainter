r"""The Sash v5 mask-generator intermediates for the current round (decision 300 item 7, section 7).

    python -m tools.parity.tier1.sash_intermediates extract --blender <blender.exe>
        --assets-root <Assets3D> [--low-record <N's export-record.json>] [--run NAME]
        [--expect <earlier intermediates-record.json>] [--store DIR] [--dry-run]
    python -m tools.parity.tier1.sash_intermediates ao --blender <blender.exe>
        --assets-root <Assets3D> --extraction <extract run's intermediates-record.json>
        [--run NAME] [--expect <earlier record>] [--store DIR] [--dry-run]
    python -m tools.parity.tier1.sash_intermediates centre
        (--derive <extract run's record> | --authored X Y --provenance TEXT | --missing REASON)
        [--run NAME] [--expect <earlier record>]

The inputs of Assets3D `waist_masks.py sash` that `sashchain.sh` made and lost: `low.npz`,
`highnormal.npy`, `ao.npy` and the construction centre. Every product is a current-round
substitute, made now from preserved files, never the historical file; each record says so. They
derive from git-ignored Assets3D files, so they stay private. This is technical preparation,
not a baseline approval (decision 300 item 8).

1. **Host pattern and pins.** Front N's (`sash_low_export`): the Blender executable by SHA-256,
   the preserved `.blend` by SHA-256 and size, a fresh run directory under the oracle work root
   (refused inside the repository), Blender's temporary folders pointed into it, a read-only,
   hash-checked private copy that Blender opens and never saves, the copy's hash checked again
   after Blender exits, and the original's hash recorded before and after.
2. **extract** (Blender, then the host). `sash_intermediates_blender.py extract` reads the
   Authoring low with the donor's algorithm and refuses a missing `PartId`. The host then
   compares it, triangle corner by triangle corner, with front N's accepted Low-Game table
   (`low_problems`): the same vertex count and positions, the same triangle vertices, the same
   per-corner UVs (all bit for bit as float32). For the normals, `deliver.py`'s own Low-Game
   construction is replayed on the Authoring low in the same Blender run, and its read-back
   corner normals must equal Low-Game's bit for bit: no tolerance is assumed. The Authoring's own
   corner normals (what `low.npz` holds, as the donor wrote them) then differ from Low-Game's by
   that custom-normal conversion only; the difference is recorded, not gated. Any other
   difference refuses: there is no proximity transfer and no fallback.
   Only then is `low.npz` packed, from the arrays Blender wrote, with fixed zip metadata
   (`npz_bytes`). `highnormal.npy` is decoded on the host from the pinned bake Normal PNG at
   its native 16 bits (`normal_array`): each sample divided by 65535 in float32, RGB, rows
   bottom first as Blender's `image.pixels` holds them. The delivered material's Normal is
   Painter's final map and is never read.
3. **ao** (Blender). Requires an accepted extraction record. The Blender side re-reads the low
   and refuses the bake unless every array's digest equals the extraction's; it bakes the
   donor's AO with every option pinned (`CYCLES_SETTINGS`, `BAKE_OPTIONS`). The bake's
   determinism is a claim only after an r1-repeat with `--expect` reproduces `ao.npy` byte for
   byte.
4. **centre** (host only), separate and optional. Extraction and AO never depend on it.
   `--derive` proves the wrap's grid topology on the Authoring polygons and its angular
   correspondence with `low_gen.wrap_low`'s columns, intersects two non-parallel radial columns
   and checks every wrap vertex against the result within float32 storage bounds
   (`derive_centre`); `--authored` takes a centre with its provenance; `--missing` records that
   there is none. A derived centre is "derived from preserved geometry for the current round",
   never the historical `construction.npz`.

`--dry-run` checks the pins and prints the plan; it writes nothing and starts no Blender.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import sys
import zipfile
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.recorder.job import pinned_assets3d_file, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1 import sash_low_blender as low_side
from tools.parity.tier1 import sash_low_export as low_host
from tools.parity.tier1.sash_intermediates_blender import ExtractError
from tools.parity.tier1.sash_low_export import SourcePin

RECORD_SCHEMA = "uzpainter/parity/sash-intermediates-record/1"
RECORD_NAME = "intermediates-record.json"
LOG_NAME = "blender.log"
RUN_PREFIX = "phase2__tier1__sash-v5-current__"
DEFAULT_RUNS = {
    "extract": RUN_PREFIX + "intermediates-r1",
    "ao": RUN_PREFIX + "ao-r1",
    "centre": RUN_PREFIX + "centre-r1",
}
TIMEOUTS_S = {"extract": 600, "ao": 3600}
SCRIPT = Path(side.__file__).resolve()
SUBSTITUTE = "current-round substitute made from preserved files; not the lost sashchain.sh product"

# Front N's accepted Low-Game export (commit 3afbbfbf; r1 and r1-repeat byte-identical).
LOW_GAME_RECORD = low_host.DEFAULT_RUN + "/" + low_host.RECORD_NAME
LOW_GAME_OBJ_SHA256 = "646bba8546ad9dcd6475eb366fced896f35f592b088e1286d1a30ec957249944"
LOW_GAME_MTL_SHA256 = "2e9174ad995c854491ac0c4e02ccc58144fe62128ee64097c5268216a575c061"
LOW_GAME_TABLE_SHA256 = "ccd1ead367862a8befbba20009aa45af0e9a504faba7822d7e5617a0d6c5d62d"
NORMAL = SourcePin(
    input_id="sash-v5-normal-bake",
    assets3d_path=(
        "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/Textures/"
        "25-Faixa-Cintura_Normal_OpenGL_bake_v5.png"
    ),
    sha256="ec05be82d5c551926b81f2e443faf227d297b37b0fba6aed14da63b397d58276",
    size_bytes=11_167_163,
)
NORMAL_LAYOUT = (2048, 2048, 16, 2)  # width, height, bit depth, colour type 2 (RGB)
NORMAL_SCALE = 65535  # 16-bit samples to [0, 1]: v / 65535, as Blender loads a 16-bit PNG

LOW_NPZ = "low.npz"
HIGHNORMAL = "highnormal.npy"
CENTRE_NPZ = "construction-centre.npz"
LOW_FILES = {name: f"low.{name}.npy" for name in side.LOW_ARRAYS}
FACE_FILES = {name: f"authoring.{name}.npy" for name in side.FACE_ARRAYS}
EXTRACT_OUTPUTS = frozenset(
    {
        side.SOURCE_BLEND_NAME,
        LOG_NAME,
        side.EXTRACT_REPORT,
        *LOW_FILES.values(),
        *FACE_FILES.values(),
        side.REDELIVERED_NAME,
    }
)
# The files an extraction record names: what Blender wrote (but the copy and the log) and the two
# products the host made.
EXTRACT_RECORD_OUTPUTS = (EXTRACT_OUTPUTS - {side.SOURCE_BLEND_NAME, LOG_NAME}) | {
    LOW_NPZ,
    HIGHNORMAL,
}
AO_OUTPUTS = frozenset(
    {side.SOURCE_BLEND_NAME, LOG_NAME, side.AO_EXPECT, side.AO_REPORT, side.AO_NAME}
)
TRIANGLES = low_side.TRIANGLES

# The construction centre (`waist_masks.py sash` reads only `centre`, the waist centre in XY).
LOW_GEN_PATH = "Pipeline/retopology/waist-v5/low_gen.py"
LOW_GEN_SHA256 = "d1153afbbba9b8d6ac47118eb8b92aed1686d200eb2502f8df14a56ff5c80346"
WAIST_GEN_PATH = "Pipeline/retopology/waist-v5/waist_gen.py"
WAIST_GEN_SHA256 = "15cf7cb9831df33ad645b5bf9b26a2cdc49d9c104f93ecf12c26eae6cb37b746"
WRAP_PART = 1  # low_gen.wrap_low `part=1`; bakeprep.py copies it to PartId
WRAP_ROWS = 13  # sash_profile(low_rows=True): 8 outer + 2 lip + 3 inner rows
WRAP_UNIFORM_STEP = 360 / 90
WRAP_EXTRA_DEGREES = (0.0, 1.2, 3.0, 5.5, 8.5, 351.5, 354.5, 357.0, 358.8, 180.0, 105.0, 255.0)
CONDITION_LIMIT = 1.5  # of the two-column system; 0 and 88 degrees give 1.07
ARITHMETIC_MARGIN = 1e-12  # metres: float64 arithmetic in the generator and here


class CentreError(ExtractError):
    """The preserved geometry does not prove the centre; nothing is derived."""


@dataclass(frozen=True)
class Plan:
    mode: str
    blender: Path
    blender_sha256: str
    script_sha256: str
    source: Path
    source_origin: str  # "assets3d" or "store"
    run_dir: Path
    command: tuple[str, ...]
    source_pin: SourcePin = low_host.SOURCE

    def as_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "blender": {"executable": str(self.blender), "sha256": self.blender_sha256},
            "script": _script_json(self.script_sha256),
            "source": {**self.source_pin.as_json(), "resolved_from": self.source_origin},
            "run_dir": str(self.run_dir),
            "command": list(self.command),
            "environment": {name: str(self.run_dir) for name in low_host.TEMP_VARIABLES},
        }


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


def _script_json(script_sha256: str) -> dict[str, Any]:
    return {
        "blender_side": SCRIPT.relative_to(REPO_ROOT).as_posix(),
        "blender_side_sha256": script_sha256,
        "host": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
        "host_sha256": sha256_file(Path(__file__)),
        "donor": {"assets3d_path": side.DONOR_PATH, "sha256": side.DONOR_SHA256},
    }


def blender_command(blender: Path, script: Path, run_dir: Path, mode: str) -> tuple[str, ...]:
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
        mode,
        str(run_dir),
    )


def run_dir_for(run: str, work: Path | None) -> Path:
    if not low_host.RUN_NAME.fullmatch(run):
        raise ExtractError(f"run name {run!r} must match {low_host.RUN_NAME.pattern}")
    run_dir = ensure_outside_repository((work if work is not None else work_root()) / run)
    if run_dir.exists():
        raise ExtractError(f"{run_dir} already exists; every run gets a fresh directory")
    return run_dir


def plan_blender(
    mode: str,
    blender: Path,
    run: str,
    assets_root: Path,
    store: OracleStore | None,
    *,
    blender_sha256: str = low_host.BLENDER_SHA256,
    work: Path | None = None,
) -> Plan:
    """Check the Blender and source pins and fix the command; writes nothing."""
    if side.SOURCE_BLEND_NAME != low_side.SOURCE_BLEND_NAME:
        raise ExtractError("the two Blender sides disagree on the source's base name")
    run_dir = run_dir_for(run, work)
    if not blender.is_file():
        raise ExtractError(f"no Blender executable at {blender}")
    blender = blender.resolve(strict=True)
    found = sha256_file(blender)
    if found != blender_sha256:
        raise ExtractError(f"{blender} has SHA-256 {found}, pinned {blender_sha256}")
    pin = low_host.SOURCE
    source = _pinned_source(pin, assets_root, store)
    origin = "assets3d" if source == assets_root / pin.assets3d_path else "store"
    return Plan(
        mode=mode,
        blender=blender,
        blender_sha256=found,
        script_sha256=sha256_file(SCRIPT),
        source=source,
        source_origin=origin,
        run_dir=run_dir,
        command=blender_command(blender, SCRIPT, run_dir, mode),
    )


def _pinned_source(pin: SourcePin, assets_root: Path, store: OracleStore | None) -> Path:
    item = {"input_id": pin.input_id, "assets3d_path": pin.assets3d_path, "sha256": pin.sha256}
    source = pinned_assets3d_file(item, assets_root, store)
    if source.stat().st_size != pin.size_bytes:
        raise ExtractError(f"{source} has {source.stat().st_size} bytes, pinned {pin}")
    return source


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


def _blender_run(
    plan: Plan,
    runner: Runner,
    outputs: frozenset[str],
    before: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    """Copy, run Blender once, check the copy, the exit code and the files present."""
    ensure_outside_repository(plan.run_dir)
    pin = plan.source_pin
    original_before = sha256_file(plan.source)
    if original_before != pin.sha256:
        raise ExtractError(f"{plan.source} changed before the run (now {original_before})")
    plan.run_dir.mkdir(parents=True, exist_ok=False)
    copy = plan.run_dir / side.SOURCE_BLEND_NAME
    shutil.copyfile(plan.source, copy)
    copy_before = sha256_file(copy)
    if copy_before != pin.sha256:
        raise ExtractError(f"the private copy {copy} differs from its pin {pin.sha256}")
    os.chmod(copy, stat.S_IREAD)
    before()
    env = {**os.environ, **{name: str(plan.run_dir) for name in low_host.TEMP_VARIABLES}}
    log = plan.run_dir / LOG_NAME

    def integrity() -> tuple[str, str, list[str]]:
        copy_after, original_after = sha256_file(copy), sha256_file(plan.source)
        problems = []
        if copy_after != pin.sha256:
            problems.append(f"Blender changed the private copy {copy} (now {copy_after})")
        if original_after != pin.sha256:
            problems.append(f"the source {plan.source} changed during the run")
        return copy_after, original_after, problems

    try:
        code = runner(plan.command, plan.run_dir, env, log, TIMEOUTS_S[plan.mode])
    except BaseException as error:
        # A timeout or any other failure still gets the after-run hashes.
        broken = integrity()[2]
        if broken:
            raise ExtractError("; ".join(broken) + f" (after {error!r})") from error
        raise
    copy_after, original_after, broken = integrity()
    if broken:
        raise ExtractError("; ".join(broken))
    if code != 0:
        raise ExtractError(f"Blender exited {code}; see {log}")
    present = {path.name for path in plan.run_dir.iterdir()}
    if present != outputs:
        raise ExtractError(
            f"{plan.run_dir}: unexpected {sorted(present - outputs)}, "
            f"missing {sorted(outputs - present)}"
        )
    return {
        **pin.as_json(),
        "resolved_from": plan.source_origin,
        "original_sha256_before": original_before,
        "original_sha256_after": original_after,
        "copy_sha256_before": copy_before,
        "copy_sha256_after": copy_after,
    }


def _blender_json(plan: Plan, build: Any) -> dict[str, Any]:
    return {
        "executable": str(plan.blender),
        "sha256": plan.blender_sha256,
        "steam_build": low_host.BLENDER_STEAM_BUILD,
        "command": list(plan.command),
        "build": build,
    }


# ------------------------------------------------------------------------- Low-Game reference
def load_low_game(
    record_path: Path,
    *,
    obj_sha256: str = LOW_GAME_OBJ_SHA256,
    mtl_sha256: str = LOW_GAME_MTL_SHA256,
    table_sha256: str = LOW_GAME_TABLE_SHA256,
) -> tuple[dict[str, Any], low_side.TriangleTable]:
    """Front N's accepted record and the table next to it, every pin checked."""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    checks = [
        ("schema", _get(record, ("schema",)), low_host.RECORD_SCHEMA),
        ("source", _get(record, ("source", "sha256")), low_host.SOURCE.sha256),
        ("obj", _get(record, ("outputs", "obj", "sha256")), obj_sha256),
        ("mtl", _get(record, ("outputs", "mtl", "sha256")), mtl_sha256),
        ("table", _get(record, ("outputs", "table", "sha256")), table_sha256),
    ]
    problems = [
        f"{what} is {found!r}, pinned {pin!r}" for what, found, pin in checks if found != pin
    ]
    if problems:
        raise ExtractError(f"{record_path}: " + "; ".join(problems))
    table_path = record_path.parent / low_side.TABLE_NAME
    data = table_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != table_sha256:
        raise ExtractError(f"{table_path} does not hash to the pinned {table_sha256}")
    table, _ = low_side.table_from_document(json.loads(data))
    if low_side.table_digests(table) != _get(record, ("mesh", "digests")):
        raise ExtractError(f"{table_path}: its digests differ from its record's")
    return record, table


# ------------------------------------------------------------------------------- extraction
def load_arrays(run_dir: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Every array the Blender side wrote, with its dtype and trailing shape checked."""
    arrays: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for pins, files in ((side.LOW_ARRAYS, LOW_FILES), (side.FACE_ARRAYS, FACE_FILES)):
        for name, (dtype, tail) in pins.items():
            data = (run_dir / files[name]).read_bytes()
            array = np.load(io.BytesIO(data), allow_pickle=False)
            if array.dtype.str != dtype or array.shape[1:] != tail or array.ndim != 1 + len(tail):
                raise ExtractError(
                    f"{files[name]} is {array.dtype.str}{list(array.shape)}, pinned {dtype}"
                    f"[n, {', '.join(map(str, tail))}]"
                )
            arrays[name], raw[name] = array, data
    return arrays, raw


def load_redelivered(run_dir: Path) -> Any:
    array = np.load(run_dir / side.REDELIVERED_NAME, allow_pickle=False)
    if array.dtype.str != "<f4" or array.ndim != 2 or array.shape[1] != 3:
        raise ExtractError(f"{side.REDELIVERED_NAME} is {array.dtype.str}{list(array.shape)}")
    return array


def _bits_differ(found: Any, expected: Any) -> Any:
    """Per element, whether two arrays differ as float32 bit patterns (so -0.0 is not 0.0)."""
    a = np.ascontiguousarray(found, np.float32).view(np.uint32)
    b = np.ascontiguousarray(np.asarray(expected, np.float64).astype(np.float32)).view(np.uint32)
    return a != b


def low_problems(
    arrays: Mapping[str, Any],
    table: low_side.TriangleTable,
    redelivered: Any,
    triangles: int = TRIANGLES,
) -> list[str]:
    """The Authoring extraction against front N's Low-Game table, per triangle corner; the
    normals through `deliver.py`'s replayed conversion (`redelivered`), bit for bit."""
    co, lt, lv, uv, cn, lining = (arrays[name] for name in side.LOW_ARRAYS)
    problems: list[str] = []
    for name in ("co", "uv", "cn", "lining"):
        if not np.isfinite(arrays[name]).all():
            problems.append(f"{name} holds non-finite values")
    positions = np.asarray(table.positions, np.float64)
    if len(co) != len(positions) or len(lining) != len(co):
        problems.append(f"{len(co)} vertices and {len(lining)} part ids, Low-Game {len(positions)}")
    if len(lt) != len(table.triangles) or len(lt) != triangles:
        problems.append(f"{len(lt)} loop triangles, Low-Game {len(table.triangles)}")
    if len(uv) != len(lv) or len(cn) != len(lv):
        problems.append(f"{len(lv)} loops, but {len(uv)} UVs and {len(cn)} corner normals")
    if lt.size and (lt.min() < 0 or lt.max() >= len(lv)):
        problems.append("a loop triangle names a loop out of range")
    if lv.size and (lv.min() < 0 or lv.max() >= len(co)):
        problems.append("a loop names a vertex out of range")
    if problems:
        return problems
    if not np.array_equal(positions.astype(np.float32).astype(np.float64), positions):
        problems.append("the Low-Game table's positions are not float32 values")
    moved = np.flatnonzero(_bits_differ(co, positions).any(axis=1))
    if moved.size:
        problems.append(f"{moved.size} positions differ from Low-Game's, first vertex {moved[0]}")
    corners = np.asarray(table.triangles, np.int64)
    wrong = np.flatnonzero((lv[lt] != corners).any(axis=1))
    if wrong.size:
        problems.append(f"{wrong.size} triangles name other vertices, first {wrong[0]}")
    loops = np.asarray(table.loops, np.int64)
    game_uv = np.asarray(table.uv, np.float64)[loops]
    wrong = np.flatnonzero(_bits_differ(uv[lt], game_uv).any(axis=(1, 2)))
    if wrong.size or not np.array_equal(game_uv.astype(np.float32).astype(np.float64), game_uv):
        problems.append(f"{wrong.size} triangles have another corner UV")
    game_normals = np.asarray(table.normals, np.float64)[loops]
    if not np.array_equal(game_normals.astype(np.float32).astype(np.float64), game_normals):
        problems.append("the Low-Game table's normals are not float32 values")
    if redelivered.shape != (3 * len(lt), 3):
        problems.append(f"{len(redelivered)} re-delivered corner normals, {3 * len(lt)} corners")
    else:
        replayed = redelivered.reshape(-1, 3, 3)
        wrong = np.flatnonzero(_bits_differ(replayed, game_normals).any(axis=(1, 2)))
        if wrong.size:
            largest = np.abs(replayed.astype(np.float64) - game_normals).max()
            problems.append(
                f"{wrong.size} triangles: deliver.py's conversion of the Authoring normals does "
                f"not reproduce Low-Game's (first {wrong[0]}, largest difference {largest:.3g})"
            )
    parts = lining[lv[lt]]
    if (parts != parts[:, :1]).any():
        problems.append("a triangle spans two PartId values")
    if not np.isfinite(lining).all() or (lining != np.rint(lining)).any() or lining.min() < 1:
        problems.append(f"{side.PART_ATTRIBUTE} holds values that are not part ids >= 1")
    if not (lining == WRAP_PART).any():
        problems.append(f"no vertex has PartId {WRAP_PART} (the wrap)")
    return problems


def normal_diagnostics(arrays: Mapping[str, Any], table: low_side.TriangleTable) -> dict[str, Any]:
    """How far the Authoring's own corner normals (in `low.npz`) are from Low-Game's: the
    custom-normal conversion's effect, recorded, not gated."""
    game = np.asarray(table.normals, np.float64)[np.asarray(table.loops, np.int64)]
    authoring = arrays["cn"][arrays["lt"]]
    unequal = (authoring != game.astype(np.float32)).any(axis=-1)
    return {
        "redelivered_equals_low_game": True,
        "authoring_vs_low_game_max_component": float(
            np.abs(authoring.astype(np.float64) - game).max(initial=0.0)
        ),
        "authoring_vs_low_game_unequal_corners": int(unequal.sum()),
        "corners": int(unequal.size),
    }


def extract_report_problems(
    report: Any, copy: Path, arrays: Mapping[str, Any], redelivered: Any
) -> list[str]:
    """The Blender side's report against the pins and the arrays it wrote."""
    try:
        obj = report["object"]
        checks: list[tuple[str, Any, Any]] = [
            ("extractor", report["extractor"], side.EXTRACTOR),
            ("mode", report["mode"], "extract"),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(report["blend"]).resolve(), copy.resolve()),
            ("object", obj["name"], side.LOW_OBJECT),
            ("depsgraph mode", obj["depsgraph_mode"], side.DEPSGRAPH_MODE),
            ("part attribute", report["part_attribute"], [side.PART_ATTRIBUTE, "POINT", "FLOAT"]),
            ("uv map", report["uv_map"], side.UV_MAP),
            ("vertices", obj["vertices"], len(arrays["co"])),
            ("loops", obj["loops"], len(arrays["lv"])),
            ("polygons", obj["polygons"], len(arrays["face_loop_start"])),
            ("loop triangles", obj["loop_triangles"], len(arrays["lt"])),
            ("digests", report["digests"], {k: side.array_digest(a) for k, a in arrays.items()}),
            (
                "redelivered",
                report["redelivered"],
                {
                    "donor": side.DELIVER_PATH,
                    "donor_sha256": side.DELIVER_SHA256,
                    "digest": side.array_digest(redelivered),
                },
            ),
        ]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    return [
        f"report {what} is {found!r}, pinned {pin!r}" for what, found, pin in checks if found != pin
    ]


def npz_bytes(members: Sequence[tuple[str, bytes]]) -> bytes:
    """An `.npz` numpy reads (`np.load`) with fixed metadata, so equal arrays give equal bytes:
    stored members `<name>.npy` in the given order, dated 1980-01-01, no attributes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, data)
    return buffer.getvalue()


def npy_bytes(array: Any) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def png_chunk_problems(data: bytes) -> list[str]:
    """Each chunk's length and CRC, and the chunk order PNG requires (IHDR first, IEND last)."""
    if not data.startswith(png.SIGNATURE):
        return ["not a PNG file"]
    problems: list[str] = []
    offset, kinds = len(png.SIGNATURE), []
    while offset + 12 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        if offset + 12 + length > len(data):
            problems.append(f"the chunk at byte {offset} runs past the end of the file")
            break
        body = data[offset + 4 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        if zlib.crc32(body) & 0xFFFFFFFF != crc:
            problems.append(f"chunk {body[:4]!r} at byte {offset} fails its CRC")
            break
        kinds.append(body[:4])
        offset += 12 + length
    if not kinds or kinds[0] != b"IHDR" or kinds[-1] != b"IEND" or offset != len(data):
        problems.append("the PNG does not run IHDR ... IEND to its last byte")
    return problems


def _runs(names: Sequence[str]) -> list[list[Any]]:
    """Chunk kinds in file order, consecutive repeats counted: [["IDAT", 1362], ...]."""
    runs: list[list[Any]] = []
    for name in names:
        if runs and runs[-1][0] == name:
            runs[-1][1] += 1
        else:
            runs.append([name, 1])
    return runs


def normal_array(
    data: bytes, pin: SourcePin = NORMAL, layout: tuple[int, int, int, int] = NORMAL_LAYOUT
) -> tuple[Any, dict[str, Any]]:
    """The bake Normal as the donor's `highnormal.npy`: float32 (height, width, 3), RGB only,
    each 16-bit sample divided by 65535 in float32 (no transfer function: the `sRGB` and `gAMA`
    chunks are recorded, not applied; the map is data), rows bottom first (Blender's
    `image.pixels` order, the order `garment_material_masks.rasterize` indexes by V)."""
    found = hashlib.sha256(data).hexdigest()
    if found != pin.sha256 or len(data) != pin.size_bytes:
        raise ExtractError(f"the Normal has SHA-256 {found}, {len(data)} bytes, pinned {pin}")
    problems = png_chunk_problems(data)
    chunks = png.chunks(data) if not problems else []
    if chunks and len(chunks[0][1]) == 13:
        width, height, depth, colour, compression, filtering, interlace = struct.unpack(
            ">IIBBBBB", chunks[0][1]
        )
        if (width, height, depth, colour, compression, filtering, interlace) != (*layout, 0, 0, 0):
            problems.append(f"the Normal's header is {width}x{height} depth {depth} type {colour}")
    elif not problems:
        problems.append("the Normal's IHDR is not 13 bytes")
    if problems:
        raise ExtractError("; ".join(problems))
    samples = png.decode(data)
    values = samples.astype(np.float32) / np.float32(NORMAL_SCALE)
    array = np.ascontiguousarray(values[::-1])
    info = {
        **pin.as_json(),
        "layout": {"width": width, "height": height, "bit_depth": depth, "colour_type": colour},
        "chunks": _runs([kind.decode("ascii") for kind, _ in chunks]),
        "colour_chunks": {
            kind.decode("ascii"): body.hex() for kind, body in chunks if kind in (b"sRGB", b"gAMA")
        },
        "normalisation": f"float32(sample) / float32({NORMAL_SCALE}); no transfer function",
        "row_order": "bottom row first (Blender image.pixels); the PNG stores the top row first",
        "channels": "RGB",
        "sample_range": [int(samples.min()), int(samples.max())],
    }
    return array, info


def _outputs(run_dir: Path, names: Sequence[str]) -> dict[str, Any]:
    return {
        name: {"sha256": sha256_file(run_dir / name), "size_bytes": (run_dir / name).stat().st_size}
        for name in sorted(names)
    }


def _write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    (run_dir / RECORD_NAME).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_extract(
    plan: Plan,
    low_record: Path,
    assets_root: Path,
    store: OracleStore | None,
    runner: Runner = run_blender,
    *,
    normal_pin: SourcePin = NORMAL,
    normal_layout: tuple[int, int, int, int] = NORMAL_LAYOUT,
    low_game_pins: Mapping[str, str] | None = None,
    triangles: int = TRIANGLES,
) -> dict[str, Any]:
    """Blender's extraction, the Low-Game comparison, then `low.npz` and `highnormal.npy`."""
    game_record, table = load_low_game(low_record, **(low_game_pins or {}))
    normal_path = _pinned_source(normal_pin, assets_root, store)
    source = _blender_run(plan, runner, EXTRACT_OUTPUTS)
    report = json.loads((plan.run_dir / side.EXTRACT_REPORT).read_bytes())
    arrays, raw = load_arrays(plan.run_dir)
    redelivered = load_redelivered(plan.run_dir)
    copy = plan.run_dir / side.SOURCE_BLEND_NAME
    problems = extract_report_problems(report, copy, arrays, redelivered)
    if not problems:
        problems += low_problems(arrays, table, redelivered, triangles)
    if problems:
        raise ExtractError("; ".join(problems))
    normal, normal_info = normal_array(normal_path.read_bytes(), normal_pin, normal_layout)
    (plan.run_dir / LOW_NPZ).write_bytes(npz_bytes([(name, raw[name]) for name in side.LOW_ARRAYS]))
    (plan.run_dir / HIGHNORMAL).write_bytes(npy_bytes(normal))
    parts, counts = np.unique(arrays["lining"], return_counts=True)
    record = {
        "schema": RECORD_SCHEMA,
        "kind": "extract",
        "label": SUBSTITUTE,
        "blender": _blender_json(plan, report["blender"]),
        "script": _script_json(plan.script_sha256),
        "source": source,
        "low_game": {
            "record": str(low_record),
            "obj_sha256": game_record["outputs"]["obj"]["sha256"],
            "mtl_sha256": game_record["outputs"]["mtl"]["sha256"],
            "table_sha256": game_record["outputs"]["table"]["sha256"],
            "comparison": "positions, triangle vertices and corner UVs bit-equal as float32; "
            "corner normals bit-equal through deliver.py's replayed conversion",
            "normals": normal_diagnostics(arrays, table),
        },
        "low": {
            "object": report["object"],
            "part_attribute": report["part_attribute"],
            "parts": {str(int(p)): int(c) for p, c in zip(parts, counts, strict=True)},
            "digests": report["digests"],
        },
        "normal": {**normal_info, "digest": side.array_digest(normal)},
        "outputs": _outputs(plan.run_dir, sorted(EXTRACT_RECORD_OUTPUTS)),
    }
    _write_record(plan.run_dir, record)
    return record


# ------------------------------------------------------------------------------------- AO
def load_extraction(
    path: Path,
    source_sha256: str = low_host.SOURCE.sha256,
    *,
    low_game_pins: Mapping[str, str] | None = None,
    triangles: int = TRIANGLES,
) -> dict[str, Any]:
    """An accepted extraction, checked again rather than trusted: the record names exactly the
    extraction's outputs and each still has its bytes; the loose arrays have the recorded digests
    and `low.npz` is exactly their packing; and the Low-Game comparison passes again against
    front N's pinned record."""
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if (record.get("schema"), record.get("kind")) != (RECORD_SCHEMA, "extract"):
        raise ExtractError(f"{path} is not a {RECORD_SCHEMA} extraction record")
    if _get(record, ("source", "sha256")) != source_sha256:
        raise ExtractError(f"{path} was extracted from another source")
    outputs = record.get("outputs")
    if not isinstance(outputs, Mapping) or set(outputs) != EXTRACT_RECORD_OUTPUTS:
        raise ExtractError(f"{path} does not name exactly the extraction's outputs")
    for name, entry in outputs.items():
        found = sha256_file(path.parent / name)
        if found != _get(entry, ("sha256",)):
            raise ExtractError(f"{path.parent / name} has SHA-256 {found}, recorded {entry}")
    arrays, raw = load_arrays(path.parent)
    if {k: side.array_digest(a) for k, a in arrays.items()} != _get(record, ("low", "digests")):
        raise ExtractError(f"{path.parent}: the arrays differ from the recorded digests")
    # The record's object facts (matrix, modifiers) must be the Blender report's, re-checked.
    report = json.loads((path.parent / side.EXTRACT_REPORT).read_bytes())
    redelivered = load_redelivered(path.parent)
    copy = path.parent / side.SOURCE_BLEND_NAME
    problems = extract_report_problems(report, copy, arrays, redelivered)
    if problems or _get(record, ("low", "object")) != report["object"]:
        raise ExtractError(f"{path}: its object facts are not its report's ({problems})")
    if report["object"].get("matrix_is_identity") != low_side.is_identity(
        report["object"].get("matrix_world", [])
    ):
        raise ExtractError(f"{path}: the identity flag disagrees with the reported matrix")
    packed = npz_bytes([(name, raw[name]) for name in side.LOW_ARRAYS])
    if (path.parent / LOW_NPZ).read_bytes() != packed:
        raise ExtractError(f"{path.parent / LOW_NPZ} is not the packing of the loose arrays")
    game = _get(record, ("low_game", "record"))
    if not isinstance(game, str):
        raise ExtractError(f"{path} names no Low-Game record")
    _, table = load_low_game(Path(game), **(low_game_pins or {}))
    problems = low_problems(arrays, table, redelivered, triangles)
    if problems:
        raise ExtractError(f"{path}: " + "; ".join(problems))
    return record


def ao_report_problems(report: Any, copy: Path, expect: Mapping[str, Any], ao: Any) -> list[str]:
    try:
        checks: list[tuple[str, Any, Any]] = [
            ("extractor", report["extractor"], side.EXTRACTOR),
            ("mode", report["mode"], "ao"),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(report["blend"]).resolve(), copy.resolve()),
            ("low", report["low"]["name"], side.LOW_OBJECT),
            ("low digests", report["low"]["digests"], dict(expect)),
            ("high", report["high"]["name"], side.HIGH_OBJECT),
            ("cycles", report["cycles_applied"], side.CYCLES_SETTINGS),
            ("bake options", report["bake_options"], side.BAKE_OPTIONS),
            ("colour space", report["image"]["colorspace"], side.AO_COLORSPACE),
            ("pixels finite", report["pixels"]["finite"], True),
            (
                "pixel range",
                0.0 <= report["pixels"]["min"] <= report["pixels"]["max"] <= 1.0,
                True,
            ),
            ("digest", report["digest"], side.array_digest(ao)),
        ]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    problems = [f"report {w} is {f!r}, pinned {p!r}" for w, f, p in checks if f != p]
    passed = set(report.get("operator_options") or ())
    scene_only = set(side.BAKE_OPTIONS) - passed
    if not scene_only <= side.SCENE_OR_OPERATOR_OPTIONS:
        problems.append(f"object.bake was not passed {sorted(scene_only)}")
    scene_after = report.get("scene_bake_after") or {}
    problems += [
        f"the scene's bake {name} is {scene_after.get(name)!r}, pinned {side.BAKE_OPTIONS[name]!r}"
        for name in sorted(side.SCENE_OR_OPERATOR_OPTIONS)
        if scene_after.get(name) != side.BAKE_OPTIONS[name]
    ]
    used = report.get("bake_options_used")
    if used is not None:
        problems += [
            f"object.bake ran with {name} {used.get(name)!r}, pinned {side.BAKE_OPTIONS[name]!r}"
            for name in sorted(passed & set(side.BAKE_OPTIONS))
            if not _same_option(used.get(name), side.BAKE_OPTIONS[name])
        ]
    shape = (side.AO_RESOLUTION, side.AO_RESOLUTION)
    if ao.dtype.str != "<f2" or ao.shape != shape:
        problems.append(f"ao.npy is {ao.dtype.str}{list(ao.shape)}, pinned <f2{list(shape)}")
    elif not np.isfinite(ao).all() or ao.min() < 0 or ao.max() > 1:
        problems.append("ao.npy holds values outside [0, 1]")
    return problems


def _same_option(found: Any, pinned: Any) -> bool:
    """Float options are float32 RNA properties, so they are compared at float32."""
    if isinstance(pinned, float) and isinstance(found, int | float) and not isinstance(found, bool):
        return bool(np.float32(found) == np.float32(pinned))
    return bool(found == pinned)


def run_ao(
    plan: Plan,
    extraction: Path,
    runner: Runner = run_blender,
    *,
    low_game_pins: Mapping[str, str] | None = None,
    triangles: int = TRIANGLES,
) -> dict[str, Any]:
    """The AO substitute on the verified low."""
    accepted = load_extraction(
        extraction, plan.source_pin.sha256, low_game_pins=low_game_pins, triangles=triangles
    )
    expect = accepted["low"]["digests"]

    def write_expect() -> None:
        side.write_json(
            plan.run_dir / side.AO_EXPECT,
            {"low_digests": expect, "extraction_record_sha256": sha256_file(extraction)},
        )

    source = _blender_run(plan, runner, AO_OUTPUTS, write_expect)
    report = json.loads((plan.run_dir / side.AO_REPORT).read_bytes())
    ao = np.load(plan.run_dir / side.AO_NAME, allow_pickle=False)
    problems = ao_report_problems(report, plan.run_dir / side.SOURCE_BLEND_NAME, expect, ao)
    if problems:
        raise ExtractError("; ".join(problems))
    record = {
        "schema": RECORD_SCHEMA,
        "kind": "ao",
        "label": "NEW AO substitute baked now from the preserved High and the verified low; "
        "not the lost 25-Faixa-Cintura_AO_v5",
        "blender": _blender_json(plan, report["blender"]),
        "script": _script_json(plan.script_sha256),
        "source": source,
        "extraction": {"record": str(extraction), "record_sha256": sha256_file(extraction)},
        "ao": {
            key: report[key]
            for key in (
                "low",
                "high",
                "as_found",
                "cycles_applied",
                "bake_options",
                "operator_options",
                "image",
            )
        }
        | {
            # The receipt: what object.bake ran with, as Blender kept it (None if it did not),
            # and the scene's bake settings afterwards.
            "bake_options_used": report.get("bake_options_used"),
            "scene_bake_after": report.get("scene_bake_after"),
            "pixels": report["pixels"],
            "digest": report["digest"],
            "row_order": "bottom first",
        },
        "outputs": _outputs(plan.run_dir, [side.AO_NAME, side.AO_EXPECT, side.AO_REPORT]),
    }
    _write_record(plan.run_dir, record)
    return record


# ------------------------------------------------------------------------------------- centre
def donor_column_degrees() -> Any:
    """`low_gen.wrap_low`'s column angles in degrees, computed as it computes them."""
    uniform = np.arange(0, 360, WRAP_UNIFORM_STEP)
    extra = np.array(WRAP_EXTRA_DEGREES)
    distance = np.abs((uniform[:, None] - extra[None] + 180) % 360 - 180)
    kept = uniform[np.min(distance, axis=1) > 1.0]
    return np.sort(np.concatenate([kept, extra]) % 360)


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _cycles(boundary: Mapping[int, Sequence[int]]) -> list[list[int]]:
    """The boundary's cycles, each from its smallest vertex towards its smaller neighbour."""
    seen: set[int] = set()
    cycles = []
    for start in sorted(boundary):
        if start in seen:
            continue
        cycle, previous, current = [start], start, min(boundary[start])
        while current != start:
            if current in seen or len(cycle) > len(boundary):
                raise CentreError("the wrap's boundary edges do not form simple cycles")
            cycle.append(current)
            following = [v for v in boundary[current] if v != previous]
            previous, current = current, following[0]
        seen.update(cycle)
        cycles.append(cycle)
    return cycles


def wrap_columns(lv: Any, face_start: Any, face_total: Any, lining: Any) -> list[list[int]]:
    """The wrap (PartId 1) as `low_gen.ring_islands` builds it, proven on the polygons alone:
    an annulus of quads, closed around and open at both ends, whose every column runs straight
    across `WRAP_ROWS` vertices from one boundary loop to the other. Columns are ordered along
    the boundary loop holding the smallest vertex index; no vertex order is assumed."""
    loops = np.asarray(lv).tolist()
    wrap = {int(v) for v in np.flatnonzero(np.asarray(lining) == WRAP_PART)}
    if not wrap:
        raise CentreError(f"no vertex has PartId {WRAP_PART}")
    quads: list[tuple[int, ...]] = []
    for start, total in zip(
        np.asarray(face_start).tolist(), np.asarray(face_total).tolist(), strict=True
    ):
        if total < 3 or start < 0 or start + total > len(loops):
            raise CentreError(f"a polygon names loops {start}..{start + total} out of range")
        face = tuple(int(v) for v in loops[start : start + total])
        inside = sum(v in wrap for v in face)
        if inside and inside != len(face):
            raise CentreError("a polygon joins the wrap to another part")
        if inside and (len(face) != 4 or len(set(face)) != 4):
            raise CentreError(f"a wrap polygon has {len(face)} corners, not a quad")
        if inside:
            quads.append(face)
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for k, face in enumerate(quads):
        for a, b in zip(face, face[1:] + face[:1], strict=True):
            edge_faces.setdefault(_edge(a, b), []).append(k)
    if any(len(faces) not in (1, 2) for faces in edge_faces.values()):
        raise CentreError("the wrap is not a manifold surface")
    if {v for face in quads for v in face} != wrap:
        raise CentreError("a wrap vertex lies on no wrap polygon")
    neighbours: dict[int, set[int]] = {v: set() for v in wrap}
    boundary: dict[int, list[int]] = {}
    for (a, b), faces in edge_faces.items():
        neighbours[a].add(b)
        neighbours[b].add(a)
        if len(faces) == 1:
            boundary.setdefault(a, []).append(b)
            boundary.setdefault(b, []).append(a)
    if any(len(ends) != 2 for ends in boundary.values()):
        raise CentreError("a wrap boundary vertex does not join exactly two boundary edges")
    cycles = _cycles(boundary)
    if len(cycles) != 2 or len(cycles[0]) != len(cycles[1]):
        raise CentreError(f"the wrap has boundary loops of {[len(c) for c in cycles]} vertices")
    first, other = cycles[0], set(cycles[1])
    columns = []
    for root in first:
        inner = [v for v in neighbours[root] if len(edge_faces[_edge(root, v)]) == 2]
        if len(inner) != 1:
            raise CentreError(f"boundary vertex {root} has {len(inner)} inner edges, not 1")
        column = [root, inner[0]]
        while column[-1] not in other:
            previous, current = column[-2], column[-1]
            if len(column) >= WRAP_ROWS or current in first:
                raise CentreError(f"the column from vertex {root} is not {WRAP_ROWS} vertices")
            incoming = set(edge_faces[_edge(previous, current)])
            ahead = [
                v
                for v in neighbours[current]
                if v != previous and not incoming & set(edge_faces[_edge(current, v)])
            ]
            if len(ahead) != 1:
                raise CentreError(f"vertex {current} is not a regular quad-grid vertex")
            column.append(ahead[0])
        if len(column) != WRAP_ROWS:
            raise CentreError(f"the column from vertex {root} has {len(column)} vertices")
        columns.append(column)
    flat = [v for column in columns for v in column]
    if len(flat) != len(set(flat)) or set(flat) != wrap:
        raise CentreError("the columns do not cover each wrap vertex exactly once")
    cells = {frozenset(face) for face in quads}
    count = len(columns)
    if len(quads) != count * (WRAP_ROWS - 1) or any(
        frozenset((columns[i][r], columns[j][r], columns[j][r + 1], columns[i][r + 1])) not in cells
        for i, j in ((i, (i + 1) % count) for i in range(count))
        for r in range(WRAP_ROWS - 1)
    ):
        raise CentreError("the wrap's quads are not the cells between neighbouring columns")
    return columns


def derive_centre(co: Any, columns: Sequence[Sequence[int]]) -> dict[str, Any]:
    """The waist centre `W.c` from the wrap's columns. `waist_gen.Waist.point` puts each column's
    vertices at c + R (sin theta, -cos theta) in XY, so each lies on its column's radial line.

    Every cyclic shift and both orientations of the donor's column angles are tried. For each,
    the centre is the intersection of the two columns at 0 degrees and at the angle nearest 90
    degrees from it (the smaller on a tie); each line passes through the mean of its column's
    n . p, n = (cos theta, sin theta). Then every wrap vertex must lie on its radial line within
    its float32 storage bound (half a unit in the last place per coordinate, projected on n),
    plus the centre's own bound (the two-line inverse's norm times its columns' bounds) and an
    arithmetic margin, and outside the centre along its ray. Exactly one hypothesis may pass.
    The 0-degree column corroborates cx: its x values must be one float32, equal to cx within
    the same bounds. Never a circle fit, never a stored constant."""
    degrees = donor_column_degrees()
    count = len(columns)
    if count != len(degrees) or any(len(column) != WRAP_ROWS for column in columns):
        raise CentreError(f"{count} wrap columns, low_gen.wrap_low builds {len(degrees)}")
    index = np.asarray(columns, np.int64)
    stored = np.asarray(co, np.float32)[index][..., :2]
    points = stored.astype(np.float64)
    half = np.spacing(np.abs(stored)).astype(np.float64) / 2
    zero = int(np.flatnonzero(degrees == 0.0)[0])
    away = np.abs(np.abs(degrees - degrees[zero]) - 90.0)
    partner = int(np.flatnonzero(away == away.min())[0])
    passing: list[tuple[Any, ...]] = []
    for shift in range(count):
        for orientation in (1, -1):
            mapping = (shift + orientation * np.arange(count)) % count
            theta = np.radians(degrees[mapping])
            normal = np.stack([np.cos(theta), np.sin(theta)], axis=1)
            ray = np.stack([np.sin(theta), -np.cos(theta)], axis=1)
            pair = [
                int(np.flatnonzero(mapping == zero)[0]),
                int(np.flatnonzero(mapping == partner)[0]),
            ]
            system = normal[pair]
            offsets = np.array([(points[i] @ normal[i]).mean() for i in pair])
            centre = np.linalg.solve(system, offsets)
            bound = (
                np.abs(normal[:, None, 0]) * half[..., 0]
                + np.abs(normal[:, None, 1]) * half[..., 1]
            )
            centre_bound = float(
                np.linalg.norm(np.linalg.inv(system), 2)
                * math.hypot(*(bound[i].max() for i in pair))
            )
            tolerance = bound + centre_bound + ARITHMETIC_MARGIN
            residual = ((points - centre) * normal[:, None, :]).sum(axis=-1)
            radius = ((points - centre) * ray[:, None, :]).sum(axis=-1)
            if (np.abs(residual) <= tolerance).all() and (radius > 0).all():
                passing.append(
                    (
                        shift,
                        orientation,
                        pair,
                        system,
                        centre,
                        centre_bound,
                        residual,
                        tolerance,
                        radius,
                    )
                )
    if len(passing) != 1:
        raise CentreError(
            f"{len(passing)} of {2 * count} column-angle hypotheses fit within float32 bounds; "
            "exactly one is required"
        )
    shift, orientation, pair, system, centre, centre_bound, residual, tolerance, radius = passing[0]
    condition = float(np.linalg.cond(system))
    if condition > CONDITION_LIMIT:
        raise CentreError(
            f"the two-column system's condition number {condition} > {CONDITION_LIMIT}"
        )
    x0 = stored[pair[0], :, 0]
    if (np.ascontiguousarray(x0).view(np.uint32) != x0[:1].view(np.uint32)).any():
        raise CentreError("the 0-degree column's x values are not one float32")
    x_bound = float(half[pair[0], 0, 0]) + centre_bound + ARITHMETIC_MARGIN
    if abs(float(x0[0]) - centre[0]) > x_bound:
        raise CentreError(f"the 0-degree column's x {float(x0[0])} differs from cx {centre[0]}")
    return {
        "centre": [float(centre[0]), float(centre[1])],
        "columns": count,
        "rows": WRAP_ROWS,
        "hypotheses": 2 * count,
        "shift": shift,
        "orientation": orientation,
        "intersection": [
            {"degrees": float(degrees[k]), "column": i, "first_vertex": int(index[i, 0])}
            for k, i in ((zero, pair[0]), (partner, pair[1]))
        ],
        "condition_number": condition,
        "centre_bound_m": centre_bound,
        "max_residual_m": float(np.abs(residual).max()),
        "max_residual_over_tolerance": float((np.abs(residual) / tolerance).max()),
        "min_radius_m": float(radius.min()),
        "theta0_x": float(x0[0]),
    }


def run_centre(
    run_dir: Path,
    *,
    derive: Path | None = None,
    authored: tuple[float, float] | None = None,
    provenance: str | None = None,
    missing: str | None = None,
    source_sha256: str = low_host.SOURCE.sha256,
    low_game_pins: Mapping[str, str] | None = None,
    triangles: int = TRIANGLES,
) -> dict[str, Any]:
    """Exactly one of: a centre derived from the accepted extraction, an authored centre with its
    provenance, or a record that the centre is missing."""
    if sum(x is not None for x in (derive, authored, missing)) != 1:
        raise ExtractError("give exactly one of --derive, --authored or --missing")
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": "centre",
        "consumer": "waist_masks.py sash reads construction.npz `centre` only",
        "historical": "not the historical construction.npz (construction_dump.py on the lost "
        "assembly); there is no historical v5 proof of its value",
    }
    centre = None
    if derive is not None:
        accepted = load_extraction(
            derive, source_sha256, low_game_pins=low_game_pins, triangles=triangles
        )
        obj = accepted["low"]["object"]
        if obj.get("matrix_is_identity") is not True or obj.get("modifiers") != []:
            raise CentreError("the float32 bounds need the low's identity matrix and no modifiers")
        low = np.load(derive.parent / LOW_NPZ, allow_pickle=False)
        faces = {k: np.load(derive.parent / f, allow_pickle=False) for k, f in FACE_FILES.items()}
        columns = wrap_columns(
            low["lv"], faces["face_loop_start"], faces["face_loop_total"], low["lining"]
        )
        derived = derive_centre(low["co"], columns)
        centre = derived["centre"]
        record |= {
            "status": "derived-from-preserved-geometry",
            "label": "centre DERIVED FROM PRESERVED GEOMETRY for the current round",
            "extraction": {"record": str(derive), "record_sha256": sha256_file(derive)},
            "donors": {
                LOW_GEN_PATH: LOW_GEN_SHA256,
                WAIST_GEN_PATH: WAIST_GEN_SHA256,
            },
            "derivation": derived,
        }
    elif authored is not None:
        if not all(math.isfinite(v) for v in authored) or not (provenance or "").strip():
            raise ExtractError("an authored centre needs two finite numbers and a provenance")
        centre = [float(authored[0]), float(authored[1])]
        record |= {"status": "authored", "label": "AUTHORED centre", "provenance": provenance}
    else:
        if not (missing or "").strip():
            raise ExtractError("--missing needs a reason")
        record |= {"status": "missing", "reason": missing}
    ensure_outside_repository(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    if centre is not None:
        array = np.asarray(centre, np.float64)
        (run_dir / CENTRE_NPZ).write_bytes(npz_bytes([("centre", npy_bytes(array))]))
        record |= {"centre": centre, "outputs": _outputs(run_dir, [CENTRE_NPZ])}
    _write_record(run_dir, record)
    return record


# ------------------------------------------------------------------------------- repeats
REPEAT_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "extract": (("low_game",), ("low",), ("normal", "digest"), ("outputs",)),
    "ao": (("extraction", "record_sha256"), ("ao",), ("outputs",)),
    "centre": (("status",), ("centre",), ("derivation",), ("outputs",)),
}
COMMON_FIELDS = (
    ("schema",),
    ("kind",),
    ("blender", "sha256"),
    ("script", "blender_side_sha256"),
    ("script", "host_sha256"),
    ("source", "sha256"),
)
RUN_SPECIFIC = frozenset({side.EXTRACT_REPORT, side.AO_REPORT, side.AO_EXPECT})


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """What a repeat must reproduce: the pins and every output byte for byte, except the files
    that name their run directory (the Blender reports and the AO expectation)."""
    kind = str(record.get("kind"))
    fields = COMMON_FIELDS[:2] if kind == "centre" else COMMON_FIELDS
    problems = []
    for path in (*fields, *REPEAT_FIELDS.get(kind, ())):
        found, wanted = _without_run(_get(record, path)), _without_run(_get(expected, path))
        if found != wanted:
            problems.append(f"{'.'.join(path)} is {found!r}, the earlier run's {wanted!r}")
    return problems


def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def _without_run(value: Any) -> Any:
    """A copy without the fields that name the run (its directory, its record path)."""
    if isinstance(value, Mapping):
        return {
            k: _without_run(v) for k, v in value.items() if k not in RUN_SPECIFIC and k != "record"
        }
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.sash_intermediates",
        description="The Sash v5 mask-generator intermediates for the current round.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("extract", "ao"):
        p = sub.add_parser(mode)
        p.add_argument("--blender", type=Path, required=True, help="the pinned blender.exe")
        p.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
        p.add_argument("--store", type=Path, help="private store root (default: located)")
        p.add_argument("--dry-run", action="store_true", help="check pins, print the plan")
    sub.choices["extract"].add_argument(
        "--low-record", type=Path, help="front N's export-record.json (default: its r1)"
    )
    sub.choices["ao"].add_argument("--extraction", type=Path, required=True)
    centre = sub.add_parser("centre")
    group = centre.add_mutually_exclusive_group(required=True)
    group.add_argument("--derive", type=Path, help="an accepted extraction record")
    group.add_argument("--authored", type=float, nargs=2, metavar=("X", "Y"))
    group.add_argument("--missing", help="why there is no centre")
    centre.add_argument("--provenance", help="where an authored centre comes from")
    for p in sub.choices.values():
        p.add_argument("--run", help="run directory name in oracle work")
        p.add_argument("--expect", type=Path, help="an earlier run's intermediates-record.json")
    args = parser.parse_args(argv)
    run = args.run or DEFAULT_RUNS[args.mode]
    try:
        expected = None
        if args.expect is not None:
            expected = json.loads(args.expect.read_text(encoding="utf-8"))
            if (_get(expected, ("schema",)), _get(expected, ("kind",))) != (
                RECORD_SCHEMA,
                args.mode,
            ):
                raise ExtractError(f"{args.expect} is not a {RECORD_SCHEMA} {args.mode} record")
        if args.mode == "centre":
            if args.provenance is not None and args.authored is None:
                raise ExtractError("--provenance belongs to --authored")
            record = run_centre(
                run_dir_for(run, None),
                derive=args.derive,
                authored=tuple(args.authored) if args.authored else None,
                provenance=args.provenance,
                missing=args.missing,
            )
        else:
            store = OracleStore.open(args.store) if args.store is not None else locate()
            plan = plan_blender(args.mode, args.blender, run, args.assets_root, store)
            if args.mode == "extract":
                low_record = args.low_record or work_root() / LOW_GAME_RECORD
                load_low_game(low_record)
                _pinned_source(NORMAL, args.assets_root, store)
            else:
                load_extraction(args.extraction)
            if args.dry_run:
                print(json.dumps(plan.as_json(), indent=2))
                return 0
            if args.mode == "extract":
                record = run_extract(plan, low_record, args.assets_root, store)
            else:
                record = run_ao(plan, args.extraction)
    except (
        ExtractError,
        RecorderError,
        StoreError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"sash_intermediates: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    problems = compare_records(record, expected) if expected is not None else []
    for problem in problems:
        print(f"sash_intermediates: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
