r"""The Sash v5 current round's 20 masks, from Assets3D `waist_masks.py sash` (decision 300 §7).

    python -m tools.parity.tier1.sash_masks --assets-root <Assets3D> --ao <AO record>
        [--extraction <extraction record>] [--centre <centre record>] [--run NAME]
        [--expect <earlier masks-record.json>] [--dry-run]

The masks producer of the current round. It makes masks only. `T_sash` (the colour) is out of
scope: it needs two swatches, and no authorized substitute for them exists. This is technical
preparation, not a baseline approval (decision 300 item 8).

1. **Sources.** `waist_masks.py` and its two imports, `garment_material_masks.py` and
   `waist_gen.py`, are read as raw git blobs of the Assets3D snapshot `SNAPSHOT` (`git
   cat-file`), never from the checkout. Each blob's git id, SHA-256 and size must equal its pin.
   `waist_gen.py`'s pin `15cf7cb9…` is the CRLF checkout of its LF blob `c109880d…`, and both are
   checked. The two imports are put into `sys.modules` before `waist_masks.py` runs, so its
   `import garment_material_masks` and `import waist_gen` bind the pinned bytes and never a live
   file. `sys.path` and `sys.modules` are restored afterwards.
2. **The formulas stay exact.** The donor's own code runs unchanged: `Field` builds the texel
   field, and `sash` evaluates and writes the masks through the donor's own `save_mask`
   (Pillow, 16-bit). Nothing is reimplemented.
3. **The split between masks and colour.** It is proven statically on the pinned bytes
   (`split_report`). In `sash`, everything up to and including the one `save_mask` loop writes
   exactly the 20 masks (`MASKS`, in the donor's order) and touches no swatch. Everything after
   that loop is colour: it reads the swatches and calls `save_rgb`. `Field` and the module's top
   level reference no swatch read either. The static proof covers `sash` and `Field` only, not
   the helpers they call, so a runtime guard covers all the code that runs: while the donor
   loads and runs, an audit hook refuses any file opened under the Assets3D root (where the
   swatches, and every live copy of the sources, live) (`no_reads_under`). The module's `swatch`
   is the colour boundary (`ColourBoundary`): the first swatch read (`swatch("cloth")`) stops
   `sash` before any swatch file is opened. All 20 masks must be written by then, and
   `save_rgb` must not be reached. The original CLI fails at that read and never writes
   `masks.json`. This run writes no `masks.json` and no `T_sash.png`: the means it would hold
   go into the receipt.
4. **Inputs.** Front P's extraction record (re-checked by `sash_intermediates.load_extraction`),
   its AO record and its centre record (status `derived-from-preserved-geometry`). The AO and
   centre records must both cite the extraction record's SHA-256 (the shared extraction link).
   The extraction record must hash the same before and after its re-check. Every consumed file
   (`low.npz`, `highnormal.npy`, `ao.npy`, `construction-centre.npz`) must hash to its record.
   `low.npz` must hold exactly the members `<name>.npy` in the extraction's order, each equal to
   the loose array of the same name. Each array's digest must equal its record's. The files are
   copied into the fresh run directory, which is refused inside the repository. They are hashed
   after the copy and again after the donor has run.
5. **Outputs.** 20 masks: the stack's 19 (`STACK_MASKS`, role `stack-input`) and `M_cloth`
   (role `auxiliary`). Each must be a `RESOLUTION`² 16-bit grey PNG, decoded with the repository's
   own decoder. It must also be padded the donor's way: read bottom row first, every texel equals
   its nearest island texel (the donor's `Field.idx`). This checks the orientation and the
   padding on the bytes.
6. **Pins.** Python, NumPy, SciPy, Pillow and Pillow's zlib (it writes the PNG bytes) are pinned
   (`RUNTIME`), as are the resolution, the orientation and the padding.
7. **Receipt.** `masks-record.json` (`RECORD_SCHEMA`) is written last, atomically, and only after
   every check has passed. A run that fails a check leaves no record. A repeat (`--expect`, whose
   baseline must be `produced` or `reproduced`) runs again from scratch, in a fresh directory and
   a fresh process. It must reproduce every pin, the host, every input hash and every output byte
   for byte. Its record states the result: `reproduced`, or `not-reproduced` with the differences
   (exit 1). Front R's consumer accepts only `reproduced`.

`--dry-run` checks the pins, the split and the inputs, and prints the plan. It writes nothing.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import types
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.feasibility import png
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import StoreError
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1.sash_intermediates_blender import ExtractError

RECORD_SCHEMA = "uzpainter/parity/sash-masks-record/1"
RECORD_NAME = "masks-record.json"
DEFAULT_RUN = host.RUN_PREFIX + "masks-r1"
DEFAULT_EXTRACTION = host.DEFAULT_RUNS["extract"] + "/" + host.RECORD_NAME
DEFAULT_CENTRE = host.DEFAULT_RUNS["centre"] + "/" + host.RECORD_NAME
CENTRE_STATUS = "derived-from-preserved-geometry"
BASELINE_STATUSES = frozenset({"produced", "reproduced"})  # what a repeat may compare against
SNAPSHOT = "1c9a312a47eea0b35aa0aa05777245ef61ac49e5"  # Assets3D, 2026-10-20 (sash_current's)


@dataclass(frozen=True)
class Source:
    """A pinned Assets3D module: its import name and path, the raw blob's git id, SHA-256 and size,
    and, where the pin was taken from the CRLF checkout, that checkout's SHA-256."""

    name: str
    path: str
    blob: str
    sha256: str
    size_bytes: int
    checkout_sha256: str | None = None

    def as_json(self, commit: str) -> dict[str, Any]:
        found: dict[str, Any] = {
            "module": self.name,
            "assets3d_path": self.path,
            "commit": commit,
            "git_blob": self.blob,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "read_from": "git object database (git cat-file), never the checkout",
        }
        if self.checkout_sha256 is not None:
            found["checkout_sha256"] = self.checkout_sha256
            found["checkout_form"] = "the blob with every LF replaced by CRLF (core.autocrlf)"
        return found


