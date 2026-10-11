"""Tests of phase1.11_compositor-mask-effects (P1-COMPOSITOR, `docs/architecture/04-layer-stack-and-
compositing.md` §1, §2 steps 2, 4, 5; `src/evaluator/`, `parity/semantics/masks-levels.json`).

The native cases run `uzp-evaluator-tests.exe` (`tests/evaluator/evaluator_test.cpp`): `masks` on
the CPU anywhere; `masks-gpu-vs-cpu` and `pow-hardware` need the DX12 adapter and skip under
`UZP_NO_GPU=1` (hosted CI, decision 028). The Tier 0 comparisons read the private oracle store
through `tools.parity` and skip, saying so, on a machine without it; the local run on the owner's
machine (`parity/reports/phase1/compositor-mask-effects.md`) is their evidence. Goldens classified
are those of the current oracle envelope (decision 037, `tools/parity/envelope/`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator.masks_fits import (
    ENVELOPE,
    PUBLISHED,
    build_document,
    envelope_golden,
    envelope_manifest,
    serialise,
    spec_from_steps,
)
from tests.evaluator.test_compositor_sources_projection import export16
from tests.evaluator.test_compositor_tile_dag import (
    backends,
    evaluate,
    needs_store,
    raster,
    run_case,
)
from tools.parity.fit.common import publishable_problems
from tools.parity.fit.oracle import Golden
from tools.parity.schemas import load_json

# ── Native cases ─────────────────────────────────────────────────────────────


def test_masks_and_effects_on_the_cpu(evaluator_tests: Path) -> None:
    """2.1-2.5, 3.6 (unit half): mask stacks, the effect mix, levels, subtraction in masks, the
    16-bit mask precision, disabled masks, geometry masks, group masks, the Height override, the
    base under complementary masks, explicit failures, and the cache shape (an upstream change
    invalidates exactly its dependants)."""
    passed, _ = run_case(evaluator_tests, "masks")
    assert {
        "a mask is its background without effects (White 1, Black 0); a disabled mask counts as 1",
        "a mask fill effect blends with the effect mix a + (r - a) alpha and is stored at 16 bits",
        "subtraction in a mask goes through the Subtract kernel, clamped to [0, 1]",
        "a mask levels effect remaps the mask (clamped, gamma through the hardware pow)",
        "a mask is stored at 16 bits on an 8-bit channel",
        "content effects run in list order: fill then levels differs from levels then fill",
        "a levels effect touches only its affected channel",
        "an invisible effect is skipped",
        "a Mesh geometry mask multiplies the mask (inclusion and exclusion lists)",
        "a UVTile geometry mask fails with unsupported_node",
        "a group mask scales the group composite",
        "a group's Height entry is its effective Height blend; a child keeps its own",
        "two fills under complementary masks leave exactly the template base uncovered "
        "(no default bleed)",
        "filter, generator and anchor effects fail with unsupported_node",
        "a PassThrough group with a mask raster evaluates",
    } <= passed


def test_effect_chains_invalidate_only_their_dependants(evaluator_tests: Path) -> None:
    """Design note of the planning review: the DAG's shape is settled by an upstream-change
    invalidation test before mask effects depend on it. A layer's content chain and mask chain are
    graph nodes keyed by chained hashes: changing one mask effect (the upstream node another
    node's output depends on, as an anchor's would be) re-evaluates that mask from the change up
    and the prefixes above the layer, and serves the content chain, the mask below the change and
    the prefixes below from the cache; the result equals a fresh evaluation."""
    passed, _ = run_case(evaluator_tests, "masks")
    assert {
        "an upstream mask-effect change re-evaluates the mask from the change up and the prefixes "
        "above, serving the content chain, the lower mask effects and the prefixes below",
        "an upstream content-effect change re-evaluates the content from the change up, serving "
        "the mask and the lower content effects",
        "the masks of one layer are shared by its channels",
        "every partially re-evaluated result equals a fresh evaluation bit for bit",
    } <= passed


def test_masks_and_effects_gpu_equal_cpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.1-2.3: random stacks with masks, mask and content effects and levels (gamma through the
    hardware pow) on every channel format: the GPU kernels equal the CPU reference bit for bit."""
    passed, _ = run_case(evaluator_tests, "masks-gpu-vs-cpu", str(tmp_path), needs_gpu=True)
    assert any(p.startswith("every masked stack evaluates to the same bytes") for p in passed)


