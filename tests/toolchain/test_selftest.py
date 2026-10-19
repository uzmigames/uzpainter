"""`UzPainter.exe selftest` (phase0.6_toolchain-hardware-slice, items 2.1-2.7 and 3.1-3.3, and
the local half of 3.5).

The executable is built once per session (`conftest.painter_bin`). The hardware slice (3.1)
needs a DX12 hardware adapter and is skipped with its reason under `UZP_NO_GPU=1` (decision
028); every other test runs anywhere, the GPU stages then skipped by `--no-gpu`.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

import pytest

from tools.toolchain.dll_closure import VC_RUNTIME, check_folder

REPO_ROOT = Path(__file__).resolve().parents[2]
HARDWARE_SLICE = ("dx12-device", "shader-compile", "compute-readback", "png16", "embree")
GPU_STAGES = ("dx12-device", "compute-readback")
VULKAN_SLICE = ("vulkan-device", "vulkan-compute-readback", "vulkan-png16")
WIDTH, HEIGHT = 100, 64


def pattern_value(x: int, y: int) -> int:
    """`PatternValue` of `src/selftest/hardware_slice.h`."""
    v = (x * 0x9E37 + y * 0x7F4A + 0x1234) & 0xFFFF
    if (v >> 10) & 0x1F == 0x1F:
        v ^= 0x4000
    return v


def run_selftest(
    exe: Path, out_dir: Path, *args: str, env: dict[str, str] | None = None
) -> tuple[int, str, dict[str, Any]]:
    environment = dict(os.environ if env is None else env)
    environment.pop("UZP_NO_GPU", None)
    proc = subprocess.run(
        [str(exe), "selftest", "--out-dir", str(out_dir), *args],
        capture_output=True,
        text=True,
        timeout=600,
        env=environment,
        check=False,
    )
    report = json.loads((out_dir / "selftest-report.json").read_text(encoding="utf-8"))
    return proc.returncode, proc.stdout + proc.stderr, report


def stages(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["name"]: s for s in report["stages"]}


def decode_png16_gray(data: bytes) -> tuple[int, int, list[int]]:
    """Independent decoder for a non-interlaced 16-bit grayscale PNG: (width, height, samples)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat = 8, b""
    width = height = 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert zlib.crc32(kind + body) == crc, kind
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, interlace) == (16, 0, 0)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride, bpp = width * 2, 2
    previous = bytearray(stride)
    samples: list[int] = []
    for row in range(height):
        start = row * (stride + 1)
        filter_type, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
                line[i] = (line[i] + pred) & 0xFF
            else:
                assert filter_type == 0, filter_type
        samples += [int.from_bytes(line[i : i + 2], "big") for i in range(0, stride, 2)]
        previous = line
    return width, height, samples


# ── 3.1 Hardware slice on the owner's machine ────────────────────────────────────────────


def test_hardware_slice_green(painter_bin: Path, tmp_path: Path) -> None:
    """3.1: every mandatory stage passes on the DX12 hardware adapter; the report lists adapter,
    driver, OS build, Zig and DXC versions."""
    if os.environ.get("UZP_NO_GPU") == "1":
        pytest.skip(
            "UZP_NO_GPU=1: no GPU on this runner (decision 028); runs on the owner's machine"
        )
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path)
    assert code == 0, output
    assert report["result"] == "passed" and report["hardware_slice"] == "passed"
    by_name = stages(report)
    # Later stages (probes, CPython) follow the slice; they are not part of it.
    assert [n for n, s in by_name.items() if s["hardware_slice"]] == list(HARDWARE_SLICE)
    for name in HARDWARE_SLICE:
        assert by_name[name]["status"] == "passed", by_name[name]
        assert by_name[name]["mandatory"] and by_name[name]["hardware_slice"]
    env = report["environment"]
    assert env["zig"] == "0.15.2" and env["os_build"].startswith("10.0.")
    device = by_name["dx12-device"]["details"]
    assert device["adapter"] and device["driver_version"] != "unknown"
    assert device["agility_sdk_version"] == "619"
    assert device["d3d12core_loaded"].lower().endswith("\\d3d12\\d3d12core.dll")
    assert by_name["shader-compile"]["details"]["dxc_version"]
    assert by_name["compute-readback"]["details"]["row_pitch"] == "256"
    assert by_name["compute-readback"]["details"]["mismatches"] == "0"
    assert by_name["png16"]["details"]["source"] == "gpu-readback"
    assert by_name["embree"]["details"]["embree_version"] == "4.4.1"


