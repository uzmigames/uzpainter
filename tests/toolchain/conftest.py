"""Shared fixture: `UzPainter.exe` and its run-time files, built once per test session with
`zig build painter` into a temporary prefix (the one-folder layout of
`13-engine-integration.md` §5)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def painter_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The `bin` folder of a fresh `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin"
