"""Project store: the settling evidence of `docs/architecture/09-project-file-format.md` §7.

Parent task `phase1.8_project-store` (items 3.1-3.5). `uzp-store-settle-tests.exe`
(`tests/store/settle_test.cpp`, `zig build uzp-store-settle-tests`) runs the §7 scenarios end to
end on one build of the store with its test-only fault hooks (`src/store/fault.h`), on content
holding a stored resource bound to a fill layer and two paint layers with multi-chunk planes on
the same channel and UV tile. It kills child copies of itself during `COMMIT`, between a commit's
plane rows and its revision row, after the durable commit, during `VACUUM INTO` and before the
rename, and checks recovery as whole-file equality. No GPU is involved: everything runs on the
hosted CPU lane.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "interruptions",  # 3.1
    "two_layers",  # 3.2
    "commit_then_die",  # 3.3
    "pruned_key_replay",  # 3.4
    "revert_edit_reopen_compact",  # 3.5
)


@pytest.fixture(scope="session")
def settle_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-store-settle-tests.exe` of a fresh `zig build uzp-store-settle-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; `zig build uzp-store-settle-tests` cannot run")
    prefix = tmp_path_factory.mktemp("uzp-store-settle-tests")
    build = subprocess.run(
        [zig, "build", "uzp-store-settle-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-store-settle-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=1800, check=False)


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(settle_tests: Path, case: str) -> None:
    proc = run(settle_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(settle_tests: Path) -> None:
    proc = run(settle_tests, "list")
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert tuple(proc.stdout.decode().split()) == NATIVE_CASES


def test_child_refuses_an_unknown_action(settle_tests: Path, tmp_path: Path) -> None:
    proc = run(settle_tests, "child", "no-such-action", str(tmp_path / "absent.uzp"))
    assert proc.returncode != 0