# ── Vulkan hardware slice (phase3.1_vulkan-compute-parity 2.8, 3.8; decision 310) ──────────


def test_vulkan_hardware_slice_green(painter_bin: Path, tmp_path: Path) -> None:
    """2.8, 3.8: on the owner's machine the Vulkan slice qualifies the device at adapter index 0
    (every criterion passed), reads the three qualification kernels back bit for bit, the 16-bit
    pattern equal to the CPU pattern and to the DX12 readback, and round-trips it through a 16-bit
    PNG. It is reported as `vulkan_hardware_slice`, apart from the DX12 slice and the
    `vulkan-availability` probe, and no stage of it is mandatory."""
    if os.environ.get("UZP_NO_GPU") == "1":
        pytest.skip(
            "UZP_NO_GPU=1: no GPU on this runner (decision 028); runs on the owner's machine"
        )
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path)
    assert code == 0, output
    assert report["vulkan_hardware_slice"] == "passed", output
    assert report["hardware_slice"] == "passed"
    by_name = stages(report)
    assert [n for n, s in by_name.items() if s["vulkan_hardware_slice"]] == list(VULKAN_SLICE)
    for name in VULKAN_SLICE:
        stage = by_name[name]
        assert stage["status"] == "passed", stage
        assert not stage["mandatory"] and not stage["hardware_slice"] and stage["needs_gpu"]
    device = by_name["vulkan-device"]["details"]
    checks = [v for k, v in device.items() if k.startswith("check.")]
    assert checks and all(v.startswith("passed: ") for v in checks), checks
    assert device["device.name"] and device["device.driver_version"]
    assert device["device.device_uuid"]
    assert device["device.feature.shaderStorageImageExtendedFormats"] == "true"
    assert device["qualification"].startswith("qualified: device 0 ")
    readback = by_name["vulkan-compute-readback"]["details"]
    for kernel in ("pattern16", "hash32", "ieee32"):
        assert readback[f"{kernel}.mismatches"] == "0"
        assert readback[f"{kernel}.odd.mismatches"] == "0"
    assert readback["pattern16.equals_cpu_pattern"] == "yes"
    assert readback["pattern16.equals_dx12_readback"] == "yes"
    png = by_name["vulkan-png16"]["details"]
    assert png["source"] == "vulkan-readback"
    width, height, samples = decode_png16_gray(
        (tmp_path / "selftest-vulkan-pattern16.png").read_bytes()
    )
    assert (width, height) == (WIDTH, HEIGHT)
    assert samples == [pattern_value(x, y) for y in range(HEIGHT) for x in range(WIDTH)]
    assert "selftest: Vulkan hardware slice passed (not mandatory, decision 310)" in output


# ── Hosted CI: GPU stages skipped with an explicit reason ─────────────────────────────────


def test_no_gpu_run_skips_gpu_stages_with_reason(painter_bin: Path, tmp_path: Path) -> None:
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, "--no-gpu")
    assert code == 0, output
    assert report["result"] == "passed" and report["hardware_slice"] == "skipped"
    assert report["environment"]["gpu_stages"] == "skipped"
    assert all(stages(report)[name]["needs_gpu"] for name in GPU_STAGES)
    for stage in stages(report).values():
        if stage["needs_gpu"]:
            assert stage["status"] == "skipped"
            assert stage["reason"] == "no GPU: --no-gpu on the command line"
        else:
            assert stage["status"] == "passed", stage
    assert "SKIP dx12-device: no GPU" in output
    assert report["vulkan_hardware_slice"] == "skipped"
    for name in VULKAN_SLICE:
        assert stages(report)[name]["needs_gpu"] and stages(report)[name]["status"] == "skipped"


