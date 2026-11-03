r"""The Tunic v10 current round's generator fields and 9 substitute masks (decision 300 s. 7).

    python -m tools.parity.tier1.tunic_masks --assets-root <Assets3D> --ao <AO r1 ao-record.json>
        --ao-repeat <AO r1-repeat ao-record.json> [--low-record <U3 r1>] [--low-repeat <U3 repeat>]
        [--run NAME] [--expect <earlier masks-record.json>] [--dry-run]

Preparation for `phase2/tier1/tunic-v10-current` (contract:
`docs/analysis/tunic-v10-current-round/01-input-contract.md`, "Substitutes" and "Generator
intermediates"). It is not a baseline approval (decision 300 item 8). The 9 masks are current-round
substitutes, never the historical files; the 8 recovered masks and the Normal are preserved and
never regenerated.

1. **The donor runs unchanged.** `garment_material_masks.py` (`DONOR`) is read as the raw LF blob
   of Assets3D `SNAPSHOT` (`git cat-file`; git id, SHA-256 and size pinned), written into the run
   directory, and executed from those bytes as a script, once per step, each step in its own
   Python process (`donor_step`): `fields --work <run> --resolution 4096`, then `masks --work
   <run> --out <run>/donor-masks`, with no `--recipe` (the donor's built-in 18-Tunica defaults).
   Each process checks the runtime against its pins (`RUNTIME`: Python, NumPy, SciPy, Pillow and
   Pillow's zlib) and writes what it found, with the SHA-256 of every repository module it loaded
   (`code_closure`), which must be the files the producer hashed before the first step, unchanged
   after each step, and the same for both steps. An audit hook refuses any file opened under
   Assets3D while the donor runs (front T's `no_reads_under`). `PYTHONHASHSEED` is fixed at 0.
2. **Inputs, by hash only.** Front U3's accepted `low.npz` and `highnormal.npy`
   (`tunic_ao.load_low`: both records pinned, every file hashed) and the AO's `ao.npy` from an AO
   record whose repeat reproduced it byte for byte (`load_ao` compares the two records again and
   hashes both AO files) and which baked exactly U3's low. The four records and every file they
   name are hashed before the run and after each step (`receipt_files`); the inputs are copied
   into the fresh run directory and hashed again after the donor.
3. **Refusals where the donor degrades.** The donor zero-fills a missing lining, skips `ridge.npy`
   without the Normal and builds `M_cav` without AO from pleat valleys only. Here all three
   inputs must be present and pass the contract's array checks before `fields`
   (`input_problems`: U3's `array_problems` again, the Normal's shape, AO float16 2048² in
   [0, 1]), and every field must exist with its keys, dtype and shape and only finite values
   before `masks` (`field_problems`).
4. **Outputs.** The donor writes 16 masks. The 9 substitutes (`SUBSTITUTES`) are each checked on
   their bytes (a 4096² 16-bit grey PNG, rows top first, every texel outside the islands its
   nearest island texel), and recorded with their hashes for the request writer. The donor's 7
   outputs at preserved names are recorded as `discarded-never-bound`. The 8 preserved masks are
   recorded by their pins only (`tunic.RECOVERED`): the request writer resolves them from the
   store, and assembles the 17-file mask folder.
5. **Repeat.** With `--expect`, a fresh run must reproduce every pin, input and output byte for
   byte, the `.npz` files included (numpy's `savez` writes stored members dated 1980-01-01, so
   equal arrays give equal bytes). Only the donor's printed timing, the `seconds` field of
   `fields_report.json` and `masks_report.json`, is excluded, and the record says so; the two
   logs, which print it, are not compared. A difference exits 1.

Budgets (`Pins`): each step needs `memory_budget` bytes of free physical memory when it starts
(16 GiB: `fields` holds 768 MiB of rasters plus several GiB of temporaries, `masks` holds about
ten float64 arrays over 10M texels at once), the run's drive `disk_budget` bytes free (8 GiB; a
run writes about 1.5 GiB), and each step `TIMEOUTS_S` seconds. Files are hashed in 1 MiB blocks.
`--dry-run` checks the pins and inputs and prints the plan; it writes nothing.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.recorder import tunic
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import StoreError
from tools.parity.tier1 import tunic_ao as ao_host
from tools.parity.tier1 import tunic_ao_blender as ao_side
from tools.parity.tier1 import tunic_low_blender as low_side
from tools.parity.tier1 import tunic_low_export as low_host
from tools.parity.tier1.sash_intermediates_blender import ExtractError
from tools.parity.tier1.sash_low_export import RUN_NAME
from tools.parity.tier1.sash_masks import (
    Source,
    found_runtime,
    git_blob_id,
    host_json,
    no_reads_under,
    read_source,
    runtime_problems,
)
from tools.parity.tier1.tunic_ao import LowInputs, LowPins
from tools.parity.tier1.tunic_ao_blender import AoError

RECORD_SCHEMA = "uzpainter/parity/tunic-masks-record/1"
RECORD_NAME = "masks-record.json"
DEFAULT_RUN = ao_host.RUN_PREFIX + "masks-r1"
SNAPSHOT = ao_host.SNAPSHOT  # Assets3D f49fe67c, the contract's donor commit
DONOR = Source(
    "garment_material_masks",
    "Pipeline/painting/garment_material_masks.py",
    "1539a06b0b3fc2ead6aaaacef5624eca2faacc4b",
    "dfed970b93a387fe9321a66538c483ef48216efd7bdbdd0489901eb91e2976ca",
    28_507,
)
DONOR_FILE = "garment_material_masks.py"
MASKS_OUT = "donor-masks"
STEPS = ("fields", "masks")
TIMEOUTS_S = {"fields": 7200, "masks": 7200}
RUNTIME = {
    "python": "3.13.9",
    "numpy": "2.4.4",
    "scipy": "1.16.3",
    "pillow": "12.2.0",
    "pillow_zlib": "1.3.1.zlib-ng",
}
HASH_SEED = "0"
GIB = 1 << 30

# The donor's `masks` loop, in its order; the 9 the round keeps; the 7 at preserved names.
DONOR_MASKS = (
    "M_fiber",
    "M_hemband",
    "M_laceholes",
    "M_lacerings",
    "M_hemline",
    "M_ridgewear",
    "M_lining",
    "M_dyeinv",
    "M_cav",
    "M_pores",
    "M_stains",
    "M_band",
    "M_embro",
    "M_piping",
    "M_fray",
    "M_hem",
)
SUBSTITUTES = (
    "M_pores",
    "M_fiber",
    "M_dyeinv",
    "M_stains",
    "M_fray",
    "M_hem",
    "M_cav",
    "M_ridgewear",
    "M_lining",
)
DISCARDED = tuple(name for name in DONOR_MASKS if name not in SUBSTITUTES)
STACK_MASKS = 17
MASK_FORM = (16, 0)  # IHDR bit depth and colour type (grey)

INPUTS = {"low": low_host.LOW_NPZ, "highnormal": low_side.HIGHNORMAL, "ao": ao_side.AO_NAME}
FIELD_FILES = ("raster.npz", "ridge.npy", "rim_sd.npy", "geo.npz")
FIELDS_REPORT = "fields_report.json"
MASKS_REPORT = "masks_report.json"
REPORT_EXCLUDED = ("seconds",)
RUN_SPECIFIC = "the donor's printed timings: the logs, and `seconds` in its two reports"

SUBSTITUTE = {
    "classification": "current-round substitute",
    "replaces": "the 9 Tunic v10 masks that exist only inside the Painter project",
    "made_from": "garment_material_masks.py (f49fe67c) run unchanged on front U3's low.npz and "
    "highnormal.npy and the NEW AO substitute",
    "historical": "not the historical masks; their recorded versions stay what originals would "
    "have to match",
}
ORIENTATION = "PNG rows top first: the donor writes its bottom-first texel grid reversed"
PADDING = (
    "every texel outside the UV islands holds its nearest island texel "
    "(scipy.ndimage.distance_transform_edt indices, the donor's pad), checked on each PNG"
)
QUANTISATION = "uint16(clip(v, 0, 1)[padded][::-1] * 65535 + 0.5), Pillow (the donor's save)"


class MasksError(AoError):
    """A pin, an input, a field or an output does not hold; nothing is recorded as valid."""


@dataclass(frozen=True)
class Pins:
    """What the producer pins; the defaults are the round's (tests pass stand-ins)."""

    snapshot: str = SNAPSHOT
    donor: Source = DONOR
    runtime: Mapping[str, str] = field(default_factory=lambda: dict(RUNTIME))
    resolution: int = 4096
    ao_resolution: int = ao_side.AO_RESOLUTION
    vertices: int = low_side.VERTICES
    triangles: int = low_side.TRIANGLES
    low: LowPins = field(default_factory=LowPins)
    memory_budget: int = 16 * GIB
    disk_budget: int = 8 * GIB


