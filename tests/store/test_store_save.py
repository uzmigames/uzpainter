"""Project store: save, checkpoints, retention, compaction, revert, save_as and the lock sidecar.

Task `phase1.6_store-save-retention`. `uzp-store-save-tests.exe` (`tests/store/save_test.cpp`,
`zig build uzp-store-save-tests`) holds the native cases, built with the test-only fault hooks
(`src/store/fault.h`): it fails the I/O of `VACUUM INTO` and of the rename after it, kills a child
copy of itself during `VACUUM INTO` and before the rename, and kills a child holding the project's
lock. No GPU is involved: everything runs on the CPU lane.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "checkpoints",  # 3.1
    "retention_window",  # 3.2
    "protected_checkpoint",  # 3.3
    "revert_edit_reopen_compact",  # 3.4
    "garbage_collection",  # 3.5
    "pruned_key_replay",  # 3.6
    "save_as_and_copy",  # 3.7
    "interrupted_rewrite",  # 3.8
    "portability",  # 3.9
    "lock_sidecar",  # 3.10
)


@pytest.fixture(scope="session")
def save_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-store-save-tests.exe` of a fresh `zig build uzp-store-save-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; `zig build uzp-store-save-tests` cannot run")
    prefix = tmp_path_factory.mktemp("uzp-store-save-tests")
    build = subprocess.run(
        [zig, "build", "uzp-store-save-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-store-save-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=900, check=False)


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(save_tests: Path, case: str) -> None:
    proc = run(save_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(save_tests: Path) -> None:
    proc = run(save_tests, "run")
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    ran = [line.split()[1] for line in proc.stdout.decode().splitlines() if line.startswith("PASS")]
    assert tuple(ran) == NATIVE_CASES


def test_child_refuses_an_unknown_action(save_tests: Path, tmp_path: Path) -> None:
    proc = run(save_tests, "child", "no-such-action", str(tmp_path / "absent.uzp"))
    assert proc.returncode != 0
