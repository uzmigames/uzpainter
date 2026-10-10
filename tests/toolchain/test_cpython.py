"""The embedded CPython boundary of `UzPainter.exe` (phase0.7_toolchain-cpython, items 2.2-2.8 and
3.1-3.4).

The executable is built once per session (`conftest.painter_bin`). The CPython stages need no
GPU, so every run here uses `--no-gpu`; the full run on the owner's machine is
`parity/reports/phase0/toolchain-cpython.md`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tests.toolchain.test_selftest import run_selftest, stages
from tools.vendoring.wheels import read_wheels, site_packages_problems

REPO_ROOT = Path(__file__).resolve().parents[2]
CPYTHON_STAGES = (
    "cpython-start",
    "cpython-uzpainter",
    "cpython-buffer16",
    "cpython-exceptions",
    "cpython-mcp-sdk",
)


def cpython_stages(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_name = stages(report)
    return {name: by_name[name] for name in CPYTHON_STAGES}


def norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def assert_all_passed(report: dict[str, Any], output: str) -> dict[str, dict[str, Any]]:
    by_name = cpython_stages(report)
    for name, stage in by_name.items():
        assert stage["status"] == "passed", (name, stage, output)
        assert stage["mandatory"] and not stage["needs_gpu"] and not stage["hardware_slice"]
    return by_name


# ── 3.1 CPython stages pass ───────────────────────────────────────────────────────────────


def test_cpython_stages_pass(painter_bin: Path, tmp_path: Path) -> None:
    """3.1 (local half): every CPython stage passes; the interpreter is the pinned 3.13.16 from
    the folder's `python313.dll`, `uzpainter` is built in and the MCP SDK is the pinned 2.3.0."""
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, "--no-gpu")
    assert code == 0, output
    by_name = assert_all_passed(report, output)
    start = by_name["cpython-start"]["details"]
    assert start["version_info"] == "3.13.16"
    assert norm(start["python313_dll"]) == norm(painter_bin / "python313.dll")
    assert norm(start["prefix"]) == norm(painter_bin)
    uzpainter = by_name["cpython-uzpainter"]["details"]
    assert uzpainter["builtin"] == "True" and uzpainter["origin"] == "built-in"
    mcp = by_name["cpython-mcp-sdk"]["details"]
    assert mcp["mcp_version"] == "2.3.0"
    assert mcp["mcp_tools"] == "repeat" and mcp["mcp_call"] == "{'result': 'uzuzuz'}"
    for wheel in ("pydantic_core", "rpds", "cffi", "cryptography", "pywin32"):
        assert mcp["native_" + wheel].startswith("Lib\\site-packages\\"), mcp
    for name in CPYTHON_STAGES:
        assert f"PASS {name}" in output