# In load order: the two imports before `waist_masks.py`. Each blob is unchanged from its last
# change (f49fe67c and d974c81e) to Assets3D HEAD a8a06a1c.
SOURCES: tuple[Source, ...] = (
    Source(
        "garment_material_masks",
        "Pipeline/painting/garment_material_masks.py",
        "1539a06b0b3fc2ead6aaaacef5624eca2faacc4b",
        "dfed970b93a387fe9321a66538c483ef48216efd7bdbdd0489901eb91e2976ca",
        28_507,
    ),
    Source(
        "waist_gen",
        "Pipeline/retopology/waist-v5/waist_gen.py",
        "33ff304bbcb61845645b76dfcdc407eb54700abb",
        "c109880dddc4912059f56d54168484908eb0566dc5c1c775dc60167969ba31b7",
        32_887,
        checkout_sha256="15cf7cb9831df33ad645b5bf9b26a2cdc49d9c104f93ecf12c26eae6cb37b746",
    ),
    Source(
        "waist_masks",
        "Pipeline/retopology/waist-v5/waist_masks.py",
        "971c9d8038a046f3afcd2de5d35be502f1ef69c5",
        "959eca0bc3e2660149806c288d002d4d0db0816dc284093e643d6ffd5837a066",
        19_989,
    ),
)
DONOR = "waist_masks"  # the module whose `sash` runs; the others are its imports

# `sash`'s masks in the donor's order. The stack uses 19 (sash_current.BITMAPS without T_sash);
# M_cloth is written too and is auxiliary.
MASKS = (
    "M_cloth",
    "M_hem",
    "M_weave",
    "M_cav",
    "M_crest",
    "M_beltgrime",
    "M_seam",
    "M_fibers",
    "M_dust",
    "M_tab_edge",
    "M_inner",
    "M_hem_top",
    "M_band_top",
    "M_band_seam",
    "M_band_stitch",
    "M_hem_crack",
    "M_hem_grime",
    "M_hem_grain",
    "M_band",
    "M_tab_var",
)
AUXILIARY = frozenset({"M_cloth"})
STACK_MASKS = tuple(sorted(set(MASKS) - AUXILIARY))
ROLES = {"stack": "stack-input", "auxiliary": "auxiliary"}
MASK_FORM = (16, 0)  # IHDR bit depth and colour type (grey); sash_current.MASK_FORM

RESOLUTION = 2048  # waist_masks.py `--res` default, the texture set's size
ORIENTATION = (
    "PNG rows top first: the donor reverses its bottom-first texel grid (rows indexed by V, as "
    "garment_material_masks.rasterize lays it), so the PNG's first row is V = 1"
)
PADDING = (
    "every texel outside the UV islands holds its nearest island texel "
    "(scipy.ndimage.distance_transform_edt indices, Field.idx), with no distance limit; "
    "checked on each decoded PNG"
)
QUANTISATION = "uint16(clip(v, 0, 1) * 65535 + 0.5), Pillow I;16 PNG (the donor's save_mask)"
# The interpreter and the libraries the donor computes and encodes with.
RUNTIME = {
    "python": "3.13.9",
    "numpy": "2.4.4",
    "scipy": "1.16.3",
    "pillow": "12.2.0",
    "pillow_zlib": "1.3.1.zlib-ng",
}

# What the mask part of `sash` may not reference, and the colour part must.
COLOUR_NAMES = frozenset({"swatch", "sample", "triplanar", "SW", "GAIN", "Image", "save_rgb"})
BOUNDARY = "swatch"
FIRST_SWATCH = "cloth"