PINS = Pins()


def stack_set_problems() -> list[str]:
    """The 9 substitutes and the 8 preserved masks are disjoint and make the stack's 17; the
    donor's other 7 outputs all carry preserved names."""
    preserved = set(tunic.RECOVERED)
    problems = []
    if not set(SUBSTITUTES) <= set(DONOR_MASKS) or len(set(SUBSTITUTES)) != 9:
        problems.append("the 9 substitutes are not 9 of the donor's masks")
    if set(SUBSTITUTES) & preserved:
        problems.append(f"{sorted(set(SUBSTITUTES) & preserved)} are preserved, never substituted")
    if not set(DISCARDED) <= preserved:
        problems.append(f"{sorted(set(DISCARDED) - preserved)} would be dropped without a source")
    if len(set(SUBSTITUTES) | preserved) != STACK_MASKS:
        problems.append(f"{len(set(SUBSTITUTES) | preserved)} masks, not {STACK_MASKS}")
    return problems


# ----------------------------------------------------------------------------- the child
def step_argv(step: str, run_dir: Path, resolution: int) -> list[str]:
    """The donor's command line for one step, the contract's arguments only."""
    if step == "fields":
        return ["fields", "--work", str(run_dir), "--resolution", str(resolution)]
    if step == "masks":
        return ["masks", "--work", str(run_dir), "--out", str(run_dir / MASKS_OUT)]
    raise MasksError(f"no donor step {step!r}")


def code_closure() -> dict[str, str]:
    """The repository's own modules (`tools/`) this process has loaded, by SHA-256: the code a
    step ran with besides the donor (the runtime's versions are no code hash)."""
    root = (REPO_ROOT / "tools").resolve()
    found = {}
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not isinstance(name, str):
            continue
        path = Path(name).resolve()
        if path.suffix == ".py" and path.is_relative_to(root):
            found[path.relative_to(REPO_ROOT.resolve()).as_posix()] = sha256_file(path)
    return dict(sorted(found.items()))


