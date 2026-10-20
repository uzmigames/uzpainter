"""CPU-only baking settings persistence, document admission and rollback."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.bake import bake_defaults

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


def test_model_equals_the_authored_table(baking_project_tests: Path, tmp_path: Path) -> None:
    """2.8 (decision 323): the native model's keys, names, labels, widget types, value types, enum
    values, ranges and defaults equal `assets/defaults/baking.json`, which the private capture
    check compares with Painter (`tests/bake/test_bake_defaults.py`)."""
    dump = tmp_path / "catalog.json"
    result = subprocess.run(
        [str(baking_project_tests), "catalog", str(dump)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    model = json.loads(dump.read_text(encoding="utf-8"))
    assert bake_defaults.check_model(bake_defaults.load_table(), model) == []
