"""The compositor kernels on Vulkan (phase3.1_vulkan-compute-parity item 2.3; decision 313).

`vulkan-kernel-spirv` needs DXC only: every generated compositor kernel compiles to SPIR-V in the
fixed-slot model of the vendored Vulkan layout. The `vulkan-<case>` cases run a DX12 GPU case on the
qualified Vulkan device (adapter index 0, through `EngineOptions::createDevice`; product paths
still refuse Vulkan, decision 310) and compare every result with the CPU reference and with a DX12
engine's: `vulkan-kernel-sweep` the blend kernels, subnormal float32 operands included;
`vulkan-projection-gpu-vs-cpu` the UV projection kernel; `vulkan-masks-gpu-vs-cpu` the Levels
kernel; `vulkan-height-normal-gpu-vs-cpu` the virtual normal and raw blend kernels;
`vulkan-gpu-vs-cpu` the random stacks of every node kind and channel format;
`vulkan-diagnostics-gpu-vs-cpu` every diagnostic source (item 3.3). They skip under
`UZP_NO_GPU=1` and when no qualified Vulkan device exists (exit code 77). None of this is parity
evidence for a Painter-visible output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "assets" / "templates"
EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"


def _run(exe: Path, case: str, work: Path, *, needs_gpu: bool) -> set[str]:
    """Run one case; return its passed checks. Fails on any failed check."""
    if needs_gpu and NO_GPU:
        pytest.skip(f"UZP_NO_GPU=1: `{case}` needs a Vulkan device (decision 028)")
    proc = subprocess.run(
        [str(exe), case, str(TEMPLATES_DIR), str(work)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    output = proc.stdout + proc.stderr
    print(output)  # the case's PASS/INFO lines are the evidence (pytest -rP shows them)
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no device for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    return {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}


def test_kernels_compile_to_fixed_slot_spirv(evaluator_tests: Path, tmp_path: Path) -> None:
    """Every compositor kernel's SPIR-V: descriptor set 0, bindings among the sampled images
    0..15, the storage image 48 and the storage buffers 64..79, one storage image of the
    destination tile's format, IEEE-strict, and only the capabilities a qualified device enables."""
    passed = _run(evaluator_tests, "vulkan-kernel-spirv", tmp_path, needs_gpu=False)
    assert any(p.startswith("every compositor kernel compiles to SPIR-V") for p in passed), passed


def test_vulkan_kernel_sweep(evaluator_tests: Path, tmp_path: Path) -> None:
    """Every blend mode x channel format on Vulkan equals the CPU reference and the DX12 result
    bit for bit. With subnormal float32 operands Vulkan equals DX12 bit for bit; both differ from
    the CPU reference, which keeps subnormals the GPU flushes on either backend (reported in the
    case's KNOWN line, decision 313)."""
    passed = _run(evaluator_tests, "vulkan-kernel-sweep", tmp_path, needs_gpu=True)
    assert any(p.startswith("every blend mode x channel format") for p in passed), passed
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed


def test_vulkan_projection_equals_cpu_and_dx12(evaluator_tests: Path, tmp_path: Path) -> None:
    """The UV projection kernel on Vulkan: `projection-gpu-vs-cpu`'s random stacks (filters, wrap
    modes, transforms, minification through the texture unit, sRGB decodes) equal the CPU reference
    and the DX12 result bit for bit."""
    passed = _run(evaluator_tests, "vulkan-projection-gpu-vs-cpu", tmp_path, needs_gpu=True)
    assert any(p.startswith("every random projection stack") for p in passed), passed
    assert any(p.startswith("every random minifying projection stack") for p in passed), passed
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed


def test_vulkan_levels_equal_cpu_and_dx12(evaluator_tests: Path, tmp_path: Path) -> None:
    """The Levels kernel on Vulkan: `masks-gpu-vs-cpu`'s masked stacks (mask and content fill
    effects, levels with gamma, group masks) equal the CPU reference and the DX12 result."""
    passed = _run(evaluator_tests, "vulkan-masks-gpu-vs-cpu", tmp_path, needs_gpu=True)
    assert any(p.startswith("every masked stack evaluates to the same") for p in passed), passed
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed


def test_vulkan_height_normal_equals_cpu_and_dx12(evaluator_tests: Path, tmp_path: Path) -> None:
    """The virtual normal and raw blend kernels on Vulkan: `height-normal-gpu-vs-cpu`'s sweeps (both
    methods and conventions across tile edges, the float32 read-out on every channel format, the
    whole virtual normal evaluation) equal the CPU reference and the DX12 result."""
    passed = _run(evaluator_tests, "vulkan-height-normal-gpu-vs-cpu", tmp_path, needs_gpu=True)
    assert any(p.startswith("the virtual normal kernel equals the CPU reference") for p in passed)
    assert any(p.startswith("the float32 read-out (raw blend) equals the CPU") for p in passed)
    assert any(p.startswith("Evaluator (GPU) and CpuEvaluator give the same") for p in passed)
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed


def test_vulkan_random_stacks_equal_cpu_and_dx12(evaluator_tests: Path, tmp_path: Path) -> None:
    """3.3: `gpu-vs-cpu`'s random stacks on Vulkan (fills, bitmap fills, groups and PassThrough
    groups under random blend modes and opacities, on every channel format) equal the CPU
    reference and the DX12 result bit for bit."""
    passed = _run(evaluator_tests, "vulkan-gpu-vs-cpu", tmp_path, needs_gpu=True)
    assert any(p.startswith("every random stack evaluates to the same bytes") for p in passed)
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed


def test_vulkan_diagnostics_equal_cpu_and_dx12(evaluator_tests: Path, tmp_path: Path) -> None:
    """3.3: `diagnostics-gpu-vs-cpu` on Vulkan: every diagnostic source (isolate and contribution
    on six channel formats, material masks, views, leaks and region statistics) equals the CPU
    reference and the DX12 result bit for bit, repeats byte-identical, and an isolation failing
    midway leaves the document as it was."""
    passed = _run(evaluator_tests, "vulkan-diagnostics-gpu-vs-cpu", tmp_path, needs_gpu=True)
    assert any(p.startswith("every diagnostic source on the GPU equals the CPU") for p in passed)
    assert any(p.startswith("a GPU isolation that fails midway") for p in passed)
    assert any(p.startswith("every Vulkan result equals the DX12 result") for p in passed), passed
