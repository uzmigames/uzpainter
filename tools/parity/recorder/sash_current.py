r"""The Sash v5 current-round request, `phase2/tier1/sash-v5-current` (decision 300 items 7-8).

    python -m tools.parity.recorder.sash_current request --assets-root <Assets3D>
        [--inputs <private inputs.json>] --out <request.json> [--store DIR]

Once the request exists it is recorded like any pipeline-script golden (`script_run.py`):

    python -m tools.parity.recorder record-script <request.json> --assets-root <Assets3D>

This is technical preparation, not a baseline approval: using the round as the changed baseline
stays the owner's yes (decision 300 item 8). It binds what the input contract
(`docs/analysis/sash-v5-current-round/01-input-contract.md`) fixes:

1. **Scripts.** `painter_create.py`, `painter_layer_stack.py` (sync), `painter_export.py`, the
   sync's import `run.py` and run's two import-time helpers, and `stack-sash.json`, each the raw
   (LF) git blob of the one Assets3D snapshot `SNAPSHOT`, pinned by SHA-256. A blob not already
   in the private store is read from Assets3D's object database (`git cat-file`), never from the
   checkout, and its hash must equal the pin; nothing is normalised after hashing.
2. **Steps.** Create, sync and export under decision 099's two adaptations, and no fourth step:
   `painter_export.py` with the authored prefix exports the five maps of the one texture set
   (Option A). The sync takes the typed options `--resource-prefix v5f_`, `--resource-group
   faixa25_v5` and `--texture-set 25-Faixa-Cintura`, its import closure (`run.py`, then its two
   helpers) and its 20 bitmaps by folder.
3. **Authored arguments.** Both arguments files are written now, as named authored values, at the
   paths the scripts hard-code; the recorder repoints `mesh`, `normal`, `ao`, `dst` and `out`.
4. **Private inputs, by hash**, named by a private inputs file (`INPUTS_SCHEMA`: role ->
   `sha256` and an optional private `file`). The Normal is the named substitute `NORMAL`.
5. **Receipts.** Each substitute is bound to its producer's record by typed fields, never by a
   hash found anywhere in a record (`check_receipts`):
   - front N's export record (`low-record`): the exporter, the preserved `.blend` and the OBJ
     and MTL pins;
   - front P's extraction, AO and centre records: kind, status, and links (the extraction's low
     is N's, by OBJ, MTL and table; its Normal is `NORMAL`; the AO and the centre name the
     extraction record by hash);
   - front T's masks record (`sash_masks.py`, `MASKS_SCHEMA`), the independent repeat's
     (`reproduced`, byte-identical): its three sources as raw blobs of `SNAPSHOT`, the executed
     `waist_gen.py` blob and its pinned CRLF checkout form (`WAIST_GEN_CHECKOUT_SHA256`, what
     P's centre donor cites), the resolution and PNG form, P's three receipts and the four
     arrays they output, and the 19 stack masks plus the auxiliary `M_cloth` (never an input);
   - the AO mesh map's record (`AO_MAP_SCHEMA`, front V's producer): P's `ao.npy` in, the PNG
     out;
   - front W's colour record (`sash_colour.py`, `COLOUR_SCHEMA`), the independent repeat's
     (`reproduced`, byte-identical): the helper, the same three source blobs, runtime,
     orientation and padding as T's masks record, the 8-bit RGB form at the pinned resolution
     and the `cloth`, then `hem` reads; P's three receipts and T's masks record, the very
     records the masks role cites, with the same arrays, masks and texels; `T_sash` as the one
     output; and both swatches, each with its provenance record (`SWATCH_SCHEMA`), each file it
     verified and staged, by hash;
   - each swatch's provenance record: its image (hash, size and PNG form) and its source, an
     `original` (its path, the pinned `v5.json` by that file's own SHA-256, and the image that
     manifest lists) or a `generated` substitute (generator, model, route, declaration, the
     prompt's hash and every visual reference by plain name, hash and size; never an original's
     bytes). The two swatches differ.
   Every bitmap is a complete, decodable PNG (`png_layout`: chunk CRCs, IHDR, one IDAT run,
   IEND, inflated size and row filters) at its native depth: the masks and the AO 16-bit grey,
   `T_sash` 8-bit RGB, each at the pinned resolution; a swatch 8-bit RGB or RGBA. Every
   substitute's provenance note names what it replaces and the records that vouch for it.

Anything absent refuses the request with every missing role listed (`MissingInputs`), before
the store is written; a wrong hash, shape, receipt or closure refuses it too. Only a complete set
is stored (decision 144) and the request is written only once its job loads from those pins.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import struct
import subprocess
import sys
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.script_run import (
    ASSETS3D_LICENCE,
    BELT,
    INTERFACE,
    RUN_SCRIPT,
    SYNC_COMMAND,
    WAND_SETTINGS,
    MissingInputs,
    material_library,
    script_job_from_manifest,
    stack_bitmaps,
    tail_matches,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore, Status, StoreError, locate

GOLDEN_ID = "phase2/tier1/sash-v5-current"
PIECE = "25-Faixa-Cintura"
SNAPSHOT = "1c9a312a47eea0b35aa0aa05777245ef61ac49e5"  # Assets3D, 2026-10-20
WAIST = "Pipeline/retopology/waist-v5"
PRODUCTION = "Pipeline/production"
CREATE_ARGS = f"{BELT}/painter_create_args.json"
EXPORT_ARGS = f"{BELT}/painter_export_args.json"
LOW_OBJ = f"{BELT}/lows/25-Faixa-Cintura-v5-low.obj"
LOW_MTL = f"{BELT}/lows/25-Faixa-Cintura-v5-low.mtl"
AO = f"{BELT}/bake/25-Faixa-Cintura_AO_v5.png"
MASKS = f"{BELT}/paint/masks-sash"
PROJECT = f"{BELT}/25-Faixa-Cintura-v5-current.spp"
EXPORT_OUT = f"{BELT}/paint/tex-sash-current"
SYNC_OPTIONS = {"resource_prefix": "v5f_", "resource_group": "faixa25_v5", "texture_set": PIECE}
CLOSURE = ("decision-evidence-py", "stage-review-evidence-py")


@dataclass(frozen=True)
class Blob:
    """A pinned Assets3D file: its input id and kind, its path and the SHA-256 of its bytes."""

    input_id: str
    kind: str
    path: str
    sha256: str


BLOBS: tuple[Blob, ...] = (
    Blob(
        "painter-create-py",
        "pipeline_script",
        f"{WAIST}/painter_create.py",
        "f3e01482efaa117b9bb7299c9bce6f384e3385b59baeaece5b503200b7e41b05",
    ),
    Blob(
        "painter-layer-stack-py",
        "pipeline_script",
        "Pipeline/painting/painter_layer_stack.py",
        "834c4bca3d32ebdeb9cd705e699782ee86fb86eb6dcff277345fae7bd63827aa",
    ),
    Blob(
        "production-run-py",
        "pipeline_script",
        f"{PRODUCTION}/run.py",
        "7d8017d256a2359d5062fcc6e9e06881fee5d2bbb113e8000f8fba819a85b0a2",
    ),
    Blob(
        "decision-evidence-py",
        "pipeline_script",
        f"{PRODUCTION}/decision_evidence.py",
        "a1f11c9a6938a8c77284e63c3e515b78a892424df480d8931a90f825a1967d60",
    ),
    Blob(
        "stage-review-evidence-py",
        "pipeline_script",
        f"{PRODUCTION}/stage_review_evidence.py",
        "598c774ade15d7893bec154aead7065ddb515fd5799ab42fcf8f6e97735f502a",
    ),
    Blob(
        "painter-export-py",
        "pipeline_script",
        f"{WAIST}/painter_export.py",
        "48c294a43cbce1073e647f6299576fedd66f31f8fb4370f8175f3df2ac64d038",
    ),
    Blob(
        "sash-stack",
        "recipe_json",
        f"{WAIST}/stack-sash.json",
        "cfa13264ab5ac83efdbeb7f7d669a6cd2f2f6e6ed563bd282d6fea1985ecf35b",
    ),
)
# The named Normal substitute: the surviving bake under the piece's Textures (input contract).
NORMAL = Blob(
    "sash-normal",
    "image",
    "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/Textures/"
    "25-Faixa-Cintura_Normal_OpenGL_bake_v5.png",
    "ec05be82d5c551926b81f2e443faf227d297b37b0fba6aed14da63b397d58276",
)
# Front N's accepted export of the low (commit 3afbbfbf; r1 and r1-repeat byte-identical).
LOW_OBJ_SHA256 = "646bba8546ad9dcd6475eb366fced896f35f592b088e1286d1a30ec957249944"
LOW_MTL_SHA256 = "2e9174ad995c854491ac0c4e02ccc58144fe62128ee64097c5268216a575c061"
# The stack's 19 masks and its base_tex colour bitmap (the saved state's 20 resources).
BITMAPS = (
    "M_band",
    "M_band_seam",
    "M_band_stitch",
    "M_band_top",
    "M_beltgrime",
    "M_cav",
    "M_crest",
    "M_dust",
    "M_fibers",
    "M_hem",
    "M_hem_crack",
    "M_hem_grain",
    "M_hem_grime",
    "M_hem_top",
    "M_inner",
    "M_seam",
    "M_tab_edge",
    "M_tab_var",
    "M_weave",
    "T_sash",
)
COLOUR = "T_sash"
SWATCHES = ("sash-cloth-BaseColor-v1.png", "hem-leather-BaseColor-v1.png")
SWATCH_NAMES = ("cloth", "hem")  # the donor's reads, in its order; SWATCHES holds their files
PIECE_FOLDER = "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura"
SWATCH_PATHS = {  # sash_colour.SWATCH_PATHS: the donor's SW entries
    name: f"{PIECE_FOLDER}/Textures/Swatches/{file}"
    for name, file in zip(SWATCH_NAMES, SWATCHES, strict=True)
}
# The pinned v5.json (raw blob at `SNAPSHOT`, sash_colour.MANIFEST) by its own SHA-256, and the
# lost originals' SHA-256 as it lists them, in `SWATCH_NAMES` order (sash_colour.ORIGINALS).
V5_JSON = f"{PIECE_FOLDER}/manifests/v5.json"
V5_JSON_SHA256 = "c5566c38a6a1ff64318d375d1819717d4bd96a6f7e00b1b5fc13d905f6800c88"
ORIGINALS = (
    "5ab8cdf3edefbac2f35613bae9b2fbe49fea2754da2c1e8ca8bf5fa32bd518a9",
    "546bba43d7291d29a70ac2bf26f234f62802feeb8be47d8f1c99a6719a80c5b7",
)

# The preserved `.blend` front N's low and front P's intermediates are both made from.
LOW_SOURCE_SHA256 = "4c770d1dcf1fd4296386155e1ae12d60126a3d9de1fcfeaadf82636353624a3b"
# The mask generator the contract names and its two imports, as front T's masks producer
# (`tools/parity/tier1/sash_masks.py`) pins them: (module, path, raw blob SHA-256) at `SNAPSHOT`.
WAIST_MASKS = f"{WAIST}/waist_masks.py"
WAIST_GEN = f"{WAIST}/waist_gen.py"
MATERIAL_MASKS = "Pipeline/painting/garment_material_masks.py"
MASK_SOURCES = (
    (
        "garment_material_masks",
        MATERIAL_MASKS,
        "dfed970b93a387fe9321a66538c483ef48216efd7bdbdd0489901eb91e2976ca",
    ),
    ("waist_gen", WAIST_GEN, "c109880dddc4912059f56d54168484908eb0566dc5c1c775dc60167969ba31b7"),
    (
        "waist_masks",
        WAIST_MASKS,
        "959eca0bc3e2660149806c288d002d4d0db0816dc284093e643d6ffd5837a066",
    ),
)
# What front P's centre donors cite for waist_gen.py: the CRLF checkout of that raw LF blob
# (every LF replaced by CRLF; checked by hashing the converted blob). The masks producer runs
# the blob and records this checkout form beside it.
WAIST_GEN_CHECKOUT_SHA256 = "15cf7cb9831df33ad645b5bf9b26a2cdc49d9c104f93ecf12c26eae6cb37b746"
AUXILIARY_MASKS = ("M_cloth",)  # written by the masks producer, not a stack input

# The private inputs file: role -> {"sha256", "file"?}. The substitutes' receipts are fixed by
# role: the low's is N's export record, each stack mask's the masks producer's repeat record,
# T_sash's the colour record and each swatch's its provenance record, the AO's the AO map's.
INPUTS_SCHEMA = "uzpainter/parity/sash-v5-current-inputs/1"
ENTRY_KEYS = frozenset({"sha256", "file"})
LOW_RECORD = "low-record"  # front N: sash_low_export's export-record.json
EXTRACT_RECORD = "intermediates-record"  # front P: sash_intermediates extract
AO_RECORD = "ao-record"  # front P: sash_intermediates ao (ao.npy)
CENTRE_RECORD = "centre-record"  # front P: sash_intermediates centre
MASKS_RECORD = "masks-record"  # front T: sash_masks, the independent repeat's record
AO_MAP_RECORD = "ao-map-record"  # the AO mesh map PNG made from ao.npy
COLOUR_RECORD = "colour-record"  # front W: sash_colour, the independent repeat's record
SWATCH_RECORDS = {name: f"swatch-{name}-record" for name in SWATCH_NAMES}  # one provenance each
RECEIPTS = (LOW_RECORD, EXTRACT_RECORD, AO_RECORD, CENTRE_RECORD, MASKS_RECORD, AO_MAP_RECORD)
LOW_SCHEMA = "uzpainter/parity/sash-low-export-record/1"  # sash_low_export.RECORD_SCHEMA
LOW_EXPORTER = "uzpainter/parity/sash-low-export/1"
INTERMEDIATES_SCHEMA = "uzpainter/parity/sash-intermediates-record/1"  # extract, ao, centre
CENTRE_STATUS = "derived-from-preserved-geometry"  # the only centre this round accepts
MASKS_SCHEMA = "uzpainter/parity/sash-masks-record/1"  # sash_masks.RECORD_SCHEMA
# The arrays the masks producer consumed, by the names front P's records give their outputs.
MASK_ARRAYS = ("low.npz", "highnormal.npy", "ao.npy", "construction-centre.npz")
AO_MAP_SCHEMA = "uzpainter/parity/sash-ao-map-record/1"  # front V: sash_ao_map.RECORD_SCHEMA
# The donor whose one line converts ao.npy into the AO mesh map (raw blob at `SNAPSHOT`).
AO_DONOR = f"{WAIST}/sashchain.sh"
AO_DONOR_SHA256 = "70ee17308d9754e5df3c1728f26549d9e6ec64a6df9f14981ef1acef2dade65e"
# Front W's colour producer (`tools/parity/tier1/sash_colour.py`): its record and swatch schemas,
# its helper and the modules it checks with, as its record names them.
COLOUR_SCHEMA = "uzpainter/parity/sash-colour-record/1"  # sash_colour.RECORD_SCHEMA
SWATCH_SCHEMA = "uzpainter/parity/sash-swatch-provenance/1"  # sash_colour.SWATCH_SCHEMA
SWATCH_RECORD_NAME = "swatch-provenance.json"  # sash_colour.SWATCH_RECORD_NAME
COLOUR_HELPER = "tools/parity/tier1/sash_colour.py"
COLOUR_CHECKS_WITH = (
    "tools/parity/tier1/sash_masks.py",
    "tools/parity/tier1/sash_intermediates.py",
    "tools/parity/tier1/sash_intermediates_blender.py",
    "tools/parity/feasibility/png.py",
)
COLOUR_KEYS = frozenset(
    {"resolution", "orientation", "padding", "quantisation", "png", "swatch_reads"}
)  # the colour record's `parameters`
COLOUR_RECEIPTS = ("extraction", "ao", "centre")  # P's, as T's masks record cites them
SWATCH_KEYS = frozenset({"schema", "kind", "swatch", "file", "image", "source", "classification"})
IMAGE_KEYS = frozenset({"sha256", "size_bytes", "width", "height", "bit_depth", "colour_type"})
SOURCE_KEYS = {
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
# sash_colour.QUANTISATION: how the donor's `save_rgb` writes T_sash.
QUANTISATION = "uint8(clip(rgb, 0, 1) * 255 + 0.5), Pillow RGB PNG (the donor's save_rgb)"
# The colour record's `masks` result once every mask equalled front T's (sash_colour.produce).
MASKS_COMPARED = "identical to front T's masks record (bytes, size and mean); none written"
PLACEHOLDER_TEXT = frozenset(  # sash_colour.PLACEHOLDER_TEXT
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
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}  # PNG colour type -> channels
GREY, RGB, RGBA = 0, 2, 6


@dataclass(frozen=True)
class Pins:
    """What the request pins; the defaults are the input contract's (tests pass stand-ins)."""

    snapshot: str = SNAPSHOT
    blobs: tuple[Blob, ...] = BLOBS
    normal: Blob = NORMAL
    low_obj: str = LOW_OBJ_SHA256
    low_mtl: str = LOW_MTL_SHA256
    bitmaps: tuple[str, ...] = BITMAPS
    low_source: str = LOW_SOURCE_SHA256
    mask_sources: tuple[tuple[str, str, str], ...] = MASK_SOURCES
    waist_gen_checkout: str = WAIST_GEN_CHECKOUT_SHA256
    ao_donor: str = AO_DONOR_SHA256
    auxiliary: tuple[str, ...] = AUXILIARY_MASKS
    resolution: int = 2048
    v5_json: str = V5_JSON_SHA256
    originals: tuple[str, ...] = ORIGINALS  # in `SWATCH_NAMES` order


