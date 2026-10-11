"""Shared fixtures of the compositor tests: `uzp-evaluator-tests.exe`
(`tests/evaluator/evaluator_test.cpp`), built once per test session with `zig build
evaluator-tests` into a temporary prefix, and the repository's template folder."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# The union run's hooks (phase1.14_compositor-core item 3.1); they do nothing outside a run.
from tests.evaluator.union_run import (  # noqa: F401
    pytest_collection_modifyitems,
    pytest_runtest_logreport,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "assets" / "templates"


@pytest.fixture(scope="session")
def evaluator_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-evaluator-tests.exe` of a fresh `zig build evaluator-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-evaluator-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("evaluator-tests")
    build = subprocess.run(
        [zig, "build", "evaluator-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-evaluator-tests.exe"