def closure_problems(found: Any, pinned: Mapping[str, str], what: str) -> list[str]:
    """A step's code against the files the producer pinned before it ran, and on disk now."""
    if not isinstance(found, dict) or not found:
        return [f"{what} recorded no code closure"]
    problems = [
        f"{what} ran {path} at {sha256}, pinned {pinned.get(path)}"
        for path, sha256 in found.items()
        if pinned.get(path) != sha256
    ]
    problems += [
        f"{path} changed after {what}"
        for path, sha256 in found.items()
        if sha256_file(REPO_ROOT / path) != sha256
    ]
    return problems


@contextmanager
def _argv(argv: Sequence[str]) -> Iterator[None]:
    saved = list(sys.argv)
    sys.argv = list(argv)
    try:
        yield
    finally:
        sys.argv = saved


def donor_step(
    step: str,
    run_dir: Path,
    assets_root: Path,
    pins: Pins = PINS,
    runtime: Callable[[], dict[str, str]] = found_runtime,
) -> None:
    """One donor step in this process: the runtime checked and written, the blob checked, then
    executed from its bytes as `__main__` with the step's arguments, reading nothing under
    Assets3D."""
    found = runtime()
    document = {
        "step": step,
        "runtime": found,
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "code": code_closure(),
    }
    ao_side.write_json(run_dir / f"{step}-runtime.json", document)
    problems = runtime_problems(found, pins.runtime)
    if document["python_hash_seed"] != HASH_SEED:
        problems.append(f"PYTHONHASHSEED is {document['python_hash_seed']!r}, pinned {HASH_SEED}")
    if problems:
        raise MasksError("the runtime is not pinned: " + "; ".join(problems))
    path = run_dir / DONOR_FILE
    data = path.read_bytes()
    if (git_blob_id(data), sha256_bytes(data)) != (pins.donor.blob, pins.donor.sha256):
        raise MasksError(f"{path} is not the donor's pinned blob")
    argv = step_argv(step, run_dir, pins.resolution)
    with no_reads_under(assets_root), _argv([str(path), *argv]):
        exec(compile(data, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})


def child_command(step: str, run_dir: Path, assets_root: Path) -> tuple[str, ...]:
    return (
        sys.executable,
        "-B",  # no bytecode written into the repository
        "-m",
        "tools.parity.tier1.tunic_masks",
        "donor-step",
        step,
        str(run_dir),
        str(assets_root),
    )


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


def run_child(
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


def available_memory() -> int:
    """Free physical memory in bytes."""
    if sys.platform == "win32":

        class Status(ctypes.Structure):
            _fields_ = [  # noqa: RUF012 (ctypes layout)
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = Status()
        status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise MasksError("GlobalMemoryStatusEx failed")
        return int(status.available_physical)
    return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))


# --------------------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class AoInputs:
    record: Path
    record_sha256: str
    repeat: Path
    repeat_sha256: str
    ao: Path
    ao_sha256: str
    digest: str

    def as_json(self) -> dict[str, Any]:
        return {
            "record": str(self.record),
            "record_sha256": self.record_sha256,
            "repeat": str(self.repeat),
            "repeat_sha256": self.repeat_sha256,
            "ao_sha256": self.ao_sha256,
            "digest": self.digest,
        }


