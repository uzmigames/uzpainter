"""The published fit of phase1.9_compositor-quantisation-profile and
phase1.10_compositor-float32-residual: `parity/semantics/quantisation-profile.json`.

The Tier 0 quantisation experiment (`tier0/semantics/quantisation-thirds`: three uniform fills at
opacity 1/3 on one channel per ChannelFormat member, four colour triplets) and the one-layer
partial-coverage stack of `tier0/semantics/blend-inputs` (s2: fields A at opacity 0.5 over the
base) evaluated by the CPU store under each registered profile (`src/evaluator/profile.h`),
against both recordings, as |delta| statistics in export units only (CONTRACT §6.4; nothing
recorded is published). Run on the owner's machine:

    python tests/evaluator/quantisation_fits.py <uzp-evaluator-tests.exe> <work-dir>

writes the file; `test_compositor_quantisation_profile.py::test_published_fit_reproduces`
re-derives it and requires the published file to match.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

if __name__ == "__main__":
    # Run as a script: the repository root is the import root, and its `tests` folder is the
    # `tests` package even when another distribution installs one.
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root))
    _tests = types.ModuleType("tests")
    _tests.__path__ = [str(_root / "tests")]
    sys.modules["tests"] = _tests

from tests.evaluator.sources_fits import channel_formats, export16, pooled, srgb8_decode
from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    REPO_ROOT,
    evaluate,
    raster,
    spec_from_manifest,
)
from tools.parity.fit.common import Context, document, entry, parameter, residual, source
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

SEMANTICS = REPO_ROOT / "parity" / "semantics"
FILE = "quantisation-profile.json"
THIRDS = "quantisation-thirds"
INPUTS = "blend-inputs"
SETS = ("s0", "s1", "s2", "s3")
PROFILE_ISOLATED = "painter-12.1-isolated-linear"
PROFILE_HALF_ALPHA = "painter-12.1-isolated-half-alpha"
PROFILE_LAYERQ = "painter-12.1-layerq-linear"
# Painter's API names the L32F channel of the experiment `Scattering`; the document model's
# channel type is its alias SubsurfaceRadiusScale (assets/templates/channel-defaults.json).
CHANNEL_ALIASES = {"Scattering": "SubsurfaceRadiusScale"}

W3C = source("S-W3C-BLEND", "§5.1 simple alpha compositing (source-over), §6 group isolation")
SRGB = source("S-SRGB", "IEC 61966-2-1:1999 §5.2-5.3 (transfer functions)")
D3D = source("X-D3D12", "Data conversion rules: FLOAT to UNORM, FLOAT to SRGB, FLOAT to FLOAT16")
D3D_HALF = source(
    "X-D3D12",
    "Data conversion rules: FLOAT32 to FLOAT16 (round to nearest even), then FLOAT to UNORM",
)
PYDOC = source(
    "A-PYDOC", "layerstack: Node.set_opacity, BlendingMode.Normal; textureset: ChannelFormat"
)


def aliased(spec: dict[str, Any]) -> dict[str, Any]:
    """`spec` with Painter's channel names replaced by the document model's channel types."""

    def rename(name: str) -> str:
        return CHANNEL_ALIASES.get(name, name)

    def layers(items: list[dict[str, Any]]) -> None:
        for layer in items:
            for key in ("blending", "sources"):
                if key in layer:
                    layer[key] = {rename(k): v for k, v in layer[key].items()}
            if "active_channels" in layer:
                layer["active_channels"] = [rename(c) for c in layer["active_channels"]]
            layers(layer.get("children", []))

    for channel in spec["channels"]:
        channel["type"] = rename(channel["type"])
    spec["outputs"] = [rename(o) for o in spec["outputs"]]
    layers(spec["layers"])
    return spec


def exported(result: dict[str, Any], channel: str, fmt: str, decode: np.ndarray) -> np.ndarray:
    """The evaluator's channel as Painter exports it: 16-bit PNG codes, or the OpenEXR floats."""
    ours = raster(result, CHANNEL_ALIASES.get(channel, channel))
    return ours if fmt.endswith("F") else export16(ours, fmt, decode)


def unit(fmt: str) -> str:
    return "float32 value" if fmt.endswith("F") else "16-bit code value"


class Runs:
    """Evaluations of the experiment's texture sets under one profile (CPU store), cached."""

    def __init__(self, exe: Path, work: Path) -> None:
        self.exe = exe
        self.work = work
        self.ctx = Context(locate(), REPO_ROOT)
        self._results: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def result(
        self, stem: str, texture_set: str, profile: str, backend: str = "cpu"
    ) -> dict[str, Any]:
        key = (stem, texture_set, profile, backend)
        if key not in self._results:
            manifest = load_json(MANIFESTS / "semantics" / f"{stem}.json")
            channels = list(channel_formats(manifest))
            workdir = self.work / stem / texture_set / profile
            spec = aliased(spec_from_manifest(manifest, texture_set, workdir, channels))
            spec["evaluator_profile"] = profile
            self._results[key] = evaluate(self.exe, spec, workdir, backend)
        return self._results[key]

    def recorded(self, stem: str, recording: str, map_name: str) -> np.ndarray:
        values: np.ndarray = self.ctx.golden(f"semantics/{stem}").map(recording, map_name).values
        return values


