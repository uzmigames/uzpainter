"""Device faults and GPU stalls through the supervisor on the selected backend.

Task phase2.1_supervisor-ipc-worker items 2.6, 2.9, 2.11, 3.3, 3.4; decisions 120 and 121).

These cases select `UZP_SUPERVISOR_BACKEND` (DX12 by default) and skip under
`UZP_NO_GPU=1` (hosted CI, decision 028). An explicit hardware lane must be ready.
Vulkan covers phase3.1_vulkan-compute-parity items 2.2 and 3.4 (decision 121).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import os
from pathlib import Path

import pytest

from tests.supervisor.conftest import NO_GPU, Mcp, make_project, with_a_refused_bitmap

pytestmark = pytest.mark.skipif(
    NO_GPU, reason="UZP_NO_GPU=1: needs a hardware adapter (decision 028)"
)

BACKEND = os.environ.get("UZP_SUPERVISOR_BACKEND", "dx12")
GPU = ("--gpu-backend", BACKEND, "--test-faults")


def gpu_session(painter: Path, tmp_path: Path, sessions: list[Mcp], *args: str) -> tuple[Mcp, int]:
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *GPU, *args)
    sessions.append(session)
    status = session.status()
    if "UZP_SUPERVISOR_BACKEND" in os.environ:
        assert status["gpu_status"] == "ready", status
    if status["gpu_status"] != "ready":
        pytest.skip(f"no {BACKEND} device on this machine (decision 028)")
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    return session, revision


def loaded_modules(pid: int) -> set[str]:
    """The lower-case file names of the modules loaded in process `pid`."""
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    assert handle
    try:
        modules = (ctypes.wintypes.HMODULE * 4096)()
        needed = ctypes.wintypes.DWORD()
        assert psapi.EnumProcessModulesEx(
            handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3
        )
        names = set()
        for module in modules[: needed.value // ctypes.sizeof(ctypes.wintypes.HMODULE)]:
            buffer = ctypes.create_unicode_buffer(1024)
            psapi.GetModuleBaseNameW(handle, ctypes.wintypes.HMODULE(module), buffer, 1024)
            names.add(buffer.value.lower())
        return names
    finally:
        kernel32.CloseHandle(handle)


def test_only_the_worker_creates_the_device(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.1: the supervisor never initialises a GPU device; the worker does."""
    session, _ = gpu_session(painter, tmp_path, sessions)
    status = session.status()
    module = "d3d12core.dll" if BACKEND == "dx12" else "vulkan-1.dll"
    assert module in loaded_modules(status["worker_pid"])
    assert module not in loaded_modules(session.process.pid)


def test_evaluation_returns_its_payload_by_path_and_hash(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.5: the evaluated tiles are written under the output root and returned as path + SHA-256."""
    session, revision = gpu_session(painter, tmp_path, sessions)
    reply = session.call("evaluate_channel", {"channel": "BaseColor"})
    result = reply["result"]
    assert result["revision"] == revision and result["channel"] == "BaseColor"
    payload = Path(result["payload"]["path"])
    assert payload.is_relative_to((tmp_path / "out").resolve())
    data = payload.read_bytes()
    assert hashlib.sha256(data).hexdigest() == result["payload"]["sha256"]
    assert len(data) == result["payload"]["size"]


def test_an_evaluator_release_gap_is_a_capability_gap(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """practical-e2e B4 (decision 242): the GPU evaluator's `NotYetSupported` (a bitmap
    minification the texture unit is not measured on) reaches the client as `capability_gap
    {tool, type, reason, operations}`, as the export's and the capture's do, not as the render
    layer's `request_failed`."""
    session = Mcp(painter, tmp_path, *GPU)
    sessions.append(session)
    status = session.status()
    if "UZP_SUPERVISOR_BACKEND" in os.environ:
        assert status["gpu_status"] == "ready", status
    if status["gpu_status"] != "ready":
        pytest.skip(f"no {BACKEND} device on this machine (decision 028)")
    with_a_refused_bitmap(session, tmp_path)
    refused = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert refused["error"]["code"] == "capability_gap", refused
    details = refused["error"]["details"]
    assert set(details) == {"tool", "type", "reason", "operations"}, details
    assert (details["tool"], details["type"], details["operations"]) == (
        "evaluate_channel",
        "NotYetSupported",
        [],
    )
    assert "evaluator:unsupported_source" in details["reason"], details


@pytest.mark.parametrize(
    ("fault", "code", "args"),
    [
        pytest.param(
            "remove_device", "device_removed", (), marks=pytest.mark.settling("device_lost")
        ),
        pytest.param(
            "gpu_stall",
            "timeout",
            ("--gpu-deadline-ms", "3000"),
            marks=pytest.mark.settling("gpu_stall"),
        ),
    ],
)
def test_device_fault_fails_the_job_and_relaunches_on_the_same_backend(
    painter: Path, tmp_path: Path, sessions: list[Mcp], fault: str, code: str, args: tuple[str, ...]
) -> None:
    """2.9, 3.3, 3.4: `ID3D12Device5::RemoveDevice` or a GPU stall through the hooks: the job fails
    with `device_removed {backend, reason}` or `timeout`, the worker exits deliberately and the
    supervisor relaunches it on the same backend at the last committed revision."""
    session, revision = gpu_session(painter, tmp_path, sessions, *args)
    old = session.status()["worker_pid"]
    output = tmp_path / "out"
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert session.call("test_fault", {"fault": fault})["result"] == {"armed": fault}
    failed = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert "error" in failed and "result" not in failed, failed
    assert {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    } == before
    error = failed["error"]
    assert error["code"] == code and error["details"]["backend"] == BACKEND, error
    if code == "device_removed":
        if BACKEND == "dx12":
            assert "(0x887A" in error["details"]["reason"], error
        else:
            assert error["details"]["reason"] == "VK_ERROR_DEVICE_LOST (-4)", error
    inspected = session.call("project_inspect")
    assert "result" in inspected and inspected["result"]["revision"] == revision, inspected
    status = session.status()
    assert status["recoveries"], status
    recovery = status["recoveries"][-1]
    assert recovery["cause"] == "device_fault" and recovery["fault_code"] == code, recovery
    assert recovery["old_pid"] == old and recovery["recovery_ms"] > 0, recovery
    assert status["gpu_backend"] == BACKEND and status["gpu_status"] == "ready", status
    assert status["worker_pid"] != old, status
    evaluated = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert "result" in evaluated, evaluated