INPUT_FILES = {
    "low": host.LOW_NPZ,
    "highnormal": host.HIGHNORMAL,
    "ao": side.AO_NAME,
    "centre": host.CENTRE_NPZ,
}
SUBSTITUTE = {
    "classification": "current-round substitute",
    "replaces": "the masks waist_masks.py sash wrote in the lost sashchain.sh round",
    "made_from": "front P's current-round intermediates (low.npz, highnormal.npy, ao.npy) and "
    "the construction centre derived from preserved geometry",
    "historical": "not the historical masks; their bytes are lost and unestablished",
}
COLOUR = {
    "status": "not-in-scope",
    "reason": "T_sash needs sash-cloth-BaseColor-v1.png and hem-leather-BaseColor-v1.png; no "
    "authorized substitute exists (the owner's generator authorization is pending). No swatch "
    "was read, and this record is no colour receipt.",
}


class MasksError(ExtractError):
    """A pin, the split, an input or an output does not hold; nothing is recorded as valid."""


class ColourBoundary(BaseException):
    """Raised by the donor's first swatch read: the masks are done and colour would begin.

    A `BaseException`, so no `except Exception` in the donor can swallow it."""

    def __init__(self, swatch: str) -> None:
        super().__init__(swatch)
        self.swatch = swatch


@dataclass(frozen=True)
class Pins:
    """What the producer pins; the defaults are the round's (tests pass stand-ins)."""

    snapshot: str = SNAPSHOT
    sources: tuple[Source, ...] = SOURCES
    runtime: Mapping[str, str] = field(default_factory=lambda: dict(RUNTIME))
    resolution: int = RESOLUTION
    masks: tuple[str, ...] = MASKS
    auxiliary: frozenset[str] = AUXILIARY


PINS = Pins()


# ------------------------------------------------------------------------------------ runtime
def found_runtime() -> dict[str, str]:
    """The running interpreter's and libraries' versions (SciPy and Pillow imported here)."""
    scipy = importlib.import_module("scipy")
    pil = importlib.import_module("PIL")
    features = importlib.import_module("PIL.features")
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": str(scipy.__version__),
        "pillow": str(pil.__version__),
        "pillow_zlib": str(features.version("zlib")),
    }


def runtime_problems(found: Mapping[str, str], pins: Mapping[str, str]) -> list[str]:
    return [
        f"{name} is {found.get(name)!r}, pinned {pinned!r}"
        for name, pinned in pins.items()
        if found.get(name) != pinned
    ]


# ------------------------------------------------------------------------------------ sources
def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def read_source(source: Source, assets_root: Path, commit: str) -> bytes:
    """The raw blob at `commit:path` from Assets3D's object database, every pin checked."""
    run = subprocess.run(
        ["git", "-C", str(assets_root), "cat-file", "blob", f"{commit}:{source.path}"],
        capture_output=True,
        check=False,
    )
    if run.returncode != 0:
        raise MasksError(f"{source.path} is not in Assets3D's object database at {commit[:8]}")
    data = run.stdout
    found = (git_blob_id(data), sha256_bytes(data), len(data))
    if found != (source.blob, source.sha256, source.size_bytes):
        raise MasksError(
            f"{source.path} at {commit[:8]} is blob {found[0]}, sha256 {found[1]}, {found[2]} "
            f"bytes; pinned {source.blob}, {source.sha256}, {source.size_bytes}"
        )
    checkout = source.checkout_sha256
    if checkout is not None and (
        b"\r" in data or sha256_bytes(data.replace(b"\n", b"\r\n")) != checkout
    ):
        raise MasksError(f"{source.path}: its CRLF form is not the pinned checkout")
    return data


def read_sources(assets_root: Path, pins: Pins) -> dict[str, bytes]:
    return {s.name: read_source(s, assets_root, pins.snapshot) for s in pins.sources}


# -------------------------------------------------------------------------------------- split
def _referenced(nodes: Sequence[ast.AST]) -> set[str]:
    """Every bare name and attribute name used anywhere in `nodes`."""
    names: set[str] = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.add(sub.attr)
    return names


def _calls(nodes: Sequence[ast.AST], attribute: str) -> list[ast.Call]:
    return [
        sub
        for node in nodes
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == attribute
    ]


def _first_swatch(nodes: Sequence[ast.AST]) -> str | None:
    for node in nodes:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == BOUNDARY
            ):
                arg = sub.args[0] if sub.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value
                return ast.dump(arg) if arg is not None else "no argument"
    return None


