r"""The Sash v5 current round's `T_sash`, from Assets3D `waist_masks.py sash` (decision 300 §7).

    python -m tools.parity.tier1.sash_colour --assets-root <Assets3D> --ao <AO record>
        [--extraction <record>] [--centre <record>] [--masks <masks-record.json>]
        [--cloth <swatch provenance>] [--hem <swatch provenance>] [--run NAME]
        [--expect <earlier colour-record.json>] [--dry-run]

The colour producer of the current round. It writes one file, `T_sash.png`. It is technical
preparation, not a baseline approval (decision 300 item 8). It cannot run until both swatches
exist with a provenance record each: the originals are lost, and no substitute is authorized.

1. **The donor is front T's.** The same three modules, read as raw git blobs of `SNAPSHOT` and
   checked against their pins (`sash_masks.read_sources`), are loaded the same way
   (`sash_masks.load_donor`), with the same static split (`sash_masks.split_report`). The donor's
   `Field` and `sash` run unchanged, past the colour boundary this time.
2. **Three remaps, nothing reimplemented.**
   - `SW`: the donor's `cloth` and `hem` entries must name their pinned Assets3D paths
     (`SWATCH_PATHS`). They are replaced by the verified private copies staged in the run
     directory; no other swatch is reachable. Every `swatch(...)` read is recorded and re-hashes
     its copy first. The reads must be exactly `cloth`, then `hem`.
   - `Field.save_mask` compares instead of writing: the donor's own `save_mask` encodes each mask
     into memory, and its bytes and mean must equal front T's accepted, reproduced masks record
     (`--masks`), mask by mask and in order. Any difference refuses the run.
   - `Field.save_rgb` writes `T_sash` only, once, into the run directory, through the donor's own
     `save_rgb`. The file must be a `RESOLUTION`² 8-bit RGB PNG, padded the donor's way.
3. **Inputs.** Front P's extraction, AO and centre records, checked as front T checks them
   (`sash_masks.check_inputs`); T's masks record, which must cite the same three receipts and
   arrays and vouch for 20 files that still hash to it; and one swatch provenance record per
   swatch (`SWATCH_SCHEMA`, `load_swatch`). Every receipt, swatch image, prompt file and visual
   reference the plan verified in place, and every staged file, is hashed before and after the
   run, and the two must agree.
4. **Swatch provenance.** A swatch is accepted only with a record that names its source: an
   `original`, which names the pinned `v5.json` by that file's own SHA-256 (`v5_json_sha256`)
   and whose image must hash to what that manifest lists for its path, or a `generated`
   substitute. A generated one names its generator, model and concrete generation
   route, a prompt file and every visual reference the generation used (a typed list of role,
   private file, SHA-256 and size; an explicitly empty list only when it used none). The prompt
   and the references are files next to the record, verified by hash. Its
   `authorization_declaration` is recorded as declared: it is neither a technical approval nor
   an authorization, and this helper never generates an image or calls an API. The image must
   be a complete, decodable, non-interlaced 8-bit RGB or RGBA PNG of the recorded bytes, size
   and form (no missing or empty file). The two swatches must differ.
5. **Receipt.** `colour-record.json` (`RECORD_SCHEMA`) is written last, atomically, and only
   after every check has passed. A repeat (`--expect`, whose baseline must be `produced` or
   `reproduced`) runs from scratch in a fresh directory and process, and must agree on every
   field but the run's own paths: `reproduced`, or `not-reproduced` with the differences
   (exit 1). Front R's consumer accepts only `reproduced`.

`--dry-run` checks the pins, the split, every receipt and both swatches, and prints the plan. It
writes nothing.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import types
from collections.abc import Callable, Mapping, Sequence
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
from tools.parity.tier1 import sash_masks as masks
from tools.parity.tier1.sash_intermediates_blender import ExtractError
from tools.parity.tier1.sash_masks import MasksError

RECORD_SCHEMA = "uzpainter/parity/sash-colour-record/1"
RECORD_NAME = "colour-record.json"
SWATCH_SCHEMA = "uzpainter/parity/sash-swatch-provenance/1"
SWATCH_RECORD_NAME = "swatch-provenance.json"
DEFAULT_RUN = host.RUN_PREFIX + "colour-r1"
DEFAULT_MASKS = host.RUN_PREFIX + "masks-r1-repeat/" + masks.RECORD_NAME
DEFAULT_SWATCH_RUNS = {
    "cloth": host.RUN_PREFIX + "swatch-cloth",
    "hem": host.RUN_PREFIX + "swatch-hem",
}
BASELINE_STATUSES = masks.BASELINE_STATUSES

COLOUR = "T_sash"
COLOUR_FORM = (8, 2)  # IHDR bit depth and colour type (RGB); sash_current's T_sash form
SWATCH_DEPTH = 8
SWATCH_COLOUR_TYPES = frozenset({2, 6})  # RGB or RGBA, as sash_current accepts a swatch
SWATCHES = ("cloth", "hem")  # the donor's reads, in its order
PIECE = "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura"
SWATCH_PATHS = {  # the donor's SW entries, relative to its ROOT
    "cloth": f"{PIECE}/Textures/Swatches/sash-cloth-BaseColor-v1.png",
    "hem": f"{PIECE}/Textures/Swatches/hem-leather-BaseColor-v1.png",
}
SWATCH_FILES = {name: Path(path).name for name, path in SWATCH_PATHS.items()}
# The lost originals' SHA-256 as the pinned v5.json lists them (`amostra-pano`,
# `amostra-couro-abas`): an `original` provenance must match these.
ORIGINALS = {
    "cloth": "5ab8cdf3edefbac2f35613bae9b2fbe49fea2754da2c1e8ca8bf5fa32bd518a9",
    "hem": "546bba43d7291d29a70ac2bf26f234f62802feeb8be47d8f1c99a6719a80c5b7",
}
MANIFEST = masks.Source(
    "v5.json",
    f"{PIECE}/manifests/v5.json",
    "fbc4f4c4bcd1b538f73fb530c7967ab1a98796af",
    "c5566c38a6a1ff64318d375d1819717d4bd96a6f7e00b1b5fc13d905f6800c88",
    24_624,
)
QUANTISATION = "uint8(clip(rgb, 0, 1) * 255 + 0.5), Pillow RGB PNG (the donor's save_rgb)"

SOURCE_TYPES = {
    "original": frozenset({"type", "assets3d_path", "v5_json_sha256"}),
    "generated": frozenset(
        {
            "type",
            "generator",
            "model",
            "route",
            "prompt_file",
            "prompt_sha256",
            "references",
            "authorization_declaration",
        }
    ),
}
REFERENCE_KEYS = frozenset({"role", "file", "sha256", "size_bytes"})
CLASSIFICATIONS = {"original": "original", "generated": "current-round substitute"}
SWATCH_KEYS = frozenset({"schema", "kind", "swatch", "file", "image", "source", "classification"})
IMAGE_KEYS = frozenset({"sha256", "size_bytes", "width", "height", "bit_depth", "colour_type"})
PLACEHOLDER_TEXT = frozenset(
    {
        "",
        "-",
        "?",
        "todo",
        "tbd",
        "placeholder",
        "unknown",
        "none",
        "null",
        "n/a",
        "na",
        "fake",
        "dummy",
        "test",
        "stand-in",
        "pending",
    }
)
SHA256 = re.compile(r"[0-9a-f]{64}")
EMPTY_SHA256 = sha256_bytes(b"")

SUBSTITUTE = {
    "classification": "current-round substitute",
    "replaces": "the T_sash waist_masks.py sash wrote in the lost sashchain.sh round",
    "made_from": "front P's current-round intermediates and construction centre (the field "
    "front T's reproduced masks run was made from) and the two swatches their provenance "
    "records name",
    "historical": "not the historical T_sash; its bytes are lost and unestablished",
}


class ColourError(MasksError):
    """A pin, an input, a swatch, the masks comparison or the output does not hold."""


class _Refused(BaseException):
    """Raised inside the donor; a `BaseException`, so no `except Exception` there swallows it."""


@dataclass(frozen=True)
class Pins:
    """What the producer pins; the defaults are the round's (tests pass stand-ins)."""

    donor: masks.Pins = masks.PINS  # front T's: snapshot, sources, runtime, resolution, masks
    manifest: masks.Source = MANIFEST
    originals: Mapping[str, str] = field(default_factory=lambda: dict(ORIGINALS))