def test_python313_pth_and_site_packages_installed(painter_bin: Path) -> None:
    """2.2/2.4: the folder holds UzPainter's `python313._pth` (not the package's) and a
    `Lib/site-packages/` that is exactly the pinned wheels' files."""
    pth = (painter_bin / "python313._pth").read_bytes()
    assert pth == (REPO_ROOT / "src/python/python313._pth").read_bytes()
    entries = [
        line.split("#", 1)[0].strip()
        for line in pth.decode("utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    ]
    assert entries == ["python313.zip", ".", "Lib\\site-packages", "import site"]
    assert not (painter_bin / "python.exe").exists()
    problems = site_packages_problems(painter_bin / "Lib/site-packages", read_wheels(REPO_ROOT))
    assert problems == []


# ── 3.2 Isolation ─────────────────────────────────────────────────────────────────────────


def test_isolated_from_user_python(painter_bin: Path, tmp_path: Path) -> None:
    """3.2: with `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, the user site-packages (through
    `APPDATA` and `PYTHONUSERBASE`) and the current folder all offering a conflicting `mcp`, the
    embedded interpreter imports only the vendored modules."""
    conflicting = "raise ImportError('conflicting mcp imported from {}')\n"
    evil = tmp_path / "evil"
    user_sites = [
        evil / "appdata" / "Python" / "Python313" / "site-packages",
        evil / "userbase" / "Python313" / "site-packages",
    ]
    for folder in [evil, *user_sites]:
        (folder / "mcp").mkdir(parents=True)
        (folder / "mcp" / "__init__.py").write_text(conflicting.format(folder), encoding="utf-8")
    (evil / "mcp.py").write_text(conflicting.format(evil), encoding="utf-8")
    (evil / "uzpainter.py").write_text(conflicting.format(evil), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(evil),
        "PYTHONHOME": str(evil),
        "PYTHONSTARTUP": str(evil / "mcp.py"),
        "PYTHONUSERBASE": str(evil / "userbase"),
        "APPDATA": str(evil / "appdata"),
    }
    env.pop("UZP_NO_GPU", None)
    out = tmp_path / "out"
    proc = subprocess.run(
        [str(painter_bin / "UzPainter.exe"), "selftest", "--no-gpu", "--out-dir", str(out)],
        cwd=evil,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    output = proc.stdout + proc.stderr
    report = json.loads((out / "selftest-report.json").read_text(encoding="utf-8"))
    assert proc.returncode == 0, output
    by_name = assert_all_passed(report, output)
    start = by_name["cpython-start"]["details"]
    for flag in ("isolated", "ignore_environment", "no_user_site"):
        assert start["flag_" + flag] == "1"
    assert start["user_site_enabled"] == "False"
    site_packages = norm(painter_bin / "Lib/site-packages")
    path = [norm(p.strip()) for p in start["sys_path"].split(" ; ")]
    assert path[:3] == [norm(painter_bin / "python313.zip"), norm(painter_bin), site_packages]
    assert all(p.startswith(site_packages + os.sep) for p in path[3:]), path
    assert norm(evil) not in path
    mcp_file = norm(by_name["cpython-mcp-sdk"]["details"]["mcp_file"])
    assert mcp_file == norm(painter_bin / "Lib/site-packages/mcp/__init__.py")


# ── 3.3 16-bit buffer round trip ──────────────────────────────────────────────────────────


def test_buffer16_round_trip_every_value(painter_bin: Path, tmp_path: Path) -> None:
    """3.3: every 16-bit value 0…65535 survives C++ → Python → C++ through the buffer protocol:
    131072 bytes compared byte for byte in C++, 65536 values compared in Python and in a bound
    function."""
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, "--no-gpu")
    assert code == 0, output
    details = cpython_stages(report)["cpython-buffer16"]["details"]
    assert details["cpp_buffer_format"] == "H" and details["cpp_buffer_itemsize"] == "2"
    assert details["cpp_buffer_length"] == "65536" and details["cpp_buffer_readonly"] == "True"
    assert details["python_values"] == "65536" and details["python_mismatches"] == "0"
    assert details["bound_function_mismatches"] == "0"
    assert details["cpp_received_format"] == "H"
    assert details["cpp_received_bytes"] == "131072"
    assert details["cpp_byte_mismatches"] == "0"


# ── 3.4 Exceptions across the boundary ────────────────────────────────────────────────────


def test_exceptions_keep_type_and_message(painter_bin: Path, tmp_path: Path) -> None:
    """3.4: Python exceptions reach C++ and C++ exceptions reach Python with type and message,
    and the interpreter stays usable afterwards (the next stage runs Python too)."""
    code, output, report = run_selftest(painter_bin / "UzPainter.exe", tmp_path, "--no-gpu")
    assert code == 0, output
    by_name = cpython_stages(report)
    details = by_name["cpython-exceptions"]["details"]
    assert details["python_ValueError"] == (
        "ValueError: uzpainter selftest: Python ValueError to C++"
    )
    assert details["python_ScriptError"] == (
        "ScriptError: uzpainter selftest: Python ScriptError to C++"
    )
    expected = {
        "invalid_argument": "builtins.ValueError",
        "out_of_range": "builtins.IndexError",
        "runtime_error": "builtins.RuntimeError",
        "boundary_error": "uzpainter._selftest.BoundaryError",
    }
    for kind, python_type in expected.items():
        assert details["cpp_" + kind] == (
            f"{python_type}: uzpainter selftest: C++ {kind} to Python"
        )
    assert details["usable_after"] == "sum(range(10)) = 45, ramp16 mismatches 0"
    assert by_name["cpython-mcp-sdk"]["status"] == "passed"


# ── Failure paths ─────────────────────────────────────────────────────────────────────────


def test_missing_standard_library_fails_start(painter_bin: Path, tmp_path: Path) -> None:
    """Without `python313.zip` the interpreter cannot start: `cpython-start` fails with the
    reason, the other CPython stages are skipped and `selftest` exits non-zero."""
    folder = tmp_path / "bin"
    shutil.copytree(painter_bin, folder)
    (folder / "python313.zip").unlink()
    code, output, report = run_selftest(folder / "UzPainter.exe", tmp_path / "out", "--no-gpu")
    assert code == 1, output
    by_name = cpython_stages(report)
    assert by_name["cpython-start"]["status"] == "failed"
    assert by_name["cpython-start"]["reason"].startswith("the interpreter did not start: ")
    for name in CPYTHON_STAGES[1:]:
        assert by_name[name]["status"] == "skipped"
        assert by_name[name]["reason"] == "needs stage cpython-start, which failed"


def test_missing_mcp_sdk_fails_its_stage(painter_bin: Path, tmp_path: Path) -> None:
    """Without the SDK in `Lib/site-packages/` only `cpython-mcp-sdk` fails, naming the missing
    module; nothing outside the folder is picked up instead."""
    folder = tmp_path / "bin"
    shutil.copytree(painter_bin, folder)
    shutil.rmtree(folder / "Lib/site-packages/mcp")
    code, output, report = run_selftest(folder / "UzPainter.exe", tmp_path / "out", "--no-gpu")
    assert code == 1, output
    by_name = cpython_stages(report)
    mcp = by_name["cpython-mcp-sdk"]
    assert mcp["status"] == "failed"
    assert mcp["reason"] == "Python raised ModuleNotFoundError: No module named 'mcp'"
    for name in CPYTHON_STAGES[:-1]:
        assert by_name[name]["status"] == "passed"