def test_uzp_no_gpu_environment_skips_with_reason(painter_bin: Path, tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(painter_bin / "UzPainter.exe"), "selftest", "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "UZP_NO_GPU": "1"},
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((tmp_path / "selftest-report.json").read_text(encoding="utf-8"))
    for name in GPU_STAGES:
        stage = stages(report)[name]
        assert stage["status"] == "skipped"
        assert stage["reason"].startswith(
            "no GPU: UZP_NO_GPU=1 (hosted CI has no GPU, decision 028"
        )


def test_usage_error(painter_bin: Path) -> None:
    proc = subprocess.run(
        [str(painter_bin / "UzPainter.exe"), "selftest", "--bogus"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 2 and "usage:" in proc.stderr


# ── 3.2 Failure path: Agility runtime missing ─────────────────────────────────────────────


def test_missing_agility_runtime_fails_device_stage(painter_bin: Path, tmp_path: Path) -> None:
    """3.2: without `D3D12\\D3D12Core.dll` the device stage fails with an explicit reason and
    `selftest` exits non-zero. (The check precedes device creation, so it needs no GPU.)"""
    folder = tmp_path / "bin"
    shutil.copytree(painter_bin, folder)
    (folder / "D3D12" / "D3D12Core.dll").unlink()
    code, output, report = run_selftest(folder / "UzPainter.exe", tmp_path / "out")
    assert code == 1, output
    assert report["result"] == "failed" and report["hardware_slice"] == "failed"
    device = stages(report)["dx12-device"]
    assert device["status"] == "failed"
    assert device["reason"].startswith("Agility SDK runtime missing: ")
    assert "D3D12\\D3D12Core.dll not found" in device["reason"]
    readback = stages(report)["compute-readback"]
    assert readback["status"] == "skipped"
    assert readback["reason"] == "needs stage dx12-device, which failed"
    assert "FAIL dx12-device: Agility SDK runtime missing" in output


# ── 3.3 PNG16 round trip ──────────────────────────────────────────────────────────────────


def test_png16_round_trip_is_bit_exact(painter_bin: Path, tmp_path: Path) -> None:
    """3.3: the PNG `selftest` writes holds the 16-bit pattern bit for bit, decoded here
    independently of spng; the pattern cannot survive an 8-bit truncation."""
    gpu = os.environ.get("UZP_NO_GPU") != "1"
    args = () if gpu else ("--no-gpu",)
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, *args)
    assert code == 0, output
    png16 = stages(report)["png16"]
    assert png16["status"] == "passed"
    assert png16["details"]["source"] == ("gpu-readback" if gpu else "cpu-pattern")
    width, height, samples = decode_png16_gray((tmp_path / "selftest-pattern16.png").read_bytes())
    expected = [pattern_value(x, y) for y in range(HEIGHT) for x in range(WIDTH)]
    assert (width, height) == (WIDTH, HEIGHT)
    assert samples == expected
    # An 8-bit round trip keeps only the high byte (or replicates it): the pattern would differ.
    assert sum((v & 0xFF) != (v >> 8) for v in expected) > len(expected) // 2


def test_out_dir_outside_the_code_page(painter_bin: Path, tmp_path: Path) -> None:
    """practical-e2e B2 review, UZP-MOD-010: an `--out-dir` outside the ANSI code page gets the
    report, the log and the 16-bit PNG, and the report and stdout name the paths in UTF-8
    (narrowing that folder used to abort `selftest` with an uncaught `filesystem_error`)."""
    out_dir = tmp_path / "ação ☃ 日本"
    environment = dict(os.environ)
    environment.pop("UZP_NO_GPU", None)
    proc = subprocess.run(
        [str(painter_bin / "UzPainter.exe"), "selftest", "--out-dir", str(out_dir), "--no-gpu"],
        capture_output=True,
        timeout=600,
        env=environment,
        check=False,
    )
    output = proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, output
    report_path = out_dir / "selftest-report.json"
    summary = f"selftest: passed; DX12 hardware slice skipped; report {report_path}"
    assert summary in output.splitlines(), output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["result"] == "passed"
    png16 = stages(report)["png16"]
    assert png16["status"] == "passed"
    assert png16["details"]["file"] == str(out_dir / "selftest-pattern16.png")
    assert (out_dir / "selftest-pattern16.png").is_file()
    assert (out_dir / "selftest.log").is_file()


# ── 2.9 / 3.5 Closure of the built folder and start without SDK paths ─────────────────────


def test_built_folder_matches_allowlist(painter_bin: Path) -> None:
    """3.5, static half: the built output folder matches the allowlist and every import resolves
    inside it or to a Windows system DLL, the Visual C++ runtime the prebuilt Embree DLLs import
    included (shipped app-local, `thirdparty/vc-runtime/`), and so do the embedded CPython's
    (phase0.7_toolchain-cpython): the embeddable package's DLLs and extension modules beside the
    executable and the pinned wheels' binaries in `Lib/site-packages/`."""
    report = check_folder(painter_bin)
    assert report.problems == []
    assert report.missing_app_local == {}
    assert report.clean_machine_ready
    wheel_binaries = [b for b in report.binaries if b.path.lower().startswith("lib/site-packages/")]
    extensions = {b.path for b in report.binaries if "/" not in b.path and b.path.endswith(".pyd")}
    names = {
        Path(b.path).name.lower()
        for b in report.binaries
        if b not in wheel_binaries and b.path not in extensions
    }
    assert names == {
        "uzpainter.exe",
        "d3d12core.dll",
        "dxcompiler.dll",
        "dxil.dll",
        "embree4.dll",
        "tbb12.dll",
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "python313.dll",
        "python3.dll",
        "libcrypto-3.dll",
        "libssl-3.dll",
        "libffi-8.dll",
        "sqlite3.dll",
    }
    cpython = json.loads((REPO_ROOT / "thirdparty/cpython/MANIFEST.json").read_text("utf-8"))
    assert extensions == {f["path"] for f in cpython["files"] if f["path"].endswith(".pyd")}
    assert wheel_binaries
    assert {b.role for b in wheel_binaries} == {
        "pinned wheel of the MCP SDK closure (`thirdparty/python-wheels/`)"
    }
    exe = next(b for b in report.binaries if b.path == "UzPainter.exe")
    assert not any(dll.lower() in VC_RUNTIME for dll in exe.load_time)
    assert "python313.dll" in [dll.lower() for dll in exe.load_time]


def test_starts_without_sdk_or_tool_paths(painter_bin: Path, tmp_path: Path) -> None:
    """3.5, local half: the copied folder starts with an environment reduced to the Windows
    folders (no SDK, Vulkan SDK, Python or Zig on PATH) and runs the non-GPU stages. The run on
    a clean machine itself is the owner's (pending, see the hardware-slice report)."""
    folder = tmp_path / "UzPainter"
    shutil.copytree(painter_bin, folder)
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", "C:"),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "PATH": f"{system_root}\\System32;{system_root}",
    }
    code, output, report = run_selftest(
        folder / "UzPainter.exe", tmp_path / "out", "--no-gpu", env=env
    )
    assert code == 0, output
    for stage in stages(report).values():
        assert stage["status"] == ("skipped" if stage["needs_gpu"] else "passed"), stage