def split_report(code: bytes, masks: Sequence[str] = MASKS) -> dict[str, Any]:
    """The masks/colour split of the donor's `sash`, proven on its source.

    The mask part is `sash`'s body up to and including its one `save_mask` loop. That loop must
    iterate a literal tuple of `(name, value)` pairs naming exactly `masks`, in order. The mask
    part, `Field` and the module's top-level statements reference no swatch name
    (`COLOUR_NAMES`). The colour part (the rest) holds no `save_mask` and reads a swatch before
    anything else touches one: the first `swatch(...)` call is `swatch("cloth")`."""
    tree = ast.parse(code)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    if "sash" not in functions or "Field" not in classes or BOUNDARY not in functions:
        raise MasksError("the donor defines no `sash`, `Field` or `swatch`")
    body = functions["sash"].body
    loops = [k for k, stmt in enumerate(body) if _calls([stmt], "save_mask")]
    if len(loops) != 1 or not isinstance(body[loops[0]], ast.For):
        raise MasksError(f"`sash` writes masks in {len(loops)} statements, not one loop")
    k = loops[0]
    loop = body[k]
    assert isinstance(loop, ast.For)
    pairs = loop.iter.elts if isinstance(loop.iter, ast.Tuple) else None
    names = [
        p.elts[0].value
        for p in pairs or ()
        if isinstance(p, ast.Tuple)
        and len(p.elts) == 2
        and isinstance(p.elts[0], ast.Constant)
        and isinstance(p.elts[0].value, str)
    ]
    if pairs is None or len(names) != len(pairs) or names != list(masks):
        raise MasksError(f"`sash`'s mask loop names {names}, pinned {list(masks)}")
    mask_part, colour_part = body[: k + 1], body[k + 1 :]
    top = [n for n in tree.body if not isinstance(n, ast.FunctionDef | ast.ClassDef)]
    # `Field` may use Pillow (the donor resizes a mismatched AO with it) and defines `save_rgb`;
    # the top level builds the swatch paths (`SW`) but must call no swatch read.
    for what, nodes, forbidden in (
        ("the mask part of `sash`", mask_part, COLOUR_NAMES),
        ("`Field`", [classes["Field"]], COLOUR_NAMES - {"Image", "save_rgb"}),
        ("the module's top level", top, {BOUNDARY}),
    ):
        touched = sorted(_referenced(nodes) & forbidden)
        if touched:
            raise MasksError(f"{what} references {touched}: masks would read colour")
    if _calls(colour_part, "save_mask"):
        raise MasksError("the colour part of `sash` writes a mask")
    if not _calls(colour_part, "save_rgb") or BOUNDARY not in _referenced(colour_part):
        raise MasksError("the colour part of `sash` reads no swatch or writes no colour")
    first = _first_swatch(colour_part)
    if first != FIRST_SWATCH:
        raise MasksError(f"the colour part's first swatch read is {first!r}, not {FIRST_SWATCH!r}")
    return {
        "function": "sash",
        "mask_statements": k + 1,
        "colour_statements": len(colour_part),
        "masks_written": len(names),
        "boundary": f'the first swatch read, {BOUNDARY}("{FIRST_SWATCH}"), in the colour part',
        "proof": "static (ast, pinned bytes) and at run time (ColourBoundary)",
    }


# ------------------------------------------------------------------------------------- donor
def load_donor(code: Mapping[str, bytes], assets_root: Path, pins: Pins) -> types.ModuleType:
    """The pinned modules, executed from their bytes in load order; the donor's imports bind
    them. `sys.path` and `sys.modules` are as before afterwards."""
    root = assets_root.resolve()
    saved_path = list(sys.path)
    saved = {s.name: sys.modules.get(s.name) for s in pins.sources}
    modules: dict[str, types.ModuleType] = {}
    try:
        for source in pins.sources:
            module = types.ModuleType(source.name)
            module.__file__ = str(root / source.path)
            sys.modules[source.name] = module
            exec(compile(code[source.name], module.__file__, "exec"), module.__dict__)
            modules[source.name] = module
    finally:
        sys.path[:] = saved_path
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    donor = modules[DONOR]
    bound = {id(v) for v in vars(donor).values() if isinstance(v, types.ModuleType)}
    unbound = [n for n, m in modules.items() if n != DONOR and id(m) not in bound]
    if unbound:
        raise MasksError(f"the donor does not bind the pinned {unbound}")
    if Path(getattr(donor, "ROOT", "")).resolve() != root:
        raise MasksError(f"the donor's ROOT is {getattr(donor, 'ROOT', None)}, not {root}")
    return donor


class ForbiddenRead(BaseException):
    """Raised by the audit hook when guarded code opens a file under a guarded root."""


_GUARDED: list[Path] = []
_OPENED: list[str] = []
_HOOK: list[bool] = []  # whether the process-wide audit hook is installed


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or not _GUARDED or not args:
        return
    target = args[0]
    if isinstance(target, bytes):
        target = os.fsdecode(target)
    if not isinstance(target, str | os.PathLike):
        return  # a file descriptor
    resolved = Path(os.path.abspath(target))
    for root in _GUARDED:
        if resolved.is_relative_to(root):
            _OPENED.append(str(resolved))
            raise ForbiddenRead(str(resolved))


