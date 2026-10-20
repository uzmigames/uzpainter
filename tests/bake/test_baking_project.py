"""CPU-only baking settings persistence, document admission and rollback."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def baking_project_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zig = shutil.which("zig")
    assert zig is not None, "zig is required for baking project tests"
    prefix = tmp_path_factory.mktemp("baking-project-build")
    result = subprocess.run(
        [zig, "build", "baking-project-tests", "-j4", "--prefix", str(prefix)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return prefix / "bin" / "uzp-baking-project-tests.exe"


@pytest.mark.parametrize("case", ["roundtrip", "transactions", "invalid"])
def test_baking_project(baking_project_tests: Path, tmp_path: Path, case: str) -> None:
    result = subprocess.run(
        [str(baking_project_tests), case, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS {case}" in result.stdout
