"""The sRGB8 threshold-tie probe under OCIO (decision 406); authored inputs and a count-only
verdict, no fitted transform.

The OCIO RGB32F decode control (`ocio16-bitmap-srgb-basecolor-rgb32f`) decodes three 16-bit codes
(2429, 6548, 14017) to a float32 equal to an sRGB8 threshold t_k (`arith.cpp`
`kSrgb8ThresholdBits`), and the sRGB8 control stores code k - 1 for each, where the native store
(`arith::Srgb8Store`: the number of thresholds at or below v) gives k. "Strict comparison" (the
number of thresholds below v) was fitted on those three points; this probe tests it on every
threshold.

The authored 256 x 256 OpenEXR float bitmap, set to `GenericColorSpace.Raw` (the configuration's
`Raw`, a data space: no OCIO conversion, so the stored value is the bitmap's; a first recording
in the default space read back `sRGB` and decoded the values through the configuration's sRGB
LUT, so that space is not left to the default), holds in column x the threshold t_x (t_0 = 0)
and its neighbours:

- rows 0-127: R = t_x, G = the largest binary16 value below t_x, B = the smallest binary16 value
  above t_x;
- rows 128-255: R = the float32 value below t_x, G = t_x, B = the float32 value above t_x.

The thresholds of codes 1-188 have at most 11 significant bits (exact in binary16), those of codes
189-255 have 12, so the verdict counts them apart: a bitmap kept at binary16 would move only the
latter. The binary16 neighbours are below or above t_x at any precision, and the float32 ones show
the precision Painter keeps. It is projected 1:1 (Nearest, identity UV) on BaseColor sRGB8 of the
256 px plane and exported as PNG 8 bits, passthrough, r1 and r2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.padding_wand import source_table
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, Golden, start
from tools.parity.tier0_semantics.ocio16_bitmap_control import (
    GET_SPACE,
    SET_MODE,
    SET_PROJECTION,
    SET_SPACE,
    UV,
)
from tools.parity.tier0_semantics.request_fixtures import exr_float_rgb

NAME = "ocio-srgb8-threshold-ties"
GOLDEN_ID = f"tier0/api-probes/{NAME}"
INPUT = "srgb8-thresholds"
INPUT_PATH = f"{FIXTURE_DIR}/bitmaps/{INPUT}.exr"
SPACE = "GenericColorSpace.Raw"
SIZE = 256


def thresholds() -> npt.NDArray[np.float32]:
    """t_0 = 0 and the 255 float32 thresholds of the native store, codes 0..255."""
    bits = np.array(source_table("src/evaluator/arith.cpp", "kSrgb8ThresholdBits[255]"), np.uint32)
    return np.concatenate([np.zeros(1, np.float32), bits.view(np.float32)])


def _binary16_around(t: npt.NDArray[np.float32]) -> tuple[Any, Any]:
    """The largest binary16 value below and the smallest above each value, as float32."""
    h = t.astype(np.float16)
    down = np.nextafter(h, np.float16(-1.0)).astype(np.float32)
    up = np.nextafter(h, np.float16(2.0)).astype(np.float32)
    rounded = h.astype(np.float32)
    below = np.where(rounded < t, rounded, down)
    above = np.where(rounded > t, rounded, up)
    return np.maximum(below, np.float32(0.0)), above


def field_values() -> npt.NDArray[np.float32]:
    """(row, column, RGB) float32 values of the authored bitmap, row 0 the top row."""
    t = thresholds()
    half_below, half_above = _binary16_around(t)
    float_below = np.maximum(np.nextafter(t, np.float32(-1.0)), np.float32(0.0))
    float_above = np.nextafter(t, np.float32(2.0))
    top = np.stack([t, half_below, half_above], axis=-1)
    bottom = np.stack([float_below, t, float_above], axis=-1)
    rows = [top] * (SIZE // 2) + [bottom] * (SIZE // 2)
    return np.ascontiguousarray(np.stack(rows), dtype=np.float32)


def field() -> bytes:
    return exr_float_rgb(field_values())


def request() -> dict[str, Any]:
    s = start("plane", resolution=SIZE)
    s.add("substance_painter.textureset.Stack.edit_channel", channel="BaseColor", format="sRGB8")
    resources = s.imports(INPUT)
    node = s.fill(["BaseColor"], position="top", texture_set="uzp_plane")
    s.blend(node, "BaseColor", "Normal", 1.0)
    s.add(SET_MODE, node_step=node, projection_mode="UV")
    s.add(SET_PROJECTION, node_step=node, **UV)
    s.add(ps.SET_SOURCE, node_step=node, channel="BaseColor", resource_step=resources[INPUT])
    s.add(SET_SPACE, node_step=node, channel="BaseColor", color_space=SPACE)
    s.add(GET_SPACE, node_step=node, channel="BaseColor", typed=True)
    s.add(
        EXPORT,
        maps=["documentMap/basecolor:RGB"],
        file_format="png",
        bit_depth=8,
        padding="passthrough",
        dithering=False,
        key_by_step=True,
    )
    golden = Golden(
        NAME,
        "tier0/api-probes/ocio16-input",
        "sRGB8 threshold-tie probe (decision 406): an authored OpenEXR float bitmap whose column "
        "x holds the native store's threshold t_x and its binary16 and float32 neighbours, set to "
        "GenericColorSpace.Raw (a data space: no OCIO conversion), into BaseColor sRGB8 on the "
        "authored 256px full-UV plane. Nearest identity UV, Normal opacity 1. Setup runs once. "
        "Read the typed bitmap space before one PNG 8-bit capture export with no dithering or "
        "padding; Full save/reopen repeats that getter and export without any setter. Records "
        "which code Painter stores for a value on a "
        "threshold; no fit, preset parity or capability promotion.",
        "plane",
        ["plane"],
        s,
        [dict(rr.OCIO_SETTING)],
    )
    hashes = {
        "plane": hashlib.sha256((REPO_ROOT / rr.fixture("plane")[1]).read_bytes()).hexdigest()
    }
    result = rr.request_manifest(golden, hashes, current_envelope())
    result["golden_id"] = GOLDEN_ID
    result["inputs"].append(
        {
            "input_id": INPUT,
            "kind": "image",
            "path": INPUT_PATH,
            "sha256": hashlib.sha256(field()).hexdigest(),
            "provenance": {
                "origin": "uzmigames_authored",
                "licence": "Apache-2.0",
                "note": "Generated by tools/parity/tier0_semantics/srgb8_threshold_ties.py.",
            },
        }
    )
    return result


def request_path(repo_root: Path = REPO_ROOT) -> Path:
    return rr.request_root(repo_root) / "tier0/api-probes" / f"{NAME}.json"


def write_authored() -> None:
    (REPO_ROOT / INPUT_PATH).write_bytes(field())
    request_path().write_text(json.dumps(request(), indent=2) + "\n", encoding="utf-8")


def predictions() -> dict[str, npt.NDArray[np.int64]]:
    """The code of every stored value under each rule: `at_or_above` (the native store: the
    thresholds at or below v) and `strict` (the thresholds below v), (row, column, RGB)."""
    t = thresholds().astype(np.float64)
    values = field_values().astype(np.float64)
    at_or_above = np.searchsorted(t, values, side="right") - 1
    strict = np.maximum(np.searchsorted(t, values, side="left") - 1, 0)
    return {"at_or_above": at_or_above, "strict": strict}


def verdict(codes: npt.NDArray[np.int64]) -> dict[str, Any]:
    """Counts of an exported PNG8 (row, column, RGB) against both rules, split by value kind."""
    t = thresholds()
    values = field_values()
    exact = np.isin(values, t[1:])
    short = np.isin(values, t[1:][t[1:].astype(np.float16).astype(np.float32) == t[1:]])
    kinds = {
        "threshold_binary16": exact & short,
        "threshold_float32": exact & ~short,
        "binary16_below": np.zeros_like(exact),
        "binary16_above": np.zeros_like(exact),
        "float32_below": np.zeros_like(exact),
        "float32_above": np.zeros_like(exact),
    }
    half = SIZE // 2
    kinds["binary16_below"][:half, 1:, 1] = True
    kinds["binary16_above"][:half, 1:, 2] = True
    kinds["float32_below"][half:, 1:, 0] = True
    kinds["float32_above"][half:, 1:, 2] = True
    rules = predictions()
    result: dict[str, Any] = {"shape": list(codes.shape)}
    for rule, predicted in rules.items():
        result[rule] = {
            kind: {
                "samples": int(np.count_nonzero(mask)),
                "misses": int(np.count_nonzero((codes != predicted) & mask)),
            }
            for kind, mask in kinds.items()
        }
        result[rule]["all_misses"] = int(np.count_nonzero(codes != predicted))
    result["distinct_thresholds_hit"] = len(np.unique(values[exact]))
    return result


def analyse(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The verdict of every recording of the admitted golden (counts only, no pixel values)."""
    from tools.parity.fit.decode import decode
    from tools.parity.store.store import load_oracle, locate

    store = locate()
    if store is None:
        raise RuntimeError("no private oracle store on this machine")
    root = manifest_root(current_envelope(repo_root), repo_root)
    manifest_path = root / "tier0/api-probes" / f"{NAME}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report: dict[str, Any] = {"golden_id": GOLDEN_ID, "recordings": {}}
    for ref in manifest["private_records"]:
        if not ref["record_id"].endswith("-basecolor-step" + str(_export_step())):
            continue
        data = load_oracle(store, ref)
        if data is None:
            raise RuntimeError(f"{ref['record_id']} is not in the private store")
        decoded = decode(data)
        if not decoded.integer or decoded.bits != 8:
            raise RuntimeError(f"{ref['record_id']}: not an 8-bit PNG")
        report["recordings"][ref["record_id"]] = verdict(np.asarray(decoded.values)[..., :3])
    return report


def _export_step() -> int:
    steps = request()["instruction_sequence"]["steps"]
    return int(next(s["step"] for s in steps if s["call"] == EXPORT))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier0_semantics.srgb8_threshold_ties"
    )
    parser.add_argument("command", choices=("write", "analyse"))
    args = parser.parse_args(argv)
    if args.command == "write":
        write_authored()
        return 0
    print(json.dumps(analyse(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
