"""Shared fixture of the export tests: `uzp-export-tests.exe` (`tests/export/export_test.cpp`),
built once per test session with `zig build export-tests` into a temporary prefix."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def export_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-export-tests.exe` of a fresh `zig build export-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-export-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("export-tests")
    build = subprocess.run(
        [zig, "build", "export-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-export-tests.exe"
