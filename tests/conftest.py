"""Session fixture shared across test folders: one fresh verbose build; the persistent caches off.

Several tests inspect what a build prints when every compile and link runs: the vendoring check's
`build-path` rule (`tests/vendoring/test_vendor_check.py`), the link map of `UzPainter.exe`
(`tests/toolchain/test_link_map.py`) and the mesh build paths (`tests/mesh/test_mesh_loader.py`).
Each used to build from its own empty cache; they now share one `zig build` of the vendoring
check's steps plus `mesh-tests`, from an empty cache under pytest's own `tmp_path`, with
`--verbose-cc --verbose-link`. No temporary folder is made in the repository (`AGENTS.override.md`).
The cache and the prefix stay after the session, so the link inputs can be relinked; the next
pytest run removes them.

Every `UzPainter.exe` a test starts runs without the persistent caches (`UZP_NO_CACHE=1`,
decision 253): no test reads a result an earlier run stored, and none writes into the user's cache
folder. The tests of the caches turn them on under a folder of their own
(`tests/python/test_pyapi_cli.py`).
"""

from __future__ import annotations

import ctypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.vendoring.vendor_check import (
    BUILD_STEPS,
    BuildEvidence,
    verbose_build,
    write_build_log,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FRESH_BUILD_STEPS = (*BUILD_STEPS, "mesh-tests")
# SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
NO_ERROR_DIALOGS = 0x8003


def pytest_configure(config: pytest.Config) -> None:
    """No Windows error dialog from any program a test starts (decision 252): they inherit this
    error mode, which also covers a DLL that fails to load before their own `main()` runs."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    kernel32.SetErrorMode(kernel32.GetErrorMode() | NO_ERROR_DIALOGS)


os.environ["UZP_NO_CACHE"] = "1"


@dataclass(frozen=True)
class FreshBuild:
    build: BuildEvidence
    log_path: Path
    cache: Path
    prefix: Path

    @property
    def log(self) -> str:
        return self.build.log


@pytest.fixture(scope="session")
def fresh_verbose_build(tmp_path_factory: pytest.TempPathFactory) -> FreshBuild:
    """`zig build` of FRESH_BUILD_STEPS from an empty cache, with its full verbose log.

    The work folder is pytest's own (`<basetemp>/fresh-build0`): `cache` and `out` are the build's
    `--cache-dir` and `--prefix`, and `build.log` is the log with its evidence line
    (`write_build_log`). pytest keeps only the latest run (`tmp_path_retention_count = 1`), so
    nothing here deletes it."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; the fresh verbose build cannot run")
    work = tmp_path_factory.mktemp("fresh-build")
    build = verbose_build(REPO_ROOT, zig, work, FRESH_BUILD_STEPS)
    log_path = work / "build.log"
    write_build_log(log_path, build)
    assert build.exit_code == 0, build.log[-6000:]
    assert build.inputs_before == build.inputs_after, (
        "a build input changed while the fresh verbose build ran (decision 041); rerun it"
    )
    return FreshBuild(build, log_path, work / "cache", work / "out")
