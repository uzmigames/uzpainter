r"""The Sash v5 current round's AO mesh map, from front P's `ao.npy` (decision 300 §7).

    python -m tools.parity.tier1.sash_ao_map --assets-root <Assets3D>
        --ao <the accepted AO record> --ao-record-sha256 <its SHA-256> [--run NAME]
        [--expect <earlier ao-map-record.json>] [--dry-run]

`sashchain.sh` turned `garment_blender_io.py`'s `ao.npy` into the AO mesh map with one line
(`DONOR_LINE`). This producer applies that conversion to front P's current-round `ao.npy` and
writes the PNG under the name the current round's request binds (`OUTPUT_NAME`, the base name
of `sash_current.AO`). The PNG is a current-round substitute, never the historical
`25-Faixa-Cintura_AO_v5`. This is technical preparation, not a baseline approval (decision 300
item 8).

1. **Donor.** `sashchain.sh` is read as the raw git blob of the Assets3D snapshot `SNAPSHOT`
   (`git cat-file`), never from the checkout. Its git id, SHA-256 and size must equal the pin,
   and it must hold `DONOR_LINE` as one line. Nothing of it is run.
2. **Inputs, by hash.** The AO record (front P's `sash_intermediates ao`, schema
   `sash-intermediates-record/1`, kind `ao`) must hash to the accepted SHA-256 given on the command
   line. Its extraction link must be exact: the extraction record it names hashes to its
   `extraction.record_sha256`, and so does the `extraction_record_sha256` of its `ao-expect.json`,
   which itself hashes to the record, as `ao-report.json` does. `ao.npy` is read once; those
   bytes must hash to the record's `outputs`, and the array they hold must be float16,
   `RESOLUTION` square, have the record's digest, and every value finite and inside [0, 1].
3. **Transformation.** `TRANSFORMATION`, the donor's arithmetic, on the bottom-first rows Blender
   writes, so the PNG's first row is V = 1. The samples are linear: no gamma, no transfer function
   and no colour chunk.
4. **Encoding.** The repository's own encoder (`tools.parity.feasibility.png.encode`): 16-bit grey,
   one IDAT holding one zlib stream at level 9, the Up filter on every row, and no ancillary chunk
   (no `tIME`, `gAMA`, `sRGB` or `iCCP`). The bytes are decoded again and must give the quantized
   samples back. The interpreter, NumPy and zlib are pinned (`RUNTIME`).
5. **Receipt.** `ao-map-record.json` (`RECORD_SCHEMA`) is written after the PNG, only once every
   check has passed; a refused or failed run leaves nothing. A repeat (`--expect`) first checks
   the earlier PNG against its record, then runs again in a fresh directory and process and must
   reproduce every pin, input hash and output byte for byte; its record states the result.

`--dry-run` checks the donor, the runtime and the inputs and prints the plan; it writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import struct
import subprocess
import sys
import zlib
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
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1.sash_intermediates_blender import ExtractError

RECORD_SCHEMA = "uzpainter/parity/sash-ao-map-record/1"  # sash_current.AO_MAP_SCHEMA
RECORD_NAME = "ao-map-record.json"
KIND = "ao-map"
DEFAULT_RUN = host.RUN_PREFIX + "ao-map-r1"
OUTPUT_NAME = "25-Faixa-Cintura_AO_v5.png"  # the base name of sash_current.AO
SNAPSHOT = "1c9a312a47eea0b35aa0aa05777245ef61ac49e5"  # Assets3D, 2026-10-20 (sash_current's)
RESOLUTION = side.AO_RESOLUTION  # sashchain.sh `--ao-resolution 2048`
PNG_FORM = (16, 0)  # IHDR bit depth and colour type (grey)


@dataclass(frozen=True)
class Donor:
    """`sashchain.sh` as one raw git blob: path, git id, SHA-256 and size."""

    path: str
    blob: str
    sha256: str
    size_bytes: int

    def as_json(self, commit: str, line: str) -> dict[str, Any]:
        return {
            "assets3d_path": self.path,
            "commit": commit,
            "git_blob": self.blob,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "read_from": "git object database (git cat-file), never the checkout",
            "line": line,
            "run": False,
        }


# The same blob from its first commit at this path (d974c81e, 2026-10-11) to Assets3D HEAD
# a8a06a1c; the checkout's bytes are the blob's too.
DONOR = Donor(
    "Pipeline/retopology/waist-v5/sashchain.sh",
    "191e91d7055cf9b3a271f1cd847c78703ef9c5c8",
    "70ee17308d9754e5df3c1728f26549d9e6ec64a6df9f14981ef1acef2dade65e",
    2_933,
)
DONOR_LINE = (
    "ao=np.load('paint/work-sash/ao.npy').astype(np.float32); Image.fromarray((np.clip(ao[::-1],"
    "0,1)*65535+0.5).astype(np.uint16)).save('paint/obj/sash-ao-v5.png')\""
)  # the last line of a `python -c "..."` argument, its closing quote included
TRANSFORMATION = "uint16(clip(ao.astype(float32)[::-1], 0, 1) * 65535 + 0.5)"
ORIENTATION = (
    "ao.npy holds rows bottom first (Blender image.pixels, V = 0 first); the [::-1] puts them top "
    "first, so the PNG's first row is V = 1"
)
TRANSFER = (
    "none: the float32 values are quantized linearly; no gamma, no transfer function, and the PNG "
    "holds no gAMA, sRGB, cHRM or iCCP chunk"
)
ENCODER = {
    "module": "tools/parity/feasibility/png.py",
    "function": "encode",
    "bit_depth": PNG_FORM[0],
    "colour_type": PNG_FORM[1],
    "filter": "Up (2) on every row",
    "zlib": {"call": "zlib.compress(raw, 9)", "level": 9, "streams": 1},
    "chunks": ["IHDR", "IDAT", "IEND"],
    "time_chunks": "none",
}
# The interpreter and the libraries the array is converted and the PNG compressed with.
RUNTIME = {"python": "3.13.9", "numpy": "2.4.4", "zlib": "1.3.1"}
SUBSTITUTE = {
    "classification": "current-round substitute",
    "replaces": "the AO mesh map sashchain.sh made from ao.npy in the lost round "
    "(paint/obj/sash-ao-v5.png), bound in the migration project as 25-Faixa-Cintura_AO_v5",
    "made_from": "front P's current-round ao.npy, baked now from the preserved High onto the "
    "verified low",
    "historical": "not the historical AO mesh map; its bytes are lost and unestablished, and no "
    "historical-original claim is made",
}


class AoMapError(ExtractError):
    """A pin, an input link or the output does not hold; nothing is recorded."""


@dataclass(frozen=True)
class Pins:
    """What the producer pins; the defaults are the round's (tests pass stand-ins)."""

    snapshot: str = SNAPSHOT
    donor: Donor = DONOR
    donor_line: str = DONOR_LINE
    runtime: Mapping[str, str] = field(default_factory=lambda: dict(RUNTIME))
    resolution: int = RESOLUTION