@contextmanager
def no_reads_under(root: Path) -> Iterator[None]:
    """Refuse every file opened under `root` while the block runs (a `sys.addaudithook` hook,
    installed once per process and active only inside this block). A swallowed refusal is
    still caught: every refused path is kept and checked on exit."""
    if not _HOOK:
        sys.addaudithook(_audit)
        _HOOK.append(True)
    root = Path(os.path.abspath(root))
    start = len(_OPENED)
    _GUARDED.append(root)
    try:
        yield
    except ForbiddenRead as error:
        raise MasksError(f"the donor opened {error} under {root}") from None
    finally:
        _GUARDED.remove(root)
    if len(_OPENED) > start:
        raise MasksError(f"the donor opened {_OPENED[start:]} under {root}")


def _colour_reached(*_: Any) -> None:
    raise MasksError("the donor reached save_rgb: colour was written")


def run_donor(donor: types.ModuleType, run_dir: Path, resolution: int) -> tuple[Any, str]:
    """`waist_masks.main`'s sash path up to the colour boundary: the construction from the
    staged centre, the `Field`, then `sash` until its first swatch read."""
    with np.load(run_dir / host.CENTRE_NPZ, allow_pickle=False) as archive:
        construction = dict(archive)
    vars(donor)[BOUNDARY] = _boundary
    donor.Field.save_rgb = _colour_reached
    field_ = donor.Field(run_dir, resolution, construction)
    try:
        donor.sash(field_, construction, run_dir)
    except ColourBoundary as stop:
        return field_, stop.swatch
    raise MasksError("`sash` returned without reading a swatch: no colour boundary")


def _boundary(name: str) -> Any:
    raise ColourBoundary(name)


# ------------------------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Inputs:
    receipts: dict[str, dict[str, Any]]
    arrays: dict[str, dict[str, Any]]
    files: dict[str, Path]
    extraction_sha256: str


def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def _no_constant(name: str) -> Any:
    raise MasksError(f"a record holds the non-JSON constant {name}")


def _record(path: Path, kind: str) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    record = json.loads(data, parse_constant=_no_constant)
    if (_get(record, ("schema",)), _get(record, ("kind",))) != (host.RECORD_SCHEMA, kind):
        raise MasksError(f"{path} is not a {host.RECORD_SCHEMA} {kind} record")
    return record, sha256_bytes(data)


def _output(record: Mapping[str, Any], record_path: Path, name: str) -> tuple[Path, str, int]:
    """A file a record names, next to it, whose bytes still hash to the record."""
    sha256 = _get(record, ("outputs", name, "sha256"))
    path = record_path.parent / name
    if not isinstance(sha256, str) or not path.is_file() or sha256_file(path) != sha256:
        raise MasksError(f"{path} is missing or does not hash to its record's {sha256}")
    return path, sha256, path.stat().st_size


