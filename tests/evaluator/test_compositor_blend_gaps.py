"""Tests of phase1.11_compositor-blend-gaps (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §3; `src/evaluator/arith.cpp`,
`src/evaluator/hwmath.h`, `src/evaluator/shaders/evaluator_blend.hlsl`).

The normal-map modes rotate the upper normal by the opacity with the recording GPU's sine, cosine
and GLSL arcsine; the component modes use the fitted hue. Their Tier 0 sweeps run in
`test_compositor_blend_kernels.py` (the normal-map modes are exact there, the component modes
reproduce their published residuals), and GPU = CPU over every mode is `kernel-sweep` and
`gpu-vs-cpu` of `test_compositor_tile_dag.py`. The native `arith` case runs anywhere;
`trig-hardware` needs a DX12 adapter (decision 028), and the sine and cosine tables describe the
RTX 4090 the Tier 0 goldens were recorded on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.evaluator.test_compositor_tile_dag import run_case


def test_glsl_arcsine_and_trig_index(evaluator_tests: Path) -> None:
    """2.2: hw::Asin equals the recording GPU's GLSL asin on measured inputs (edges, the 0.57
    branch point and values over [0, 1]), and the sine and cosine tables index [0, pi/2] with
    2^23 fixed-point turns."""
    passed, _ = run_case(evaluator_tests, "arith")
    assert "hw::Asin equals the recording GPU's GLSL asin on 48 measured inputs" in passed
    assert "the sine and cosine tables cover [0, float32(pi / 2)] with 2^23 entries" in passed


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