PINS = Pins()


# ------------------------------------------------------------------------------------ runtime
def found_runtime() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
    }


def runtime_problems(found: Mapping[str, str], pins: Mapping[str, str]) -> list[str]:
    return [
        f"{name} is {found.get(name)!r}, pinned {pinned!r}"
        for name, pinned in pins.items()
        if found.get(name) != pinned
    ]


# -------------------------------------------------------------------------------------- donor
def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def read_donor(assets_root: Path, pins: Pins) -> bytes:
    """The raw blob at `snapshot:path` from Assets3D's object database, every pin checked, and
    the conversion line in it."""
    donor = pins.donor
    run = subprocess.run(
        ["git", "-C", str(assets_root), "cat-file", "blob", f"{pins.snapshot}:{donor.path}"],
        capture_output=True,
        check=False,
    )
    if run.returncode != 0:
        raise AoMapError(f"{donor.path} is not in Assets3D's object database at {pins.snapshot}")
    data = run.stdout
    found = (git_blob_id(data), sha256_bytes(data), len(data))
    if found != (donor.blob, donor.sha256, donor.size_bytes):
        raise AoMapError(
            f"{donor.path} at {pins.snapshot[:8]} is blob {found[0]}, sha256 {found[1]}, "
            f"{found[2]} bytes; pinned {donor.blob}, {donor.sha256}, {donor.size_bytes}"
        )
    if pins.donor_line not in data.decode("utf-8").splitlines():
        raise AoMapError(f"{donor.path} does not hold the pinned conversion line")
    return data


