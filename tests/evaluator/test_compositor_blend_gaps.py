"""Tests of phase1.11_compositor-blend-gaps (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §3; `src/evaluator/arith.cpp`,
`src/evaluator/hwmath.h`, `src/evaluator/shaders/evaluator_blend.hlsl`).

The normal-map modes rotate the upper normal by the opacity with the recording GPU's sine, cosine
and GLSL arcsine; the component modes use the float32 hue identified on `blend-component-hue`; a
PassThrough group composites its children onto a copy of the stack below it and mixes by its
opacity and mask (the UI-set golden `semantics-ui/group-passthrough-masks` of the current
envelope). Their Tier 0 sweeps run in `test_compositor_blend_kernels.py` (every mode is exact
there), and GPU = CPU over every mode is `kernel-sweep` and `gpu-vs-cpu` of
`test_compositor_tile_dag.py`. The native `arith` case runs anywhere;
`trig-hardware` needs a DX12 adapter (decision 028), and the sine and cosine tables describe the
RTX 4090 the Tier 0 goldens were recorded on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.evaluator import blend_fits, masks_fits
from tests.evaluator.sources_fits import channel_formats, export16
from tests.evaluator.sources_fits import srgb8_decode as decode_table
from tests.evaluator.test_compositor_tile_dag import (
    backends,
    evaluate,
    needs_store,
    raster,
    run_case,
)


def test_glsl_arcsine_and_trig_index(evaluator_tests: Path) -> None:
    """2.2: hw::Asin equals the recording GPU's GLSL asin on measured inputs (edges, the 0.57
    branch point and values over [0, 1]), and the sine and cosine tables index [0, pi/2] with
    2^23 fixed-point turns."""
    passed, _ = run_case(evaluator_tests, "arith")
    assert "hw::Asin equals the recording GPU's GLSL asin on 48 measured inputs" in passed
    assert "the sine and cosine tables cover [0, float32(pi / 2)] with 2^23 entries" in passed


def test_component_hue_rules(evaluator_tests: Path) -> None:
    """2.1, 2.4: the fitted hue of Tint, Saturation, Color and Value takes red for a grey source
    and keeps a hue wrapped to 1 unreduced (its Tier 0 sweeps, `blend-component` and
    `blend-component-hue`, run in `test_compositor_blend_kernels.py`)."""
    passed, _ = run_case(evaluator_tests, "arith")
    assert "the component hue: grey is red, a hue wrapped to 1 is not reduced" in passed


def test_trig_tables_equal_the_gpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.4: the embedded sine and cosine tables equal the GPU on every index of their domain,
    every measured input lies at its own index, and hw::Sin/Cos equal the GPU on 2^20 inputs."""
    passed, output = run_case(evaluator_tests, "trig-hardware", str(tmp_path), needs_gpu=True)
    if "RTX 4090" not in output:
        pytest.skip("the sine and cosine tables describe the RTX 4090 the goldens were recorded on")
    assert {
        "every measured input lies at its table index (8388608)",
        "the embedded sin table equals the GPU on every entry of its domain (8388608)",
        "the embedded cos table equals the GPU on every entry of its domain (8388608)",
    } <= passed
    assert any(p.startswith("hw::Sin and hw::Cos equal the GPU") for p in passed)


@pytest.mark.parametrize("backend", backends())
def test_passthrough_groups_equal_the_golden(
    evaluator_tests: Path, tmp_path: Path, backend: str
) -> None:
    """2.3: the Passthrough group (set through Painter's UI) without a mask, with a group mask, a
    child mask and both, over fields A with a Multiply and a Screen child, equals both recordings
    on RGB16, sRGB8 and RGB32F (owner's machine: private store)."""
    needs_store()
    manifest = masks_fits.envelope_manifest(blend_fits.PASSTHROUGH)
    golden = masks_fits.envelope_golden(blend_fits.PASSTHROUGH)
    formats = channel_formats(manifest)
    decode = decode_table(evaluator_tests, tmp_path / "tables")
    for texture_set in blend_fits.PASSTHROUGH_SETS:
        workdir = tmp_path / texture_set
        spec = blend_fits.passthrough_spec(manifest, texture_set, workdir, sorted(formats))
        result = evaluate(evaluator_tests, spec, workdir, backend)
        for channel, fmt in formats.items():
            ours = raster(result, channel)
            value = ours if fmt.endswith("F") else export16(ours, fmt, decode)
            for recording in ("r1", "r2"):
                map_name = f"{texture_set}/{channel.lower()}"
                theirs = golden.map(recording, map_name).values.reshape(value.shape)
                differing = int(np.count_nonzero(value.astype(np.float64) != theirs))
                assert differing == 0, f"{map_name} {recording}: {differing} values differ"