def residuals(runs: Runs, decode: np.ndarray, profile: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    thirds = channel_formats(load_json(MANIFESTS / "semantics" / f"{THIRDS}.json"))
    for channel, fmt in thirds.items():
        for recording in ("r1", "r2"):
            pairs = []
            for texture_set in SETS:
                ours = exported(runs.result(THIRDS, texture_set, profile), channel, fmt, decode)
                theirs = runs.recorded(THIRDS, recording, f"{texture_set}/{channel.lower()}")
                pairs.append((ours, theirs.reshape(ours.shape).astype(ours.dtype)))
            out.append(
                residual(
                    f"tier0/semantics/{THIRDS}",
                    f"s0-s3/{channel.lower()}",
                    recording,
                    unit(fmt),
                    pooled(pairs),
                )
            )
    inputs = channel_formats(load_json(MANIFESTS / "semantics" / f"{INPUTS}.json"))
    for channel, fmt in inputs.items():
        ours = exported(runs.result(INPUTS, "s2", profile), channel, fmt, decode)
        for recording in ("r1", "r2"):
            theirs = runs.recorded(INPUTS, recording, f"s2/{channel.lower()}")
            out.append(
                residual(
                    f"tier0/semantics/{INPUTS}",
                    f"s2/{channel.lower()}",
                    recording,
                    unit(fmt),
                    pooled([(ours, theirs.reshape(ours.shape).astype(ours.dtype))]),
                )
            )
    return out


ISOLATED_FORMULA = (
    "Root stack isolated (a group without its own blend): the root layers composite bottom-up "
    "from a transparent start, straight colour C and coverage a, with the fitted kernels of "
    "blend-modes.json and W3C Compositing §5.1 (a transparent backdrop passes the source "
    "through, a partly covered one uses the general source-over formula in float32 with a "
    "correctly rounded reciprocal); after every layer C and a are stored in the channel format "
    "(UNORM n bits: truncate to n + 4 fractional bits, nearest, ties down; sRGB8: the recording "
    "GPU's float-to-sRGB8 conversion, blending on its linear decode; 16-bit float toward zero; "
    "32-bit float as it is). At read-out the result is composited over the channel base once, "
    "v = base + (C - base) * a in float32 (one subtraction, one multiplication, one addition), "
    "and stored with the same write rule; an empty stack is the base. A grey channel takes the "
    "mean of the colour's three components. With a = 1 this is the 1 + (v - 1) read-out of "
    "blend-modes.json; with a < 1 the stored coverage below 1/2 (32767/65535 on 16 bits) sends "
    "every exact tie of a 0.5-opacity layer over the base up, as Painter does."
)
HALF_ALPHA_FORMULA = (
    "The isolated root of painter-12.1-isolated-linear (entry quantisation-isolated-root) with two "
    "write rules changed: the coverage plane of an sRGB8 intermediate is written as the 8-bit "
    "UNORM code of its binary16 value (round to nearest even), WriteUnorm(binary16(a), 8), and a "
    "uniform colour on a 32-bit float channel is the float32 of the value (the earlier profiles "
    "read it back as 1 + (v - 1) over the white base)."
)
LAYERQ_FORMULA = (
    "Root layers blended onto an accumulator that starts at the channel base, "
    "v = acc (1 - alpha) + r alpha in float32, stored in the channel format after every layer "
    "with the same write rules; 32-bit float channels re-composited over the base once at "
    "read-out (1 + (v - 1)). The provisional profile of evaluator-profile.json."
)
HALF_ALPHA_NOTES = (
    "Selected: profile painter-12.1-isolated-half-alpha (src/evaluator/profile.h, decision 044), "
    "stamped into new projects; painter-12.1-isolated-linear and painter-12.1-layerq-linear stay "
    "registered for projects stamped with them. The binary16 coverage rule is measured on "
    "group-masks s2-s3 (masks-levels.json): a group coverage half-way between two 8-bit codes "
    "is stored up or down as its binary16 value lies, and only that rule makes their sRGB8 maps "
    "exact. The partial coverages of this experiment (1/3, 5/9, 19/27, 1/2) store the same codes "
    "under both rules, so every UNORM, sRGB8 and 16-bit float map here is exact against r1 as "
    "before. The plain 32-bit float operand is measured on group-masks row 0 and makes one more "
    "value of this experiment exact (s0 RGB32F G). The 32-bit float maps are still not exact: 3 "
    "of the 12 RGB32F values and 2 of the 4 L32F values lie 2^-25 or 2^-24 from r1; the float32 "
    "operation order of Painter's source-over onto a partly covered backdrop is not identified "
    "(parity/reports/phase1/compositor-float32-residual.md; a divergence, never counted as a "
    "pass, decision 032). r2 is covered by EXC-001 and EXC-002 as for the earlier profile."
)
ISOLATED_NOTES = (
    "Superseded by painter-12.1-isolated-half-alpha (entry quantisation-isolated-half-alpha); "
    "still registered and evaluated as it was. Against "
    "the same-session recording r1 the isolated model reproduces every UNORM, sRGB8 and 16-bit "
    "float map of the experiment and every map of the blend-inputs s2 stack exactly (sRGB8 "
    "blended on linear values). The 32-bit float maps of the experiment are not exact: 4 of the "
    "12 RGB32F values and 2 of the 4 L32F values lie 2^-25 or 2^-24 from r1 (the float32 "
    "operation order of Painter's source-over is not identified; r1 and r2 themselves differ "
    "on 9 of these 16 values). The after-reopen "
    "recording r2 differs from r1 itself on 16 of the experiment's 36 maps and on the sRGB8 and "
    "RGB8 maps of blend-inputs s2 (parity/reports/phase0/tier0-stability.md): both goldens are "
    "unstable, so under decision 032 r1 is their exact target and the register entries EXC-001 "
    "and EXC-002 (parity/exceptions.json) bound their r2 comparisons by the r2 residuals below; "
    "the 32-bit float residual against r1 stays a divergence "
    "(phase1.10_compositor-float32-residual). Run: "
    "parity/reports/phase1/compositor-quantisation-profile.md."
)
LAYERQ_NOTES = (
    "Superseded: per-layer quantisation over the base leaves ties of a 0.5-opacity layer over the "
    "base going down (Painter: up) and does not reproduce the 8-bit and 16-bit codes of the "
    "three 1/3 fills on either recording."
)


def build(exe: Path, work: Path) -> dict[str, Any]:
    runs = Runs(exe, work)
    decode = srgb8_decode(exe, work)
    params = [
        parameter("opacity", float(np.float32(1 / 3)), "authored"),
        parameter("opacity_blend_inputs_s2", 0.5, "authored"),
    ]
    entries = [
        entry(
            "quantisation-isolated-half-alpha",
            "Evaluator profile painter-12.1-isolated-half-alpha: the isolated root with the sRGB8 "
            "coverage written through binary16 and plain 32-bit float uniform colours",
            HALF_ALPHA_FORMULA,
            [W3C, SRGB, D3D, D3D_HALF, PYDOC],
            [*params, parameter("evaluator_profile", PROFILE_HALF_ALPHA, "fitted")],
            residuals(runs, decode, PROFILE_HALF_ALPHA),
            HALF_ALPHA_NOTES,
        ),
        entry(
            "quantisation-isolated-root",
            "Evaluator profile painter-12.1-isolated-linear: isolated root stack, per-layer "
            "storage in the channel format, one composite over the base at read-out, sRGB8 on "
            "linear values",
            ISOLATED_FORMULA,
            [W3C, SRGB, D3D, PYDOC],
            [*params, parameter("evaluator_profile", PROFILE_ISOLATED, "fitted")],
            residuals(runs, decode, PROFILE_ISOLATED),
            ISOLATED_NOTES,
        ),
        entry(
            "quantisation-over-base",
            "Evaluator profile painter-12.1-layerq-linear (provisional, superseded): per-layer "
            "quantisation over the base",
            LAYERQ_FORMULA,
            [W3C, SRGB, D3D, PYDOC],
            [*params, parameter("evaluator_profile", PROFILE_LAYERQ, "fitted")],
            residuals(runs, decode, PROFILE_LAYERQ),
            LAYERQ_NOTES,
        ),
    ]
    return document(
        "quantisation-profile",
        "Quantisation profile of the evaluator (04 section 4, task "
        "phase1.9_compositor-quantisation-profile): the registered profiles evaluated on the "
        "Tier 0 quantisation experiment and on the one-layer partial-coverage stack of "
        "blend-inputs. Residuals are |delta| in export units (16-bit PNG codes, OpenEXR float32 "
        "values) pooled over the texture sets, against both recordings (r1 same session, r2 "
        "after save and reopen).",
        [f"tier0/semantics/{THIRDS}", f"tier0/semantics/{INPUTS}"],
        entries,
    )


def serialise(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python tests/evaluator/quantisation_fits.py <uzp-evaluator-tests.exe> "
            "<work-dir>"
        )
        return 2
    doc = build(Path(argv[0]), Path(argv[1]))
    (SEMANTICS / FILE).write_text(serialise(doc), encoding="utf-8", newline="\n")
    print(f"wrote parity/semantics/{FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