# ------------------------------------------------------------------------------------- inputs
def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def _recorded_file(record: Mapping[str, Any], record_path: Path, name: str) -> bytes:
    """A file the record names as an output, next to it, read once; its bytes match the record."""
    entry = _get(record, ("outputs", name))
    path = record_path.parent / name
    if not isinstance(entry, Mapping) or not path.is_file():
        raise AoMapError(f"{record_path} names no {name}, or {path} is missing")
    data = path.read_bytes()
    if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
        raise AoMapError(f"{path} is not the {name} its record names ({dict(entry)})")
    return data


@dataclass(frozen=True)
class Inputs:
    receipt: dict[str, Any]
    array: dict[str, Any]
    ao: Any


def check_inputs(ao_record: Path, ao_record_sha256: str, resolution: int) -> Inputs:
    """Front P's AO record by its accepted hash, its exact extraction link, and its `ao.npy`."""
    data = ao_record.read_bytes()
    found = sha256_bytes(data)
    if found != ao_record_sha256:
        raise AoMapError(f"{ao_record} has SHA-256 {found}, the accepted {ao_record_sha256}")
    record = json.loads(data)
    if (_get(record, ("schema",)), _get(record, ("kind",))) != (host.RECORD_SCHEMA, "ao"):
        raise AoMapError(f"{ao_record} is not a {host.RECORD_SCHEMA} ao record")

    link = _get(record, ("extraction", "record_sha256"))
    extraction = _get(record, ("extraction", "record"))
    if not isinstance(link, str) or not isinstance(extraction, str):
        raise AoMapError(f"{ao_record} names no extraction record and hash")
    if not Path(extraction).is_file() or sha256_file(Path(extraction)) != link:
        raise AoMapError(f"{extraction} is missing or does not hash to {link}")
    expect = json.loads(_recorded_file(record, ao_record, side.AO_EXPECT))
    if _get(expect, ("extraction_record_sha256",)) != link:
        raise AoMapError(f"{side.AO_EXPECT} names another extraction than {link}")

    _recorded_file(record, ao_record, side.AO_REPORT)

    raw = _recorded_file(record, ao_record, side.AO_NAME)
    try:
        ao = np.load(io.BytesIO(raw), allow_pickle=False)
    except (EOFError, ValueError, OSError) as error:
        raise AoMapError(f"{side.AO_NAME} is not a .npy array ({error})") from error
    if not isinstance(ao, np.ndarray):
        raise AoMapError(f"{side.AO_NAME} holds a {type(ao).__name__}, not one .npy array")
    shape = (resolution, resolution)
    if ao.dtype.str != "<f2" or ao.shape != shape:
        raise AoMapError(
            f"{side.AO_NAME} is {ao.dtype.str}{list(ao.shape)}, pinned <f2{list(shape)}"
        )
    if not np.isfinite(ao).all():
        raise AoMapError(f"{side.AO_NAME} holds non-finite values")
    if ao.min() < 0 or ao.max() > 1:
        raise AoMapError(f"{side.AO_NAME} holds values outside [0, 1]")
    if side.array_digest(ao) != _get(record, ("ao", "digest")):
        raise AoMapError(f"{side.AO_NAME} differs from its record's digest")
    receipt = {
        "path": str(ao_record),
        "sha256": found,
        "schema": host.RECORD_SCHEMA,
        "kind": "ao",
        "extraction_record": extraction,
        "extraction_record_sha256": link,
        "ao_expect_sha256": _get(record, ("outputs", side.AO_EXPECT, "sha256")),
    }
    array = {
        "file": side.AO_NAME,
        "path": str(ao_record.parent / side.AO_NAME),
        "sha256": sha256_bytes(raw),
        "size_bytes": len(raw),
        "digest": side.array_digest(ao),
        "dtype": ao.dtype.str,
        "shape": list(ao.shape),
        "range": [float(ao.min()), float(ao.max())],
        "row_order": "bottom first",
    }
    return Inputs(receipt, array, ao)


