"""Device faults and GPU stalls through the supervisor on DX12 (task phase2.1_supervisor-ipc-worker
items 2.6, 2.9, 2.11, 3.3, 3.4; decisions 120 and 121).

These cases create a DX12 device in the worker and skip under `UZP_NO_GPU=1` (hosted CI,
decision 028). The Vulkan device-loss variant waits for the Vulkan device
(phase3.1_vulkan-compute-parity items 2.2 and 3.4, decision 121).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
from pathlib import Path

import pytest

from tests.supervisor.conftest import NO_GPU, Mcp, make_project

pytestmark = pytest.mark.skipif(
    NO_GPU, reason="UZP_NO_GPU=1: needs a DX12 hardware adapter (decision 028)"
)

DX12 = ("--gpu-backend", "dx12", "--test-faults")


def dx12_session(painter: Path, tmp_path: Path, sessions: list[Mcp], *args: str) -> tuple[Mcp, int]:
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *DX12, *args)
    sessions.append(session)
    status = session.status()
    if status["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
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
    session, _ = dx12_session(painter, tmp_path, sessions)
    status = session.status()
    assert "d3d12core.dll" in loaded_modules(status["worker_pid"])
    assert "d3d12core.dll" not in loaded_modules(session.process.pid)


def test_evaluation_returns_its_payload_by_path_and_hash(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.5: the evaluated tiles are written under the output root and returned as path + SHA-256."""
    session, revision = dx12_session(painter, tmp_path, sessions)
    reply = session.call("evaluate_channel", {"channel": "BaseColor"})
    result = reply["result"]
    assert result["revision"] == revision and result["channel"] == "BaseColor"
    payload = Path(result["payload"]["path"])
    assert payload.is_relative_to((tmp_path / "out").resolve())
    data = payload.read_bytes()
    assert hashlib.sha256(data).hexdigest() == result["payload"]["sha256"]
    assert len(data) == result["payload"]["size"]


@pytest.mark.parametrize(
    ("fault", "code", "args"),
    [
        ("remove_device", "device_removed", ()),
        ("gpu_stall", "timeout", ("--gpu-deadline-ms", "3000")),
    ],
)
def test_device_fault_fails_the_job_and_relaunches_on_the_same_backend(
    painter: Path, tmp_path: Path, sessions: list[Mcp], fault: str, code: str, args: tuple[str, ...]
) -> None:
    """2.9, 3.3, 3.4: `ID3D12Device5::RemoveDevice` or a GPU stall through the hooks: the job fails
    with `device_removed {backend, reason}` or `timeout`, the worker exits deliberately and the
    supervisor relaunches it on DX12 at the last committed revision."""
    session, revision = dx12_session(painter, tmp_path, sessions, *args)
    old = session.status()["worker_pid"]
    assert session.call("test_fault", {"fault": fault})["result"] == {"armed": fault}
    failed = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert "error" in failed, failed
    error = failed["error"]
    assert error["code"] == code and error["details"]["backend"] == "dx12", error
    if code == "device_removed":
        # The device's own removal reason (a DXGI_ERROR_* HRESULT), not a creation symptom.
        assert "(0x887A" in error["details"]["reason"], error
    inspected = session.call("project_inspect")
    assert "result" in inspected and inspected["result"]["revision"] == revision, inspected
    status = session.status()
    assert status["recoveries"], status
    recovery = status["recoveries"][-1]
    assert recovery["cause"] == "device_fault" and recovery["fault_code"] == code, recovery
    assert recovery["old_pid"] == old and recovery["recovery_ms"] > 0, recovery
    assert status["gpu_backend"] == "dx12" and status["gpu_status"] == "ready", status
    evaluated = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert "result" in evaluated, evaluated
