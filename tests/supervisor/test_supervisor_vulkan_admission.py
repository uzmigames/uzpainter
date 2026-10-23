"""Synthetic heap-only capability records through a real Vulkan worker's admission.

The driver remains real and may support VK_EXT_memory_budget. Only the recorded
memory facts are simulated, before the ordinary startup query and Session wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.supervisor.conftest import NO_GPU, PLANE, Mcp

HEAP_ENV = "UZP_TEST_VULKAN_HEAP_BYTES"


@pytest.mark.skipif(NO_GPU, reason="Vulkan hardware worker (decision 028)")
def test_heap_fallback_admission_is_atomic(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session = Mcp(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-faults",
        env={HEAP_ENV: str(768 << 20)},
    )
    sessions.append(session)
    status = session.status()
    assert status["gpu_status"] == "ready" and status["gpu_backend"] == "vulkan", status
    pid = status["worker_pid"]

    arguments = {"mesh": str(PLANE), "wait": True}
    refused = session.call(
        "project_create", {**arguments, "settings": {"default_texture_resolution": 8192}}
    )
    assert "error" in refused, refused
    assert "texture_set_over_budget" in json.dumps(refused), refused
    assert "budget is 128.0 MiB" in json.dumps(refused), refused
    assert session.call("project_inspect")["result"]["open"] is False

    created = session.call(
        "project_create", {**arguments, "settings": {"default_texture_resolution": 256}}
    )
    assert "error" not in created, created
    before = session.call("project_inspect")["result"]["revision"]
    refused_resize = session.call("set_resolution", {"width": 8192, "height": 8192})
    assert "error" in refused_resize, refused_resize
    assert "texture_set_over_budget" in json.dumps(refused_resize), refused_resize
    assert "budget is 128.0 MiB" in json.dumps(refused_resize), refused_resize
    assert session.call("project_inspect")["result"]["revision"] == before
    [texture_set] = session.call("set_list")["result"]["texture_sets"]
    assert texture_set["resolution"] == {"width": 256, "height": 256}
    assert session.status()["worker_pid"] == pid
    assert "error" not in session.call("project_close", {"discard": True})


def test_invalid_heap_fixture_refuses_before_device_creation(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session = Mcp(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-faults",
        env={HEAP_ENV: "invalid"},
        expected_gpu_status="unavailable",
    )
    sessions.append(session)
    status = session.status()
    assert status["gpu_status"] == "unavailable", status
    assert status["gpu_backend"] == "vulkan", status
    assert "UZP_TEST_VULKAN_HEAP_BYTES must be a positive byte count" in session.log()


@pytest.mark.skipif(NO_GPU, reason="Vulkan hardware worker (decision 028)")
def test_heap_fixture_is_inert_without_test_faults(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session = Mcp(painter, tmp_path, "--gpu-backend", "vulkan", env={HEAP_ENV: "invalid"})
    sessions.append(session)
    status = session.status()
    assert status["gpu_status"] == "ready" and status["gpu_backend"] == "vulkan", status