# --------------------------------------------------------------------------------- conversion
def quantize(ao: Any) -> Any:
    """`sashchain.sh`'s conversion: float32, rows reversed, clipped, scaled and truncated."""
    return (np.clip(ao.astype(np.float32)[::-1], 0, 1) * 65535 + 0.5).astype(np.uint16)


def encode(samples: Any) -> bytes:
    """The PNG bytes, checked: exactly IHDR, one IDAT and IEND, the pinned form, and decoded
    back to `samples`."""
    data = png.encode(samples, PNG_FORM[0])
    if host.png_chunk_problems(data):
        raise AoMapError("; ".join(host.png_chunk_problems(data)))
    kinds = [kind for kind, _ in png.chunks(data)]
    if kinds != [b"IHDR", b"IDAT", b"IEND"]:
        raise AoMapError(f"the PNG holds the chunks {kinds}")
    width, height, depth, colour = struct.unpack(">IIBB", png.chunks(data)[0][1][:10])
    if (height, width, (depth, colour)) != (*samples.shape, PNG_FORM):
        raise AoMapError(f"the PNG is {width}x{height} depth {depth} colour type {colour}")
    if not np.array_equal(png.decode(data)[:, :, 0], samples):
        raise AoMapError("the PNG does not decode to the quantized samples")
    return data


# ---------------------------------------------------------------------------------- producer
@dataclass(frozen=True)
class Plan:
    run_dir: Path
    donor_sha256: str
    inputs: Inputs
    runtime: dict[str, str]
    expected: dict[str, Any] | None
    expected_path: Path | None
    expected_sha256: str | None = None

    def as_json(self, pins: Pins) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "donor": pins.donor.as_json(pins.snapshot, pins.donor_line),
            "runtime": self.runtime,
            "receipt": self.inputs.receipt,
            "array": self.inputs.array,
            "output": OUTPUT_NAME,
            "expect": str(self.expected_path) if self.expected_path else None,
        }


def plan(
    run_dir: Path,
    assets_root: Path,
    ao_record: Path,
    ao_record_sha256: str,
    *,
    expect: Path | None = None,
    pins: Pins = PINS,
    runtime: Callable[[], dict[str, str]] = found_runtime,
) -> Plan:
    """Every check that needs no output: the run directory, runtime, donor, inputs, the earlier
    record."""
    run_dir = ensure_outside_repository(run_dir)
    if run_dir.exists():
        raise AoMapError(f"{run_dir} already exists; every run gets a fresh directory")
    found = runtime()
    problems = runtime_problems(found, pins.runtime)
    if problems:
        raise AoMapError("the runtime is not pinned: " + "; ".join(problems))
    donor = read_donor(assets_root, pins)
    inputs = check_inputs(ao_record, ao_record_sha256, pins.resolution)
    expected, expected_sha256 = None, None
    if expect is not None:
        data = expect.read_bytes()
        expected, expected_sha256 = json.loads(data), sha256_bytes(data)
        if (_get(expected, ("schema",)), _get(expected, ("kind",))) != (RECORD_SCHEMA, KIND):
            raise AoMapError(f"{expect} is not a {RECORD_SCHEMA} record")
        # The earlier PNG itself, not only its record's word for it.
        _recorded_file(expected, expect, OUTPUT_NAME)
    return Plan(run_dir, sha256_bytes(donor), inputs, found, expected, expect, expected_sha256)


