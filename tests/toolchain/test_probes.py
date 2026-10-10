"""`selftest` probes (phase0.7_toolchain-probes, items 2.1-2.7 and 3.1-3.4).

Two sources:

- `uzp-probe-tests.exe` (`tests/native/selftest_probes_test.cpp`, `zig build probe-tests`) runs
  the probe decisions of `src/selftest/probe_report.h` on fabricated capability sources (DXR
  Tier 1.0, SM 6.5, absent or too-old Vulkan loader, a device without `VK_KHR_ray_query`, a WARP
  check that fails) and prints the probe report; these tests run anywhere.
- `UzPainter.exe selftest` on this machine's GPU; those tests skip with the reason under
  `UZP_NO_GPU=1` (hosted CI, decision 028), where the probe stages themselves skip.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.toolchain.test_selftest import run_selftest, stages
from tools.toolchain.probes_report import PROBES, hide_vulkan_loader, passed, probes, render

REPO_ROOT = Path(__file__).resolve().parents[2]
WARP_CHECKS = ("dx12-device", "shader-compile", "compute-readback", "png16")
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
needs_gpu = pytest.mark.skipif(
    NO_GPU, reason="UZP_NO_GPU=1: no GPU on this runner (decision 028); runs on the owner's machine"
)


@pytest.fixture(scope="session")
def probe_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-probe-tests.exe` of a fresh `zig build probe-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-probe-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("probe-tests")
    build = subprocess.run(
        [zig, "build", "probe-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-probe-tests.exe"


def case(exe: Path, name: str) -> dict[str, Any]:
    proc = subprocess.run([str(exe), name], capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


def unsupported(report: dict[str, Any]) -> dict[str, str]:
    return {u["item"]: u["reason"] for u in report["unsupported"]}


@pytest.fixture(scope="module")
def gpu_run(painter_bin: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if NO_GPU:
        pytest.skip("UZP_NO_GPU=1: no GPU on this runner (decision 028)")
    out = tmp_path_factory.mktemp("probes-gpu")
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", out)
    assert code == 0, output
    return report


# ── 3.1 Vulkan loader absent ─────────────────────────────────────────────────────────────


@needs_gpu
def test_loader_hidden_reports_unavailable_and_slice_passes(
    painter_bin: Path, tmp_path: Path
) -> None:
    """3.1: with the Vulkan loader hidden from the process, `vulkan-availability` completes and
    reports `unavailable` with the loader reason; `selftest` still passes the DX12 slice."""
    folder = tmp_path / "bin"
    shutil.copytree(painter_bin, folder)
    hide_vulkan_loader(folder)
    code, output, report = run_selftest(folder / "UzPainter.exe", tmp_path / "out")
    assert code == 0, output
    assert report["result"] == "passed" and report["hardware_slice"] == "passed"
    found = probes(report)
    vulkan = found["vulkan-availability"]
    assert vulkan["completed"] is True and vulkan["qualified"] is False
    assert vulkan["verdict"] == "unavailable"
    reasons = unsupported(vulkan)
    assert list(reasons) == ["Vulkan loader (vulkan-1.dll)"]
    assert reasons["Vulkan loader (vulkan-1.dll)"].startswith(
        "the Vulkan loader vulkan-1.dll could not be loaded: error 193"
    )
    ray_query = found["vulkan-ray-query"]
    assert ray_query["completed"] is True and ray_query["qualified"] is False
    assert unsupported(ray_query)["Vulkan"].startswith("Vulkan unavailable: Vulkan loader")
    assert stages(report)["vulkan-availability"]["status"] == "passed"
    # The DX12 probes are unaffected.
    assert found["dx12-ray-query"]["completed"] and found["warp"]["completed"]


def test_loader_absent_decision(probe_tests: Path) -> None:
    """3.1, decision: an absent loader (error 126) is `unavailable` with that reason."""
    report = case(probe_tests, "vulkan-availability-loader-absent")
    assert (report["completed"], report["qualified"], report["verdict"]) == (
        True,
        False,
        "unavailable",
    )
    assert "error 126" in unsupported(report)["Vulkan loader (vulkan-1.dll)"]
    assert report["executed_checks"] == [
        {
            "check": "load vulkan-1.dll through volk",
            "result": "failed",
            "detail": unsupported(report)["Vulkan loader (vulkan-1.dll)"],
        }
    ]


def test_loader_too_old_decision(probe_tests: Path) -> None:
    report = case(probe_tests, "vulkan-availability-loader-too-old")
    assert (report["completed"], report["qualified"], report["verdict"]) == (
        True,
        False,
        "unavailable",
    )
    reason = unsupported(report)["Vulkan 1.2 instance"]
    assert "supports Vulkan 1.1.0 only" in reason and "loader too old" in reason


# ── 3.2 DX12 missing feature ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "missing", "reported"),
    [
        ("dx12-tier-1-0", ["DXR Tier 1.1"], "the device reports DXR Tier 1.0"),
        ("dx12-sm-6-5", ["Shader Model 6.6"], "highest shader model 6.5"),
        ("dx12-no-dxr", ["DXR Tier 1.1", "Shader Model 6.6"], "DXR not supported"),
    ],
)
def test_dx12_missing_item_is_named(
    probe_tests: Path, name: str, missing: list[str], reported: str
) -> None:
    """3.2: a capability source with DXR Tier 1.0 or SM 6.5 makes the DX12 ray-query probe
    report unsupported and name each missing item; the vendored decision agrees."""
    report = case(probe_tests, name)
    assert report["probe"] == "dx12-ray-query" and report["backend"] == "dx12"
    assert (report["completed"], report["qualified"], report["verdict"]) == (
        True,
        False,
        "unsupported",
    )
    assert list(unsupported(report)) == missing
    assert any(reported in reason for reason in unsupported(report).values())
    vendored = next(c for c in report["executed_checks"] if "UZP-MOD-004" in c["check"])
    assert vendored["result"] == "failed"


def test_dx12_tier_1_1_and_sm_6_6_qualify(probe_tests: Path) -> None:
    report = case(probe_tests, "dx12-tier-1-1-sm-6-6")
    assert (report["completed"], report["qualified"], report["verdict"]) == (
        True,
        True,
        "supported",
    )
    assert report["unsupported"] == []
    assert all(c["result"] == "passed" for c in report["executed_checks"])


# ── 3.3 WARP report ──────────────────────────────────────────────────────────────────────


def assert_warp_report_shape(report: dict[str, Any]) -> None:
    """Supported capabilities, executed checks with results, an explicit reason for every
    unsupported item, and a hosted lane made only of checks that passed."""
    assert report["probe"] == "warp"
    executed = {c["check"]: c["result"] for c in report["executed_checks"]}
    assert set(executed) <= set(WARP_CHECKS)
    assert set(executed.values()) <= {"passed", "failed"}
    for item in report["unsupported"]:
        assert item["item"] and item["reason"].strip(), item
    lane = report["hosted_warp_lane"]
    assert lane == [c for c in WARP_CHECKS if executed.get(c) == "passed"]
    for check in WARP_CHECKS:
        if check not in lane:
            assert check in unsupported(report), check
    assert report["qualified"] == (lane == list(WARP_CHECKS))


def test_warp_failing_check_leaves_lane_and_is_reported(probe_tests: Path) -> None:
    """3.3: a compute check that fails on WARP is listed unsupported with its reason, the checks
    after it are not run (with the reason) and the hosted lane keeps only the passed ones."""
    report = case(probe_tests, "warp-failing-check")
    assert_warp_report_shape(report)
    assert report["completed"] is True and report["qualified"] is False
    assert report["verdict"] == "partially qualified"
    assert report["hosted_warp_lane"] == ["dx12-device", "shader-compile"]
    reasons = unsupported(report)
    assert reasons["compute-readback"] == "failed on WARP: 17 read-back values differ"
    assert reasons["png16"].startswith("not run on WARP: needs check compute-readback")


def test_warp_without_adapter_is_unsupported(probe_tests: Path) -> None:
    report = case(probe_tests, "warp-no-adapter")
    assert_warp_report_shape(report)
    assert report["completed"] is True and report["verdict"] == "unsupported"
    assert report["hosted_warp_lane"] == []


def test_warp_all_pass_qualifies(probe_tests: Path) -> None:
    report = case(probe_tests, "warp-all-pass")
    assert_warp_report_shape(report)
    assert report["qualified"] is True and report["verdict"] == "qualified"


def test_warp_probe_on_this_machine(gpu_run: dict[str, Any]) -> None:
    """3.3 on the owner's machine: the WARP probe completes on the Microsoft Basic Render Driver
    and reports capabilities, checks and lane."""
    warp = probes(gpu_run)["warp"]
    assert warp["completed"] is True
    assert warp["adapter"] == "Microsoft Basic Render Driver"
    assert warp["supported"], warp
    assert [c["check"] for c in warp["executed_checks"]][:1] == ["dx12-device"]
    assert_warp_report_shape(warp)


# ── 3.4 completed and qualified reported separately ──────────────────────────────────────


def test_vulkan_without_ray_query_completed_not_qualified(probe_tests: Path) -> None:
    """3.4 scenario: a Vulkan device without `VK_KHR_ray_query`: the probes completed, Vulkan is
    available and the Vulkan ray-query path is not qualified, each missing item named."""
    availability = case(probe_tests, "vulkan-availability-no-ray-query")
    assert (availability["completed"], availability["qualified"]) == (True, True)
    assert availability["verdict"] == "available"
    report = case(probe_tests, "vulkan-ray-query-no-ray-query")
    assert (report["completed"], report["qualified"], report["verdict"]) == (
        True,
        False,
        "unsupported",
    )
    reasons = unsupported(report)
    assert list(reasons) == ["VK_KHR_ray_query", "rayQuery"]
    assert reasons["rayQuery"] == "cannot be queried: VK_KHR_ray_query is not exposed"
    full = case(probe_tests, "vulkan-ray-query-full")
    assert (full["qualified"], full["verdict"], full["unsupported"]) == (True, "supported", [])


def test_not_completed_is_distinct(probe_tests: Path) -> None:
    report = case(probe_tests, "not-completed")
    assert report["completed"] is False and report["qualified"] is False
    assert report["verdict"] == "probe not completed"
    assert report["error"] == "exception: fabricated"


def test_optional_memory_budget_does_not_decide_availability(probe_tests: Path) -> None:
    report = case(probe_tests, "vulkan-availability-no-budget")
    assert report["qualified"] is True and report["verdict"] == "available"
    assert "VK_EXT_memory_budget (optional)" in unsupported(report)


def test_vendored_device_selection_is_followed(probe_tests: Path) -> None:
    """The adapter judged is the one the vendored backend selects: discrete before integrated."""
    report = case(probe_tests, "vulkan-availability-selects-discrete")
    assert report["adapter"] == "Fabricated dGPU" and report["qualified"] is True


def test_every_probe_reports_completed_and_qualified(gpu_run: dict[str, Any]) -> None:
    """3.4 and 2.6 on the owner's machine: each probe states `completed` and `qualified` as
    separate booleans; a probe stage passes exactly when its probe completed; no probe stage
    is mandatory or part of the hardware slice."""
    found = probes(gpu_run)
    assert list(found) == list(PROBES)
    by_stage = stages(gpu_run)
    for name, probe in found.items():
        assert isinstance(probe["completed"], bool) and isinstance(probe["qualified"], bool)
        assert probe["completed"], probe
        stage = by_stage[name]
        assert stage["status"] == "passed"
        assert not stage["mandatory"] and not stage["hardware_slice"] and stage["needs_gpu"]
        assert stage["details"]["completed"] == "yes"
        assert stage["details"]["qualified"] == ("yes" if probe["qualified"] else "no")
    assert gpu_run["hardware_slice"] == "passed"


def test_vulkan_probe_records_devices(gpu_run: dict[str, Any]) -> None:
    """2.2: per physical device the API version, driver, extensions and features."""
    vulkan = probes(gpu_run)["vulkan-availability"]
    assert vulkan["completed"]
    if vulkan["verdict"] == "unavailable" and not vulkan["devices"]:
        pytest.skip("no Vulkan device on this machine: " + str(vulkan["unsupported"]))
    for device in vulkan["devices"]:
        facts = device["facts"]
        assert facts["api_version"] and facts["driver_version"] and facts["name"]
        assert int(facts["extension_count"]) == len(device["extensions"]) > 0
        for feature in ("bufferDeviceAddress", "descriptorIndexing", "rayQuery"):
            assert feature in device["features"]
    assert sum(d["facts"]["selected"] == "yes" for d in vulkan["devices"]) == 1


def test_no_gpu_run_skips_probes_with_reason(painter_bin: Path, tmp_path: Path) -> None:
    """Hosted CI: the probe stages skip with the reason and leave the `probes` array empty."""
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, "--no-gpu")
    assert code == 0, output
    by_stage = stages(report)
    for name in PROBES:
        assert by_stage[name]["status"] == "skipped"
        assert by_stage[name]["reason"] == "no GPU: --no-gpu on the command line"
    assert report["probes"] == []


# ── 2.7 report renderer ──────────────────────────────────────────────────────────────────


def test_report_renders_every_probe(gpu_run: dict[str, Any], tmp_path: Path) -> None:
    text = render(tmp_path, (0, gpu_run), (0, gpu_run))
    for name in PROBES:
        assert f"### `{name}`" in text
    assert "| Probe | Backend | Adapter | Driver | Completed | Qualified | Verdict |" in text
    assert "Hosted WARP lane" in text
    assert passed((0, gpu_run))