def _record(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    document = ao_host._json(data, path)
    if (document.get("schema"), document.get("kind"), document.get("status")) != (
        ao_host.RECORD_SCHEMA,
        "ao",
        ao_host.STATUS["ao"],
    ):
        raise MasksError(f"{path} is not a baked {ao_host.RECORD_SCHEMA} AO record")
    return document, sha256_bytes(data)


def load_ao(record: Path, repeat: Path, low: LowInputs) -> AoInputs:
    """The AO r1 record and its reproduced repeat, both on exactly U3's accepted low."""
    first, first_sha = _record(record)
    again, again_sha = _record(repeat)
    if "expect" in first:
        raise MasksError(f"{record} is itself a repeat")
    if again.get("expect") != {"of_record_sha256": first_sha, "reproduced": True, "problems": []}:
        raise MasksError(f"{repeat} does not say it reproduced {record} byte for byte")
    # The repeat's own word is not taken: the two records are compared again, field for field.
    differ = ao_host.compare_records(again, first)
    if differ:
        raise MasksError(f"{repeat} does not reproduce {record}: " + "; ".join(differ))
    for path, document in ((record, first), (repeat, again)):
        inputs = document.get("low_inputs") or {}
        if (inputs.get("record_sha256"), inputs.get("repeat_sha256")) != (
            low.record_sha256,
            low.repeat_sha256,
        ) or inputs.get("digests") != low.digests:
            raise MasksError(f"{path} baked another low than front U3's accepted one")
    name = f"{ao_side.DONOR_OUT}/{ao_side.AO_NAME}"
    sha256 = ao_host._get(first, ("outputs", name, "sha256"))
    if ao_host._get(again, ("outputs", name, "sha256")) != sha256 or not isinstance(sha256, str):
        raise MasksError(f"{repeat} has another ao.npy than {record}")
    for folder in (record.parent, repeat.parent):
        if not (folder / name).is_file() or sha256_file(folder / name) != sha256:
            raise MasksError(
                f"{folder / name} is missing or does not hash to its record's {sha256}"
            )
    path = record.parent / name
    digest = ao_host._get(first, ("ao", "bake", "digest"))
    if not isinstance(digest, str):
        raise MasksError(f"{record} holds no AO digest")
    return AoInputs(record, first_sha, repeat, again_sha, path, sha256, digest)


def members(path: Path, names: Sequence[str]) -> Iterator[tuple[str, str, Any]]:
    """An `.npz`'s members, refused unless they are exactly `<name>.npy` in `names`' order:
    each one's name, SHA-256 (streamed) and array, one member in memory at a time."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        found = [info.filename for info in infos]
        if found != [f"{name}.npy" for name in names]:
            raise MasksError(f"{path.name} holds {found}, not {[f'{n}.npy' for n in names]}")
        for name, info in zip(names, infos, strict=True):
            digest = hashlib.sha256()
            with archive.open(info) as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
            with archive.open(info) as stream:
                array = np.lib.format.read_array(stream, allow_pickle=False)
            yield name, digest.hexdigest(), array
            del array


def input_problems(run_dir: Path, low: LowInputs, ao: AoInputs, pins: Pins) -> list[str]:
    """The contract's array checks on the three staged inputs, before `fields`."""
    arrays = {}
    problems = []
    for name, sha256, array in members(run_dir / INPUTS["low"], list(low_side.LOW_ARRAYS)):
        if sha256 != low.outputs[low_side.LOW_FILES[name]]:
            problems.append(f"low.npz member {name} is not U3's accepted array")
        arrays[name] = array
    evaluated_cn = np.load(low.path(low_side.RAW_NORMALS), allow_pickle=False)
    problems += low_host.array_problems(arrays, evaluated_cn, pins.vertices, pins.triangles)
    normal = np.load(run_dir / INPUTS["highnormal"], allow_pickle=False)
    if normal.dtype.str != "<f4":
        problems.append(f"highnormal.npy is {normal.dtype.str}, pinned <f4")
    problems += low_host.normal_array_problems(normal, (pins.resolution, pins.resolution, 3))
    occlusion = np.load(run_dir / INPUTS["ao"], allow_pickle=False)
    shape = (pins.ao_resolution, pins.ao_resolution)
    if occlusion.dtype.str != "<f2" or occlusion.shape != shape:
        problems.append(
            f"ao.npy is {occlusion.dtype.str}{list(occlusion.shape)}, pinned <f2{shape}"
        )
    elif not np.isfinite(occlusion).all() or occlusion.min() < 0 or occlusion.max() > 1:
        problems.append("ao.npy holds values outside [0, 1]")
    elif ao_side.array_digest(occlusion) != ao.digest:
        problems.append("ao.npy differs from its record's digest")
    return problems


# --------------------------------------------------------------------------------- fields
def field_specs(pins: Pins, valid: int) -> dict[str, dict[str, tuple[str, tuple[int, ...]]]]:
    """Each field file's members in the donor's order, with dtype and shape."""
    r = pins.resolution
    return {
        "raster.npz": {
            "tri_id": ("<i4", (r, r)),
            "P": ("<f4", (r, r, 3)),
            "N": ("<f4", (r, r, 3)),
            "L": ("<f4", (r, r)),
            "island": ("<i4", (r, r)),
            "isl_of_tri": ("<i8", (pins.triangles,)),
            "bary": ("<f2", (r, r, 3)),
        },
        "ridge.npy": {"": ("<f4", (r, r))},
        "rim_sd.npy": {"": ("<f4", (r, r))},
        "geo.npz": {
            "sd_hem": ("<f4", (valid,)),
            "sd_other": ("<f4", (valid,)),
            "conv": ("<f4", (valid,)),
            "d_hem": ("<f8", (pins.vertices,)),
            "is_rim": ("|b1", (pins.vertices,)),
        },
    }


def _array_problems(name: str, array: Any, spec: tuple[str, tuple[int, ...]]) -> list[str]:
    dtype, shape = spec
    if array.dtype.str != dtype or array.shape != shape:
        return [f"{name} is {array.dtype.str}{list(array.shape)}, pinned {dtype}{list(shape)}"]
    if array.dtype.kind == "f" and not np.isfinite(array).all():
        return [f"{name} holds non-finite values"]
    return []


def field_problems(run_dir: Path, pins: Pins) -> tuple[list[str], dict[str, Any]]:
    """Every field present with its keys, dtype, shape and only finite values; the texel count
    and each `.npz` member's hash (a diagnostic: the files themselves are compared whole)."""
    missing = [n for n in (*FIELD_FILES, FIELDS_REPORT) if not (run_dir / n).is_file()]
    if missing:
        return [f"fields wrote no {missing} (a missing Normal skips ridge.npy)"], {}
    with np.load(run_dir / "raster.npz", allow_pickle=False) as raster:
        tri_id = raster["tri_id"] if "tri_id" in raster.files else np.zeros(0, np.int32)
    valid = int((tri_id >= 0).sum())
    problems: list[str] = []
    hashes: dict[str, Any] = {}
    for name, spec in field_specs(pins, valid).items():
        path = run_dir / name
        if name.endswith(".npz"):
            hashes[name] = {}
            try:
                for key, sha256, array in members(path, list(spec)):
                    hashes[name][key] = sha256
                    problems += _array_problems(f"{name}:{key}", array, spec[key])
                    del array
            except MasksError as error:
                problems.append(str(error))
        else:
            problems += _array_problems(name, np.load(path, allow_pickle=False), spec[""])
    if problems:
        return problems, hashes
    if tri_id.min() < -1 or tri_id.max() >= pins.triangles or valid == 0:
        problems.append("raster.npz tri_id names no triangle or one out of range")
    return problems, {"valid_texels": valid, "npz_members_sha256": hashes}


def report_content(path: Path, required: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A donor report without its `seconds`, and the problems of its required values."""
    document = ao_host._json(path.read_bytes(), path)
    content = {k: v for k, v in document.items() if k not in REPORT_EXCLUDED}
    problems = [
        f"{path.name} {key} is {content.get(key)!r}, pinned {value!r}"
        for key, value in required.items()
        if content.get(key) != value
    ]
    return {"excluded": list(REPORT_EXCLUDED), "content": content}, problems


# --------------------------------------------------------------------------------- masks
def nearest_island_texel(valid: Any) -> Any:
    """The donor's padding indices: `distance_transform_edt(~valid, return_indices=True)`."""
    from scipy import ndimage

    return ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)


Nearest = Callable[[Any], Any]


def check_masks(
    run_dir: Path, pins: Pins, nearest: Nearest = nearest_island_texel
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every donor mask's form; the substitutes' orientation and padding on their bytes."""
    out = run_dir / MASKS_OUT
    with np.load(run_dir / "raster.npz", allow_pickle=False) as raster:
        valid = raster["tri_id"] >= 0
    rows, cols = nearest(valid)
    res = pins.resolution
    kept, dropped = [], []
    for name in DONOR_MASKS:
        path = out / f"{name}.png"
        data = path.read_bytes()
        header = png.chunks(data)[0][1] if data.startswith(png.SIGNATURE) else b""
        if len(header) != 13:
            raise MasksError(f"{path} is not a PNG")
        width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
        form = (header[8], header[9])
        if (width, height, form) != (res, res, MASK_FORM):
            raise MasksError(f"{path} is {width}x{height} depth {form[0]} colour type {form[1]}")
        entry = {
            "name": name,
            "file": f"{MASKS_OUT}/{path.name}",
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }
        if name not in SUBSTITUTES:
            dropped.append({**entry, "role": "discarded-never-bound"})
            continue
        bottom_first = png.decode(data)[::-1, :, 0]
        if not np.array_equal(bottom_first, bottom_first[rows, cols]):
            raise MasksError(f"{path}: a texel is not its nearest island texel (padding)")
        kept.append({**entry, "role": SUBSTITUTE["classification"], "shape": [res, res]})
    return kept, dropped


def preserved_json() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "packed_image": image,
            "sha256": sha256,
            "role": "preserved: resolved from the private store by its pin, never regenerated",
        }
        for name, (image, sha256) in sorted(tunic.RECOVERED.items())
    ]


# ---------------------------------------------------------------------------------- plan
@dataclass(frozen=True)
class Plan:
    run_dir: Path
    code: bytes
    low: LowInputs
    ao: AoInputs
    runtime: dict[str, str]
    expected: dict[str, Any] | None
    expected_path: Path | None
    expected_sha256: str | None

    def as_json(self, pins: Pins = PINS) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "donor": pins.donor.as_json(pins.snapshot),
            "steps": {step: step_argv(step, self.run_dir, pins.resolution) for step in STEPS},
            "runtime": self.runtime,
            "low_inputs": self.low.as_json(),
            "ao_inputs": self.ao.as_json(),
            "budgets": {
                "memory_bytes_per_step": pins.memory_budget,
                "disk_bytes_free": pins.disk_budget,
                "timeout_s": TIMEOUTS_S,
            },
            "expect": str(self.expected_path) if self.expected_path else None,
        }


def plan(
    run_dir: Path,
    assets_root: Path,
    low: LowInputs,
    ao_record: Path,
    ao_repeat: Path,
    *,
    expect: Path | None = None,
    pins: Pins = PINS,
    runtime: Callable[[], dict[str, str]] = found_runtime,
) -> Plan:
    """Every check that needs no output: the sets, the runtime, the donor, the inputs."""
    problems = stack_set_problems()
    run_dir = ensure_outside_repository(run_dir)
    if run_dir.exists():
        problems.append(f"{run_dir} already exists; every run gets a fresh directory")
    found = runtime()
    problems += runtime_problems(found, pins.runtime)
    if problems:
        raise MasksError("; ".join(problems))
    code = read_source(pins.donor, assets_root, pins.snapshot)
    ao = load_ao(ao_record, ao_repeat, low)
    expected = expected_sha256 = None
    if expect is not None:
        data = expect.read_bytes()
        expected, expected_sha256 = ao_host._json(data, expect), sha256_bytes(data)
        if (expected.get("schema"), expected.get("status")) != (RECORD_SCHEMA, "produced"):
            raise MasksError(f"{expect} is not a first produced {RECORD_SCHEMA} record")
    return Plan(run_dir, code, low, ao, found, expected, expect, expected_sha256)


def _stage(the_plan: Plan) -> dict[str, str]:
    run_dir = the_plan.run_dir
    sources = {
        "low": (the_plan.low.path(low_host.LOW_NPZ), the_plan.low.outputs[low_host.LOW_NPZ]),
        "highnormal": (
            the_plan.low.path(low_side.HIGHNORMAL),
            the_plan.low.outputs[low_side.HIGHNORMAL],
        ),
        "ao": (the_plan.ao.ao, the_plan.ao.ao_sha256),
    }
    staged = {}
    for key, (source, sha256) in sources.items():
        target = run_dir / INPUTS[key]
        shutil.copyfile(source, target)
        staged[target.name] = sha256_file(target)
        if staged[target.name] != sha256:
            raise MasksError(f"the staged {target} differs from {source}")
    return staged


def receipt_files(the_plan: Plan) -> dict[str, tuple[Path, str]]:
    """Front U3's two records and every file they name, the AO's two records and both AO files:
    each with the SHA-256 the plan accepted."""
    low, ao = the_plan.low, the_plan.ao
    found = {
        "low_record": (low.record, low.record_sha256),
        "low_repeat": (low.repeat, low.repeat_sha256),
        "ao_record": (ao.record, ao.record_sha256),
        "ao_repeat": (ao.repeat, ao.repeat_sha256),
        "ao_npy": (ao.ao, ao.ao_sha256),
        "ao_repeat_npy": (ao.repeat.parent / ao.ao.relative_to(ao.record.parent), ao.ao_sha256),
    }
    found |= {f"low/{name}": (low.path(name), sha256) for name, sha256 in low.outputs.items()}
    return found


def receipt_problems(the_plan: Plan, when: str) -> list[str]:
    found = {path: _sha(path) for path, _ in receipt_files(the_plan).values()}
    return [
        f"{when}: {path} is {found[path]}, accepted {sha256}"
        for path, sha256 in receipt_files(the_plan).values()
        if found[path] != sha256
    ]


def produce(
    the_plan: Plan,
    assets_root: Path,
    pins: Pins = PINS,
    runner: Runner = run_child,
    memory: Callable[[], int] = available_memory,
    nearest: Nearest = nearest_island_texel,
) -> tuple[dict[str, Any], list[str]]:
    """Stage, check, run the two donor steps in their own processes, check, record. The
    receipts, the interpreter and the producer's code are hashed first and again after each
    step (`integrity`); any failure once the run directory exists writes a `refused` record
    with those hashes, taken again at the failure, before it is raised."""
    run_dir = ensure_outside_repository(the_plan.run_dir)
    closure = code_closure()
    evidence: dict[str, Any] = {"before": integrity(the_plan, closure)}
    problems = unreadable(evidence["before"], "before the run")
    problems += receipt_problems(the_plan, "before the run")
    if problems:
        raise MasksError("; ".join(problems))
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        return _produce(the_plan, assets_root, pins, runner, memory, nearest, closure, evidence)
    except BaseException as error:
        # Best effort: nothing here may replace the original error.
        evidence["at_failure"] = integrity(the_plan, closure)
        try:
            files: Any = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*"))
        except OSError as listing:
            files = f"unreadable: {listing}"
        refused = {
            "schema": RECORD_SCHEMA,
            "kind": "masks",
            "status": "refused",
            "error": f"{type(error).__name__}: {error}",
            "integrity": evidence,
            "files": files,
        }
        try:
            _write_record(run_dir, refused)
        except OSError as writing:
            error.add_note(f"tunic_masks: the refused record could not be written: {writing}")
        raise


def _sha(path: Path) -> str | None:
    """A file's SHA-256, None when it is absent, `unreadable: <error>` when it cannot be read
    (recorded, and refused by `unreadable`, never raised)."""
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError as error:
        return f"unreadable: {error}"


def unreadable(found: Any, when: str, where: str = "") -> list[str]:
    """Every hash in an integrity pass that could not be read: the run fails closed on them."""
    if isinstance(found, Mapping):
        return [
            p for key, value in found.items() for p in unreadable(value, when, f"{where}/{key}")
        ]
    if isinstance(found, str) and found.startswith("unreadable"):
        return [f"{when}: {where.lstrip('/')} is {found}"]
    return []


def integrity(the_plan: Plan, closure: Mapping[str, str]) -> dict[str, Any]:
    """What the run is checked against, hashed now: the interpreter, the donor's copy, the
    producer's code and every receipt. It never raises on a read: see `_sha`."""
    sha = _sha
    return {
        "python": {"executable": sys.executable, "sha256": sha(Path(sys.executable))},
        "donor_copy": sha(the_plan.run_dir / DONOR_FILE),
        "code": {path: sha(REPO_ROOT / path) for path in closure},
        "receipts": {key: sha(path) for key, (path, _) in receipt_files(the_plan).items()},
    }


def _write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    text = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial = run_dir / (RECORD_NAME + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, run_dir / RECORD_NAME)


def _produce(
    the_plan: Plan,
    assets_root: Path,
    pins: Pins,
    runner: Runner,
    memory: Callable[[], int],
    nearest: Nearest,
    closure: Mapping[str, str],
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    run_dir = the_plan.run_dir
    free = shutil.disk_usage(run_dir).free
    if free < pins.disk_budget:
        raise MasksError(f"{free} bytes free on the run's drive, budget {pins.disk_budget}")
    (run_dir / DONOR_FILE).write_bytes(the_plan.code)
    if sha256_file(run_dir / DONOR_FILE) != pins.donor.sha256:
        raise MasksError("the donor's copy differs from its pin")
    staged = _stage(the_plan)
    problems = input_problems(run_dir, the_plan.low, the_plan.ao, pins)
    if problems:
        raise MasksError("; ".join(problems))
    env = {**os.environ, "PYTHONHASHSEED": HASH_SEED}
    children: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    for step in STEPS:
        available = memory()
        if available < pins.memory_budget:
            raise MasksError(
                f"{available} bytes of memory free for {step}, budget {pins.memory_budget}"
            )
        command = child_command(step, run_dir, assets_root)
        try:
            code = runner(command, REPO_ROOT, env, run_dir / f"{step}.log", TIMEOUTS_S[step])
        finally:
            evidence[f"after_{step}"] = integrity(the_plan, closure)
        # The receipts and the code first, whatever the step's exit.
        problems = unreadable(evidence[f"after_{step}"], f"after {step}")
        problems += receipt_problems(the_plan, f"after {step}")
        changed = [p for p, sha in evidence[f"after_{step}"]["code"].items() if sha != closure[p]]
        problems += [f"{path} changed during {step}" for path in changed]
        if evidence[f"after_{step}"]["python"] != evidence["before"]["python"]:
            problems.append(f"the interpreter changed during {step}")
        if problems:
            raise MasksError("; ".join(problems))
        found_path = run_dir / f"{step}-runtime.json"
        found = ao_host._json(found_path.read_bytes(), found_path) if found_path.is_file() else {}
        children[step] = {"argv": step_argv(step, run_dir, pins.resolution), **found}
        if code != 0:
            raise MasksError(f"the donor's {step} exited {code}; see {run_dir / f'{step}.log'}")
        if found.get("runtime") != dict(pins.runtime) or found.get("python_hash_seed") != HASH_SEED:
            raise MasksError(f"the {step} process ran on {found}, pinned {dict(pins.runtime)}")
        problems = closure_problems(found.get("code"), closure, f"the {step} process")
        if step == "masks" and found.get("code") != children["fields"].get("code"):
            problems.append("the fields and masks processes ran other code")
        if problems:
            raise MasksError("; ".join(problems))
        if step == "fields":
            problems, fields = field_problems(run_dir, pins)
            if problems:
                raise MasksError("; ".join(problems))
    expected_files = {
        DONOR_FILE,
        *staged,
        *FIELD_FILES,
        FIELDS_REPORT,
        MASKS_OUT,
        *(f"{step}.log" for step in STEPS),
        *(f"{step}-runtime.json" for step in STEPS),
    }
    present = {path.name for path in run_dir.iterdir()}
    out = {path.name for path in (run_dir / MASKS_OUT).iterdir()}
    wanted_out = {f"{name}.png" for name in DONOR_MASKS} | {MASKS_REPORT}
    if present != expected_files or out != wanted_out:
        raise MasksError(
            f"{run_dir}: unexpected {sorted((present - expected_files) | (out - wanted_out))}, "
            f"missing {sorted((expected_files - present) | (wanted_out - out))}"
        )
    for name, sha256 in staged.items():
        if sha256_file(run_dir / name) != sha256:
            raise MasksError(f"the donor changed its input {name}")
    if sha256_file(run_dir / DONOR_FILE) != pins.donor.sha256:
        raise MasksError("the donor's copy changed during the run")
    fields_report, problems = report_content(
        run_dir / FIELDS_REPORT, {"resolution": pins.resolution}
    )
    masks_report, more = report_content(run_dir / MASKS_OUT / MASKS_REPORT, {})
    mean = masks_report["content"].get("mean")
    if not isinstance(mean, dict) or sorted(mean) != sorted(DONOR_MASKS):
        more.append(f"masks_report.json means cover {sorted(mean or {})}, not the 16 masks")
    if problems + more:
        raise MasksError("; ".join(problems + more))
    kept, dropped = check_masks(run_dir, pins, nearest)
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": "masks",
        "status": "produced",
        "piece": "tunic-v10",
        "run_dir": str(run_dir),
        "helper": helper_json(),
        "donor": pins.donor.as_json(pins.snapshot),
        "runtime": dict(pins.runtime),
        "code": children["fields"]["code"],
        "children": children,
        "receipts": {key: sha256 for key, (_, sha256) in receipt_files(the_plan).items()},
        "integrity": evidence,
        "host": host_json(),
        "parameters": {
            "steps": {step: step_argv(step, Path("<run>"), pins.resolution) for step in STEPS},
            "recipe": None,
            "resolution": pins.resolution,
            "orientation": ORIENTATION,
            "padding": PADDING,
            "quantisation": QUANTISATION,
            "png": {"bit_depth": MASK_FORM[0], "colour_type": MASK_FORM[1]},
            "python_hash_seed": HASH_SEED,
        },
        "budgets": {
            "memory_bytes_per_step": pins.memory_budget,
            "disk_bytes_free": pins.disk_budget,
            "timeout_s": TIMEOUTS_S,
        },
        "low_inputs": the_plan.low.as_json(),
        "ao_inputs": the_plan.ao.as_json(),
        "staged": staged,
        "fields": {
            "outputs": _outputs(run_dir, FIELD_FILES),
            **fields,
            "report": fields_report,
        },
        "masks_report": masks_report,
        "substitutes": kept,
        "discarded": dropped,
        "preserved": preserved_json(),
        "stack_masks": sorted([*SUBSTITUTES, *tunic.RECOVERED]),
        "substitute": SUBSTITUTE,
        "run_specific": RUN_SPECIFIC,
        "repeat": {
            "result": "not-a-repeat",
            "note": "a repeat with --expect must agree byte for byte",
        },
    }
    problems = []
    if the_plan.expected is not None:
        problems = compare_records(record, the_plan.expected)
        record["status"] = "not-reproduced" if problems else "reproduced"
        record["repeat"] = {
            "of_record": str(the_plan.expected_path),
            "of_record_sha256": the_plan.expected_sha256,
            "result": "differs" if problems else "byte-identical",
            "problems": problems,
        }
    _write_record(run_dir, record)
    return record, problems


def _outputs(run_dir: Path, names: Sequence[str]) -> dict[str, Any]:
    return {
        name: {"sha256": sha256_file(run_dir / name), "size_bytes": (run_dir / name).stat().st_size}
        for name in names
    }


def helper_json() -> dict[str, Any]:
    def pin(path: Path) -> dict[str, str]:
        return {"path": path.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(path)}

    modules = (ao_host, ao_side, low_side, low_host, png)
    return {
        **pin(Path(__file__).resolve()),
        "checks_with": [pin(Path(m.__file__ or "").resolve()) for m in modules],
    }


# ------------------------------------------------------------------------------- repeats
REPEAT_FIELDS = (
    "schema",
    "kind",
    "piece",
    "helper",
    "donor",
    "runtime",
    "code",
    "children",
    "receipts",
    "integrity",
    "host",
    "parameters",
    "budgets",
    "low_inputs",
    "ao_inputs",
    "staged",
    "fields",
    "masks_report",
    "substitutes",
    "discarded",
    "preserved",
    "stack_masks",
    "substitute",
)
# Where a record names its run: the receipts' paths and each step's argv. Nothing else is left
# out of a comparison; the donor's reports are compared whole but for their `seconds`.
RUN_PATHS = {
    "low_inputs": frozenset({"record", "repeat"}),
    "ao_inputs": frozenset({"record", "repeat"}),
    "children": frozenset({"argv"}),
}


def _without_run(key: str, value: Any) -> Any:
    names = RUN_PATHS.get(key)
    if names is None or not isinstance(value, Mapping):
        return value
    if key == "children":
        return {
            step: {k: v for k, v in entry.items() if k not in names}
            if isinstance(entry, Mapping)
            else entry
            for step, entry in value.items()
        }
    return {k: v for k, v in value.items() if k not in names}


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """Every pin, input and output byte for byte, the `.npz` files whole; only the run's paths
    (`RUN_PATHS`) and the donor's `seconds`, already left out of its reports, differ."""
    return [
        f"{key} is {_without_run(key, record.get(key))!r}, the earlier run's "
        f"{_without_run(key, expected.get(key))!r}"
        for key in REPEAT_FIELDS
        if _without_run(key, record.get(key)) != _without_run(key, expected.get(key))
    ]


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["donor-step"]:
        if len(argv) != 4:
            print("tunic_masks: donor-step STEP RUN_DIR ASSETS_ROOT", file=sys.stderr)
            return 2
        run_dir = ensure_outside_repository(Path(argv[2]))
        if not run_dir.is_relative_to(work_root().resolve()) or not run_dir.is_dir():
            print(f"tunic_masks: {run_dir} is not a run directory in oracle work", file=sys.stderr)
            return 2
        donor_step(argv[1], run_dir, Path(argv[3]))
        return 0
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.tunic_masks",
        description="The Tunic v10 current round's fields and 9 substitute masks (the donor "
        "garment_material_masks.py, unchanged).",
    )
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument("--ao", type=Path, required=True, help="the AO r1 ao-record.json")
    parser.add_argument("--ao-repeat", type=Path, required=True, help="its reproduced repeat")
    parser.add_argument("--low-record", type=Path, help="front U3's r1 export-record.json")
    parser.add_argument("--low-repeat", type=Path, help="front U3's r1-repeat export-record.json")
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's masks-record.json")
    parser.add_argument("--dry-run", action="store_true", help="check, print the plan")
    args = parser.parse_args(argv)
    try:
        work = work_root()
        if not RUN_NAME.fullmatch(args.run):
            raise MasksError(f"run name {args.run!r} is not a plain name")
        low = ao_host.load_low(
            args.low_record or work / ao_host.LOW_RECORD,
            args.low_repeat or work / ao_host.LOW_REPEAT,
        )
        the_plan = plan(
            work / args.run, args.assets_root, low, args.ao, args.ao_repeat, expect=args.expect
        )
        if args.dry_run:
            print(json.dumps(the_plan.as_json(), indent=2))
            return 0
        record, problems = produce(the_plan, args.assets_root)
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
        print(f"tunic_masks: {error}", file=sys.stderr)
        return 2
    summary = {
        "run": the_plan.run_dir.name,
        "status": record["status"],
        "substitutes": {o["name"]: o["sha256"] for o in record["substitutes"]},
        "fields": record["fields"]["outputs"],
        "repeat": record["repeat"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    for problem in problems:
        print(f"tunic_masks: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
