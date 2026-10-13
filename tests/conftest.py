"""Session fixture shared across test folders: one fresh verbose build; the persistent caches off.

Several tests inspect what a build prints when every compile and link runs: the vendoring check's
`build-path` rule (`tests/vendoring/test_vendor_check.py`), the link map of `UzPainter.exe`
(`tests/toolchain/test_link_map.py`) and the mesh build paths (`tests/mesh/test_mesh_loader.py`).
Each used to build from its own empty cache; they now share one `zig build` of the vendoring
check's steps plus `mesh-tests`, from an empty local cache inside the repository (as
`python -m tools.vendoring.vendor_check` builds), with `--verbose-cc --verbose-link`. The cache
and the prefix stay until the session ends, so the link inputs can be relinked.

Every `UzPainter.exe` a test starts runs without the persistent caches (`UZP_NO_CACHE=1`,
decision 253): no test reads a result an earlier run stored, and none writes into the user's cache
folder. The tests of the caches turn them on under a folder of their own
(`tests/python/test_pyapi_cli.py`).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.vendoring.vendor_check import BUILD_STEPS, verbose_build

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
    log: str
    log_path: Path
    prefix: Path


@pytest.fixture(scope="session")
def fresh_verbose_build(tmp_path_factory: pytest.TempPathFactory) -> Iterator[FreshBuild]:
    """`zig build` of FRESH_BUILD_STEPS from an empty local cache, with its full verbose log."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; the fresh verbose build cannot run")
    work = REPO_ROOT / ".zig-cache" / f"fresh-build-{uuid.uuid4().hex[:12]}"
    try:
        code, log = verbose_build(REPO_ROOT, zig, work, FRESH_BUILD_STEPS)
        assert code == 0, log[-6000:]
        log_path = tmp_path_factory.mktemp("fresh-build") / "build.log"
        log_path.write_text(log, encoding="utf-8")
        yield FreshBuild(log=log, log_path=log_path, prefix=work / "out")
    finally:
        shutil.rmtree(work, ignore_errors=True)
