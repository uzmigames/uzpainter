"""Diagnostic fits over the private material channel survey (`phase3.3_procedural-families` 2.16).

Reads the newest survey of `python -m tools.parity.recorder.material_channel_survey` (one Painter
instance per material: the default material fill's channel exports and the paired split User0
L32F / User1 RGB32F views of every output) and prints, per material and active channel, how many
texels or components each candidate composition misses. Only counts are printed; no Painter value
is published.

    python -m tools.parity.fit.material_channel_survey [--survey <private directory>]

Candidates (x is the L32F view, (r, g, b) the RGB32F view of the output `output_mapping` gives the
channel; tz16 is binary16 rounding toward zero):

- Height (L16F, LinearDodge): tz16(float32(2 x - 1)), decision 416's rule;
- BaseColor (sRGB8): the stored code round(255 v) of each view component, with no transfer; the
  export must then be one strictly increasing value per code;
- BaseMetalness and SpecularRoughness (L8): ((x16 >> 4) 255 + 2047) >> 12 of the 16-bit code
  x16 = 65535 x, against round(255 x); the export is float32(code / 255);
- Normal (RGB16F, NormalMapDetail over the empty stack): (tz16(r), tz16(1 - g), tz16(b)).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.fit.decode import decode_exr
from tools.parity.fit.material_channels import binary16_toward_zero
from tools.parity.recorder.output import work_root

F64 = npt.NDArray[np.float64]


def latest() -> Path:
    found = sorted(p for p in (work_root() / "material-channel-survey").glob("*") if p.is_dir())
    if not found:
        raise FileNotFoundError("no material channel survey under the private work root")
    return found[-1]


def load(directory: Path, name: str) -> F64:
    values = decode_exr((directory / f"{name}.exr").read_bytes()).values
    return np.asarray(values, dtype=np.float64)


def tz(values: Any) -> F64:
    return np.asarray(binary16_toward_zero(np.asarray(values, np.float32)), np.float64)


def unorm8_of_16(x: F64) -> npt.NDArray[np.int64]:
    """The L8 store candidate: the 16-bit code truncated to 12 bits, then to 8 bits."""
    codes = np.round(x * 65535).astype(np.int64)
    return np.asarray(((codes >> 4) * 255 + 2047) >> 12, np.int64)


def channel_report(channel: str, x: F64, rgb: F64, exported: F64) -> Iterator[str]:
    if channel == "Height":
        predicted = tz(np.float32(2) * x.astype(np.float32) - np.float32(1))
        yield f"tz16(2x - 1) misses {np.count_nonzero(predicted != exported)} of {x.size}"
    elif channel == "BaseColor":
        codes = np.floor(rgb * 255 + 0.5).astype(np.int64).ravel()
        values = exported.ravel()
        pairs = np.unique(np.stack([codes, values], axis=1), axis=0)
        function = np.unique(pairs[:, 0]).size == pairs.shape[0]
        increasing = bool(np.all(np.diff(pairs[:, 1]) > 0))
        yield (
            f"round(255 v) codes {np.unique(codes).size}: one export per code {function}, "
            f"strictly increasing {increasing} ({codes.size} components)"
        )
    elif channel in ("BaseMetalness", "SpecularRoughness"):
        stored = np.round(exported * 255)
        division = np.array_equal(exported.astype(np.float32), (stored / 255).astype(np.float32))
        candidate = np.count_nonzero(unorm8_of_16(x) != stored)
        nearest = np.count_nonzero(np.floor(x * 255 + 0.5) != stored)
        sixteen = np.allclose(x * 65535, np.round(x * 65535), atol=1e-3)
        yield (
            f"16-bit view {sixteen}, export code/255 {division}; 12-bit rule misses {candidate}, "
            f"round(255 x) misses {nearest} of {x.size}"
        )
    elif channel == "Normal":
        f32 = rgb.astype(np.float32)
        predicted = np.stack(
            [tz(f32[..., 0]), tz(np.float32(1) - f32[..., 1]), tz(f32[..., 2])], -1
        )
        misses = [int(np.count_nonzero(predicted[..., k] != exported[..., k])) for k in range(3)]
        yield f"(tz16 r, tz16(1 - g), tz16 b) misses {misses} of {x.size} per component"
    else:
        yield "no candidate"


def report(directory: Path) -> Iterator[str]:
    survey = json.loads((directory / "survey.json").read_text(encoding="utf-8"))
    yield f"survey {directory.name}, Painter {survey['painter_build']}"
    for family in ("felt", "leather-grain"):
        exports = survey[family]["exports"]
        material = exports["material"]
        outputs = exports["split"]["outputs"]
        colours = survey[family]["colour"]["material"]["colours"]
        split = survey[family]["colour"]["split"]["colours"]
        for name in sorted(colours):
            yield (
                f"{family} {name}: material {colours[name]['class']} {colours[name]['color_space']}"
                f", split {split[name]['color_space']}, value equal "
                f"{colours[name]['value'] == split[name]['value']}"
            )
        for channel in material["active_channels"]:
            index = outputs.index(material["output_mapping"][channel])
            x = load(directory, f"{family}-split{index}-User0")[..., 0]
            rgb = load(directory, f"{family}-split{index}-User1")
            exported = load(directory, f"{family}-material-{channel}")
            if exported.ndim == 3 and exported.shape[-1] == 1:
                exported = exported[..., 0]
            for line in channel_report(channel, x, rgb, exported):
                yield f"{family} {channel} ({material['export']['formats'][channel]}): {line}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.fit.material_channel_survey")
    parser.add_argument("--survey", type=Path, help="private survey directory (default: newest)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    for line in report(args.survey or latest()):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
