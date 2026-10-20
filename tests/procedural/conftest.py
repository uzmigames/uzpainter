"""Shared fixture of the procedural seam tests: `uzp-procedural-tests.exe`
(`tests/procedural/procedural_test.cpp`), built once per test session with
`zig build procedural-tests` into a temporary prefix."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def procedural_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-procedural-tests.exe` of a fresh `zig build procedural-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-procedural-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("procedural-tests")
    build = subprocess.run(
        [zig, "build", "procedural-tests", "-j4", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-procedural-tests.exe"