PINS = Pins()


@dataclass(frozen=True)
class Found:
    """An input's pinned bytes: a file (Assets3D, the store or a private file) or a git blob."""

    sha256: str
    file: Path | None = None
    data: bytes | None = None

    def read(self) -> bytes:
        if self.data is not None:
            return self.data
        assert self.file is not None
        return self.file.read_bytes()


def substitute_roles(pins: Pins) -> tuple[str, ...]:
    """The private inputs; `T_sash` brings its two swatches."""
    colour = SWATCHES if COLOUR in pins.bitmaps else ()
    return ("low-obj", "low-mtl", "ao", *pins.bitmaps, *colour)


def receipt_roles(pins: Pins) -> tuple[str, ...]:
    """The receipts; `T_sash` brings its colour record and a provenance record per swatch."""
    colour = (COLOUR_RECORD, *SWATCH_RECORDS.values()) if COLOUR in pins.bitmaps else ()
    return (*RECEIPTS, *colour)


def load_inputs(path: Path) -> dict[str, dict[str, Any]]:
    """The private inputs file, refused unless it has the expected shape."""
    data = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != INPUTS_SCHEMA:
        raise RecorderError(f"{path}: not a {INPUTS_SCHEMA} file")
    if set(data) != {"schema", "files"} or not isinstance(data["files"], dict):
        raise RecorderError(f"{path}: holds exactly `schema` and `files`")
    for role, entry in data["files"].items():
        if not isinstance(entry, dict) or not set(entry) <= ENTRY_KEYS or "sha256" not in entry:
            raise RecorderError(f"{path}: `{role}` must hold `sha256` and `file` only")
        if not all(isinstance(value, str) for value in entry.values()):
            raise RecorderError(f"{path}: `{role}` holds strings only")
    return dict(data["files"])


