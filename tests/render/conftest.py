"""Shared fixture of the render-layer tests: `uzp-render-tests.exe`
(`tests/render/render_core_test.cpp`), built once per test session with `zig build render-tests`
into a temporary prefix."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def render_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-render-tests.exe` of a fresh `zig build render-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-render-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("render-tests")
    build = subprocess.run(
        [zig, "build", "render-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-render-tests.exe"
