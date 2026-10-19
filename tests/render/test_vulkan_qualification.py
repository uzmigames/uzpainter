"""Tests of the Vulkan device qualification slice of phase3.1_vulkan-compute-parity (decision 310):
`src/render/vulkan_qualification.h`, `vulkan_backend.h` and `vulkan_kernels.h`, through the
`vulkan-*` cases of `uzp-render-tests.exe` (`tests/render/vulkan_test.cpp`).

`vulkan-qualify` needs no GPU: the criteria judged on fabricated capability records, and the
refusal of an unqualified device before the Vulkan loader is even loaded (the deterministic
unavailable-device fixture of the render layer). `vulkan-device` and `vulkan-faults` create Vulkan
devices; they skip under `UZP_NO_GPU=1` (decision 028) or when the machine has no Vulkan device
(exit code 77). None of them is parity evidence for a Painter-visible output.
"""

from __future__ import annotations

from pathlib import Path

from tests.render.test_core_device_kernels import run_case


def _run(exe: Path, case: str, work: Path | None = None) -> set[str]:
    passed, _ = run_case(exe, case, work)
    return passed


def test_criteria_name_every_unmet_capability(render_tests: Path) -> None:
    """2.1, 2.6: each criterion of the vendored backend and the kernels is judged and a refusal
    names the first unmet one: loader and instance version (a 1.1 loader is refused, not used),
    instance and device extensions, feature bits (an unqueried one is not taken as present),
    update-after-bind limits, formats, the queue family, memory types; the vendored order picks the
    discrete device and an unqualified one is never replaced by another."""
    passed = _run(render_tests, "vulkan-qualify")
    assert {
        "a device meeting every criterion qualifies on the first graphics queue family",
        "no loader: refused, no device judged",
        "a Vulkan 1.1 loader is refused before any device is judged",
        "a missing instance extension is named",
        "a Vulkan 1.1 device is refused",
        "a missing required feature bit is named",
        "shaderStorageImageExtendedFormats (the R16f storage image) is required",
        "an unqueried feature is not taken as present",
        "a missing device extension is named",
        "a CPU device is refused as a hardware device",
        "an update-after-bind limit below the vendored layout is named",
        "a pool smaller than the vendored descriptor pool is named",
        "a format without storage-image support is named",
        "a graphics family without compute is refused (no other family is picked)",
        "a device without host-visible memory is refused",
        "a device without signed-zero/Inf/NaN preservation is refused for IEEE-strict kernels",
        "an adapter index past the devices is refused",
        "the vendored order puts discrete before integrated",
        "adapter index 0 judges the discrete device",
        "an unqualified discrete device is refused, not replaced by the qualified integrated one",
    } <= passed


def test_entry_points_and_refusal_before_any_work(render_tests: Path) -> None:
    """2.1, 2.8: a missing entry point is named (the KHR names, not the core 1.3 ones); an
    unqualified device is refused with `gpu_backend_unavailable {backend: vulkan}` naming the
    criterion, before anything is created or the loader is loaded."""
    passed = _run(render_tests, "vulkan-qualify")
    assert {
        "every entry point resolving: none missing",
        "a missing entry point is named",
        "the backend names the KHR entry points, not the core 1.3 ones",
        "an unqualified device is refused before any work, naming the criterion",
        "the refusal loaded no Vulkan loader",
    } <= passed


def test_descriptor_and_admission_model(render_tests: Path) -> None:
    """2.6: descriptors in Vulkan's own terms (per-dispatch bindings, set snapshots in the vendored
    pool, no descriptor bound on live tiles) and the VRAM budget from VK_EXT_memory_budget or the
    heap sizes."""
    passed = _run(render_tests, "vulkan-qualify")
    assert {
        "one dispatch binds 16 of each descriptor type",
        "the vendored pool holds 128 set snapshots at once, bounded by its 2048 samplers",
        "a lower device limit bounds the bindings of one dispatch",
        "without VK_EXT_memory_budget the budget is the device-local heap size, usage unknown",
        "with VK_EXT_memory_budget the device-local heaps' budget and usage",
        "admission = (budget - usage - reserve) x 50 %, no descriptor bound on live tiles",
    } <= passed


def test_device_dispatch_readback_bit_exact(render_tests: Path, tmp_path: Path) -> None:
    """2.1, 2.8, 3.1 (pitch): on this machine's device the three qualification kernels compile to
    SPIR-V that declares its image format (no ...WithoutFormat capability,
    StorageImageExtendedFormats exactly for R16f, NoContraction for the IEEE kernel) and read back
    bit for bit at 100x64 and odd widths; the device is destroyed after its work completed."""
    passed = _run(render_tests, "vulkan-device", tmp_path)
    assert "this machine's device at adapter index 0 qualifies" in passed
    assert "the qualified device is created on the judged device and queue family" in passed
    for kernel in ("pattern16", "hash32", "ieee32"):
        assert {
            f"{kernel}: compiles to SPIR-V",
            f"{kernel}: the SPIR-V storage image declares its format",
            f"{kernel}: the SPIR-V needs no ...WithoutFormat capability",
            f"{kernel}: every SPIR-V capability is one the qualification covers",
            f"{kernel}: SignedZeroInfNanPreserve is declared exactly for the IEEE-strict kernel",
            f"{kernel}: StorageImageExtendedFormats is declared exactly when the format needs it",
            f"{kernel}: every read-back texel equals the CPU reference bit for bit, "
            "odd widths included",
            f"{kernel}: rows are read at the texel-aware pitch",
        } <= passed
    assert "ieee32: the SPIR-V arithmetic is NoContraction" in passed
    assert "after its work completed the device is destroyed" in passed


def test_bounded_waits_and_failure_teardown(render_tests: Path, tmp_path: Path) -> None:
    """2.2, 3.4 (in-process part): a wait past its deadline returns `timeout` at it; a refused
    command list fails at once and the queue goes on; a partial submission (host barrier refused
    after the command list) keeps its staging buffer and fails the device; a refused fence signal
    fails its wait at once; VK_ERROR_DEVICE_LOST is `device_removed {backend: vulkan, reason}`;
    a stalled queue's teardown ends at its deadline, abandoned; a new device then runs exactly."""
    passed = _run(render_tests, "vulkan-faults", tmp_path)
    assert {
        "a wait for a value never submitted returns timeout",
        "the timeout returns at the 500 ms deadline, not later",
        "after a timeout the device still runs a kernel exactly",
        "a refused command list fails Submit with request_failed",
        "the refusal is immediate and consumes no fence value",
        "the next submission runs exactly",
        "the command list, the barrier and the fence signal were each submitted",
        "the refused barrier fails Submit, stating the command list was submitted",
        "the staging buffer is not destroyed while its copy may be in flight",
        "a failed device accepts no further submission",
        "the failed device is abandoned at once, never waited on",
        "the wait on the refused value fails at once with its VkResult, not by a timeout",
        "VK_ERROR_DEVICE_LOST is reported as device_removed {backend: vulkan, reason}",
        "a lost device accepts no submission",
        "the lost device is abandoned at once",
        "the stalled wait returns timeout at its 500 ms deadline",
        "teardown of the stalled device ends at its 500 ms deadline, abandoned",
        "the abandoned device's staging buffer is not freed",
        "a new device is created after abandoned ones",
        "the new device runs the kernel bit for bit",
    } <= passed
