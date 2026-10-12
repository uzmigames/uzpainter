"""Shared fixtures of the preview tests (task phase2.1_preview-viewport-window):
`uzp-preview-tests.exe` (`tests/preview/preview_test.cpp`), built once per test session with
`zig build preview-tests` into a temporary prefix, and `UzPainter.exe` with its worker pipes
(`painter` and `pipes` of tests/supervisor/conftest.py: the Debug build, whose worker carries the
test-only preview stall hook)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.supervisor.conftest import painter, pipes  # noqa: F401  (fixtures)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
GOLDENS = REPO_ROOT / "tests" / "preview" / "viewport-goldens.json"


@pytest.fixture(scope="session")
def preview_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-preview-tests.exe` of a fresh `zig build preview-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-preview-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("preview-tests")
    build = subprocess.run(
        [zig, "build", "preview-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-preview-tests.exe"


def run_case(exe: Path, case: str, *args: str, gpu: bool = False) -> tuple[set[str], str]:
    """Runs one case; returns its passed checks and its output. Fails on any failed check."""
    if gpu and NO_GPU:
        pytest.skip(
            f"UZP_NO_GPU=1: `{case}` needs a DX12 hardware adapter; run it locally on the "
            "owner's machine (decision 028)"
        )
    proc = subprocess.run(
        [str(exe), case, *args],
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