def git_blob(assets_root: Path, commit: str, path: str) -> bytes | None:
    """The raw blob at `commit:path` in the Assets3D object database, or None."""
    run = subprocess.run(
        ["git", "-C", str(assets_root), "cat-file", "blob", f"{commit}:{path}"],
        capture_output=True,
        check=False,
    )
    return run.stdout if run.returncode == 0 else None


def stored(store: OracleStore, label: str, sha256: str) -> Found | None:
    resolution = store.resolve(label, sha256)
    if resolution.status is Status.AVAILABLE and resolution.path is not None:
        return Found(sha256, file=resolution.path)
    return None


def find_blob(blob: Blob, assets_root: Path, store: OracleStore, commit: str) -> Found | None:
    """A script or stack: the store's blob of its pin, else the raw git blob (hash-checked)."""
    found = stored(store, blob.input_id, blob.sha256)
    if found is not None:
        return found
    data = git_blob(assets_root, commit, blob.path)
    if data is None:
        return None
    if sha256_bytes(data) != blob.sha256:
        raise RecorderError(
            f"{blob.path} at Assets3D {commit[:8]} has sha256 {sha256_bytes(data)}, not the "
            f"pinned {blob.sha256}"
        )
    return Found(blob.sha256, data=data)


def find_normal(normal: Blob, assets_root: Path, store: OracleStore) -> Found | None:
    file = assets_root / normal.path
    if file.is_file() and sha256_file(file) == normal.sha256:
        return Found(normal.sha256, file=file)
    found = stored(store, normal.input_id, normal.sha256)
    if found is None and file.is_file():
        raise RecorderError(f"{file} has other bytes than the pinned Normal {normal.sha256}")
    return found


def find_entry(role: str, entry: Mapping[str, str], store: OracleStore) -> Found | None:
    """A private input: the store's blob of its hash, else its private file (hash-checked)."""
    found = stored(store, role, entry["sha256"])
    if found is not None or "file" not in entry:
        return found
    file = ensure_outside_repository(Path(entry["file"]))
    if not file.is_file():
        return None
    if sha256_file(file) != entry["sha256"]:
        raise RecorderError(f"`{role}`: {file} is not the bytes {entry['sha256']}")
    return Found(entry["sha256"], file=file)


@dataclass(frozen=True)
class PngLayout:
    width: int
    height: int
    depth: int
    colour: int


def png_layout(role: str, data: bytes) -> PngLayout:
    """The layout of a complete PNG, refused unless every part holds: the signature; every chunk
    whole, with its CRC; IHDR first and once (no interlace); the IDAT chunks in one run; IEND
    last with nothing after; the image data one complete zlib stream that inflates to exactly a
    filter byte (0-4) and a row of samples per row at the header's native depth. No sample is
    reconstructed or converted."""

    def bad(why: str) -> RecorderError:
        return RecorderError(f"`{role}` is not a complete PNG: {why}")

    if not data.startswith(PNG_SIGNATURE):
        raise bad("no PNG signature")
    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(data) and (not chunks or chunks[-1][0] != b"IEND"):
        if offset + 12 > len(data):
            raise bad("truncated")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        end = offset + 12 + length
        if end > len(data):
            raise bad("truncated")
        kind, body = data[offset + 4 : offset + 8], data[offset + 8 : end - 4]
        if zlib.crc32(kind + body) != struct.unpack(">I", data[end - 4 : end])[0]:
            raise bad(f"the {kind!r} chunk fails its CRC")
        chunks.append((kind, body))
        offset = end
    kinds = [kind for kind, _ in chunks]
    if not chunks or kinds[-1] != b"IEND" or offset != len(data):
        raise bad("no IEND at the end")
    if kinds[0] != b"IHDR" or kinds.count(b"IHDR") != 1 or len(chunks[0][1]) != 13:
        raise bad("no single IHDR first")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    if (compression, filtering, interlace) != (0, 0, 0) or colour not in CHANNELS:
        raise bad(f"unsupported layout (colour type {colour}, interlace {interlace})")
    if depth not in (8, 16) or not width or not height:
        raise bad(f"unsupported depth {depth} or empty size {width}x{height}")
    runs = [i for i, kind in enumerate(kinds) if kind == b"IDAT"]
    if not runs or runs != list(range(runs[0], runs[-1] + 1)):
        raise bad("no single run of IDAT chunks")
    inflate = zlib.decompressobj()
    try:
        raw = inflate.decompress(b"".join(chunks[i][1] for i in runs))
    except zlib.error as error:
        raise bad(f"the image data does not inflate ({error})") from error
    if not inflate.eof or inflate.unused_data:
        raise bad("the image data is not one complete zlib stream")
    stride = width * CHANNELS[colour] * depth // 8
    if len(raw) != height * (stride + 1):
        raise bad(f"the image data holds {len(raw)} bytes, not {height} rows of {stride + 1}")
    if max(raw[:: stride + 1]) > 4:
        raise bad("a row has an invalid filter")
    return PngLayout(width, height, depth, colour)


