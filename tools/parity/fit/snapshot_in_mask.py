"""Fit of `tier0/semantics/snapshot-in-mask` (phase3.3_procedural-families item 2.15).

`python -m tools.parity.fit.snapshot_in_mask` reads the two admitted goldens (private store):

- `snapshot-in-mask`: the recipes' mask stacks over the 2.13/2.14 grunges and generators;
- `snapshot-in-mask-sources`: each of those sources alone at Normal 1 in a black mask, recorded
  in a second, fresh Painter session (the separating recording);

and the 2.13/2.14 snapshot captures of the same sources (the Painter exports kept under
`%LOCALAPPDATA%/UzPainter/snapshot-recordings/`, found by the receipts' SHA-256 that
`tests/procedural/test_proc_grunge_snapshot_served.py` pins). It prints counts only:

1. Stability: texels where r1 and r2 differ, and where each source of the separating golden
   differs from its snapshot capture (another Painter session).
2. The 16-bit read: every exported value v is some float32 G(k) of a 16-bit code k = round(65535 v).
   The map k -> G(k) over every observed code, whether it is a function (no code with two values),
   and how many codes are not the correctly rounded float32(k / 65535), by code range.
3. The mask arithmetic as codes: m starts at the background code (Black 0, White 65535); each
   effect bottom-up reads m and its source as float32(k / 65535) of their codes (a snapshot's code
   round(65535 b), the bitmap's own code), r = kernel(mode, m, b) clamped to [0, 1], then the
   effect mix (`plain` m + (r - m) alpha, the evaluator's; `fma` fma(r - m, alpha, m)), stored at
   16 bits by the UNORM write rule (arith.h `WriteUnorm`). The User channel's observed code is
   compared with the model's, and its value with G of the model's code.

Nothing is written. Owner machine only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode, decode_exr
from tools.parity.store.store import OracleStore, locate
from tools.parity.tier0_semantics.snapshot_in_mask import (
    BITMAPS,
    CASES,
    NAME,
    READ_NAME,
    SESSION_NAME,
    SOURCE_CASES,
    SOURCES_NAME,
    Case,
    Effect,
)

F32 = npt.NDArray[np.float32]
I64 = npt.NDArray[np.int64]
ROOT = Path(__file__).resolve().parents[3]
SNAPSHOTS = Path.home() / "AppData" / "Local" / "UzPainter" / "snapshot-recordings"
TEXELS = 256 * 256
# The 2.13/2.14 receipts (`capture.json` SHA-256, size), as the served test pins them.
RECEIPTS: dict[str, tuple[str, int]] = {
    "rock": ("744562600f6c345d1205b800af2ebc816a7f1ae8da83b76a47df56de92530d1c", 19098),
    "dirt-large": ("2f9fc160449b0b7cc0af7e58c9b76fe4d3f07d335ed3c24e48a076f3cce3b58c", 16450),
    "dirt-a-seed-1": ("5aed7061b9bb69ca89124c7c98e0b114a0be06127d8523a636780db1a44652dd", 18776),
    "dirt-a-seed-2": ("45d69257803aa34296a63e692d5e11f4002891c22cbddc117e82a859cf1e26a8", 18776),
    "dirt": ("565af07259517ee1b623ea59aa3d59dd366aeb984702877a1b1562e71f4b487d", 12924),
    "dirt-seed-2": ("ea5e561921d469e72cd815636df3aa5967af02833f99f9e5c2a20cc1016d1891", 12934),
    "metal-edge-wear": ("01a0d9121da79b388195b9283f7d0319cbd81fd686b49d5f1c890524746bb472", 13168),
    "mask-builder-legacy": (
        "927b6a167f5c6649d9d2287710f3d603fc3c56b5d5a76e34a84342565d219902",
        15646,
    ),
}
# The captures of the one-session probe of 2026-11-11 (decision 431,
# `tests/python/capture_snapshot_in_mask_session.py`): `capture.json` SHA-256 and size.
SESSION_RECEIPTS: dict[str, tuple[str, int]] = {
    "rock": ("9ef8dc1c6397b59b9d187da0086dcebda344b77a0c2a66e2f4b41dfa08a291b7", 19085),
    "dirt-large": ("aa8006144cb181f4c5dd9d8c1c0869938ecd301864f2d87c4040d27a2c86471c", 16437),
    "dirt-a-seed-1": ("87903364831160847ec60bcc65953ee49c6c0cea777f9dd57caa31f7a25b5fde", 18763),
    "dirt-a-seed-2": ("4faea404f8e9ba2af3cd4ffc1ccf210100c08ebc9081758c8ab2b4c16e053858", 18763),
    "dirt": ("0c0ecb21aba205ac45c0aaca3a66bcfdbf387faab6b25bf7bdf343f7ddfd98e3", 12903),
    "dirt-seed-2": ("67cac4c7108da550c42ef82422510d1090577e48e0ac54e88f4e5d5ec7f5fa37", 12903),
    "metal-edge-wear": ("1a748a21f6633d1fbf2196d0274ee66b99402322bb88d90b426c3bfea2e90553", 13147),
    "mask-builder-legacy": (
        "f37f2cc731c305e999244a2f170b98e520badf442846a5e72284c3c3d2a66001",
        15625,
    ),
}
GENERATOR_CAPTURES = {
    "Dirt": "dirt",
    "Metal Edge Wear": "metal-edge-wear",
    "Mask Builder - Legacy": "mask-builder-legacy",
}
RANGES = ((0, 256), (256, 4096), (4096, 16384), (16384, 32768), (32768, 65536))


def capture_name(effect: Effect) -> str:
    """The 2.13/2.14 capture holding exactly this effect's source and parameters."""
    seed = dict(effect.parameters).get("$randomseed")
    base = effect.asset if effect.kind == "grunge" else GENERATOR_CAPTURES[effect.asset]
    return base if seed is None else f"{base}-seed-{seed}"