def test_pow_tables_equal_the_recording_gpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.2: the log2 and exp2 tables of `hwmath.h` are the recording GPU's: every entry of the four
    tables, and log2, exp2 and pow on edge values and hashed inputs over every exponent."""
    passed, output = run_case(evaluator_tests, "pow-hardware", str(tmp_path), needs_gpu=True)
    if "RTX 4090" not in output:
        pytest.skip("the log2/exp2 tables were measured on the recording GPU (RTX 4090)")
    assert {
        "the embedded lg2-hi table equals the GPU on every entry of its domain (8388608)",
        "the embedded lg2-lo table equals the GPU on every entry of its domain (8388608)",
        "the embedded ex2-pos table equals the GPU on every entry of its domain (8388608)",
        "the embedded ex2-neg table equals the GPU on every entry of its domain (8388608)",
    } <= passed
    assert any(p.startswith("hw::Log2, hw::Exp2 and hw::Pow equal the GPU") for p in passed)


# ── Tier 0 goldens (owner's machine: private store, decision 028) ────────────


def channel_formats(document: dict[str, Any]) -> dict[str, str]:
    return {
        s["args"]["channel"]: s["args"]["format"]
        for s in document["instruction_sequence"]["steps"]
        if s["call"].endswith("Stack.add_channel")
    }


def compare_channel(
    result: dict[str, Any],
    channel: str,
    fmt: str,
    decode: np.ndarray,
    golden: Golden,
    map_name: str,
    recordings: tuple[str, ...] = ("r1", "r2"),
) -> dict[str, int]:
    """Value for value against the recordings; returns the differing values per recording."""
    ours = raster(result, channel)
    differing: dict[str, int] = {}
    for recording in recordings:
        theirs = golden.map(recording, map_name).values
        if fmt.endswith("F"):
            expected = ours.reshape(theirs.shape)
            equal = (expected == theirs) | (np.isnan(expected) & np.isnan(theirs))
        else:
            expected = export16(ours, fmt, decode).reshape(theirs.shape)
            equal = expected == theirs.astype(np.int64)
        differing[recording] = int(np.count_nonzero(~equal))
    return differing


@pytest.fixture(scope="module")
def srgb8_decode(evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> np.ndarray:
    """The sRGB8 operand of every code (float32 values), from the `tables` case."""
    work = tmp_path_factory.mktemp("tables")
    run_case(evaluator_tests, "tables", str(work))
    document = json.loads((work / "tables.json").read_text(encoding="utf-8"))
    bits = np.asarray(document["srgb8_decode_bits"], np.uint32)
    return bits.view(np.float32).astype(np.float64)


def assert_golden(
    evaluator_tests: Path,
    tmp_path: Path,
    srgb8_decode: np.ndarray,
    stem: str,
    texture_set: str,
    backend: str,
    channels: list[str] | None = None,
) -> None:
    needs_store()
    golden = envelope_golden(f"semantics/{stem}")
    document = envelope_manifest(f"semantics/{stem}")
    formats = channel_formats(document)
    selected = channels if channels is not None else sorted(formats)
    spec = spec_from_steps(document, texture_set, tmp_path, selected)
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    failures = []
    for channel in selected:
        map_name = f"{texture_set}/{channel.lower()}"
        differing = compare_channel(
            result, channel, formats[channel], srgb8_decode, golden, map_name
        )
        if any(differing.values()):
            failures.append(f"{map_name} ({formats[channel]}): {differing}")
    assert not failures, failures


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_mask_precision_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.1, 3.5: `mask-precision` (a black fill over a white one, masked by the bitmap holding
    every 16-bit code: White and Black backgrounds, the mask effect at opacity 0.5, a second
    Multiply mask effect) on RGB16, L16, RGB32F, sRGB8 and L8: the mask is stored at 16 bits on
    every channel format and its effects blend with the effect mix."""
    assert_golden(evaluator_tests, tmp_path, srgb8_decode, "mask-precision", texture_set, backend)


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s2", "s3"])
def test_group_masks_equal_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.4: `group-masks` with masks: a mask (grey A) on the group in its default mode (s2) and in
    `Normal` (s3), and a mask (grey B, a ramp along y) on its Multiply child, on RGB16, sRGB8 and
    RGB32F, equal both recordings under the current profile: where the child's mask is 0 the
    uniform fill's plain float32 operand enters the result directly, the sRGB8 coverage goes
    through binary16, and where the child's mask lies strictly between 0 and 1 the uniform fill
    above it composites over the partly covered backdrop with the coverage weights
    (phase1.10_compositor-float32-residual)."""
    assert_golden(evaluator_tests, tmp_path, srgb8_decode, "group-masks", texture_set, backend)


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_group_coverage_order_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """phase1.10 3.1: `group-coverage-order` (an isolated group over an opaque black root: a fill
    under a row-ramp mask, a fill of fields A above it, Normal at 0.5, Screen at 0.5, Normal at
    0.3) on RGB32F, L32F, RGB16, sRGB8, RGB8 and L8 equals both recordings: the coverage-weighted
    source-over, also over the zero-coverage row, the copied first layer, the plain 8-bit coverage
    ties of RGB8 and L8 and the sRGB8 coverage through binary16 from 1/2 up."""
    assert_golden(
        evaluator_tests, tmp_path, srgb8_decode, "group-coverage-order", texture_set, backend
    )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_levels_clamp_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.2: `levels-clamp` (input 0.25-0.75 without and with clamp; output -0.5..1.5 then input
    -0.25..1.25 with gamma 0.5, without and with clamp) on RGB32F, RGB16F, RGB16 and L16F: clamp
    limits the normalised input to [0, 1], the output range is not clamped, gamma goes through the
    recording GPU's pow."""
    assert_golden(evaluator_tests, tmp_path, srgb8_decode, "levels-clamp", texture_set, backend)


