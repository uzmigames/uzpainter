"""P0-TOOLCHAIN acceptance (`phase0.8_toolchain-slice`, items 3.1 and 4.1; `docs/dag.md`).

The three children test their own stages; this module checks the gate as a whole on one build
(`conftest.painter_bin`) and one `selftest` run: the DX12 hardware slice passes, every probe
completes and reports without being able to fail the run, and the CPython boundary passes. The
GPU run is the owner's machine's (decision 028); hosted CI (`UZP_NO_GPU=1`) runs the second test.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

HARDWARE_SLICE = ("dx12-device", "shader-compile", "compute-readback", "png16", "embree")
PROBES = ("dx12-ray-query", "vulkan-availability", "vulkan-ray-query", "warp")
# The non-mandatory Vulkan hardware slice of decision 310 (`tests/toolchain/test_selftest.py`).
VULKAN_SLICE = ("vulkan-device", "vulkan-compute-readback", "vulkan-png16")
CPYTHON = (
    "cpython-start",
    "cpython-uzpainter",
    "cpython-buffer16",
    "cpython-exceptions",
    "cpython-mcp-sdk",
)
NO_GPU_REASON = "no GPU: UZP_NO_GPU=1 (hosted CI has no GPU, decision 028"


def selftest(exe: Path, out_dir: Path, no_gpu: bool) -> tuple[int, str, dict[str, Any]]:
    env = dict(os.environ)
    env.pop("UZP_NO_GPU", None)
    if no_gpu:
        env["UZP_NO_GPU"] = "1"
    proc = subprocess.run(
        [str(exe), "selftest", "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    report = json.loads((out_dir / "selftest-report.json").read_text(encoding="utf-8"))
    return proc.returncode, proc.stdout + proc.stderr, report


def test_gate_on_the_owners_machine(painter_bin: Path, tmp_path: Path) -> None:
    """4.1: hardware slice green, every probe completed and reported (none mandatory, none part
    of the slice, so a WARP or Vulkan failure cannot fail the gate), the Vulkan slice of decision
    310 not mandatory either, CPython boundary qualified directly; all from one build and one
    run."""
    if os.environ.get("UZP_NO_GPU") == "1":
        pytest.skip("UZP_NO_GPU=1: no GPU here (decision 028); runs on the owner's machine")
    code, output, report = selftest(painter_bin / "UzPainter.exe", tmp_path, no_gpu=False)
    assert code == 0, output
    assert report["result"] == "passed" and report["hardware_slice"] == "passed"
    stages = {s["name"]: s for s in report["stages"]}
    assert list(stages) == [*HARDWARE_SLICE, *PROBES, *VULKAN_SLICE, *CPYTHON]
    for name in HARDWARE_SLICE:
        assert stages[name]["status"] == "passed" and stages[name]["hardware_slice"], name
    for name in (*PROBES, *VULKAN_SLICE):
        assert not stages[name]["mandatory"] and not stages[name]["hardware_slice"], name
    for name in CPYTHON:
        assert stages[name]["status"] == "passed" and stages[name]["mandatory"], name
    probes = {p["probe"]: p for p in report["probes"]}
    assert set(probes) == set(PROBES)
    for probe in probes.values():
        assert probe["completed"] is True, probe
        assert probe["verdict"] and probe["adapter"] and probe["executed_checks"], probe
        # Every item not supported carries its reason.
        assert all(u["item"] and u["reason"] for u in probe["unsupported"]), probe
    assert probes["warp"]["backend"] == "dx12-warp"


def test_hosted_lane_without_gpu(painter_bin: Path, tmp_path: Path) -> None:
    """Hosted CI (decision 028): under `UZP_NO_GPU=1` every stage that needs a GPU, probes
    included, skips with the decision's reason; the CPU stages of the slice and the whole CPython
    boundary still run and pass, and the run passes."""
    code, output, report = selftest(painter_bin / "UzPainter.exe", tmp_path, no_gpu=True)
    assert code == 0, output
    assert report["result"] == "passed" and report["hardware_slice"] == "skipped"
    stages = {s["name"]: s for s in report["stages"]}
    assert all(stages[name]["needs_gpu"] for name in PROBES)
    for stage in stages.values():
        if stage["needs_gpu"]:
            assert stage["status"] == "skipped" and stage["reason"].startswith(NO_GPU_REASON)
        else:
            assert stage["status"] == "passed", stage
    assert all(not stages[name]["needs_gpu"] for name in CPYTHON)
    assert report["probes"] == []
