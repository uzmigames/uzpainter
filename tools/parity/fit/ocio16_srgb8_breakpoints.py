"""The sRGB8 code a 16-bit sRGB colour bitmap stores under OCIO with Painter's substance config
(phase3.2_unreal-ue56-packed-preset item 2.5, R-322; decisions 190, 405, 406): counts only.

The admitted control `ocio16-bitmap-srgb-basecolor` projects the authored RGB16 field-a (B holds
every 16-bit code, row 0 the top row: B(x, y) = 256 x + y) 1:1 on BaseColor sRGB8 of the 256 px
plane, one Normal fill at opacity 1, Nearest identity UV. Its r1 PNG 8 B channel gives the stored
code of every 16-bit code. The stored code is a non-decreasing step function of the code, so it is
exactly 255 breakpoints: code c stores k where `bp[k - 1] <= c < bp[k]`.

`verify` checks, without fitting anything else:
- the PNG 8 of every recording of the five-control family that holds a field (field-a r1, r2 and
  their host checks, field-a-brg and field-a-gbr r1 and r2: every channel), through the breakpoints;
- their PNG 16 through the native OCIO table (`encode.cpp` `kOcioSrgbPng16`) of the stored code and
  their OpenEXR 32f through the native sRGB8 operand (`arith.cpp` `kSrgb8DecodeBits`);
- the RGB32F decode control (`-rgb32f`): the native store (`kSrgb8ThresholdBits`, thresholds at or
  below) of its value misses the breakpoints exactly at the decision-406 ties;
- R-322 OCIO (`export-presets-unreal-packed-ocio`): BaseColor (field-a) and Emissive (field-b) of
  every PNG 8, TGA 8 and PNG 16 probe, r1 and r2, on the texels where the Legacy twin equals the
  Legacy rule (the RGB32F Legacy decode control's value through the native store), which is the
  cube's UV coverage.

`table` prints the 255 breakpoints as a C++ initializer (numbers only).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.padding_wand import source_table

CONTROL = "ocio16-bitmap-srgb-basecolor"
PERMUTED = {CONTROL: "rgb", f"{CONTROL}-field-a-brg": "brg", f"{CONTROL}-field-a-gbr": "gbr"}
SIZE = 256

Codes = npt.NDArray[np.int64]


def _grid() -> tuple[Codes, Codes]:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    return x.astype(np.int64), y.astype(np.int64)


def field_a(order: str = "rgb") -> Codes:
    """(row, column, RGB) 16-bit codes of field-a or a cyclic permutation (fixtures.py)."""
    x, y = _grid()
    rgb = (x * 257, y * 257, x * 256 + y)
    return np.stack([rgb["rgb".index(c)] for c in order], -1)


def field_b() -> Codes:
    x, y = _grid()
    return np.stack([y * 257, (255 - x) * 257, 0xFFFF - (y * 256 + x)], -1)


def _records(group: str, name: str) -> list[dict[str, Any]]:
    path = manifest_root(current_envelope()) / group / f"{name}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in manifest["private_records"] if r.get("kind") == "exported_map"]


def _decoded(reference: dict[str, Any]) -> npt.NDArray[Any]:
    from tools.parity.fit.decode import decode
    from tools.parity.store.store import load_oracle, locate

    store = locate()
    if store is None:
        raise RuntimeError("no private oracle store on this machine")
    data = load_oracle(store, reference)
    if data is None:
        raise RuntimeError(f"{reference['record_id']} is not in the private store")
    return np.asarray(decode(data).values)[..., :3]


def _step(record_id: str) -> int:
    return int(record_id.rsplit("-step", 1)[1])


def _export_steps(records: list[dict[str, Any]]) -> list[int]:
    return sorted({_step(r["record_id"]) for r in records if "-step" in r["record_id"]})


def breakpoints() -> Codes:
    """The first 16-bit code storing each sRGB8 code 1..255, from field-a r1's PNG 8 B channel."""
    records = _records("tier0/api-probes", CONTROL)
    png8 = _export_steps(records)[0]
    [ref] = [r for r in records if r["record_id"] == f"r1-uzp_plane-basecolor-step{png8}"]
    stored = np.zeros(65536, np.int64)
    stored[field_a()[..., 2].ravel()] = _decoded(ref)[..., 2].ravel()
    if np.any(np.diff(stored) < 0) or np.any(np.diff(stored) > 1) or stored[0] or stored[-1] != 255:
        raise RuntimeError("the stored code is not a complete non-decreasing step function")
    return np.searchsorted(stored, np.arange(1, 256), side="left").astype(np.int64)