PINS = Pins()


# ---------------------------------------------------------------------------------- swatches
@dataclass(frozen=True)
class Swatch:
    name: str
    record_path: Path
    record_sha256: str
    image: Path
    entry: dict[str, Any]  # what the colour record says of this swatch
    # A generated swatch's prompt and visual references: (label, file, verified SHA-256).
    side_files: tuple[tuple[str, Path, str], ...] = ()


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or value.strip().lower() in PLACEHOLDER_TEXT:
        raise ColourError(f"{what} is {value!r}: a placeholder or no text")
    return value


def _digest(value: Any, what: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value) or value == EMPTY_SHA256:
        raise ColourError(f"{what} is {value!r}, not the SHA-256 of some bytes")
    return value


def _side_file(folder: Path, value: Any, what: str) -> Path:
    """A file the record names by its plain name, next to the record."""
    name = _text(value, what)
    path = folder / name
    if Path(name).name != name or not path.is_file():
        raise ColourError(f"{what}: {name!r} is not a file next to the record")
    return path


def manifest_originals(assets_root: Path, pins: Pins) -> dict[str, str]:
    """Each swatch's SHA-256 as the pinned `v5.json` blob lists it, checked against its pin."""
    data = masks.read_source(pins.manifest, assets_root, pins.donor.snapshot)
    files = json.loads(data, parse_constant=masks._no_constant).get("files")
    found = {}
    for name, path in SWATCH_PATHS.items():
        entries = [
            e for e in (files or {}).values() if isinstance(e, Mapping) and e.get("path") == path
        ]
        digest = entries[0].get("sha256") if len(entries) == 1 else None
        if not isinstance(digest, Mapping) or digest.get("algorithm") != "sha256":
            raise ColourError(f"{pins.manifest.path} lists {path} {len(entries)} times")
        found[name] = digest.get("value")
    if found != dict(pins.originals):
        raise ColourError(f"{pins.manifest.path} lists {found}, pinned {dict(pins.originals)}")
    return {name: str(value) for name, value in found.items()}