def snapshot_rasters(receipts: dict[str, tuple[str, int]] = RECEIPTS) -> dict[str, F32]:
    wanted = {value: name for name, value in receipts.items()}
    found: dict[str, F32] = {}
    for receipt in sorted(SNAPSHOTS.glob("*/capture.json")):
        data = receipt.read_bytes()
        name = wanted.get((hashlib.sha256(data).hexdigest(), len(data)))
        if name is not None:
            values = decode_exr((receipt.parent / "export1" / "user0.exr").read_bytes()).values
            found[name] = np.asarray(values, dtype=np.float32).reshape(-1)
    missing = sorted(set(receipts) - set(found))
    if missing:
        raise SystemExit(f"snapshot captures not on this machine: {missing}")
    return found


def golden_maps(store: OracleStore, name: str) -> dict[tuple[str, int], F32]:
    path = manifest_root(current_envelope()) / "tier0" / "semantics" / f"{name}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    (ref,) = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    record = json.loads(store.blob_path(ref["sha256"]).read_text(encoding="utf-8"))
    maps: dict[tuple[str, int], F32] = {}
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] != "exported_map":
                continue
            k = int(str(output["map"]).rsplit("user", 1)[1].split(":")[0])
            data = store.blob_path(output["blob"]["sha256"]).read_bytes()
            values = np.asarray(decode_exr(data).values, dtype=np.float32).reshape(-1)
            maps[(str(recording["recording_id"]), k)] = values
    return maps


def codes(v: F32) -> I64:
    return np.round(v.astype(np.float64) * 65535.0).astype(np.int64)


def operand(k: I64) -> F32:
    return (k.astype(np.float64) / 65535.0).astype(np.float32)


def bitmap_codes(input_id: str) -> I64:
    """A 16-bit grey fixture's codes, rows top first like the exports."""
    values = np.asarray(decode((ROOT / BITMAPS / f"{input_id}.png").read_bytes()).values)
    if values.ndim == 3:
        values = values[..., 0]
    return values.astype(np.int64).reshape(-1)