def require_png(
    role: str, data: bytes, depths: frozenset[int], colours: frozenset[int], size: int | None
) -> None:
    """A complete PNG of one of `depths` and `colours`, `size` x `size` when it is given."""
    found = png_layout(role, data)
    square = size is None or (found.width, found.height) == (size, size)
    if found.depth not in depths or found.colour not in colours or not square:
        raise RecorderError(
            f"`{role}` is a {found.width}x{found.height} PNG of depth {found.depth} and colour "
            f"type {found.colour}, not {size}x{size} of depth {sorted(depths)} and colour type "
            f"{sorted(colours)}"
        )


def value_at(record: Any, role: str, path: Sequence[str]) -> Any:
    """`record[path[0]][path[1]]...`, refused when a key is absent."""
    for key in path:
        if not isinstance(record, dict) or key not in record:
            raise RecorderError(f"`{role}` has no `{'.'.join(path)}`")
        record = record[key]
    return record


def expect(record: Any, role: str, path: Sequence[str], value: Any) -> None:
    found = value_at(record, role, path)
    if found != value:
        raise RecorderError(f"`{role}` `{'.'.join(path)}` is {found!r}, not {value!r}")


def sha_at(record: Any, role: str, path: Sequence[str]) -> str:
    found = value_at(record, role, path)
    if not isinstance(found, str) or not SHA256.fullmatch(found):
        raise RecorderError(f"`{role}` `{'.'.join(path)}` is no SHA-256 ({found!r})")
    return found


def expect_output(record: Any, role: str, name: str, item: Found) -> None:
    """A record's `outputs.<name>` is exactly `item`'s bytes (hash and size)."""
    expect(record, role, ("outputs", name, "sha256"), item.sha256)
    expect(record, role, ("outputs", name, "size_bytes"), len(item.read()))


def check_low(record: Any, pins: Pins) -> None:
    """Front N's export record (written only once every check of the export passed): the
    exporter, the preserved `.blend` and the OBJ and MTL pins."""
    expect(record, LOW_RECORD, ("schema",), LOW_SCHEMA)
    expect(record, LOW_RECORD, ("exporter",), LOW_EXPORTER)
    expect(record, LOW_RECORD, ("source", "sha256"), pins.low_source)
    expect(record, LOW_RECORD, ("outputs", "obj", "sha256"), pins.low_obj)
    expect(record, LOW_RECORD, ("outputs", "mtl", "sha256"), pins.low_mtl)
    sha_at(record, LOW_RECORD, ("outputs", "table", "sha256"))


def check_extract(record: Any, low: Any, pins: Pins) -> None:
    """Front P's extraction record (written only after the low matched N's): the same `.blend`,
    N's OBJ, MTL and table, the pinned Normal, and its `low.npz` and `highnormal.npy`."""
    expect(record, EXTRACT_RECORD, ("schema",), INTERMEDIATES_SCHEMA)
    expect(record, EXTRACT_RECORD, ("kind",), "extract")
    expect(record, EXTRACT_RECORD, ("source", "sha256"), pins.low_source)
    expect(record, EXTRACT_RECORD, ("low_game", "obj_sha256"), pins.low_obj)
    expect(record, EXTRACT_RECORD, ("low_game", "mtl_sha256"), pins.low_mtl)
    table = sha_at(low, LOW_RECORD, ("outputs", "table", "sha256"))
    expect(record, EXTRACT_RECORD, ("low_game", "table_sha256"), table)
    expect(record, EXTRACT_RECORD, ("normal", "sha256"), pins.normal.sha256)
    for name in ("low.npz", "highnormal.npy"):
        sha_at(record, EXTRACT_RECORD, ("outputs", name, "sha256"))


def check_ao(record: Any, extract_sha256: str) -> None:
    """Front P's AO record: baked from the extraction record it names by hash; its `ao.npy`."""
    expect(record, AO_RECORD, ("schema",), INTERMEDIATES_SCHEMA)
    expect(record, AO_RECORD, ("kind",), "ao")
    expect(record, AO_RECORD, ("extraction", "record_sha256"), extract_sha256)
    sha_at(record, AO_RECORD, ("outputs", "ao.npy", "sha256"))


def check_centre(record: Any, extract_sha256: str) -> None:
    """Front P's centre record: derived from the extraction record it names (the input contract
    allows no authored centre, and front T's masks producer runs only on a derived one); its
    `construction-centre.npz` and its donors' `waist_gen.py`."""
    expect(record, CENTRE_RECORD, ("schema",), INTERMEDIATES_SCHEMA)
    expect(record, CENTRE_RECORD, ("kind",), "centre")
    expect(record, CENTRE_RECORD, ("status",), CENTRE_STATUS)
    expect(record, CENTRE_RECORD, ("extraction", "record_sha256"), extract_sha256)
    sha_at(record, CENTRE_RECORD, ("donors", WAIST_GEN))
    sha_at(record, CENTRE_RECORD, ("outputs", "construction-centre.npz", "sha256"))


def produced_arrays(records: Mapping[str, Any]) -> dict[str, str]:
    """The SHA-256 of each array front P's records give as an output, by file name."""
    return {
        "low.npz": sha_at(
            records[EXTRACT_RECORD], EXTRACT_RECORD, ("outputs", "low.npz", "sha256")
        ),
        "highnormal.npy": sha_at(
            records[EXTRACT_RECORD], EXTRACT_RECORD, ("outputs", "highnormal.npy", "sha256")
        ),
        "ao.npy": sha_at(records[AO_RECORD], AO_RECORD, ("outputs", "ao.npy", "sha256")),
        "construction-centre.npz": sha_at(
            records[CENTRE_RECORD], CENTRE_RECORD, ("outputs", "construction-centre.npz", "sha256")
        ),
    }


def check_masks(
    record: Any,
    files: Mapping[str, Mapping[str, str]],
    records: Mapping[str, Any],
    found: Mapping[str, Found],
    pins: Pins,
) -> None:
    """Front T's masks record (`sash_masks.py`), the independent repeat's: it reproduced its
    first run byte for byte; its three pinned sources at `SNAPSHOT` (waist_gen's checkout form is
    the centre's donor); its resolution and PNG form; P's three receipts and the four arrays they
    output; and the 20 masks, each stack input exactly the inputs file's bytes."""
    role = MASKS_RECORD
    expect(record, role, ("schema",), MASKS_SCHEMA)
    expect(record, role, ("kind",), "masks")
    expect(record, role, ("piece",), "sash")
    expect(record, role, ("status",), "reproduced")
    expect(record, role, ("repeat", "result"), "byte-identical")
    expect(record, role, ("repeat", "problems"), [])
    sha_at(record, role, ("repeat", "of_record_sha256"))

    sources = value_at(record, role, ("sources",))
    if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
        raise RecorderError(f"`{role}` `sources` is no list of sources")
    by_module = {s.get("module"): s for s in sources}
    if len(sources) != len(pins.mask_sources) or set(by_module) != {
        m for m, _, _ in pins.mask_sources
    }:
        raise RecorderError(f"`{role}` `sources` must be {[m for m, _, _ in pins.mask_sources]}")
    for module, path, sha256 in pins.mask_sources:
        source = by_module[module]
        for key, value in (("assets3d_path", path), ("commit", pins.snapshot), ("sha256", sha256)):
            expect(source, role, (key,), value)
    # The executed waist_gen.py is its raw blob (checked above); the centre's donor cites that
    # blob's pinned CRLF checkout form, which the masks record must name beside it.
    expect(by_module["waist_gen"], role, ("checkout_sha256",), pins.waist_gen_checkout)
    expect(records[CENTRE_RECORD], CENTRE_RECORD, ("donors", WAIST_GEN), pins.waist_gen_checkout)

    expect(record, role, ("parameters", "resolution"), pins.resolution)
    expect(record, role, ("parameters", "png"), {"bit_depth": 16, "colour_type": GREY})
    extract_sha256 = files[EXTRACT_RECORD]["sha256"]
    for name, receipt, kind in (
        ("extraction", EXTRACT_RECORD, "extract"),
        ("ao", AO_RECORD, "ao"),
        ("centre", CENTRE_RECORD, "centre"),
    ):
        expect(record, role, ("receipts", name, "sha256"), files[receipt]["sha256"])
        expect(record, role, ("receipts", name, "schema"), INTERMEDIATES_SCHEMA)
        expect(record, role, ("receipts", name, "kind"), kind)
        if name != "extraction":
            expect(record, role, ("receipts", name, "extraction_record_sha256"), extract_sha256)
    expect(record, role, ("receipts", "centre", "status"), CENTRE_STATUS)
    expect(record, role, ("extraction_link", "extraction_record_sha256"), extract_sha256)
    arrays = value_at(record, role, ("arrays",))
    if not isinstance(arrays, dict) or set(arrays) != set(MASK_ARRAYS):
        raise RecorderError(f"`{role}` `arrays` must be exactly {list(MASK_ARRAYS)}")
    for name, sha256 in produced_arrays(records).items():
        expect(record, role, ("arrays", name, "sha256"), sha256)

    stack = tuple(b for b in pins.bitmaps if b != COLOUR)
    outputs = value_at(record, role, ("outputs",))
    if not isinstance(outputs, list) or not all(isinstance(o, dict) for o in outputs):
        raise RecorderError(f"`{role}` `outputs` is no list of masks")
    by_name = {o.get("name"): o for o in outputs}
    if len(outputs) != len(by_name) or set(by_name) != {*stack, *pins.auxiliary}:
        raise RecorderError(
            f"`{role}` `outputs` must be the {len(stack)} stack masks and {list(pins.auxiliary)}"
        )
    for name, output in by_name.items():
        where = f"{role} {name}"
        expect(output, where, ("file",), f"{name}.png")
        expect(output, where, ("role",), "auxiliary" if name in pins.auxiliary else "stack-input")
        expect(output, where, ("shape",), [pins.resolution, pins.resolution])
        expect(output, where, ("depth",), 16)
        expect(output, where, ("colour_type",), GREY)
        if name in stack:
            expect(output, where, ("sha256",), found[name].sha256)
            expect(output, where, ("size_bytes",), len(found[name].read()))
    listed = value_at(record, role, ("stack_inputs",))  # in the donor's order
    if not isinstance(listed, list) or len(set(listed)) != len(listed) or set(listed) != set(stack):
        raise RecorderError(
            f"`{role}` `stack_inputs` must be the {len(stack)} stack masks once each"
        )
    expect(record, role, ("auxiliary",), list(pins.auxiliary))