def _ihdr(data: bytes) -> bytes:
    """A PNG's IHDR body, or nothing when the bytes are no PNG."""
    try:
        return png.chunks(data)[0][1] if data.startswith(png.SIGNATURE) else b""
    except Exception:
        return b""


def check_image(path: Path, image: Mapping[str, Any], what: str) -> None:
    """A complete, decodable swatch PNG of its record's bytes, size and form."""
    if set(image) != IMAGE_KEYS:
        raise ColourError(f"{what}: `image` holds {sorted(image)}, not {sorted(IMAGE_KEYS)}")
    if not path.is_file() or path.stat().st_size == 0:
        raise ColourError(f"{what}: {path} is missing or empty")
    data = path.read_bytes()
    if (sha256_bytes(data), len(data)) != (image["sha256"], image["size_bytes"]):
        raise ColourError(f"{what}: {path} does not hash to its record")
    header = _ihdr(data)
    if len(header) != 13:
        raise ColourError(f"{what}: {path} is not a PNG")
    width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
    form = (width, height, header[8], header[9])
    recorded = (image["width"], image["height"], image["bit_depth"], image["colour_type"])
    if form != recorded:
        raise ColourError(f"{what}: {path} is {form}, its record says {recorded}")
    if header[8] != SWATCH_DEPTH or header[9] not in SWATCH_COLOUR_TYPES or header[12] != 0:
        raise ColourError(f"{what}: {path} is not a non-interlaced 8-bit RGB or RGBA PNG")
    try:
        png.decode(data)
    except Exception as error:
        raise ColourError(f"{what}: {path} does not decode: {error}") from None


