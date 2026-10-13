"""Mesh reload (phase1.6_mesh-reload, items 3.1-3.5; `docs/architecture/12-mesh-import.md` §7, §9).

`uzp-mesh-reload-tests.exe` (`tests/mesh/reload_test.cpp`, `zig build mesh-tests`) holds the
cases: an identical reload, moved vertices, a UV change, the rename, split and merge fixtures,
added and removed sets, and failures injected mid-reload. No GPU is involved: everything runs on
the CPU lane.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CASES = (
    "identical_reload",  # 3.1
    "moved_vertices",  # 3.2
    "uv_change_replaced",
    "rename_fixture",  # 3.3
    "split_fixture",  # 3.4
    "merge_fixture",
    "added_and_removed_sets",
    "failure_mid_reload",  # 3.5
    "gltf_external_buffer",  # phase2.1_recipe-dump-manifest-blocks: stored buffers, old projects
)


@pytest.fixture(scope="session")
def reload_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-mesh-reload-tests.exe` of a fresh `zig build mesh-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-mesh-reload-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-mesh-reload-tests")
    build = subprocess.run(
        [zig, "build", "mesh-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-mesh-reload-tests.exe"


def _run(exe: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def test_case_list(reload_tests: Path) -> None:
    proc = _run(reload_tests, "run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(line.split()[1] for line in proc.stdout.splitlines()) == sorted(CASES)


@pytest.mark.parametrize("case", CASES)
def test_reload_case(reload_tests: Path, case: str) -> None:
    proc = _run(reload_tests, "run", case)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == f"PASS {case}"