def check_ao_map(record: Any, ao_sha256: str, found: Found, pins: Pins) -> None:
    """Front V's AO map record (`sash_ao_map.py`), the independent repeat's: it reproduced its
    first run byte for byte; the conversion `sashchain.sh` holds (its raw blob at `SNAPSHOT`,
    with the line), from P's `ao.npy` to one 16-bit grey PNG at the pinned resolution."""
    role = AO_MAP_RECORD
    expect(record, role, ("schema",), AO_MAP_SCHEMA)
    expect(record, role, ("kind",), "ao-map")
    expect(record, role, ("status",), "reproduced")
    expect(record, role, ("repeat", "result"), "byte-identical")
    expect(record, role, ("resolution",), pins.resolution)
    value_at(record, role, ("generator", "path"))
    sha_at(record, role, ("generator", "sha256"))
    expect(record, role, ("donor", "assets3d_path"), AO_DONOR)
    expect(record, role, ("donor", "commit"), pins.snapshot)
    expect(record, role, ("donor", "sha256"), pins.ao_donor)
    line = value_at(record, role, ("donor", "line"))
    if not isinstance(line, str) or "ao.npy" not in line or "65535" not in line:
        raise RecorderError(f"`{role}` `donor.line` is not the donor's conversion line")
    expect(record, role, ("inputs",), {"ao.npy": {"sha256": ao_sha256}})
    name = PurePosixPath(AO).name
    if set(value_at(record, role, ("outputs",))) != {name}:
        raise RecorderError(f"`{role}` `outputs` must be {name} only")
    expect_output(record, role, name, found)
    expect(record, role, ("outputs", name, "shape"), [pins.resolution, pins.resolution])
    expect(record, role, ("outputs", name, "depth"), 16)
    expect(record, role, ("outputs", name, "colour_type"), GREY)


class NonFinite(ValueError):
    """A record holds NaN or an infinity, which no producer writes (`allow_nan=False`)."""


def no_constant(name: str) -> Any:
    raise NonFinite(f"it holds {name}")


def finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise NonFinite(f"it holds {text}, which is not finite")
    return value


def text_at(record: Any, role: str, path: Sequence[str]) -> str:
    """Text that says something: no placeholder (`PLACEHOLDER_TEXT`) and not blank."""
    found = value_at(record, role, path)
    if not isinstance(found, str) or found.strip().lower() in PLACEHOLDER_TEXT:
        raise RecorderError(f"`{role}` `{'.'.join(path)}` is {found!r}: a placeholder or no text")
    return found


def digest_at(record: Any, role: str, path: Sequence[str]) -> str:
    """The SHA-256 of some bytes, never of none."""
    found = sha_at(record, role, path)
    if found == EMPTY_SHA256:
        raise RecorderError(f"`{role}` `{'.'.join(path)}` is the SHA-256 of no bytes")
    return found


def keys_at(record: Any, role: str, path: Sequence[str], keys: frozenset[str]) -> dict[str, Any]:
    """An object of exactly `keys`."""
    found = value_at(record, role, path)
    if not isinstance(found, dict) or set(found) != keys:
        held = sorted(found) if isinstance(found, dict) else type(found)
        where = ".".join(path) or "record"
        raise RecorderError(f"`{role}` `{where}` holds {held}, not {sorted(keys)}")
    return found


def name_at(record: Any, role: str, path: Sequence[str]) -> str:
    """A file named by its plain name, next to the record that names it."""
    found = text_at(record, role, path)
    if found in (".", "..") or PureWindowsPath(found).name != found:
        raise RecorderError(f"`{role}` `{'.'.join(path)}` is {found!r}, not a plain file name")
    return found


def swatch_image(role: str, item: Found) -> dict[str, Any]:
    """A swatch image as its records describe it: its bytes, size and PNG form."""
    data = item.read()
    layout = png_layout(role, data)
    return {
        "sha256": item.sha256,
        "size_bytes": len(data),
        "width": layout.width,
        "height": layout.height,
        "bit_depth": layout.depth,
        "colour_type": layout.colour,
    }