def load_swatch(
    path: Path, name: str, originals: Mapping[str, str], manifest_sha256: str
) -> Swatch:
    """A swatch provenance record (`SWATCH_SCHEMA`) and the image next to it, both checked. An
    original names the pinned `v5.json` by its own SHA-256 (`manifest_sha256`); its image must
    hash to what that manifest lists for its path (`originals`)."""
    what = f"the {name} swatch record {path}"
    data = path.read_bytes()
    record = json.loads(data, parse_constant=masks._no_constant)
    if not isinstance(record, dict) or set(record) != SWATCH_KEYS:
        found = sorted(record) if isinstance(record, dict) else type(record).__name__
        raise ColourError(f"{what} holds {found}, not {sorted(SWATCH_KEYS)}")
    if (record["schema"], record["kind"], record["swatch"]) != (SWATCH_SCHEMA, "swatch", name):
        raise ColourError(f"{what} is not a {SWATCH_SCHEMA} record of the {name} swatch")
    if record["file"] != SWATCH_FILES[name]:
        raise ColourError(f"{what} names {record['file']!r}, not {SWATCH_FILES[name]!r}")
    image, source = record["image"], record["source"]
    if not isinstance(image, dict) or not isinstance(source, dict):
        raise ColourError(f"{what}: `image` and `source` must be objects")
    kind = source.get("type")
    if not isinstance(kind, str) or kind not in SOURCE_TYPES or set(source) != SOURCE_TYPES[kind]:
        raise ColourError(f"{what}: source {sorted(source)} is no known source type")
    if record["classification"] != CLASSIFICATIONS[kind]:
        raise ColourError(f"{what}: a {kind} swatch is classified {record['classification']!r}")
    image_path = path.parent / record["file"]
    check_image(image_path, image, what)
    side_files: list[tuple[str, Path, str]] = []
    if kind == "original":
        if source["assets3d_path"] != SWATCH_PATHS[name]:
            raise ColourError(f"{what}: the original is {source['assets3d_path']!r}")
        if source["v5_json_sha256"] != manifest_sha256:
            raise ColourError(f"{what}: v5_json_sha256 is not the pinned v5.json's own SHA-256")
        if image["sha256"] != originals[name]:
            raise ColourError(f"{what}: the image is not the original v5.json lists")
    else:
        for key in ("generator", "model", "route", "authorization_declaration"):
            _text(source[key], f"{what}: {key}")
        prompt = _side_file(path.parent, source["prompt_file"], f"{what}: prompt_file")
        digest = _digest(source["prompt_sha256"], f"{what}: prompt_sha256")
        if sha256_file(prompt) != digest:
            raise ColourError(f"{what}: {prompt} does not hash to prompt_sha256")
        side_files.append((f"prompt-{name}", prompt, digest))
        references = source["references"]
        if not isinstance(references, list):
            raise ColourError(f"{what}: references must be a list (empty only if none was used)")
        taken = {path.name, image_path.name, prompt.name}
        for k, reference in enumerate(references):
            label = f"{what}: reference {k}"
            if not isinstance(reference, dict) or set(reference) != REFERENCE_KEYS:
                raise ColourError(f"{label} is not an object of {sorted(REFERENCE_KEYS)}")
            _text(reference["role"], f"{label} role")
            file = _side_file(path.parent, reference["file"], f"{label} file")
            if file.name in taken:
                raise ColourError(f"{label}: {file.name} is already named by this record")
            taken.add(file.name)
            digest = _digest(reference["sha256"], f"{label} sha256")
            if (sha256_file(file), file.stat().st_size) != (digest, reference["size_bytes"]):
                raise ColourError(f"{label}: {file} does not hash to its entry")
            side_files.append((f"reference-{name}-{file.name}", file, digest))
        if image["sha256"] in originals.values():
            raise ColourError(f"{what}: a generated swatch has an original's bytes")
    entry = {
        "file": record["file"],
        "assets3d_path": SWATCH_PATHS[name],
        "classification": record["classification"],
        "source": source,
        **{key: image[key] for key in sorted(IMAGE_KEYS)},
    }
    return Swatch(name, path, sha256_bytes(data), image_path, entry, tuple(side_files))


# ------------------------------------------------------------------------------- masks record
@dataclass(frozen=True)
class MasksRecord:
    path: Path
    sha256: str
    outputs: dict[str, dict[str, Any]]  # by mask name, in the donor's order
    texels: int
    receipt: dict[str, Any]


def check_masks_record(path: Path, inputs: masks.Inputs, pins: masks.Pins) -> MasksRecord:
    """Front T's accepted masks record: a byte-identical repeat, made from the same pins, P
    receipts and arrays as this run, whose 20 masks still hash to it."""
    data = path.read_bytes()
    record = json.loads(data, parse_constant=masks._no_constant)
    get = masks._get
    if (get(record, ("schema",)), get(record, ("kind",))) != (masks.RECORD_SCHEMA, "masks"):
        raise ColourError(f"{path} is not a {masks.RECORD_SCHEMA} record")
    repeat = get(record, ("repeat",)) or {}
    if get(record, ("status",)) != "reproduced" or (
        get(repeat, ("result",)),
        get(repeat, ("problems",)),
    ) != ("byte-identical", []):
        raise ColourError(f"{path} is no byte-identical, reproduced masks repeat")
    of_record = _digest(get(repeat, ("of_record_sha256",)), f"{path}: of_record_sha256")
    if get(record, ("sources",)) != [s.as_json(pins.snapshot) for s in pins.sources]:
        raise ColourError(f"{path} was made from other sources than the pinned three")
    if get(record, ("runtime",)) != dict(pins.runtime):
        raise ColourError(f"{path} was made with another runtime")
    if get(record, ("parameters", "resolution")) != pins.resolution:
        raise ColourError(f"{path} is not at {pins.resolution}")
    for role, receipt in inputs.receipts.items():
        if get(record, ("receipts", role, "sha256")) != receipt["sha256"]:
            raise ColourError(f"{path} cites another {role} receipt than this run's")
    for name, array in inputs.arrays.items():
        if get(record, ("arrays", name, "sha256")) != array["sha256"]:
            raise ColourError(f"{path} consumed another {name} than this run's")
    outputs = get(record, ("outputs",))
    names = [get(o, ("name",)) for o in outputs] if isinstance(outputs, list) else None
    if names != list(pins.masks):
        raise ColourError(f"{path} records the masks {names}, pinned {list(pins.masks)}")
    by_name: dict[str, dict[str, Any]] = {}
    for output in outputs:
        mask = path.parent / f"{output['name']}.png"
        if output.get("file") != mask.name or not mask.is_file():
            raise ColourError(f"{path}: {mask} is missing")
        if (sha256_file(mask), mask.stat().st_size) != (output["sha256"], output["size_bytes"]):
            raise ColourError(f"{mask} does not hash to {path}")
        by_name[output["name"]] = output
    texels = get(record, ("texels",))
    if not isinstance(texels, int) or texels <= 0:
        raise ColourError(f"{path} records {texels!r} texels")
    receipt = {
        "path": str(path),
        "sha256": sha256_bytes(data),
        "schema": masks.RECORD_SCHEMA,
        "kind": "masks",
        "status": "reproduced",
        "of_record_sha256": of_record,
    }
    return MasksRecord(path, sha256_bytes(data), by_name, texels, receipt)


