"""Project store: SQLite container, zstd blobs, mutation commit, raster planes.

Tasks `phase1.4_store-container-operations` and `phase1.5_store-planes`. `uzp-store-tests.exe`
(`tests/store/store_test.cpp`, `zig build uzp-store-tests`) holds the native cases, built with the
test-only fault hooks (`src/store/fault.h`): it kills a child copy of itself during and after the
commit and between a commit's plane rows and its revision row, refuses database growth as a full
disk does, and corrupts blobs, manifests and plane chunks through the container. These
tests run each case and check that the release library `uzp_store.lib` (`zig build uzp-store`)
contains none of the hooks. No GPU is involved: everything runs on the CPU lane.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "schema_and_pragmas",  # 2.2
    "commit_atomicity",  # 3.1
    "disk_full",  # 3.2
    "corrupt_blob",  # 3.3
    "corrupt_manifest",  # 3.3
    "corrupt_structure",  # B9 (parity/reports/phase2/practical-e2e.md)
    "commit_then_die",  # 3.4
    "unknown_key_rules",  # 3.5
    "deduplication",  # 3.6
    "versioning_newer_major",  # 3.7
    "versioning_older_minor",  # 3.7
    "non_portable_missing",  # 3.8
    "round_trip",  # 2.3-2.6
    "planes_no_alias",  # planes 3.1
    "planes_copy_on_write",  # planes 3.2
    "planes_binding_resolution",  # planes 3.3
    "planes_empty_chunks",  # planes 3.4
    "planes_native_formats",  # planes 3.5
    "planes_interrupted_commit",  # planes 3.6
    "planes_corruption",  # planes 3.7
    "planes_binding_rules",  # planes 2.1, 2.5, 2.7
    "filter_observations",  # decision 362, phase3.1 2.6g
)


def zig_build(step: str, prefix: Path) -> None:
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip(f"zig is not on PATH; `zig build {step}` cannot run")
    build = subprocess.run(
        [zig, "build", step, "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr


@pytest.fixture(scope="session")
def store_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-store-tests.exe` of a fresh `zig build uzp-store-tests`."""
    prefix = tmp_path_factory.mktemp("uzp-store-tests")
    zig_build("uzp-store-tests", prefix)
    return prefix / "bin" / "uzp-store-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=600, check=False)


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(store_tests: Path, case: str) -> None:
    proc = run(store_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(store_tests: Path) -> None:
    proc = run(store_tests, "run")
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    ran = [line.split()[1] for line in proc.stdout.decode().splitlines() if line.startswith("PASS")]
    assert tuple(ran) == NATIVE_CASES


def test_child_refuses_an_unknown_fault(store_tests: Path, tmp_path: Path) -> None:
    proc = run(store_tests, "child", "no-such-fault", str(tmp_path / "absent.uzp"))
    assert proc.returncode != 0


def test_release_library_has_no_fault_hooks(tmp_path: Path) -> None:
    """2.9: the hooks are compiled into the test executable only; `uzp_store.lib` carries neither
    the fault VFS nor its source file, while the store and SQLite are in it."""
    zig_build("uzp-store", tmp_path)
    library = (tmp_path / "lib" / "uzp_store.lib").read_bytes()
    assert b"checkpoint" in library and b"sqlite_schema" in library
    assert b"uzp-fault" not in library
    assert b"fault.cpp" not in library
    build_zig = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    assert "UZP_STORE_FAULT_HOOKS" in build_zig
    for source in sorted((REPO_ROOT / "src" / "store").glob("*.cpp")):
        text = source.read_text(encoding="utf-8")
        if "fault::" in text and source.name != "fault.cpp":
            assert "#if defined(UZP_STORE_FAULT_HOOKS)" in text, source.name