def check_swatch(record: Any, name: str, image: Found, pins: Pins) -> None:
    """A swatch provenance record (`SWATCH_SCHEMA`, as front W's `load_swatch` accepts it): the
    swatch's file and its image, by hash, size and PNG form; its source, either the `original`
    the pinned `v5.json` (named by its own SHA-256) lists, or a `generated` substitute with its
    generator, model, route and declaration as text, its prompt's hash and every visual
    reference by plain name, hash and size (an empty list only when it used none)."""
    role = SWATCH_RECORDS[name]
    file = SWATCHES[SWATCH_NAMES.index(name)]
    keys_at(record, role, (), SWATCH_KEYS)
    for key, value in (("schema", SWATCH_SCHEMA), ("kind", "swatch"), ("swatch", name)):
        expect(record, role, (key,), value)
    expect(record, role, ("file",), file)
    keys_at(record, role, ("image",), IMAGE_KEYS)
    expect(record, role, ("image",), swatch_image(file, image))
    source = value_at(record, role, ("source",))
    kind = source.get("type") if isinstance(source, dict) else None
    if not isinstance(kind, str) or kind not in SOURCE_KEYS:
        raise RecorderError(f"`{role}` `source.type` is {kind!r}, not one of {sorted(SOURCE_KEYS)}")
    keys_at(record, role, ("source",), SOURCE_KEYS[kind])
    expect(record, role, ("classification",), CLASSIFICATIONS[kind])
    originals = dict(zip(SWATCH_NAMES, pins.originals, strict=True))
    if kind == "original":
        expect(record, role, ("source", "assets3d_path"), SWATCH_PATHS[name])
        expect(record, role, ("source", "v5_json_sha256"), pins.v5_json)
        expect(record, role, ("image", "sha256"), originals[name])
        return
    for key in ("generator", "model", "route", "authorization_declaration"):
        text_at(record, role, ("source", key))
    prompt = name_at(record, role, ("source", "prompt_file"))
    taken = {SWATCH_RECORD_NAME, file, prompt}
    if len(taken) != 3:
        raise RecorderError(f"`{role}` `source.prompt_file` {prompt!r} names the record or image")
    digest_at(record, role, ("source", "prompt_sha256"))
    references = value_at(record, role, ("source", "references"))
    if not isinstance(references, list):
        raise RecorderError(f"`{role}` `source.references` is no list (empty only if none used)")
    for k, reference in enumerate(references):
        where = f"{role} reference {k}"
        keys_at(reference, where, (), REFERENCE_KEYS)
        text_at(reference, where, ("role",))
        named = name_at(reference, where, ("file",))
        if named in taken:
            raise RecorderError(f"`{where}` `file` {named!r} is already named by the record")
        taken.add(named)
        digest_at(reference, where, ("sha256",))
        size = reference["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise RecorderError(f"`{where}` `size_bytes` is {size!r}, not a size")
    if image.sha256 in originals.values():
        raise RecorderError(f"`{role}` is generated, but its image has an original's bytes")


def check_colour(
    record: Any,
    files: Mapping[str, Mapping[str, str]],
    records: Mapping[str, Any],
    found: Mapping[str, Found],
    pins: Pins,
) -> None:
    """Front W's colour record (`sash_colour.py`), the independent repeat's: it reproduced its
    first run byte for byte; its helper; the donor T's masks record ran (the same source blobs,
    runtime, orientation and padding), past the colour boundary, at the pinned resolution, 8-bit
    RGB, reading `cloth`, then `hem`; P's three receipts and T's masks record, the very records
    the masks role cites, with their arrays, masks and texels; each swatch's provenance record
    and image; every file it verified and staged, unchanged by the run; and `T_sash` as its one
    output, exactly the inputs file's bytes. (Its `host` and `split` are its own repeat's.)"""
    role = COLOUR_RECORD
    masks = records[MASKS_RECORD]
    swatches = {name: records[SWATCH_RECORDS[name]] for name in SWATCH_NAMES}
    for key, value in (("schema", COLOUR_SCHEMA), ("kind", "colour"), ("piece", "sash")):
        expect(record, role, (key,), value)
    expect(record, role, ("status",), "reproduced")
    expect(record, role, ("repeat", "result"), "byte-identical")
    expect(record, role, ("repeat", "problems"), [])
    sha_at(record, role, ("repeat", "of_record_sha256"))

    expect(record, role, ("helper", "path"), COLOUR_HELPER)
    sha_at(record, role, ("helper", "sha256"))
    checks = value_at(record, role, ("helper", "checks_with"))
    if not isinstance(checks, list) or len(checks) != len(COLOUR_CHECKS_WITH):
        raise RecorderError(f"`{role}` `helper.checks_with` must be {list(COLOUR_CHECKS_WITH)}")
    for check, path in zip(checks, COLOUR_CHECKS_WITH, strict=True):
        keys_at(check, f"{role} checks_with", (), frozenset({"path", "sha256"}))
        expect(check, f"{role} checks_with", ("path",), path)
        sha_at(check, f"{role} checks_with", ("sha256",))
    expect(record, role, ("sources",), masks["sources"])  # checked against the pins already
    expect(record, role, ("manifest", "assets3d_path"), V5_JSON)
    expect(record, role, ("manifest", "commit"), pins.snapshot)
    expect(record, role, ("manifest", "sha256"), pins.v5_json)
    lists = dict(zip(SWATCH_NAMES, pins.originals, strict=True))
    expect(record, role, ("manifest", "lists"), lists)
    expect(record, role, ("runtime",), value_at(masks, MASKS_RECORD, ("runtime",)))
    keys_at(record, role, ("parameters",), COLOUR_KEYS)
    expect(record, role, ("parameters", "resolution"), pins.resolution)
    for key in ("orientation", "padding"):
        expect(
            record, role, ("parameters", key), value_at(masks, MASKS_RECORD, ("parameters", key))
        )
    expect(record, role, ("parameters", "quantisation"), QUANTISATION)
    expect(record, role, ("parameters", "png"), {"bit_depth": 8, "colour_type": RGB})
    expect(record, role, ("parameters", "swatch_reads"), list(SWATCH_NAMES))

    cited: dict[str, dict[str, Any]] = {
        name: {k: v for k, v in masks["receipts"][name].items() if k != "path"}
        for name in COLOUR_RECEIPTS
    }
    cited["masks"] = {
        "sha256": files[MASKS_RECORD]["sha256"],
        "schema": MASKS_SCHEMA,
        "kind": "masks",
        "status": "reproduced",
        "of_record_sha256": masks["repeat"]["of_record_sha256"],
    }
    for name, swatch in swatches.items():
        cited[f"swatch-{name}"] = {
            "sha256": files[SWATCH_RECORDS[name]]["sha256"],
            "schema": SWATCH_SCHEMA,
            "kind": "swatch",
            "swatch": name,
            "classification": swatch["classification"],
            "image_sha256": swatch["image"]["sha256"],
        }
    keys_at(record, role, ("receipts",), frozenset(cited))
    for name, receipt in cited.items():
        keys_at(record, role, ("receipts", name), frozenset({*receipt, "path"}))
        for key, value in receipt.items():
            expect(record, role, ("receipts", name, key), value)
    link = {"extraction_record_sha256": files[EXTRACT_RECORD]["sha256"]}
    expect(record, role, ("extraction_link",), link | {"cited_by": ["ao", "centre", "masks"]})
    expect(record, role, ("arrays",), masks["arrays"])
    entries = {
        name: {
            "file": swatch["file"],
            "assets3d_path": SWATCH_PATHS[name],
            "classification": swatch["classification"],
            "source": swatch["source"],
            **swatch["image"],
        }
        for name, swatch in swatches.items()
    }
    expect(record, role, ("swatches",), entries)

    verified = {
        name: files[receipt]["sha256"]
        for name, receipt in (
            ("extraction", EXTRACT_RECORD),
            ("ao", AO_RECORD),
            ("centre", CENTRE_RECORD),
            ("masks", MASKS_RECORD),
        )
    }
    staged = {name: masks["arrays"][name]["sha256"] for name in MASK_ARRAYS}
    for name, swatch in swatches.items():
        verified[f"swatch-{name}"] = files[SWATCH_RECORDS[name]]["sha256"]
        verified[f"image-{name}"] = swatch["image"]["sha256"]
        staged[swatch["file"]] = swatch["image"]["sha256"]
        source = swatch["source"]
        if source["type"] == "generated":
            verified[f"prompt-{name}"] = source["prompt_sha256"]
            for reference in source["references"]:
                verified[f"reference-{name}-{reference['file']}"] = reference["sha256"]
    both = {"verified": verified, "staged": staged}
    expect(record, role, ("inputs",), {"before": both, "after": both})
    compared = [output["name"] for output in masks["outputs"]]
    keys_at(record, role, ("masks",), frozenset({"compared", "result", "record_sha256"}))
    expect(record, role, ("masks", "compared"), compared)
    expect(record, role, ("masks", "result"), MASKS_COMPARED)
    expect(record, role, ("masks", "record_sha256"), files[MASKS_RECORD]["sha256"])
    expect(record, role, ("texels",), value_at(masks, MASKS_RECORD, ("texels",)))

    outputs = value_at(record, role, ("outputs",))
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise RecorderError(f"`{role}` `outputs` must be {COLOUR} only")
    where = f"{role} {COLOUR}"
    output = keys_at(
        outputs[0],
        where,
        (),
        frozenset(
            {
                "name",
                "file",
                "role",
                "sha256",
                "size_bytes",
                "shape",
                "depth",
                "colour_type",
                "median_srgb",
            }
        ),
    )
    wanted: tuple[tuple[str, Any], ...] = (
        ("name", COLOUR),
        ("file", f"{COLOUR}.png"),
        ("role", "base-colour"),
        ("sha256", found[COLOUR].sha256),
        ("size_bytes", len(found[COLOUR].read())),
        ("shape", [pins.resolution, pins.resolution]),
        ("depth", 8),
        ("colour_type", RGB),
    )
    for key, value in wanted:
        expect(output, where, (key,), value)
    median = output["median_srgb"]
    if (
        not isinstance(median, list)
        or len(median) != 3
        or not all(
            isinstance(x, int | float) and not isinstance(x, bool) and 0 <= x <= 1 for x in median
        )
    ):
        raise RecorderError(
            f"`{where}` `median_srgb` is {median!r}, not three sRGB values in [0, 1]"
        )
    expect(record, role, ("substitute", "classification"), "current-round substitute")
    classified = {name: swatch["classification"] for name, swatch in swatches.items()}
    expect(record, role, ("substitute", "swatches"), classified)


def check_receipts(
    files: Mapping[str, Mapping[str, str]], found: Mapping[str, Found], pins: Pins
) -> dict[str, Any]:
    """Every receipt read and its typed links checked; returns the records by role. With `T_sash`,
    each swatch's provenance record, then the colour record, which must cite them."""
    records: dict[str, Any] = {}
    for role in receipt_roles(pins):
        try:
            records[role] = json.loads(
                found[role].read().decode("utf-8"),
                parse_constant=no_constant,
                parse_float=finite_float,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, NonFinite) as error:
            raise RecorderError(f"`{role}` is not a JSON record ({error})") from error
    extract_sha256 = files[EXTRACT_RECORD]["sha256"]
    check_low(records[LOW_RECORD], pins)
    check_extract(records[EXTRACT_RECORD], records[LOW_RECORD], pins)
    check_ao(records[AO_RECORD], extract_sha256)
    check_centre(records[CENTRE_RECORD], extract_sha256)
    check_masks(records[MASKS_RECORD], files, records, found, pins)
    check_ao_map(records[AO_MAP_RECORD], produced_arrays(records)["ao.npy"], found["ao"], pins)
    if COLOUR in pins.bitmaps:
        for name, file in zip(SWATCH_NAMES, SWATCHES, strict=True):
            check_swatch(records[SWATCH_RECORDS[name]], name, found[file], pins)
        if found[SWATCHES[0]].sha256 == found[SWATCHES[1]].sha256:
            raise RecorderError("the cloth and hem swatches are the same image")
        check_colour(records[COLOUR_RECORD], files, records, found, pins)
    return records


def windows_root(script: bytes, name: str, args_path: str) -> str:
    """The Assets3D root as the script's one hard-coded arguments path writes it."""
    found = {
        node.value
        for node in ast.walk(ast.parse(script, filename=name))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and tail_matches(node.value, args_path)
    }
    if len(found) != 1:
        raise RecorderError(f"{name} must name {args_path} in exactly one string literal")
    literal = found.pop()
    return literal[: len(literal) - len(args_path) - 1]


def arguments_bytes(arguments: Mapping[str, str]) -> bytes:
    return (json.dumps(dict(arguments), indent=2) + "\n").encode("utf-8")


def authored_arguments(root: str, normal: Blob) -> tuple[bytes, bytes]:
    """Both arguments files, authored for the round: the create arguments name the staged low,
    the Normal substitute and the AO (the recorder repoints them and `dst`); the export prefix is
    the piece, so the five maps take the migration's names."""

    def windows(path: str) -> str:
        return root + "\\" + path.replace("/", "\\")

    create = {
        "mesh": windows(LOW_OBJ),
        "normal": windows(normal.path),
        "ao": windows(AO),
        "dst": windows(PROJECT),
        "name": PIECE,
    }
    export = {"out": windows(EXPORT_OUT), "prefix": PIECE}
    return arguments_bytes(create), arguments_bytes(export)


def note_of(role: str, records: Mapping[str, Any], files: Mapping[str, Mapping[str, str]]) -> str:
    """A receipt as a note cites it: its schema, its kind when it has one, and its hash."""
    kind = records[role].get("kind")
    schema = records[role]["schema"] + (f" {kind}" if kind else "")
    return f"{schema} record sha256 {files[role]['sha256']}"


def assets3d_item(input_id: str, kind: str, path: str, sha256: str, note: str) -> dict[str, Any]:
    return {
        "input_id": input_id,
        "kind": kind,
        "assets3d_path": path,
        "sha256": sha256,
        "provenance": {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE, "note": note},
    }


DESCRIPTION = (
    "Tier 1 current round of the UzmiGames sash 25-Faixa-Cintura v5 (decision 300 items 7-8): a "
    "current reference, not the historical round and not an approved baseline. The waist-v5 "
    "scripts run byte-unchanged in Painter under decision 099's two adaptations, each the raw "
    "git blob of one Assets3D snapshot pinned by SHA-256: painter_create.py (the low under OCIO "
    "with Painter's substance config, OpenGL normals, 2048 px, no cameras; the Normal and AO "
    "mesh maps; save_as Full), painter_layer_stack.py sync with stack-sash.json (20 fills, 19 "
    "masks and the T_sash base colour, resource prefix v5f_, group faixa25_v5, texture set "
    "25-Faixa-Cintura; its import run.py and run's two import-time helpers loaded from their "
    "pinned bytes) and painter_export.py with the authored prefix 25-Faixa-Cintura (BaseColor, "
    "Roughness, Metallic, Height and Normal as 16-bit PNG, sizeLog2 11, infinite padding, no "
    "dithering; no fourth step). Both arguments files are authored for the round. Every other "
    "input is a named substitute made now (the low, the Normal, the AO, the masks, T_sash), "
    "pinned by hash under the receipt its note names; the historical inputs stay missing. "
    "Recordings: r1 (create, sync, export), r1-repeat (export again) and r2 (after save, close "
    "and reopen, export again), which must be byte-identical."
)


def current_request(
    assets_root: Path,
    store: OracleStore,
    files: Mapping[str, Mapping[str, str]] | None,
    pins: Pins = PINS,
) -> dict[str, Any]:
    """The request: refused with `MissingInputs` naming every absent role before anything is
    stored; refused on a wrong hash, shape or receipt; else every input is stored and the
    request returned once its job loads from the store."""
    files = dict(files or {})
    roles = {*substitute_roles(pins), *receipt_roles(pins)}
    unknown = sorted(set(files) - roles)
    if unknown:  # M_cloth among them: an auxiliary mask is no input
        raise RecorderError(f"the inputs file names unknown roles {unknown}")
    for role, sha256 in (("low-obj", pins.low_obj), ("low-mtl", pins.low_mtl)):
        if role in files and files[role]["sha256"] != sha256:
            raise RecorderError(f"`{role}` is {files[role]['sha256']}, not front N's {sha256}")
    missing: list[str] = []
    found: dict[str, Found] = {}
    for blob in pins.blobs:
        item = find_blob(blob, assets_root, store, pins.snapshot)
        if item is None:
            missing.append(f"{blob.path}@{pins.snapshot[:8]}")
        else:
            found[blob.input_id] = item
    normal = find_normal(pins.normal, assets_root, store)
    if normal is None:
        missing.append(pins.normal.input_id)
    else:
        found[pins.normal.input_id] = normal
    for role in sorted(roles | set(files)):
        item = find_entry(role, files[role], store) if role in files else None
        if item is None:
            missing.append(role)
        else:
            found[role] = item
    if missing:
        raise MissingInputs(GOLDEN_ID, missing)

    stack = json.loads(found["sash-stack"].read().decode("utf-8"))
    if sorted(stack_bitmaps(stack)) != sorted(pins.bitmaps):
        raise RecorderError(f"the stack's bitmaps are {sorted(stack_bitmaps(stack))}")
    size = pins.resolution
    for role in pins.bitmaps:
        if role == COLOUR:
            require_png(role, found[role].read(), frozenset({8}), frozenset({RGB}), size)
        else:
            require_png(role, found[role].read(), frozenset({16}), frozenset({GREY}), size)
    require_png("ao", found["ao"].read(), frozenset({16}), frozenset({GREY}), size)
    for swatch in (s for s in SWATCHES if s in found):
        require_png(swatch, found[swatch].read(), frozenset({8}), frozenset({RGB, RGBA}), None)
    obj = found["low-obj"].file
    assert obj is not None  # a private input is a file, never a git blob
    library = material_library(obj)
    if library != PurePosixPath(LOW_MTL).name:
        raise RecorderError(f"the low OBJ names the material library {library!r}")
    records = check_receipts(files, found, pins)
    root = windows_root(found["painter-create-py"].read(), "painter_create.py", CREATE_ARGS)
    if windows_root(found["painter-export-py"].read(), "painter_export.py", EXPORT_ARGS) != root:
        raise RecorderError("the create and export scripts hard-code different Assets3D roots")
    create_args, export_args = authored_arguments(root, pins.normal)
    found["painter-create-args"] = Found(sha256_bytes(create_args), data=create_args)
    found["painter-export-args"] = Found(sha256_bytes(export_args), data=export_args)

    paths = {blob.input_id: blob.path for blob in (*pins.blobs, pins.normal)}
    paths.update(
        {
            "painter-create-args": CREATE_ARGS,
            "painter-export-args": EXPORT_ARGS,
            "low-obj": LOW_OBJ,
            "low-mtl": LOW_MTL,
            "ao": AO,
            **{role: f"{MASKS}/{role}.png" for role in pins.bitmaps},
        }
    )
    manifest = request_manifest(found, files, records, pins)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the {GOLDEN_ID} request is invalid: {problems}")
    for role, item in found.items():
        store_input(store, item, paths.get(role, f"private/{GOLDEN_ID}/{role}"))
    script_job_from_manifest(manifest, assets_root, store)
    return manifest


def store_input(store: OracleStore, item: Found, path: str) -> None:
    """Into the private store (decision 144), unless it is there: a file as it is, a git blob's
    or an authored file's bytes through a staging file inside the store, removed afterwards."""
    if stored(store, path, item.sha256) is not None:
        return
    if item.file is not None:
        store.add_input(item.file, item.sha256, path)
        return
    staging = store.staging_path()
    try:
        with staging.open("xb") as stream:
            stream.write(item.read())
        store.add_input(staging, item.sha256, path)
    finally:
        staging.unlink(missing_ok=True)
    if stored(store, path, item.sha256) is None:
        raise RecorderError(f"{path}: not stored")


def request_manifest(
    found: Mapping[str, Found],
    files: Mapping[str, Mapping[str, str]],
    records: Mapping[str, Mapping[str, Any]],
    pins: Pins,
) -> dict[str, Any]:
    snapshot = pins.snapshot[:8]
    inputs = [
        assets3d_item(
            blob.input_id,
            blob.kind,
            blob.path,
            blob.sha256,
            f"Raw git blob of Assets3D {snapshot} {blob.path} (LF), read from Assets3D's object "
            "database into the private store: the committed file the current round runs. Which "
            "bytes the historical round ran is unestablished.",
        )
        for blob in pins.blobs
    ]
    for input_id, path in (
        ("painter-create-args", CREATE_ARGS),
        ("painter-export-args", EXPORT_ARGS),
    ):
        inputs.append(
            assets3d_item(
                input_id,
                "recipe_json",
                path,
                found[input_id].sha256,
                "Authored for the current round (decision 300 item 7), not the lost round's "
                f"arguments: the piece name and export prefix {PIECE}; the recorder repoints "
                "its paths into the private work directory.",
            )
        )
    low_receipt = note_of(LOW_RECORD, records, files)
    low = f"from the preserved .blend {pins.low_source}, receipt {low_receipt}"
    for input_id, role, path in (
        ("sash-mesh", "low-obj", LOW_OBJ),
        ("sash-mesh-mtl", "low-mtl", LOW_MTL),
    ):
        inputs.append(
            assets3d_item(
                input_id,
                "mesh",
                path,
                found[role].sha256,
                "Current-round substitute, not the round's lost low: front N's deterministic "
                f"export (sash_low_export) {low}.",
            )
        )
    inputs.append(
        assets3d_item(
            pins.normal.input_id,
            "image",
            pins.normal.path,
            pins.normal.sha256,
            "Named substitute for the Normal mesh map: the surviving bake under the piece's "
            "Textures. Its identity with the historical Normal is unestablished.",
        )
    )
    inputs.append(
        assets3d_item(
            "sash-ao",
            "image",
            AO,
            found["ao"].sha256,
            "Current-round substitute, not the historical AO mesh map: made by "
            f"{records[AO_MAP_RECORD]['generator']['path']} "
            f"({records[AO_MAP_RECORD]['generator']['sha256']}), receipt "
            f"{note_of(AO_MAP_RECORD, records, files)}, from front P's ao.npy "
            f"{records[AO_RECORD]['outputs']['ao.npy']['sha256']} (receipt "
            f"{note_of(AO_RECORD, records, files)}).",
        )
    )
    masks = records[MASKS_RECORD]
    sources = {s["module"]: s["sha256"] for s in masks["sources"]}
    intermediates = (
        "from front P's "
        + ", ".join(f"{n} {masks['arrays'][n]['sha256']}" for n in MASK_ARRAYS)
        + f" (receipts {note_of(EXTRACT_RECORD, records, files)}; "
        f"{note_of(AO_RECORD, records, files)}; {note_of(CENTRE_RECORD, records, files)})"
    )
    for role in sorted(pins.bitmaps):
        if role == COLOUR:
            colour = records[COLOUR_RECORD]
            swatches = "; ".join(
                f"{file} {files[file]['sha256']} "
                f"({records[SWATCH_RECORDS[name]]['classification']}, receipt "
                f"{note_of(SWATCH_RECORDS[name], records, files)})"
                for name, file in zip(SWATCH_NAMES, SWATCHES, strict=True)
            )
            note = (
                f"Current-round substitute, not the historical {role}: written by "
                f"{WAIST_MASKS} sash ({sources['waist_masks']}, colour only) through front W's "
                f"sash_colour, receipt {note_of(COLOUR_RECORD, records, files)} (an independent "
                f"repeat of {colour['repeat']['of_record_sha256']}, byte-identical), its masks "
                f"identical to receipt {note_of(MASKS_RECORD, records, files)}, from the "
                f"swatches {swatches}."
            )
        else:
            note = (
                f"Current-round substitute, not the historical {role}: written by "
                f"{WAIST_MASKS} sash ({sources['waist_masks']}, masks only) through front T's "
                f"sash_masks, receipt {note_of(MASKS_RECORD, records, files)} (an independent "
                f"repeat of {masks['repeat']['of_record_sha256']}, byte-identical), "
                f"{intermediates}."
            )
        inputs.append(
            assets3d_item(
                f"mask-{role.lower()}",
                "image" if role == COLOUR else "mask",
                f"{MASKS}/{role}.png",
                found[role].sha256,
                note,
            )
        )
    create = {
        "script": "painter-create-py",
        "args_file": "painter-create-args",
        "mesh": "sash-mesh",
        "mesh_material_library": "sash-mesh-mtl",
        "normal": pins.normal.input_id,
        "ao": "sash-ao",
    }
    sync = {
        "script": "painter-layer-stack-py",
        "command": SYNC_COMMAND,
        "stack": "sash-stack",
        "mask_folder": MASKS,
        "imports": ["production-run-py"],
        "import_closure": list(CLOSURE),
        **SYNC_OPTIONS,
    }
    export = {"script": "painter-export-py", "args_file": "painter-export-args"}
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": GOLDEN_ID,
        "tier": "1",
        "domain": "tier1/pilot/sash-v5-current",
        "description": DESCRIPTION,
        "inputs": inputs,
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": INTERFACE,
            "steps": [
                {"step": n, "call": RUN_SCRIPT, "args": args}
                for n, args in enumerate((create, sync, export), start=1)
            ],
        },
        "applied_settings": [
            {"name": name, "value": value, "applied_by": by} for name, value, by in WAND_SETTINGS
        ],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.2.0",
                "build_id": "12.2.0+js-api.1.1.20",
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.sash_current")
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="write the request once every input exists")
    request.add_argument("--assets-root", type=Path, required=True)
    request.add_argument("--inputs", type=Path, help="the private inputs file (INPUTS_SCHEMA)")
    request.add_argument("--out", type=Path, required=True)
    request.add_argument("--store", type=Path, help="the private store (default: this machine's)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        store = OracleStore.open(args.store) if args.store else locate()
        if store is None:
            raise RecorderError("there is no private store on this machine")
        files = load_inputs(args.inputs) if args.inputs else None
        manifest = current_request(args.assets_root.resolve(), store, files, PINS)
    except MissingInputs as error:
        print(f"refused: {error}", file=sys.stderr)
        print(json.dumps({"missing": error.missing}, indent=2), file=sys.stderr)
        return 2
    except (RecorderError, StoreError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