# ------------------------------------------------------------------------------------- donor
class _Memory(io.BytesIO):
    """An in-memory file Pillow writes to; its `name` gives Pillow the format."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class _Sink:
    """What the donor's `save_mask` takes as `out`: `out / name` is one in-memory file."""

    def __init__(self) -> None:
        self.files: dict[str, _Memory] = {}

    def __truediv__(self, name: str) -> _Memory:
        if self.files:
            raise _Refused("save_mask wrote two files")
        self.files[name] = _Memory(name)
        return self.files[name]


@dataclass
class Trace:
    """What the donor did while it ran under the remaps."""

    compared: list[str] = field(default_factory=list)
    swatches: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def refuse(self, problem: str) -> None:
        self.problems.append(problem)
        raise _Refused(problem)


def remap(
    donor: types.ModuleType,
    run_dir: Path,
    expected: MasksRecord,
    staged: Mapping[str, str],
    pins: masks.Pins,
) -> Trace:
    """The three remaps: `SW` to the staged copies, `save_mask` to a comparison against front T's
    record, `save_rgb` to the one `T_sash` write."""
    trace = Trace()
    root = Path(donor.ROOT)
    sw = vars(donor).get("SW")
    if not isinstance(sw, Mapping) or any(
        Path(sw.get(name, "")) != root / SWATCH_PATHS[name] for name in SWATCHES
    ):
        raise ColourError(f"the donor's SW does not name {sorted(SWATCH_PATHS.values())}")
    copies = {name: run_dir / SWATCH_FILES[name] for name in SWATCHES}
    vars(donor)["SW"] = dict(copies)
    read = donor.swatch

    def swatch(name: str) -> Any:
        if name not in copies or name in trace.swatches:
            trace.refuse(f"the donor read the swatch {name!r} (only cloth, then hem, once)")
        if sha256_file(copies[name]) != staged[copies[name].name]:
            trace.refuse(f"the staged {name} swatch changed before it was read")
        trace.swatches.append(name)
        return read(name)

    vars(donor)["swatch"] = swatch
    save_mask, save_rgb = donor.Field.save_mask, donor.Field.save_rgb

    def compare_mask(self: Any, out: Any, name: str, v: Any) -> None:
        k = len(trace.compared)
        if Path(out) != run_dir or k >= len(pins.masks) or name != pins.masks[k]:
            trace.refuse(f"the donor's mask {k} is {name!r} into {out}")
        sink = _Sink()
        save_mask(self, sink, name, v)
        files = list(sink.files.items())
        if len(files) != 1 or files[0][0] != f"{name}.png":
            trace.refuse(f"save_mask({name!r}) wrote {[f for f, _ in files]}")
        data = files[0][1].getvalue()
        want = expected.outputs[name]
        found = (sha256_bytes(data), len(data), self.out.get(name))
        if found != (want["sha256"], want["size_bytes"], want["coverage_mean"]):
            trace.refuse(
                f"{name} is {found}, front T's record holds "
                f"{(want['sha256'], want['size_bytes'], want['coverage_mean'])}"
            )
        trace.compared.append(name)

    def write_rgb(self: Any, out: Any, name: str, rgb: Any) -> None:
        if name != COLOUR or Path(out) != run_dir or trace.written:
            trace.refuse(f"the donor's save_rgb wrote {name!r} into {out} after {trace.written}")
        if trace.compared != list(pins.masks) or trace.swatches != list(SWATCHES):
            trace.refuse(f"save_rgb came after {trace.compared} and {trace.swatches}")
        trace.written.append(name)
        save_rgb(self, out, name, rgb)

    donor.Field.save_mask = compare_mask
    donor.Field.save_rgb = write_rgb
    return trace