def _members(path: Path, names: Sequence[str]) -> dict[str, bytes]:
    """The archive's members, refused unless they are exactly `<name>.npy` in `names`' order."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        found = [info.filename for info in infos]
        if found != [f"{name}.npy" for name in names]:
            raise MasksError(f"{path} holds {found}, not {[f'{n}.npy' for n in names]}")
        return {name: archive.read(info) for name, info in zip(names, infos, strict=True)}


def check_inputs(
    extraction: Path,
    ao: Path,
    centre: Path,
    resolution: int,
    verify_extraction: Callable[[Path], dict[str, Any]] = host.load_extraction,
) -> Inputs:
    """Front P's three receipts and the four files the donor reads, each checked by hash."""
    link = sha256_file(extraction)
    record = verify_extraction(extraction)
    if sha256_file(extraction) != link or json.loads(extraction.read_bytes()) != record:
        raise MasksError(f"{extraction} changed while it was checked")
    if (record.get("schema"), record.get("kind")) != (host.RECORD_SCHEMA, "extract"):
        raise MasksError(f"{extraction} is not a {host.RECORD_SCHEMA} extraction record")
    receipts: dict[str, dict[str, Any]] = {
        "extraction": {
            "path": str(extraction),
            "sha256": link,
            "schema": record["schema"],
            "kind": "extract",
        }
    }
    files: dict[str, Path] = {}
    arrays: dict[str, dict[str, Any]] = {}

    low, low_sha, low_size = _output(record, extraction, host.LOW_NPZ)
    members = _members(low, list(side.LOW_ARRAYS))
    member_hashes = {}
    for name, data in members.items():
        loose = host.LOW_FILES[name]
        if sha256_bytes(data) != _get(record, ("outputs", loose, "sha256")):
            raise MasksError(f"{low}: member {name} is not the recorded {loose}")
        array = np.load(io.BytesIO(data), allow_pickle=False)
        if side.array_digest(array) != _get(record, ("low", "digests", name)):
            raise MasksError(f"{low}: member {name} differs from its recorded digest")
        member_hashes[name] = sha256_bytes(data)
    files["low"] = low
    arrays[host.LOW_NPZ] = {
        "receipt": "extraction",
        "sha256": low_sha,
        "size_bytes": low_size,
        "members_sha256": member_hashes,
    }

    normal, normal_sha, normal_size = _output(record, extraction, host.HIGHNORMAL)
    array = np.load(normal, allow_pickle=False)
    if array.dtype.str != "<f4" or array.shape != (resolution, resolution, 3):
        raise MasksError(f"{normal} is {array.dtype.str}{list(array.shape)}")
    if side.array_digest(array) != _get(record, ("normal", "digest")):
        raise MasksError(f"{normal} differs from its recorded digest")
    files["highnormal"] = normal
    arrays[host.HIGHNORMAL] = {
        "receipt": "extraction",
        "sha256": normal_sha,
        "size_bytes": normal_size,
        "digest": side.array_digest(array),
    }

    ao_record, ao_receipt = _record(ao, "ao")
    if _get(ao_record, ("extraction", "record_sha256")) != link:
        raise MasksError(f"{ao} cites another extraction than {link}")
    if _get(ao_record, ("ao", "low", "digests")) != _get(record, ("low", "digests")):
        raise MasksError(f"{ao} baked another low than the extraction's")
    ao_path, ao_sha, ao_size = _output(ao_record, ao, side.AO_NAME)
    occlusion = np.load(ao_path, allow_pickle=False)
    if occlusion.dtype.str != "<f2" or occlusion.shape != (resolution, resolution):
        raise MasksError(f"{ao_path} is {occlusion.dtype.str}{list(occlusion.shape)}")
    if not np.isfinite(occlusion).all() or occlusion.min() < 0 or occlusion.max() > 1:
        raise MasksError(f"{ao_path} holds values outside [0, 1]")
    if side.array_digest(occlusion) != _get(ao_record, ("ao", "digest")):
        raise MasksError(f"{ao_path} differs from its recorded digest")
    receipts["ao"] = {"path": str(ao), "sha256": ao_receipt, "schema": host.RECORD_SCHEMA}
    receipts["ao"] |= {"kind": "ao", "extraction_record_sha256": link}
    files["ao"] = ao_path
    arrays[side.AO_NAME] = {
        "receipt": "ao",
        "sha256": ao_sha,
        "size_bytes": ao_size,
        "digest": side.array_digest(occlusion),
    }

    centre_record, centre_receipt = _record(centre, "centre")
    if centre_record.get("status") != CENTRE_STATUS:
        raise MasksError(f"{centre} is {centre_record.get('status')!r}, not {CENTRE_STATUS!r}")
    if _get(centre_record, ("extraction", "record_sha256")) != link:
        raise MasksError(f"{centre} cites another extraction than {link}")
    centre_path, centre_sha, centre_size = _output(centre_record, centre, host.CENTRE_NPZ)
    with np.load(centre_path, allow_pickle=False) as archive:
        stored = {name: archive[name] for name in archive.files}
    value = stored.get("centre")
    if (
        list(stored) != ["centre"]
        or value is None
        or value.dtype.str != "<f8"
        or value.shape != (2,)
        or not np.isfinite(value).all()
        or value.tolist() != centre_record.get("centre")
    ):
        raise MasksError(f"{centre_path} is not the recorded finite float64 centre")
    receipts["centre"] = {
        "path": str(centre),
        "sha256": centre_receipt,
        "schema": host.RECORD_SCHEMA,
    }
    receipts["centre"] |= {"kind": "centre", "status": CENTRE_STATUS}
    receipts["centre"] |= {"extraction_record_sha256": link}
    files["centre"] = centre_path
    arrays[host.CENTRE_NPZ] = {
        "receipt": "centre",
        "sha256": centre_sha,
        "size_bytes": centre_size,
        "centre": value.tolist(),
    }
    return Inputs(receipts=receipts, arrays=arrays, files=files, extraction_sha256=link)