def read_g(k: I64) -> F32:
    """G(k): the float32 the channel holds for a mask of 16-bit code k, 1 + (F(k) - 1) with F the
    correctly rounded fetch (decision 424) and the L32F read-out over the white base (arith.h
    `Float32Readout`); equal to 1 - (1 - F(k)), the AO's I(I(F(k)))."""
    one = np.float32(1)
    return ((operand(k) - one).astype(np.float32) + one).astype(np.float32)


def write_unorm16(v: F32) -> I64:
    c = np.clip(np.nan_to_num(v, nan=0.0), 0.0, 1.0).astype(np.float32)
    j = np.floor(c.astype(np.float64) * 2.0**20).astype(np.uint64)
    return ((j * np.uint64(65535) + np.uint64(2**19 - 1)) >> np.uint64(20)).astype(np.int64)


def kernel(mode: str, a: F32, b: F32) -> F32:
    kernels: dict[str, Callable[[F32, F32], F32]] = {
        "Normal": lambda _a, b_: b_,
        "Multiply": lambda a_, b_: (a_ * b_).astype(np.float32),
        "LinearDodge": lambda a_, b_: (a_ + b_).astype(np.float32),
        "Subtract": lambda a_, b_: (a_ - b_).astype(np.float32),
    }
    return np.clip(kernels[mode](a, b), np.float32(0), np.float32(1)).astype(np.float32)


def mix_plain(m: F32, r: F32, alpha: np.float32) -> F32:
    return (m + (r - m) * alpha).astype(np.float32)


def mix_fma(m: F32, r: F32, alpha: np.float32) -> F32:
    d = (r - m).astype(np.float32).astype(np.float64)
    return (d * float(alpha) + m.astype(np.float64)).astype(np.float32)


def model_codes(
    case: Case, sources: dict[str, F32], mix: Callable[[F32, F32, np.float32], F32]
) -> I64:
    k = np.full(TEXELS, 65535 if case.background == "White" else 0, dtype=np.int64)
    for effect in case.effects:
        if effect.kind == "bitmap":
            source = bitmap_codes(effect.asset)
        else:
            source = codes(sources[capture_name(effect)])
        m = operand(k)
        r = kernel(effect.mode, m, operand(source))
        k = write_unorm16(mix(m, r, np.float32(effect.opacity)))
    return k


def read_table(values: list[F32]) -> tuple[dict[int, int], int]:
    """Code -> float32 bits over every observed value, and the codes seen with two values."""
    table: dict[int, int] = {}
    conflicts: set[int] = set()
    for v in values:
        for k, bits in zip(codes(v).tolist(), v.view(np.uint32).tolist(), strict=True):
            if table.setdefault(k, bits) != bits:
                conflicts.add(k)
    return table, len(conflicts)


def report(store: OracleStore) -> Iterator[str]:
    sources = snapshot_rasters()
    probe = golden_maps(store, NAME)
    separating = golden_maps(store, SOURCES_NAME)
    yield "1. Stability"
    for label, maps, cases in (
        (NAME, probe, CASES),
        (SOURCES_NAME, separating, SOURCE_CASES),
    ):
        unstable = sum(int((maps[("r1", k)] != maps[("r2", k)]).sum()) for k in range(len(cases)))
        yield f"   {label}: texels where r1 and r2 differ: {unstable}"
    for k, case in enumerate(SOURCE_CASES):
        other = separating[("r1", k)]
        differ = np.nonzero(other.view(np.uint32) != sources[case.case_id].view(np.uint32))[0]
        largest = int(
            np.abs(codes(other)[differ] - codes(sources[case.case_id])[differ]).max(initial=0)
        )
        yield (
            f"   {case.case_id}: fresh session vs snapshot capture: {differ.size} texels differ, "
            f"largest {largest} codes"
        )
    yield "2. The 16-bit read"
    observed = list(sources.values()) + list(probe.values()) + list(separating.values())
    table, conflicts = read_table(observed)
    off = sum(
        int(((np.abs(v.astype(np.float64) * 65535.0 - codes(v))) > 0.01).sum()) for v in observed
    )
    keys = np.array(sorted(table), dtype=np.int64)
    bits = np.array([table[int(k)] for k in keys], dtype=np.uint32)
    rounded = operand(keys).view(np.uint32)
    yield (
        f"   values not within 0.01 code of a code: {off}; codes seen {keys.size}, "
        f"with two values {conflicts}"
    )
    for lo, hi in RANGES:
        sel = (keys >= lo) & (keys < hi)
        apart = int((bits[sel] != rounded[sel]).sum())
        yield f"   codes {lo}..{hi - 1}: seen {int(sel.sum())}, G(k) != float32(k / 65535): {apart}"
    yield "3. Mask arithmetic as codes (mismatching texels of 65 536, r1 = r2)"
    for k, case in enumerate(CASES):
        observed_codes = codes(probe[("r1", k)])
        cells = []
        for label, mix in (("plain", mix_plain), ("fma", mix_fma)):
            predicted = model_codes(case, sources, mix)
            values = np.array([table.get(int(c), 0) for c in predicted.tolist()], dtype=np.uint32)
            exact_read = operand(predicted).view(np.uint32)
            plain_read = int((exact_read != probe[("r1", k)].view(np.uint32)).sum())
            cells.append(
                f"{label} codes {int((predicted != observed_codes).sum())}"
                f" values {int((values != probe[('r1', k)].view(np.uint32)).sum())}"
                f" (read as float32(k / 65535): {plain_read})"
            )
        yield f"   User{k} {case.case_id}: " + "; ".join(cells)