def run_donor(
    donor: types.ModuleType,
    run_dir: Path,
    expected: MasksRecord,
    staged: Mapping[str, str],
    pins: masks.Pins,
) -> tuple[Any, Trace]:
    """`waist_masks.main`'s sash path, all of it, under the remaps."""
    with np.load(run_dir / host.CENTRE_NPZ, allow_pickle=False) as archive:
        construction = dict(archive)
    trace = remap(donor, run_dir, expected, staged, pins)
    try:
        field_ = donor.Field(run_dir, pins.resolution, construction)
        donor.sash(field_, construction, run_dir)
    except _Refused as refused:
        raise ColourError(str(refused)) from None
    if trace.problems:
        raise ColourError("; ".join(trace.problems))
    if (trace.compared, trace.swatches, trace.written) != (
        list(pins.masks),
        list(SWATCHES),
        [COLOUR],
    ):
        raise ColourError(
            f"sash compared {trace.compared}, read {trace.swatches}, wrote {trace.written}"
        )
    return field_, trace


def check_colour(run_dir: Path, field_: Any, pins: masks.Pins) -> dict[str, Any]:
    """`T_sash.png`'s form, orientation and padding on its bytes."""
    res = pins.resolution
    valid = np.asarray(field_.valid)
    rows, cols = np.asarray(field_.idx[0]), np.asarray(field_.idx[1])
    if valid.shape != (res, res) or rows.shape != (res, res) or cols.shape != (res, res):
        raise ColourError(f"the donor's texel field is {list(valid.shape)}, not {res}²")
    if list(field_.out) != [*pins.masks, COLOUR]:
        raise ColourError(f"the donor's means are {list(field_.out)}")
    path = run_dir / f"{COLOUR}.png"
    data = path.read_bytes()
    header = _ihdr(data)
    if len(header) != 13:
        raise ColourError(f"{path} is not a PNG")
    width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
    depth, colour = header[8], header[9]
    if (width, height, (depth, colour), header[12]) != (res, res, COLOUR_FORM, 0):
        raise ColourError(f"{path} is {width}x{height} depth {depth} colour type {colour}")
    bottom_first = png.decode(data)[::-1]
    if not np.array_equal(bottom_first, bottom_first[rows, cols]):
        raise ColourError(f"{path}: a texel is not its nearest island texel (padding)")
    return {
        "name": COLOUR,
        "file": path.name,
        "role": "base-colour",
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
        "shape": [height, width],
        "depth": depth,
        "colour_type": colour,
        "median_srgb": field_.out[COLOUR],
    }


# ---------------------------------------------------------------------------------- producer
@dataclass(frozen=True)
class Plan:
    run_dir: Path
    code: dict[str, bytes]
    split: dict[str, Any]
    inputs: masks.Inputs
    masks_record: MasksRecord
    swatches: dict[str, Swatch]
    manifest: dict[str, str]
    runtime: dict[str, str]
    expected: dict[str, Any] | None
    expected_path: Path | None
    expected_sha256: str | None

    def receipts(self) -> dict[str, dict[str, Any]]:
        found = dict(self.inputs.receipts)
        found["masks"] = self.masks_record.receipt
        for name, swatch in self.swatches.items():
            found[f"swatch-{name}"] = {
                "path": str(swatch.record_path),
                "sha256": swatch.record_sha256,
                "schema": SWATCH_SCHEMA,
                "kind": "swatch",
                "swatch": name,
                "classification": swatch.entry["classification"],
                "image_sha256": swatch.entry["sha256"],
            }
        return found

    def verified(self) -> dict[str, tuple[Path, str]]:
        """Every file the plan verified in place, with the SHA-256 it verified: the receipts,
        each swatch image and each generated swatch's prompt file and visual references."""
        found = {role: (Path(r["path"]), r["sha256"]) for role, r in self.receipts().items()}
        for name, swatch in self.swatches.items():
            found[f"image-{name}"] = (swatch.image, swatch.entry["sha256"])
            for label, path, sha256 in swatch.side_files:
                found[label] = (path, sha256)
        return found

    def as_json(self, pins: Pins) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "sources": [s.as_json(pins.donor.snapshot) for s in pins.donor.sources],
            "manifest": pins.manifest.as_json(pins.donor.snapshot) | {"lists": self.manifest},
            "runtime": self.runtime,
            "split": self.split,
            "receipts": self.receipts(),
            "arrays": self.inputs.arrays,
            "swatches": {name: s.entry for name, s in self.swatches.items()},
            "expect": str(self.expected_path) if self.expected_path else None,
        }


