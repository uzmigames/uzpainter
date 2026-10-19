"""Tests of phase1.1_core-device-kernels: the render layer's device, engine thread, kernel cache
and capability query (`src/render/`, `docs/architecture/13-engine-integration.md` §4.1, §6).

Every case runs `uzp-render-tests.exe` (`tests/render/render_core_test.cpp`, `zig build
render-tests`). The CPU cases (XXH64, the admission derivation, compilation to DXIL and SPIR-V and
the kernel cache) run anywhere; the cases that create a DX12 device skip under `UZP_NO_GPU=1`
(hosted CI, decision 028) or when the executable reports no adapter (exit code 77), and run on
the owner's hardware adapter otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
GPU_CASES = frozenset(
    {
        "dispatch",
        "deadline",
        "device-removed",
        "unavailable",
        "capabilities",
        "readback-pitch",
        "readback-exact",
        "readback-drain",
        "readback-failure",
        "readback-kernel",
        "uv-raster-plane",
        "uv-raster-thin",
        "uv-raster-coverage",
        "uv-raster-ids",
        "uv-raster-repeat",
        "uv-raster-tier0",
        "image-dilation",
        "image-resample",
        "image-mips",
        "image-repeat",
        "vulkan-device",
        "vulkan-faults",
    }
)


def run_case(exe: Path, case: str, work: Path | None = None) -> tuple[set[str], str]:
    """Run one case; return its passed checks and its output. Fails on any failed check."""
    if case in GPU_CASES and NO_GPU:
        pytest.skip(
            f"UZP_NO_GPU=1: `{case}` needs a DX12 hardware adapter; run it locally on the "
            "owner's machine (decision 028)"
        )
    args = [str(exe), case] + ([str(work)] if work is not None else [])
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    return passed, output


def test_xxh64_reference_digests(render_tests: Path) -> None:
    """2.5: the cache key's XXH64 is bit-exact with the reference implementation."""
    passed, _ = run_case(render_tests, "xxhash")
    assert "xxh64 matches the reference digests (0..1000 bytes, two seeds)" in passed


def test_admission_budget_derivation(render_tests: Path) -> None:
    """2.6: the admission budget follows from the VRAM budget and the descriptor capacity."""
    passed, _ = run_case(render_tests, "admission")
    assert "admission = (budget - usage - reserve) x 50 %" in passed
    assert "live tiles bounded by descriptors" in passed


def test_kernel_compiles_to_dxil_and_spirv(render_tests: Path, tmp_path: Path) -> None:
    """3.1 (compile half): one kernel source compiles to DXIL and to SPIR-V, IEEE-strict.
    3.2: an identical key hits; a change of source, include, define, target or DXC version
    misses."""
    passed, _ = run_case(render_tests, "kernel-cache", tmp_path)
    assert {
        "the kernel compiles to a DXIL container",
        "the same kernel compiles to a SPIR-V module",
        "SPIR-V arithmetic is IEEE-strict (NoContraction decorations)",
        "an identical key hits without compiling",
        "an identical key hits from disk in a new cache",
        "a changed source misses and recompiles",
        "a changed include misses and recompiles",
        "a changed define misses and recompiles",
        "a changed target misses and recompiles",
        "a changed DXC version misses and recompiles",
        "every changed key part gives a distinct key",
        "a damaged entry is recompiled",
        "an undeclared include fails to compile",
        "the default cache folder is %LOCALAPPDATA%\\UzPainter\\kernel-cache",
    } <= passed


def test_dxil_kernel_dispatch_on_dx12(render_tests: Path, tmp_path: Path) -> None:
    """3.1: the cached DXIL kernel, dispatched by the engine thread for a request submitted from
    another thread, writes exactly the expected values."""
    passed, _ = run_case(render_tests, "dispatch", tmp_path)
    assert {
        "the request ran on the engine thread, not the caller's",
        "written values equal the expected IEEE-strict values bit for bit",
        "a later revision's snapshot is evaluated exactly",
        "the same source compiles to SPIR-V",
    } <= passed


def test_stalled_fence_times_out(render_tests: Path, tmp_path: Path) -> None:
    """3.3: a stalled GPU queue makes the wait return `timeout` at the configured deadline."""
    passed, _ = run_case(render_tests, "deadline", tmp_path)
    assert {
        "the stalled wait returns timeout",
        "the wait ends at the deadline, not later",
        "later requests fail with the timeout without running",
    } <= passed


def test_device_removal_reported(render_tests: Path, tmp_path: Path) -> None:
    """3.4: after `ID3D12Device5::RemoveDevice` the engine thread reports
    `device_removed {backend: dx12, reason}`."""
    passed, output = run_case(render_tests, "device-removed", tmp_path)
    assert "the next request fails with device_removed {backend: dx12, reason}" in passed
    assert "device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED" in output


def test_unavailable_backend(render_tests: Path, tmp_path: Path) -> None:
    """3.5: an unavailable backend yields `gpu_backend_unavailable` before any work runs and
    no other backend is used."""
    passed, _ = run_case(render_tests, "unavailable", tmp_path)
    for name in ("vulkan", "dx12 adapter 64"):
        assert (
            f"{name}: a request fails with gpu_backend_unavailable before its work runs" in passed
        )
    assert "no DX12 device was created (D3D12Core.dll not loaded)" in passed
    assert "no Vulkan device was created (vulkan-1.dll not loaded)" in passed


def test_capability_report(render_tests: Path, tmp_path: Path) -> None:
    """3.6: the DX12 report lists formats with usages, ray-query support and the VRAM budget;
    the admission budget is derived from it."""
    passed, output = run_case(render_tests, "capabilities", tmp_path)
    assert "the admission budget is derived from the reported budget" in passed
    line = next(line for line in output.splitlines() if line.startswith("REPORT "))
    report: dict[str, Any] = json.loads(line.removeprefix("REPORT "))
    assert report["backend"] == "dx12"
    assert isinstance(report["ray_query"], bool)
    formats = {f["format"]: set(f["usages"]) for f in report["formats"]}
    assert {"copy", "shader_resource", "unordered_access"} <= formats["RGBA16Float"]
    assert report["vram"]["budget_bytes"] > 0
    assert report["admission"]["bytes"] > 0
    assert report["descriptors"]["shader_resources"] > 0