# ------------------------------------------------------------------------------------ outputs
def check_masks(run_dir: Path, field_: Any, pins: Pins) -> list[dict[str, Any]]:
    """Each mask's form, orientation and padding on its bytes, and its role."""
    res = pins.resolution
    valid = np.asarray(field_.valid)
    rows, cols = np.asarray(field_.idx[0]), np.asarray(field_.idx[1])
    if valid.shape != (res, res) or rows.shape != (res, res) or cols.shape != (res, res):
        raise MasksError(f"the donor's texel field is {list(valid.shape)}, not {res}²")
    if list(field_.out) != list(pins.masks):
        raise MasksError(f"the donor wrote {list(field_.out)}, pinned {list(pins.masks)}")
    outputs = []
    for name in pins.masks:
        path = run_dir / f"{name}.png"
        data = path.read_bytes()
        header = png.chunks(data)[0][1] if data.startswith(png.SIGNATURE) else b""
        if len(header) != 13:
            raise MasksError(f"{path} is not a PNG")
        width, height, depth, colour = (
            int.from_bytes(header[0:4], "big"),
            int.from_bytes(header[4:8], "big"),
            header[8],
            header[9],
        )
        if (width, height, (depth, colour)) != (res, res, MASK_FORM):
            raise MasksError(f"{path} is {width}x{height} depth {depth} colour type {colour}")
        bottom_first = png.decode(data)[::-1, :, 0]
        if not np.array_equal(bottom_first, bottom_first[rows, cols]):
            raise MasksError(f"{path}: a texel is not its nearest island texel (padding)")
        outputs.append(
            {
                "name": name,
                "file": path.name,
                "role": ROLES["auxiliary"] if name in pins.auxiliary else ROLES["stack"],
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
                "shape": [height, width],
                "depth": depth,
                "colour_type": colour,
                "coverage_mean": field_.out[name],
            }
        )
    return outputs


# ---------------------------------------------------------------------------------- producer
@dataclass(frozen=True)
class Plan:
    run_dir: Path
    code: dict[str, bytes]
    split: dict[str, Any]
    inputs: Inputs
    runtime: dict[str, str]
    expected: dict[str, Any] | None
    expected_path: Path | None
    expected_sha256: str | None  # of the bytes `expected` was parsed from

    def as_json(self, pins: Pins) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "sources": [s.as_json(pins.snapshot) for s in pins.sources],
            "runtime": self.runtime,
            "split": self.split,
            "receipts": self.inputs.receipts,
            "arrays": self.inputs.arrays,
            "expect": str(self.expected_path) if self.expected_path else None,
        }


def plan(
    run_dir: Path,
    assets_root: Path,
    extraction: Path,
    ao: Path,
    centre: Path,
    *,
    expect: Path | None = None,
    pins: Pins = PINS,
    runtime: Callable[[], dict[str, str]] = found_runtime,
    verify_extraction: Callable[[Path], dict[str, Any]] = host.load_extraction,
) -> Plan:
    """Every check that needs no output: runtime, sources, split, inputs, the earlier record."""
    run_dir = ensure_outside_repository(run_dir)
    if run_dir.exists():
        raise MasksError(f"{run_dir} already exists; every run gets a fresh directory")
    found = runtime()
    problems = runtime_problems(found, pins.runtime)
    if problems:
        raise MasksError("the runtime is not pinned: " + "; ".join(problems))
    code = read_sources(assets_root, pins)
    split = split_report(code[DONOR], pins.masks)
    inputs = check_inputs(extraction, ao, centre, pins.resolution, verify_extraction)
    expected, expected_sha256 = None, None
    if expect is not None:
        data = expect.read_bytes()
        expected, expected_sha256 = (
            json.loads(data, parse_constant=_no_constant),
            sha256_bytes(data),
        )
        if _get(expected, ("schema",)) != RECORD_SCHEMA or _get(expected, ("kind",)) != "masks":
            raise MasksError(f"{expect} is not a {RECORD_SCHEMA} record")
        if _get(expected, ("status",)) not in BASELINE_STATUSES:
            raise MasksError(f"{expect} is {_get(expected, ('status',))!r}, not a baseline")
    return Plan(run_dir, code, split, inputs, found, expected, expect, expected_sha256)


def helper_json() -> dict[str, Any]:
    def pin(path: str) -> dict[str, str]:
        return {"path": path, "sha256": sha256_file(REPO_ROOT / path)}

    return {
        **pin(Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()),
        "checks_with": [
            pin(Path(module.__file__ or "").resolve().relative_to(REPO_ROOT).as_posix())
            for module in (host, side, png)
        ],
    }