def plan(
    run_dir: Path,
    assets_root: Path,
    extraction: Path,
    ao: Path,
    centre: Path,
    masks_record: Path,
    swatch_records: Mapping[str, Path],
    *,
    expect: Path | None = None,
    pins: Pins = PINS,
    runtime: Callable[[], dict[str, str]] = masks.found_runtime,
    verify_extraction: Callable[[Path], dict[str, Any]] = host.load_extraction,
) -> Plan:
    """Every check that needs no output: runtime, sources, split, receipts, swatches."""
    run_dir = ensure_outside_repository(run_dir)
    if run_dir.exists():
        raise ColourError(f"{run_dir} already exists; every run gets a fresh directory")
    found = runtime()
    problems = masks.runtime_problems(found, pins.donor.runtime)
    if problems:
        raise ColourError("the runtime is not pinned: " + "; ".join(problems))
    code = masks.read_sources(assets_root, pins.donor)
    split = masks.split_report(code[masks.DONOR], pins.donor.masks)
    originals = manifest_originals(assets_root, pins)
    inputs = masks.check_inputs(extraction, ao, centre, pins.donor.resolution, verify_extraction)
    record = check_masks_record(masks_record, inputs, pins.donor)
    if sorted(swatch_records) != sorted(SWATCHES):
        raise ColourError(f"the swatch records are {sorted(swatch_records)}, not {SWATCHES}")
    swatches = {
        name: load_swatch(swatch_records[name], name, originals, pins.manifest.sha256)
        for name in SWATCHES
    }
    if swatches["cloth"].entry["sha256"] == swatches["hem"].entry["sha256"]:
        raise ColourError("the cloth and hem swatches are the same image")
    expected, expected_sha256 = None, None
    if expect is not None:
        data = expect.read_bytes()
        expected = json.loads(data, parse_constant=masks._no_constant)
        expected_sha256 = sha256_bytes(data)
        get = masks._get
        if (get(expected, ("schema",)), get(expected, ("kind",))) != (RECORD_SCHEMA, "colour"):
            raise ColourError(f"{expect} is not a {RECORD_SCHEMA} record")
        if get(expected, ("status",)) not in BASELINE_STATUSES:
            raise ColourError(f"{expect} is {get(expected, ('status',))!r}, not a baseline")
    return Plan(
        run_dir,
        code,
        split,
        inputs,
        record,
        swatches,
        originals,
        found,
        expected,
        expect,
        expected_sha256,
    )


def helper_json() -> dict[str, Any]:
    def pin(path: str) -> dict[str, str]:
        return {"path": path, "sha256": sha256_file(REPO_ROOT / path)}

    return {
        **pin(Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()),
        "checks_with": [
            pin(Path(module.__file__ or "").resolve().relative_to(REPO_ROOT).as_posix())
            for module in (masks, host, side, png)
        ],
    }