def stored_code(bp: Codes, codes: Codes) -> Codes:
    return np.searchsorted(bp, codes, side="right").astype(np.int64)


def _native(name: str, file: str, dtype: Any) -> npt.NDArray[Any]:
    return np.array(source_table(file, name), dtype)


def verify() -> dict[str, Any]:
    bp = breakpoints()
    png16 = _native("kOcioSrgbPng16[256]", "src/export/encode.cpp", np.int64)
    arith = "src/evaluator/arith.cpp"
    operand = _native("kSrgb8DecodeBits[256]", arith, np.uint32).view(np.float32)
    thresholds = np.concatenate(
        [[0.0], _native("kSrgb8ThresholdBits[255]", arith, np.uint32).view(np.float32)]
    ).astype(np.float64)
    report: dict[str, Any] = {"controls": {}, "rgb32f": {}, "r322": {}}
    for name, order in PERMUTED.items():
        records = _records("tier0/api-probes", name)
        p8, p16, exr = _export_steps(records)
        code = stored_code(bp, field_a(order))
        expected = {p8: code, p16: png16[code], exr: operand[code].astype(np.float64)}
        for ref in records:
            observed = _decoded(ref)
            if expected[_step(ref["record_id"])].dtype == np.float64:
                observed = observed.astype(np.float32).astype(np.float64)
            misses = np.count_nonzero(observed != expected[_step(ref["record_id"])])
            report["controls"][f"{name}/{ref['record_id']}"] = int(misses)

    def decode_table(name: str) -> npt.NDArray[np.float64]:
        [ref, *_] = sorted(_records("tier0/api-probes", name), key=lambda r: r["record_id"])
        table = np.zeros(65536, np.float64)
        table[field_a()[..., 2].ravel()] = _decoded(ref)[..., 2].astype(np.float32).ravel()
        return table

    ocio = decode_table(f"{CONTROL}-rgb32f")
    native = np.searchsorted(thresholds, ocio, side="right") - 1
    stored = stored_code(bp, np.arange(65536))
    ties = np.nonzero(native != stored)[0]
    report["rgb32f"] = {
        "native_store_misses": int(ties.size),
        "misses_on_an_exact_threshold": int(np.count_nonzero(np.isin(ocio[ties], thresholds))),
    }

    legacy = decode_table(f"{CONTROL}-rgb32f-legacy")
    r322 = "tier0/semantics"
    legacy_records = _records(r322, "export-presets-unreal-packed-legacy")
    ocio_records = _records(r322, "export-presets-unreal-packed-ocio")
    for map_name, field in (("basecolor", field_a()), ("emissive", field_b())):
        legacy_code = np.searchsorted(thresholds, legacy[field], side="right") - 1
        [cover_ref] = [
            r
            for r in legacy_records
            if r["record_id"].startswith("r1-probe-s52-") and f"_{map_name}" in r["record_id"]
        ]
        covered = np.all(_decoded(cover_ref) == legacy_code, -1)
        code = stored_code(bp, field)
        report["r322"][f"{map_name}/covered_texels"] = int(covered.sum())
        for ref in ocio_records:
            if f"_{map_name}" not in ref["record_id"]:
                continue
            observed = _decoded(ref)
            prediction = code if int(observed.max()) <= 255 else png16[code]
            misses = np.count_nonzero(~np.all(observed == prediction, -1) & covered)
            report["r322"][f"{map_name}/{ref['record_id']}"] = int(misses)
    return report


def table() -> str:
    values = ", ".join(str(int(b)) for b in breakpoints())
    return "constexpr uint16_t kOcioSrgb16Breakpoints[255] = {" + values + "};"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.fit.ocio16_srgb8_breakpoints")
    parser.add_argument("command", choices=("verify", "table"))
    args = parser.parse_args(argv)
    if args.command == "table":
        print(table())
        return 0
    print(json.dumps(verify(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