def host_json() -> dict[str, Any]:
    """The machine and interpreter build: a repeat must run on the same."""
    return {
        "python_executable": sys.executable,
        "python_build": list(platform.python_build()),
        "python_compiler": platform.python_compiler(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def produce(
    the_plan: Plan, assets_root: Path, pins: Pins = PINS
) -> tuple[dict[str, Any], list[str]]:
    """Stage the inputs, run the donor to its colour boundary, check and record the masks."""
    run_dir = the_plan.run_dir
    run_dir.mkdir(parents=True, exist_ok=False)
    staged = {}
    for key, source in the_plan.inputs.files.items():
        target = run_dir / INPUT_FILES[key]
        shutil.copyfile(source, target)
        staged[target.name] = sha256_file(target)
        if staged[target.name] != the_plan.inputs.arrays[target.name]["sha256"]:
            raise MasksError(f"the staged {target} differs from {source}")
    with no_reads_under(assets_root):
        donor = load_donor(the_plan.code, assets_root, pins)
        field_, swatch = run_donor(donor, run_dir, pins.resolution)
    if swatch != FIRST_SWATCH:
        raise MasksError(f"the colour boundary was swatch({swatch!r}), not {FIRST_SWATCH!r}")
    expected = set(staged) | {f"{name}.png" for name in pins.masks}
    present = {path.name for path in run_dir.iterdir()}
    if present != expected:
        raise MasksError(
            f"{run_dir}: unexpected {sorted(present - expected)}, "
            f"missing {sorted(expected - present)}"
        )
    for name, sha256 in staged.items():
        if sha256_file(run_dir / name) != sha256:
            raise MasksError(f"the donor changed its input {name}")
    outputs = check_masks(run_dir, field_, pins)
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": "masks",
        "status": "produced",
        "piece": "sash",
        "run_dir": str(run_dir),
        "helper": helper_json(),
        "sources": [s.as_json(pins.snapshot) for s in pins.sources],
        "runtime": dict(pins.runtime),
        "host": host_json(),
        "parameters": {
            "resolution": pins.resolution,
            "orientation": ORIENTATION,
            "padding": PADDING,
            "quantisation": QUANTISATION,
            "png": {"bit_depth": MASK_FORM[0], "colour_type": MASK_FORM[1]},
        },
        "receipts": the_plan.inputs.receipts,
        "extraction_link": {
            "extraction_record_sha256": the_plan.inputs.extraction_sha256,
            "cited_by": ["ao", "centre"],
        },
        "arrays": the_plan.inputs.arrays,
        "split": the_plan.split | {"boundary_reached": f'{BOUNDARY}("{swatch}")'},
        "texels": int(np.asarray(field_.valid).sum()),
        "outputs": outputs,
        "stack_inputs": [o["name"] for o in outputs if o["role"] == ROLES["stack"]],
        "auxiliary": [o["name"] for o in outputs if o["role"] == ROLES["auxiliary"]],
        "substitute": SUBSTITUTE,
        "colour": COLOUR,
        "repeat": {
            "result": "not-a-repeat",
            "note": "a repeat with --expect must agree byte for byte",
        },
    }
    problems: list[str] = []
    if the_plan.expected is not None:
        assert the_plan.expected_path is not None
        problems = compare_records(record, the_plan.expected)
        record["status"] = "not-reproduced" if problems else "reproduced"
        record["repeat"] = {
            "of_record": str(the_plan.expected_path),
            "of_record_sha256": the_plan.expected_sha256,
            "result": "differs" if problems else "byte-identical",
            "problems": problems,
        }
    text = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    partial = run_dir / (RECORD_NAME + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, run_dir / RECORD_NAME)
    return record, problems


# ------------------------------------------------------------------------------------ repeats
REPEAT_FIELDS = (
    "schema",
    "kind",
    "piece",
    "helper",
    "sources",
    "runtime",
    "host",
    "parameters",
    "receipts",
    "extraction_link",
    "arrays",
    "split",
    "texels",
    "outputs",
    "stack_inputs",
    "auxiliary",
    "substitute",
    "colour",
)
RUN_KEYS = frozenset({"path", "run_dir"})


def _without_run(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _without_run(v) for k, v in value.items() if k not in RUN_KEYS}
    if isinstance(value, list):
        return [_without_run(v) for v in value]
    return value


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """What a repeat must reproduce: every pin, input hash and output, byte for byte; only the
    paths that name a run differ."""
    return [
        f"{key} is {_without_run(record.get(key))!r}, the earlier run's "
        f"{_without_run(expected.get(key))!r}"
        for key in REPEAT_FIELDS
        if _without_run(record.get(key)) != _without_run(expected.get(key))
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.sash_masks",
        description="The Sash v5 current round's 20 masks (waist_masks.py sash, masks only).",
    )
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument("--ao", type=Path, required=True, help="front P's AO record")
    parser.add_argument("--extraction", type=Path, help="front P's extraction record")
    parser.add_argument("--centre", type=Path, help="front P's centre record")
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's masks-record.json")
    parser.add_argument("--dry-run", action="store_true", help="check, print the plan")
    args = parser.parse_args(argv)
    try:
        work = work_root()
        run_dir = host.run_dir_for(args.run, work)
        the_plan = plan(
            run_dir,
            args.assets_root,
            args.extraction or work / DEFAULT_EXTRACTION,
            args.ao,
            args.centre or work / DEFAULT_CENTRE,
            expect=args.expect,
        )
        if args.dry_run:
            print(json.dumps(the_plan.as_json(PINS), indent=2))
            return 0
        record, problems = produce(the_plan, args.assets_root)
    except (ExtractError, RecorderError, StoreError, OSError, ValueError, KeyError) as error:
        print(f"sash_masks: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    for problem in problems:
        print(f"sash_masks: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