def generator_json() -> dict[str, Any]:
    def pin(path: Path) -> dict[str, str]:
        relative = path.resolve().relative_to(REPO_ROOT).as_posix()
        return {"path": relative, "sha256": sha256_file(REPO_ROOT / relative)}

    return {
        **pin(Path(__file__)),
        "checks_with": [
            pin(Path(png.__file__)),
            pin(Path(host.__file__)),
            pin(Path(side.__file__)),
        ],
    }


def produce(the_plan: Plan, pins: Pins = PINS) -> tuple[dict[str, Any], list[str]]:
    """Convert and encode in memory, then write the PNG and, last, the record."""
    samples = quantize(the_plan.inputs.ao)
    data = encode(samples)
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "kind": KIND,
        "status": "produced",
        "piece": "sash",
        "run_dir": str(the_plan.run_dir),
        "resolution": pins.resolution,
        "generator": generator_json(),
        "donor": pins.donor.as_json(pins.snapshot, pins.donor_line),
        "runtime": dict(pins.runtime),
        "host": {"python_executable": sys.executable, "platform": platform.platform()},
        "receipt": the_plan.inputs.receipt,
        "inputs": {side.AO_NAME: {"sha256": the_plan.inputs.array["sha256"]}},
        "array": the_plan.inputs.array,
        "transformation": {
            "expression": TRANSFORMATION,
            "orientation": ORIENTATION,
            "transfer": TRANSFER,
            "donor_output_name": "paint/obj/sash-ao-v5.png",
        },
        "encoder": ENCODER,
        "outputs": {
            OUTPUT_NAME: {
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
                "shape": list(samples.shape),
                "depth": PNG_FORM[0],
                "colour_type": PNG_FORM[1],
                "sample_range": [int(samples.min()), int(samples.max())],
            }
        },
        "substitute": SUBSTITUTE,
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
    run_dir = ensure_outside_repository(the_plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    written = [run_dir / OUTPUT_NAME, run_dir / RECORD_NAME]
    try:
        with written[0].open("xb") as stream:
            stream.write(data)
        if sha256_file(written[0]) != record["outputs"][OUTPUT_NAME]["sha256"]:
            raise AoMapError(f"{written[0]} was not written as encoded")
        with written[1].open("x", encoding="utf-8", newline="\n") as text:
            text.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    except BaseException:
        # A failed run leaves nothing: only this run's own fresh files are removed.
        for path in written:
            path.unlink(missing_ok=True)
        run_dir.rmdir()
        raise
    return record, problems


# ------------------------------------------------------------------------------------ repeats
REPEAT_FIELDS = (
    "schema",
    "kind",
    "piece",
    "resolution",
    "generator",
    "donor",
    "runtime",
    "receipt",
    "inputs",
    "array",
    "transformation",
    "encoder",
    "outputs",
    "substitute",
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
        prog="python -m tools.parity.tier1.sash_ao_map",
        description="The Sash v5 current round's AO mesh map from front P's ao.npy.",
    )
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument(
        "--ao-record-sha256", required=True, help="the accepted AO record's SHA-256"
    )
    parser.add_argument(
        "--ao", type=Path, required=True, help="front P's accepted AO record (no default)"
    )
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's ao-map-record.json")
    parser.add_argument("--dry-run", action="store_true", help="check, print the plan")
    args = parser.parse_args(argv)
    try:
        work = work_root()
        the_plan = plan(
            host.run_dir_for(args.run, work),
            args.assets_root,
            args.ao,
            args.ao_record_sha256,
            expect=args.expect,
        )
        if args.dry_run:
            print(json.dumps(the_plan.as_json(PINS), indent=2))
            return 0
        record, problems = produce(the_plan)
    except (ExtractError, RecorderError, OSError, ValueError, KeyError) as error:
        print(f"sash_ao_map: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    for problem in problems:
        print(f"sash_ao_map: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