def produce(
    the_plan: Plan, assets_root: Path, pins: Pins = PINS
) -> tuple[dict[str, Any], list[str]]:
    """Stage the inputs and swatches, run the donor through `sash`, check and record T_sash."""
    run_dir = the_plan.run_dir
    verified = the_plan.verified()
    verified_before = {label: sha256 for label, (_, sha256) in verified.items()}
    copies = {masks.INPUT_FILES[key]: path for key, path in the_plan.inputs.files.items()}
    wanted = {name: the_plan.inputs.arrays[name]["sha256"] for name in copies}
    for name, swatch in the_plan.swatches.items():
        copies[SWATCH_FILES[name]] = swatch.image
        wanted[SWATCH_FILES[name]] = swatch.entry["sha256"]
    run_dir.mkdir(parents=True, exist_ok=False)
    staged = {}
    for name, source in copies.items():
        shutil.copyfile(source, run_dir / name)
        staged[name] = sha256_file(run_dir / name)
        if staged[name] != wanted[name]:
            raise ColourError(f"the staged {run_dir / name} differs from {source}")
    with masks.no_reads_under(assets_root):
        donor = masks.load_donor(the_plan.code, assets_root, pins.donor)
        field_, trace = run_donor(donor, run_dir, the_plan.masks_record, staged, pins.donor)
    present = {path.name for path in run_dir.iterdir()}
    if present != set(staged) | {f"{COLOUR}.png"}:
        raise ColourError(f"{run_dir} holds {sorted(present)}")
    staged_after = {name: sha256_file(run_dir / name) for name in staged}
    verified_after = {
        label: sha256_file(path) if path.is_file() else None
        for label, (path, _) in verified.items()
    }
    if (staged_after, verified_after) != (staged, verified_before):
        raise ColourError("an input, a receipt or a prompt changed while the donor ran")
    texels = int(np.asarray(field_.valid).sum())
    if texels != the_plan.masks_record.texels:
        raise ColourError(f"{texels} texels, front T's record {the_plan.masks_record.texels}")
    output = check_colour(run_dir, field_, pins.donor)
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": "colour",
        "status": "produced",
        "piece": "sash",
        "run_dir": str(run_dir),
        "helper": helper_json(),
        "sources": [s.as_json(pins.donor.snapshot) for s in pins.donor.sources],
        "manifest": pins.manifest.as_json(pins.donor.snapshot) | {"lists": the_plan.manifest},
        "runtime": dict(pins.donor.runtime),
        "host": masks.host_json(),
        "parameters": {
            "resolution": pins.donor.resolution,
            "orientation": masks.ORIENTATION,
            "padding": masks.PADDING,
            "quantisation": QUANTISATION,
            "png": {"bit_depth": COLOUR_FORM[0], "colour_type": COLOUR_FORM[1]},
            "swatch_reads": trace.swatches,
        },
        "receipts": the_plan.receipts(),
        "extraction_link": {
            "extraction_record_sha256": the_plan.inputs.extraction_sha256,
            "cited_by": ["ao", "centre", "masks"],
        },
        "arrays": the_plan.inputs.arrays,
        "swatches": {name: s.entry for name, s in the_plan.swatches.items()},
        "inputs": {
            "before": {"verified": verified_before, "staged": staged},
            "after": {"verified": verified_after, "staged": staged_after},
        },
        "split": the_plan.split | {"colour": f"run to its end; {COLOUR} written once"},
        "masks": {
            "compared": trace.compared,
            "result": "identical to front T's masks record (bytes, size and mean); none written",
            "record_sha256": the_plan.masks_record.sha256,
        },
        "texels": texels,
        "outputs": [output],
        "substitute": SUBSTITUTE
        | {"swatches": {n: s.entry["classification"] for n, s in the_plan.swatches.items()}},
        "repeat": {
            "result": "not-a-repeat",
            "note": "a repeat with --expect must agree byte for byte",
        },
    }
    problems: list[str] = []
    if the_plan.expected is not None:
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
UNCOMPARED = frozenset({"status", "run_dir", "repeat"})


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """Every field but the status, the repeat and the paths that name a run must agree."""
    keys = sorted((set(record) | set(expected)) - UNCOMPARED)
    without = masks._without_run
    return [
        f"{key} is {without(record.get(key))!r}, the earlier run's {without(expected.get(key))!r}"
        for key in keys
        if without(record.get(key)) != without(expected.get(key))
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.sash_colour",
        description="The Sash v5 current round's T_sash (waist_masks.py sash, colour only).",
    )
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument("--ao", type=Path, required=True, help="front P's AO record")
    parser.add_argument("--extraction", type=Path, help="front P's extraction record")
    parser.add_argument("--centre", type=Path, help="front P's centre record")
    parser.add_argument("--masks", type=Path, help="front T's reproduced masks-record.json")
    for name in SWATCHES:
        parser.add_argument(f"--{name}", type=Path, help=f"the {name} swatch provenance record")
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's colour-record.json")
    parser.add_argument("--dry-run", action="store_true", help="check, print the plan")
    args = parser.parse_args(argv)
    try:
        work = work_root()
        run_dir = host.run_dir_for(args.run, work)
        swatch_records = {
            name: getattr(args, name) or work / DEFAULT_SWATCH_RUNS[name] / SWATCH_RECORD_NAME
            for name in SWATCHES
        }
        the_plan = plan(
            run_dir,
            args.assets_root,
            args.extraction or work / masks.DEFAULT_EXTRACTION,
            args.ao,
            args.centre or work / masks.DEFAULT_CENTRE,
            args.masks or work / DEFAULT_MASKS,
            swatch_records,
            expect=args.expect,
        )
        if args.dry_run:
            print(json.dumps(the_plan.as_json(PINS), indent=2))
            return 0
        record, problems = produce(the_plan, args.assets_root)
    except (ExtractError, RecorderError, StoreError, OSError, ValueError, KeyError) as error:
        print(f"sash_colour: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    for problem in problems:
        print(f"sash_colour: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
