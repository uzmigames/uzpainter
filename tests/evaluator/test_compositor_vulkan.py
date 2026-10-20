"""The compositor kernels on Vulkan (phase3.1_vulkan-compute-parity item 2.3; decision 313).

`vulkan-kernel-spirv` needs DXC only: every generated compositor kernel compiles to SPIR-V in the
fixed-slot model of the vendored Vulkan layout. `vulkan-kernel-sweep` runs the DX12 blend sweep on
the qualified Vulkan device (adapter index 0, through `EngineOptions::createDevice`; product paths
still refuse Vulkan, decision 310) and compares every result with the CPU reference and with a DX12
engine's, subnormal float32 operands included; it skips under `UZP_NO_GPU=1` and when no qualified
Vulkan device exists (exit code 77). The Levels, virtual normal, UV projection and raw blend kernels
are refused on Vulkan until their sweeps run (their cases evaluate through the engine's capability
query, item 2.6). None of this is parity evidence for a Painter-visible output.
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


def test_unverified_kernels_are_refused_on_vulkan(evaluator_tests: Path, tmp_path: Path) -> None:
    """The Levels, virtual normal, UV projection and raw blend kernels are refused on Vulkan by
    name (`unsupported_node`, NotYetSupported) before anything is queued; a blend is accepted."""
    passed = _run(evaluator_tests, "vulkan-refusals", tmp_path, needs_gpu=True)
    assert "a blend is accepted on Vulkan" in passed, passed
    assert sum(p.endswith("is refused on Vulkan by name") for p in passed) == 4, passed