@pytest.mark.parametrize("backend", backends())
def test_content_effect_levels_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, backend: str
) -> None:
    """3.3: `effect-order` s6 (levels alone, input 0.1-0.8, gamma 1.6, output 0.05-0.95, one
    effect per channel) on RGB16 and sRGB8. The other orders contain the starter-asset Blur
    filter, a release gap until P3-PROC; the order of fill and levels effects is the list order
    (unit case `masks`)."""
    assert_golden(evaluator_tests, tmp_path, srgb8_decode, "effect-order", "s6", backend)


def test_mask_stack_probe_is_reported_not_compared(evaluator_tests: Path, tmp_path: Path) -> None:
    """3.1: the `api-probes/mask-stack` probe converts and evaluates (a 0.9 fill under a Black mask
    holding a UV-projected 8-bit bitmap fill effect in Screen at 0.75 below a clamped levels effect
    with gamma 1.2). It is an API probe, not a compositing golden: its masked half exports above
    both the fill colour and the base, and its values lie off the sRGB8 export lattice of every
    semantics golden, so the project's BaseColor colour path differs from the evaluator's linear
    colour (a sources question, not a mask one). Its residual is published (`masks-levels.json`,
    entry `mask-stack-probe`) and not asserted; the mask semantics are settled by
    `mask-precision`, `group-masks` and `levels-clamp`."""
    needs_store()
    document = envelope_manifest("api-probes/mask-stack")
    spec = spec_from_steps(document, "uzp_plane", tmp_path, ["BaseColor"])
    (layer,) = spec["layers"]
    assert [e["kind"] for e in layer["mask"]["effects"]] == ["levels", "fill"]
    assert layer["mask"]["effects"][1]["mode"] == "Screen"
    result = evaluate(evaluator_tests, spec, tmp_path, "cpu")
    assert raster(result, "BaseColor").shape == (256, 256, 3)


# ── Published fit ────────────────────────────────────────────────────────────


def test_fit_is_published_and_valid() -> None:
    """2.6: `parity/semantics/masks-levels.json` is publishable (sources, formulas, residuals;
    no recorded values)."""
    document = load_json(PUBLISHED)
    assert document["schema"] == "uzpainter/parity/semantics/1"
    assert not publishable_problems(document)
    assert document["painter_build_id"] == ENVELOPE["painter_build"]
    ids = {entry["entry_id"] for entry in document["entries"]}
    assert {
        "mask-stack-effect-mix",
        "mask-precision",
        "levels",
        "levels-clamp",
        "content-effect-order",
        "group-masks",
        "group-coverage-order",
        "mask-stack-probe",
        "geometry-mask-mesh",
    } <= ids


def test_published_fit_reproduces(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.6: re-deriving the fit against the private store reproduces the published file."""
    needs_store()
    document = build_document(evaluator_tests, tmp_path)
    assert serialise(document) == PUBLISHED.read_text(encoding="utf-8")