def differing(a: F32, b: F32) -> tuple[int, int]:
    """Texels where `a` and `b` differ, and the largest difference in 16-bit codes."""
    where = np.nonzero(a.view(np.uint32) != b.view(np.uint32))[0]
    return where.size, int(np.abs(codes(a)[where] - codes(b)[where]).max(initial=0))


def session_report(store: OracleStore) -> Iterator[str]:
    """Decision 431: the one-session probe of 2026-11-11 against its own captures, and the
    cross-session differences, reported and not compared."""
    sources = snapshot_rasters(SESSION_RECEIPTS)
    earlier = snapshot_rasters()
    session = golden_maps(store, SESSION_NAME)
    read = golden_maps(store, READ_NAME)
    old = golden_maps(store, NAME)
    yield "4. The 16-bit read on this path (snapshot-in-mask-read, every code)"
    k = np.arange(TEXELS, dtype=np.int64)
    for rec in ("r1", "r2"):
        values = read[(rec, 0)]
        g_off = int((values.view(np.uint32) != read_g(k).view(np.uint32)).sum())
        f_off = int((values.view(np.uint32) != operand(k).view(np.uint32)).sum())
        yield (
            f"   {rec}: codes off {int((codes(values) != k).sum())}; "
            f"G(k) = 1 + (F(k) - 1) misses {g_off}; float32(k / 65535) misses {f_off}"
        )
    yield "5. Same session (snapshot-in-mask-session over its own captures, mismatching texels)"
    unstable = sum(int((session[("r1", i)] != session[("r2", i)]).sum()) for i in range(len(CASES)))
    yield f"   texels where r1 and r2 differ: {unstable}"
    for i, case in enumerate(CASES):
        cells = []
        for label, mix in (("plain", mix_plain), ("fma", mix_fma)):
            predicted = read_g(model_codes(case, sources, mix)).view(np.uint32)
            cells.append(f"{label} {int((predicted != session[('r1', i)].view(np.uint32)).sum())}")
        yield f"   User{i} {case.case_id}: " + "; ".join(cells)
    yield "6. Across sessions (reported, not compared)"
    for name in SESSION_RECEIPTS:
        count, largest = differing(sources[name], earlier[name])
        yield f"   {name}: vs the 2026-11-10 capture: {count} texels, largest {largest} codes"
    for i, case in enumerate(CASES):
        count, largest = differing(session[("r1", i)], old[("r1", i)])
        yield f"   User{i} {case.case_id}: vs `{NAME}`: {count} texels, largest {largest} codes"


def main() -> int:
    store = locate()
    if store is None:
        raise SystemExit("no private store on this machine")
    for line in report(store):
        print(line)
    for line in session_report(store):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
